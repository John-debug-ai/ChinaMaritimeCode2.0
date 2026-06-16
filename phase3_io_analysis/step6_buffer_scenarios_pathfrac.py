"""
Phase 3 / Step 6: 缓冲情景 MRIO 计算（路径份额缩放版）

与 step5 的区别
================
step5 在筛选要道流量时使用 ports_updated.csv 的港口级聚合（单端 id.isin），
导致 CHN2World 方向各要道得到几乎相同的 trade_total / Dind / multiplier_B ——
因为大型中国出口港全球通达，"经过任意要道的中国港口集合"在不同要道间近乎重合。

step6 改用 phase1 GPKG 的路径级流量构造每个 (iso3_O, iso3_D, Industries) 的
物理路径份额 chokefrac = V_choke / V_all，再用它缩放 ports_updated.csv 的
v_share_trade，使 MRIO 冲击精确对应"实际经过此要道的贸易"。

算法
----
1. 一次性聚合：从全量 GPKG 把 v1..v11 melt 成长表，按 (iso3_O, iso3_D, Industries)
   汇总得 V_all。
2. 逐要道：空间相交得到经过要道的路径 → 同样 melt + 汇总 → V_choke。
3. chokefrac = V_choke / V_all（按 (O, D, Industries) 对齐，clip 到 [0,1]）。
4. 用 chokefrac 缩放 ports_updated.csv 的 port_export 行 v_share_trade：
       v_share_trade_new = v_share_trade × chokefrac(O, D, Industries)
5. 按 (O, D, Industries) 聚合 → all_flows_100，喂给 step5 的 run_scenario。

两层冲击逻辑叠加
----------------
  chokefrac 层（物理）：(O,D,ind) 贸易中物理上经过该要道的比例
  alt_status 层（可替代）：经过该要道的国家是否有替代路线（含 1.5x 距离阈值）
  scenario 层（情景）：有替代国家按 s% 缩放，无替代国家保持 100% 中断

复用模块
--------
  compute_alt_status, run_scenario  ← import 自 step5（一字不改）

输出目录
--------
  output/mrio/{direction}/buffer_pathfrac/
    {direction}_buffer_results.csv  长表
    {direction}_宽表汇总.xlsx        宽表

诊断列（每要道一行）
--------------------
  V_choke_total  该要道在所有 (O,D,Industries) 上的 USD 流量之和
  V_all_total    同 (O,D,Industries) 覆盖范围内的全量 USD（仅参与 V_choke>0 的子集）
  frac_avg       v_share_trade 加权的全局平均 chokefrac
"""

import datetime
import os
import sys
import traceback
import warnings

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import geopandas as gpd
import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

from shared.config import EORA_PATH, CHN_ISO3, out, mrio, CHOKEPOINTS_DIR
from shared.mrio_utils import load_eora

# 复用 step5 的核心逻辑（alt_status 判断 + 单情景 MRIO 计算）
from phase3_io_analysis.step5_buffer_scenarios import (
    compute_alt_status,
    run_scenario,
    SCENARIOS,
    DETOUR_THRESHOLD,
    DIRECTION_CONFIG,
)

# EORA 11 部门，对应 GPKG 中的 v1..v11 列
V_COLS = [f"v{i}" for i in range(1, 12)]


# ── 工具函数 ──────────────────────────────────────────────────────────────────

def _log(msg: str, end: str = "\n") -> None:
    ts = datetime.datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {msg}", end=end, flush=True)


# ── 路径份额计算 ──────────────────────────────────────────────────────────────

def _melt_routes_to_long(
    routes_df: pd.DataFrame,
    direction: str,
) -> pd.DataFrame:
    """把路径 DataFrame 的 v1..v11 melt 成 (iso3_O, iso3_D, Industries, v_usd) 长表。

    GPKG 中路径按货物实际流向存储（start = 出发地, end = 到达地），所以两个方向下
    都满足 start_iso3 → iso3_O（origin），end_iso3 → iso3_D（destination）：
      CHN2World: start=CHN(iso3_O), end=外国(iso3_D)
      World2CHN: start=外国(iso3_O), end=CHN(iso3_D)
    这与 ports_updated.csv 中 iso3_O / iso3_D 的语义一致。
    """
    if direction not in ("CHN2World", "World2CHN"):
        raise ValueError(f"unknown direction: {direction}")

    cols = ["start_iso3", "end_iso3"] + V_COLS
    long = routes_df[cols].melt(
        id_vars=["start_iso3", "end_iso3"],
        value_vars=V_COLS,
        var_name="Industries",
        value_name="v_usd",
    )
    long["Industries"] = long["Industries"].str[1:].astype(int)
    long = long.rename(columns={"start_iso3": "iso3_O", "end_iso3": "iso3_D"})
    return long


