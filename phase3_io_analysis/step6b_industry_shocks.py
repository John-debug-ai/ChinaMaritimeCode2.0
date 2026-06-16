"""
Phase 3 / Step 6b: 逐行业隔离冲击分析

目标
----
对每个要道 × 每个情景 × 每个行业（1~11），单独中断该行业的贸易流量，
运行完整 MRIO 计算（Backward + Forward），得到该行业单独中断时对全球
和中国产出的影响。

与 step6 的关系
--------------
step6 的 multiplier_A 是 11 个行业同时中断后的整体乘数。
本脚本将行业拆开，逐个隔离冲击，因此每个要道×情景会运行 11 次 MRIO，
总计算量约为 step6 的 11 倍。

算法
----
1. 复用 step6 的路径份额逻辑（chokefrac 缩放），得到 all_flows_100。
2. 对每个行业 ind ∈ [1..11]，过滤 flows_ind = all_flows_100[Industries == ind]。
3. 将 flows_ind 单独传给 run_scenario，得到该行业隔离冲击下的乘数。
4. 汇总输出长表和宽表。

复用模块
--------
  compute_alt_status, run_scenario  ← import 自 step5
  _melt_routes_to_long, _build_v_table, _compute_chokefrac  ← import 自 step6

输出目录
--------
  output/mrio/{direction}/industry_shocks/
    {direction}_industry_shocks.csv     长表（每要道×情景×行业一行）
    {direction}_industry_shocks.xlsx    宽表（每要道×行业一行，情景横向展开）
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

from phase3_io_analysis.step5_buffer_scenarios import (
    compute_alt_status,
    run_scenario,
    SCENARIOS,
    DETOUR_THRESHOLD,
    DIRECTION_CONFIG,
)

from phase3_io_analysis.step6_buffer_scenarios_pathfrac import (
    _build_v_table,
    _compute_chokefrac,
    V_COLS,
)

INDUSTRY_NAMES = {
    1:  "Agriculture",
    2:  "Fishing",
    3:  "Mining and Quarrying",
    4:  "Food & Beverages",
    5:  "Textiles and Wearing Apparel",
    6:  "Wood and Paper",
    7:  "Petroleum, Chemical and Non-Metallic Mineral Products",
    8:  "Metal Products",
    9:  "Electrical and Machinery",
    10: "Transport Equipment",
    11: "Other Manufacturing",
}


def _log(msg: str, end: str = "\n") -> None:
    ts = datetime.datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {msg}", end=end, flush=True)


def _process_direction(
    direction: str,
    eora_data: dict,
    L_orig: np.ndarray,
) -> None:
    cfg = DIRECTION_CONFIG[direction]

    out_dir     = mrio(direction, "industry_shocks")
    ports_path  = os.path.join(mrio(direction, "input"), f"{direction}_ports_updated.csv")
    routes_gpkg = os.path.join(
        out(direction, "routes"),
        f"shortest_paths_{direction}_with_flows.gpkg",
    )

    filter_iso_col = cfg["filter_iso_col"]
    foreign_check  = cfg["foreign_check"]

    for path, label in [
        (CHOKEPOINTS_DIR, "要道SHP目录"),
        (ports_path,      "ports_updated.csv"),
        (routes_gpkg,     "全量路线GPKG"),
    ]:
        if not os.path.exists(path):
            _log(f"[{direction}] ⚠ {label} 不存在: {path}，跳过此方向。")
            return

    # ── 加载全量路线 ─────────────────────────────────────────────────────────
    _log(f"[{direction}] 加载全量路线 GPKG...")
    full_routes_geo = gpd.read_file(routes_gpkg)
    full_routes_geo = full_routes_geo[
        full_routes_geo[filter_iso_col] == CHN_ISO3
    ].reset_index(drop=True)

    route_cols = ["start_id", "end_id", "start_iso3", "end_iso3", "length"]
    full_routes = full_routes_geo[route_cols].copy()
    _log(f"[{direction}] 全量路线: {len(full_routes):,} 条")

    # ── V_all ────────────────────────────────────────────────────────────────
    _log(f"[{direction}] 构造 V_all...")
    v_all = _build_v_table(full_routes_geo, direction, out_col="V_all")

    # ── port_export ──────────────────────────────────────────────────────────
    ports_df  = pd.read_csv(ports_path)
    ports_exp = ports_df[ports_df["flow"] == "port_export"].copy()

    # ── 遍历要道 ─────────────────────────────────────────────────────────────
    shp_files = sorted(f for f in os.listdir(CHOKEPOINTS_DIR) if f.lower().endswith(".shp"))
    n_total   = len(shp_files) * len(SCENARIOS) * 11
    _log(f"[{direction}] 发现 {len(shp_files)} 个要道，"
         f"共 {n_total} 次 MRIO 计算（{len(shp_files)}×{len(SCENARIOS)}情景×11行业）")

    ind_results = []

    for fname in shp_files:
        choke_name = os.path.splitext(fname)[0]
        _log(f"\n[{direction}] ▶ {choke_name}")

        try:
            # 1. 空间相交
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

            # 2. 替代路线判断
            alt_status, no_alt_set = compute_alt_status(
                choke_df, full_routes, cfg, detour_threshold=DETOUR_THRESHOLD
            )

            # 3. chokefrac
            v_choke = _build_v_table(choke_routes_geo, direction, out_col="V_choke")
            frac    = _compute_chokefrac(v_all, v_choke)

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

            # 5. 逐行业 × 逐情景
            industries_present = sorted(all_flows_100["Industries"].unique())
            _log(f"     有效行业: {industries_present}")

            for ind in industries_present:
                flows_ind = all_flows_100[all_flows_100["Industries"] == ind].copy()
                if flows_ind.empty:
                    continue

                ind_trade = flows_ind["v_share_trade"].sum()
                ind_name  = INDUSTRY_NAMES.get(ind, f"Unknown_{ind}")

                for s in SCENARIOS:
                    _log(f"     行业{ind:2d} ({ind_name[:20]:<20s}) 情景{int(s*100):3d}% ... ",
                         end="")
                    res = run_scenario(
                        flows_ind, alt_status, foreign_check, s, eora_data, L_orig
                    )
                    res.update({
                        "chokepoint":       choke_name,
                        "direction":        direction,
                        "industry":         ind,
                        "industry_name":    ind_name,
                        "ind_trade_100":    ind_trade,
                        "n_countries":      len(alt_status),
                        "n_no_alt":         len(no_alt_set),
                        "no_alt_countries": "|".join(sorted(no_alt_set)),
                    })
                    ind_results.append(res)
                    _log(f"mult_A={res['multiplier_A']}  Dind={res['Dind_total']/1e9:.3f}B$")

        except Exception:
            _log(f"     ✗ 出错:")
            traceback.print_exc()

    if not ind_results:
        _log(f"[{direction}] 无结果生成。")
        return

    # ── 保存长表 ─────────────────────────────────────────────────────────────
    col_order = [
        "chokepoint", "direction", "industry", "industry_name", "scenario",
        "n_countries", "n_no_alt", "no_alt_countries", "no_alt_frac",
        "ind_trade_100", "trade_total_100", "trade_total_S",
        "Dind_total", "Dind_chn", "Dind_row",
        "Dind_total_bw", "Dind_total_fw",
        "multiplier_B", "multiplier_A",
        "multiplier_A_chn", "multiplier_A_row",
    ]
    df_long   = pd.DataFrame(ind_results)[col_order]
    long_path = os.path.join(out_dir, f"{direction}_industry_shocks.csv")
    df_long.to_csv(long_path, index=False, encoding="utf-8-sig")
    _log(f"\n[{direction}] ✅ 长表 → {long_path}")

    # ── 保存宽表（每要道×行业一行，情景横向展开）─────────────────────────────
    fixed_cols = [
        "chokepoint", "direction", "industry", "industry_name",
        "n_countries", "n_no_alt", "no_alt_countries", "no_alt_frac",
        "ind_trade_100", "trade_total_100",
    ]
    metric_cols = [
        "trade_total_S", "Dind_total", "Dind_chn", "Dind_row",
        "multiplier_B", "multiplier_A", "multiplier_A_chn", "multiplier_A_row",
    ]

    wide_rows = []
    for (choke, ind), grp in df_long.groupby(["chokepoint", "industry"]):
        row = {c: grp.iloc[0][c] for c in fixed_cols}
        for s in SCENARIOS:
            lbl = f"s{int(s * 100)}"
            sr  = grp[grp["scenario"] == s]
            if not sr.empty:
                for m in metric_cols:
                    row[f"{m}_{lbl}"] = sr.iloc[0][m]
        wide_rows.append(row)

    df_wide   = pd.DataFrame(wide_rows)
    wide_path = os.path.join(out_dir, f"{direction}_industry_shocks.xlsx")
    df_wide.to_excel(wide_path, index=False, engine="openpyxl")
    _log(f"[{direction}] ✅ 宽表 → {wide_path}")

    # ── 打印 multiplier_A 汇总（100% 情景）──────────────────────────────────
    _log(f"\n[{direction}] multiplier_A 汇总（scenario=1.0）：")
    s100 = df_long[df_long["scenario"] == 1.0]
    pivot = s100.pivot_table(
        index="chokepoint", columns="industry_name",
        values="multiplier_A", aggfunc="first",
    )
    print(pivot.to_string())


def run(direction: str, eora_data: dict | None = None) -> None:
    t0 = datetime.datetime.now()

    if eora_data is None:
        eora_data = load_eora(EORA_PATH)

    _log(f"[{direction}] 预计算 Leontief 逆 (L_orig)...")
    A0     = eora_data["A_orig"]
    I_full = eora_data["I_full"]
    L_orig = np.linalg.inv(I_full - A0.values)

    _process_direction(direction, eora_data, L_orig)

    _log(f"[{direction}] Step 6b 完成，耗时 {datetime.datetime.now() - t0}")


if __name__ == "__main__":
    directions = sys.argv[1:] or ["CHN2World", "World2CHN"]
    eora = load_eora(EORA_PATH)
    for d in directions:
        run(d, eora_data=eora)