def _build_v_table(
    routes_df: pd.DataFrame,
    direction: str,
    out_col: str,
) -> pd.DataFrame:
    """对路径集合算 (iso3_O, iso3_D, Industries) 汇总 USD 流量。"""
    long = _melt_routes_to_long(routes_df, direction)
    agg = (
        long
        .groupby(["iso3_O", "iso3_D", "Industries"], as_index=False)["v_usd"]
        .sum()
        .rename(columns={"v_usd": out_col})
    )
    return agg


def _compute_chokefrac(
    v_all: pd.DataFrame,
    v_choke: pd.DataFrame,
) -> pd.DataFrame:
    """合并 V_all / V_choke 算 chokefrac，clip 到 [0, 1]。

    返回字段：iso3_O, iso3_D, Industries, V_all, V_choke, chokefrac
    """
    frac = v_all.merge(
        v_choke, on=["iso3_O", "iso3_D", "Industries"], how="left"
    )
    frac["V_choke"] = frac["V_choke"].fillna(0.0)
    frac["chokefrac"] = np.where(
        frac["V_all"] > 0,
        frac["V_choke"] / frac["V_all"],
        0.0,
    )
    # 浮点容差/路径重复导致 >1 时截断（理论上不该出现）
    frac["chokefrac"] = frac["chokefrac"].clip(lower=0.0, upper=1.0)
    return frac


# ── 单方向处理 ────────────────────────────────────────────────────────────────

def _process_direction(
    direction: str,
    eora_data: dict,
    L_orig: np.ndarray,
) -> None:
    """遍历 CHOKEPOINTS_DIR 中的要道 SHP，对每个要道×每个情景运行 MRIO。

    与 step5 的差异：在调用 run_scenario 前，先用 chokefrac 缩放 ports_exp
    的 v_share_trade，再按 (iso3_O, iso3_D, Industries) 聚合。
    """
    cfg = DIRECTION_CONFIG[direction]

    out_dir     = mrio(direction, "buffer_pathfrac")
    ports_path  = os.path.join(mrio(direction, "input"), f"{direction}_ports_updated.csv")
    routes_gpkg = os.path.join(
        out(direction, "routes"),
        f"shortest_paths_{direction}_with_flows.gpkg",
    )

    filter_iso_col = cfg["filter_iso_col"]
    foreign_check  = cfg["foreign_check"]

    # ── 前置检查 ─────────────────────────────────────────────────────────────
    for path, label in [
        (CHOKEPOINTS_DIR, "要道SHP目录"),
        (ports_path,      "ports_updated.csv"),
        (routes_gpkg,     "全量路线GPKG"),
    ]:
        if not os.path.exists(path):
            _log(f"[{direction}] ⚠ {label} 不存在: {path}，跳过此方向。")
            return

    # ── 加载全量路线（含 geometry + v1..v11）─────────────────────────────────
    _log(f"[{direction}] 加载全量路线 GPKG（含 geometry + v1..v11）...")
    full_routes_geo = gpd.read_file(routes_gpkg)
    full_routes_geo = full_routes_geo[
        full_routes_geo[filter_iso_col] == CHN_ISO3
    ].reset_index(drop=True)

    route_cols = ["start_id", "end_id", "start_iso3", "end_iso3", "length"]
    full_routes = full_routes_geo[route_cols].copy()
    _log(f"[{direction}] 全量路线: {len(full_routes):,} 条  "
         f"（替代路线距离阈值: {DETOUR_THRESHOLD}x）")

    # ── 一次性算 V_all（全量 O×D×Industries USD 流量）────────────────────────
    _log(f"[{direction}] 构造 V_all (全量 O×D×Industries USD)...")
    v_all = _build_v_table(full_routes_geo, direction, out_col="V_all")
    _log(f"[{direction}] V_all: {len(v_all):,} 行  "
         f"全量流量 {v_all['V_all'].sum() / 1e9:.2f}B$")

    # ── 加载 port_export 行（与 step5 一致）──────────────────────────────────
    ports_df  = pd.read_csv(ports_path)
    ports_exp = ports_df[ports_df["flow"] == "port_export"].copy()
    _log(f"[{direction}] port_export 行数: {len(ports_exp):,}")

    # ── 预先算 v_share_trade 在 (O,D,Ind) 上的总和，供 frac_avg 加权 ────────
    od_share_sum = (
        ports_exp.groupby(["iso3_O", "iso3_D", "Industries"], as_index=False)["v_share_trade"]
        .sum()
        .rename(columns={"v_share_trade": "_share_sum"})
    )

    # ── 遍历要道 ─────────────────────────────────────────────────────────────
    shp_files = sorted(f for f in os.listdir(CHOKEPOINTS_DIR) if f.lower().endswith(".shp"))
    _log(f"[{direction}] 发现 {len(shp_files)} 个要道，"
         f"共 {len(shp_files) * len(SCENARIOS)} 次 MRIO 计算")

    all_results = []

    for fname in shp_files:
        choke_name = os.path.splitext(fname)[0]
        _log(f"\n[{direction}] ▶ {choke_name}")

        try:
            # 1. 空间相交：经过该要道的路径
            points = gpd.read_file(os.path.join(CHOKEPOINTS_DIR, fname))
            if full_routes_geo.crs != points.crs:
                points = points.to_crs(full_routes_geo.crs)
            choke_routes_geo = full_routes_geo[
                full_routes_geo.geometry.intersects(points.union_all())
            ].copy()
            choke_df = pd.DataFrame(choke_routes_geo[route_cols])
            _log(f"     空间相交路径: {len(choke_df)} 条")

            if choke_df.empty:
                _log(f"     ⚠ 无路径与该要道相交，跳过")
                continue

            # 2. 替代路线判断（沿用 step5）
            _log(f"     替代路线判断（阈值={DETOUR_THRESHOLD}x）:")
            alt_status, no_alt_set = compute_alt_status(
                choke_df, full_routes, cfg, detour_threshold=DETOUR_THRESHOLD
            )
            _log(f"     ▷ 外国数={len(alt_status)}  "
                 f"有替代={len(alt_status) - len(no_alt_set)}  "
                 f"无替代={len(no_alt_set)}: {sorted(no_alt_set)}")

            # 3. 算 V_choke 和 chokefrac
            v_choke = _build_v_table(choke_routes_geo, direction, out_col="V_choke")
            frac    = _compute_chokefrac(v_all, v_choke)

            V_choke_total = float(frac["V_choke"].sum())
            V_all_covered = float(frac.loc[frac["V_choke"] > 0, "V_all"].sum())

            # 加权平均 chokefrac（用 ports_exp 端 (O,D,Ind) v_share_trade 之和作权重）
            frac_w = frac.merge(od_share_sum, on=["iso3_O", "iso3_D", "Industries"], how="left")
            frac_w["_share_sum"] = frac_w["_share_sum"].fillna(0.0)
            if frac_w["_share_sum"].sum() > 0:
                frac_avg = float(np.average(frac_w["chokefrac"], weights=frac_w["_share_sum"]))
            else:
                frac_avg = float("nan")

            _log(f"     V_choke={V_choke_total / 1e9:.3f}B$  "
                 f"V_all(覆盖)={V_all_covered / 1e9:.3f}B$  "
                 f"frac_avg={frac_avg:.4f}")

            # 4. 缩放 ports_exp.v_share_trade
            sub = ports_exp.merge(
                frac[["iso3_O", "iso3_D", "Industries", "chokefrac"]],
                on=["iso3_O", "iso3_D", "Industries"],
                how="left",
            )
            sub["chokefrac"] = sub["chokefrac"].fillna(0.0)
            sub["v_share_trade"] = sub["v_share_trade"] * sub["chokefrac"]
            sub = sub[sub["v_share_trade"] > 0]

            if sub.empty:
                _log(f"     ⚠ chokefrac 缩放后无有效流量，跳过")
                continue

            all_flows_100 = (
                sub.groupby(["iso3_O", "iso3_D", "Industries"], as_index=False)["v_share_trade"]
                .sum()
            )
            _log(f"     缩放后流量行={len(all_flows_100)}  "
                 f"Σv_share_trade={all_flows_100['v_share_trade'].sum():.4f}")

            # 5. 逐情景计算
            for s in SCENARIOS:
                _log(f"     情景{int(s * 100):3d}% ... ", end="")
                res = run_scenario(
                    all_flows_100, alt_status, foreign_check, s, eora_data, L_orig
                )
                res.update({
                    "chokepoint":       choke_name,
                    "direction":        direction,
                    "n_countries":      len(alt_status),
                    "n_no_alt":         len(no_alt_set),
                    "no_alt_countries": "|".join(sorted(no_alt_set)),
                    "V_choke_total":    V_choke_total,
                    "V_all_total":      V_all_covered,
                    "frac_avg":         round(frac_avg, 6) if not np.isnan(frac_avg) else np.nan,
                })
                all_results.append(res)
                _log(
                    f"mult_B={res['multiplier_B']:.4f}  "
                    f"Dind={res['Dind_total'] / 1e9:.3f}B$  "
                    f"no_alt_frac={res['no_alt_frac']}"
                )

        except Exception:
            _log(f"     ✗ 出错:")
            traceback.print_exc()

    if not all_results:
        _log(f"[{direction}] 无结果生成。")
        return

    # ── 保存长表 ─────────────────────────────────────────────────────────────
    col_order = [
        "chokepoint", "direction", "scenario",
        "n_countries", "n_no_alt", "no_alt_countries", "no_alt_frac",
        "V_choke_total", "V_all_total", "frac_avg",
        "trade_total_100", "trade_total_S",
        "Dind_total", "Dind_chn", "Dind_row",
        "Dind_total_bw", "Dind_total_fw",
        "multiplier_B", "multiplier_A",
        "multiplier_A_chn", "multiplier_A_row",
    ]
    df_long   = pd.DataFrame(all_results)[col_order]
    long_path = os.path.join(out_dir, f"{direction}_buffer_results.csv")
    df_long.to_csv(long_path, index=False, encoding="utf-8-sig")
    _log(f"\n[{direction}] ✅ 长表 → {long_path}")

    # ── 保存宽表 ─────────────────────────────────────────────────────────────
    fixed_cols = [
        "chokepoint", "direction", "n_countries", "n_no_alt", "no_alt_countries",
        "no_alt_frac", "V_choke_total", "V_all_total", "frac_avg", "trade_total_100",
    ]
    metric_cols = [
        "trade_total_S", "Dind_total", "Dind_chn", "Dind_row",
        "multiplier_B", "multiplier_A", "multiplier_A_chn", "multiplier_A_row",
    ]

    wide_rows = []
    for choke in df_long["chokepoint"].unique():
        sub_c = df_long[df_long["chokepoint"] == choke]
        row   = {c: sub_c.iloc[0][c] for c in fixed_cols}
        for s in SCENARIOS:
            lbl = f"s{int(s * 100)}"
            sr  = sub_c[sub_c["scenario"] == s]
            if not sr.empty:
                for m in metric_cols:
                    row[f"{m}_{lbl}"] = sr.iloc[0][m]
        wide_rows.append(row)

    df_wide   = pd.DataFrame(wide_rows)
    wide_path = os.path.join(out_dir, f"{direction}_宽表汇总.xlsx")
    df_wide.to_excel(wide_path, index=False, engine="openpyxl")
    _log(f"[{direction}] ✅ 宽表 → {wide_path}")

    # ── 打印 multiplier_B 汇总 ────────────────────────────────────────────────
    _log(f"\n[{direction}] multiplier_B 汇总：")
    pivot = df_long.pivot_table(
        index="chokepoint", columns="scenario",
        values="multiplier_B", aggfunc="first",
    ).rename(columns={s: f"{int(s * 100)}%" for s in SCENARIOS})
    print(pivot.to_string())


# ── 公开入口 ──────────────────────────────────────────────────────────────────

def load_eora_once() -> dict:
    """加载 EORA26 并返回预计算字典（与 step5 共用）。"""
    return load_eora(EORA_PATH)


def run(direction: str, eora_data: dict | None = None) -> None:
    """
    运行 Phase 3 Step 6 路径份额缩放版缓冲情景分析。

    Parameters
    ----------
    direction  : "CHN2World" 或 "World2CHN"
    eora_data  : load_eora() 返回的预计算字典；若为 None 则在函数内部加载。
    """
    t0 = datetime.datetime.now()

    if eora_data is None:
        eora_data = load_eora_once()

    # 预计算 Leontief 逆，复用 step5 风格
    _log(f"[{direction}] 预计算 Leontief 逆 (L_orig)...")
    A0     = eora_data["A_orig"]
    I_full = eora_data["I_full"]
    L_orig = np.linalg.inv(I_full - A0.values)
    _log(f"[{direction}] L_orig 计算完毕")

    _process_direction(direction, eora_data, L_orig)

    _log(f"[{direction}] Step 6 完成，耗时 {datetime.datetime.now() - t0}")


if __name__ == "__main__":
    eora = load_eora_once()
    for d in ["CHN2World", "World2CHN"]:
        run(d, eora_data=eora)
