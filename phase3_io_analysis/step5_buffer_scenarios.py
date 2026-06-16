"""
Phase 3 / Step 5: 缓冲情景 MRIO 计算

在 25% / 50% / 75% / 100% 四个贸易中断情景下，计算各海运要道对全球
和中国产出的影响，并评估"有无替代路线"的缓冲效果。

核心逻辑
--------
1. 替代路线判断（每要道一次）
   - 要道路径识别：对全量 GPKG 做空间相交（复用 step1 逻辑），但不过滤零流量行，
     确保 choke_pairs 集合完整（避免漏标导致误判"有替代"）
   - 端口级：该港口自身是否有不经过该要道即可到达CHN（或来自CHN）的路线
   - 距离阈值（DETOUR_THRESHOLD=1.5）：替代路线最短距离 / 要道路线最短距离 ≤ 阈值
     → 绕行倍率过高的路线视为"不可行替代"
   - 国家级：该国任意港口满足连通性 + 距离阈值，即判定为"有替代路线"
   → 有替代路线的国家：v_share_trade × scenario（按情景缩放）
   → 无替代路线的国家：v_share_trade 保持100%（中断不受情景缓冲）

2. 流量提取
   - 只取 port_export 行，按 (iso3_O, iso3_D, Industries) 汇总
   - 避免 port_export / port_trans / port_import 三重计数

3. MRIO 计算（每个"要道 × 情景 × 方向"运行一次）
   - Backward 联系：A 矩阵冲击 + Y 矩阵冲击 → Leontief 逆
   - Forward 联系：B 矩阵冲击 → Ghosian 逆

输出指标
--------
  no_alt_frac   无替代路线贸易占该要道总贸易比例
  Dind_total    全球绝对产出损失（$）
  Dind_chn      中国产出损失
  Dind_row      其他国家产出损失
  multiplier_B  主乘数（分母固定为100%基准贸易损失，体现缓冲效果变化）
  multiplier_A  参考乘数（分母为情景实际贸易损失，接近常数）

输出目录
--------
  output/mrio/{direction}/buffer/
    {direction}_buffer_results.csv   长表（每要道×情景一行）
    {direction}_宽表汇总.xlsx         宽表（每要道一行，四情景横向展开）
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

from shared.config import EORA_PATH, CHN_ISO3, out, mrio, disrupt, CHOKEPOINTS_DIR
from shared.mrio_utils import (
    load_eora,
    modify_A_matrix,
    modify_Y_matrix,
    modify_B_matrix,
)

# ── 情景配置 ──────────────────────────────────────────────────────────────────
SCENARIOS = [1.0, 0.75, 0.5, 0.25]   # 贸易中断比例（100% → 25%）

# ── 替代路线距离阈值 ──────────────────────────────────────────────────────────
# 若替代路线（不经要道的最短绕行距离）/ 原要道路线最短距离 > DETOUR_THRESHOLD，
# 则视为"无可行替代路线"（绕行成本过高）。
# 设为 None 可禁用距离检验（仅判断连通性）。
DETOUR_THRESHOLD: float | None = 1.5

# ── 方向配置 ──────────────────────────────────────────────────────────────────
# filter_iso_col : 全量路线 GPKG 中用于过滤 CHN 方向的列
# foreign_check  : 判断替代路线时，"外国"对应的 iso3 列（在汇总贸易流量中）
# port_match_col : 要道 CSV 中用于提取"本方向主导端"港口 ID 的列
DIRECTION_CONFIG = {
    "World2CHN": {
        "filter_iso_col":  "end_iso3",    # 终点 = CHN
        "foreign_check":   "iso3_O",      # 外国是出口方
        "port_match_col":  "start_id",    # 要道CSV中 start_id 是外国港口
        "alt_foreign_col": "start_iso3",  # compute_alt_status 用
        "alt_port_col":    "start_id",
        "alt_other_col":   "end_id",
    },
    "CHN2World": {
        "filter_iso_col":  "start_iso3",  # 起点 = CHN
        "foreign_check":   "iso3_D",      # 外国是进口方
        "port_match_col":  "start_id",    # 要道CSV中 start_id 是CHN港口
        "alt_foreign_col": "end_iso3",    # compute_alt_status 用
        "alt_port_col":    "end_id",
        "alt_other_col":   "start_id",
    },
}


# ── 工具函数 ──────────────────────────────────────────────────────────────────

def _log(msg: str, end: str = "\n") -> None:
    ts = datetime.datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {msg}", end=end, flush=True)


# ── 替代路线判断 ──────────────────────────────────────────────────────────────

def compute_alt_status(
    choke_df: pd.DataFrame,
    full_routes_df: pd.DataFrame,
    cfg: dict,
    detour_threshold: float | None = DETOUR_THRESHOLD,
) -> tuple[dict, set]:
    """
    判断每个外国在该要道关闭后是否还有可行的替代路线到/来自 CHN。

    判断逻辑
    --------
    对某国每个港口：
      1. 连通性检验：是否存在不经过该要道的目的/来源港口对（alt 路由集合非空）
      2. 距离阈值检验（当 detour_threshold 非 None 时）：
             L_alt_min / L_choke_min ≤ detour_threshold
         即替代路线绕行倍率不超过阈值才视为"可行替代"
    只要该国任一港口满足以上两点，该国即判定为"有替代路线"。

    Parameters
    ----------
    choke_df          : 当前要道的路线 CSV DataFrame（含 port_col/other_col/foreign_col）
    full_routes_df    : 完整方向路线 DataFrame（已过滤为 CHN 方向，含 "length" 列）
    cfg               : DIRECTION_CONFIG 中的方向配置项
    detour_threshold  : 距离倍率阈值；None 表示仅做连通性判断，不施加距离约束

    Returns
    -------
    alt_status : {iso3: True(有替代) / False(无替代)}
    no_alt_set : 无替代路线的国家集合
    """
    foreign_col = cfg["alt_foreign_col"]
    port_col    = cfg["alt_port_col"]
    other_col   = cfg["alt_other_col"]
    has_length  = "length" in full_routes_df.columns and detour_threshold is not None

    # 要道中 (本侧港口, 对侧港口) 配对集合，用于快速判断某条路线是否过要道
    choke_pairs = set(
        zip(choke_df[port_col].astype(str), choke_df[other_col].astype(str))
    )

    # 为全量路线打上 via_choke 标记（向量化，避免逐行循环）
    routes = full_routes_df.copy()
    routes["_port"]      = routes[port_col].astype(str)
    routes["_other"]     = routes[other_col].astype(str)
    routes["_via_choke"] = list(
        zip(routes["_port"], routes["_other"])
    )
    routes["_via_choke"] = routes["_via_choke"].isin(choke_pairs)

    alt_status: dict = {}

    for country in choke_df[foreign_col].unique():
        country_routes = routes[routes[foreign_col] == country]

        # ── 诊断计数器 ────────────────────────────────────────────────────────
        n_ports_total        = country_routes["_port"].nunique()
        n_no_path            = 0   # 完全无非要道路径的港口数
        n_threshold_rejected = 0   # 有替代路径但超阈值的港口数
        n_threshold_passed   = 0   # 有可行替代路径的港口数（一旦>0即可判定has_alt）

        has_alt = False
        for port, port_routes in country_routes.groupby("_port"):
            via = port_routes[port_routes["_via_choke"]]
            alt = port_routes[~port_routes["_via_choke"]]

            if alt.empty:
                # 该港口完全没有绕行路径（网络孤立或完全依赖该要道）
                n_no_path += 1
                continue

            if not has_length:
                # 无距离约束 → 连通即可行
                n_threshold_passed += 1
                has_alt = True
                break

            # 距离阈值检验：替代路线最短距离 vs 要道路线最短距离
            L_alt = alt["length"].min()
            if via.empty:
                # 该港口在全量路线中无经过要道的路径 → 直接视为有替代
                n_threshold_passed += 1
                has_alt = True
                break

            L_choke = via["length"].min()
            ratio   = L_alt / L_choke if L_choke > 0 else float("inf")
            if ratio <= detour_threshold:
                n_threshold_passed += 1
                has_alt = True
                break
            else:
                n_threshold_rejected += 1

        alt_status[country] = has_alt

        # ── 详细诊断输出（每个国家一行）────────────────────────────────────
        if has_alt:
            status_str = "✓ 有替代"
        else:
            reasons = []
            if n_no_path > 0:
                reasons.append(f"{n_no_path}个港口完全无绕行路径")
            if n_threshold_rejected > 0:
                reasons.append(f"{n_threshold_rejected}个港口绕行倍率>阈值{detour_threshold}")
            reason_str = "；".join(reasons) if reasons else "所有港口均无可行替代"
            status_str = f"✗ 无替代（{reason_str}）"

        _log(
            f"       {country:6s}  共{n_ports_total}个港口  "
            f"无绕行:{n_no_path}  超阈值:{n_threshold_rejected}  "
            f"通过:{n_threshold_passed}  → {status_str}"
        )

    no_alt_set = {c for c, v in alt_status.items() if not v}
    return alt_status, no_alt_set


# ── 单个"要道 × 情景"的完整 MRIO 计算 ──────────────────────────────────────

def run_scenario(
    all_flows_100: pd.DataFrame,
    alt_status: dict,
    foreign_check: str,
    scenario: float,
    eora_data: dict,
    L_orig: np.ndarray,
) -> dict:
    """
    对给定要道在情景 scenario 下运行一次 MRIO 计算。

    Parameters
    ----------
    all_flows_100  : 100% 中断下该要道涉及的汇总贸易流量
                     (iso3_O, iso3_D, Industries, v_share_trade)
    alt_status     : {iso3: bool}，外国是否有替代路线
    foreign_check  : all_flows_100 中外国 ISO3 所在列名
    scenario       : 贸易中断比例，0.25 / 0.50 / 0.75 / 1.00
    eora_data      : load_eora() 返回的预计算字典
    L_orig         : 预计算的 Leontief 逆 np.linalg.inv(I - A0)

    Returns
    -------
    dict，含全部输出指标
    """
    A0  = eora_data["A_orig"]
    Y0  = eora_data["Y_orig"]
    Z0  = eora_data["Z_orig"]
    B0  = eora_data["B_orig"]
    I   = eora_data["I_full"]
    v   = eora_data["v_ndarray"]
    x0  = eora_data["x_indout"]
    lc  = eora_data["list_countries"]
    sc  = eora_data["sectors"]
    chn_idx = eora_data["chn_idx"]

    g0   = eora_data["global_out_0"]
    c0   = eora_data["chn_out_0"]
    gC0  = eora_data["global_C_0"]
    cC0  = eora_data["chn_C_0"]
    rC0  = eora_data["row_C_0"]

    # ── (1) 100% 基准贸易损失（multiplier_B 分母，固定不变）──────────────────
    _, ti100 = modify_A_matrix(A0, Z0, all_flows_100, lc, sc)
    _, tC100 = modify_Y_matrix(Y0, all_flows_100, lc, sc)
    trade_total_100 = ti100 + tC100

    # ── (2) 无替代路线贸易占比 ───────────────────────────────────────────────
    no_alt_mask  = all_flows_100[foreign_check].map(lambda x: not alt_status.get(x, True))
    no_alt_flows = all_flows_100[no_alt_mask]
    if not no_alt_flows.empty:
        _, nai = modify_A_matrix(A0, Z0, no_alt_flows, lc, sc)
        _, naC = modify_Y_matrix(Y0, no_alt_flows, lc, sc)
        no_alt_trade = nai + naC
    else:
        no_alt_trade = 0.0
    no_alt_frac = (no_alt_trade / trade_total_100) if trade_total_100 > 0 else np.nan

    # ── (3) 按情景缩放 v_share_trade ─────────────────────────────────────────
    flows_S = all_flows_100.copy()
    has_alt = flows_S[foreign_check].map(lambda x: alt_status.get(x, True))
    flows_S.loc[has_alt, "v_share_trade"] *= scenario
    # 无替代路线的行保持原值（始终 100% 中断）

    # ── (4) Backward 联系（Leontief）────────────────────────────────────────
    A_mod, ti_S = modify_A_matrix(A0, Z0, flows_S, lc, sc)
    Y_mod, tC_S = modify_Y_matrix(Y0, flows_S, lc, sc)
    trade_total_S = ti_S + tC_S

    # A 冲击：中间投入减少 → 重新计算 Leontief 逆
    L_mod  = np.linalg.inv(I - A_mod.values)
    out_A  = np.dot(L_mod, Y0.values)
    g_A    = float(out_A.sum())
    chn_A  = float(out_A.sum(axis=1)[chn_idx].sum())

    # Y 冲击：最终消费减少（L_orig 预计算，传入后直接使用）
    out_Y  = np.dot(L_orig, Y_mod.values)
    g_Y    = float(out_Y.sum())
    chn_Y  = float(out_Y.sum(axis=1)[chn_idx].sum())

    # CHN 消费变化（供 Forward 计算使用）
    chn_C_new = float(Y_mod["CHN"].sum().sum())
    g_C_new   = float(Y_mod.sum().sum())
    DC_chn    = cC0 - chn_C_new
    DC_row    = rC0 - (g_C_new - chn_C_new)

    Dind_bw     = (g0 - g_A)   + (g0 - g_Y)
    Dind_chn_bw = (c0 - chn_A) + (c0 - chn_Y)
    Dind_row_bw = Dind_bw - Dind_chn_bw

    # ── (5) Forward 联系（Ghosian）──────────────────────────────────────────
    B_mod  = modify_B_matrix(B0, Z0, flows_S, lc, sc)
    indin  = np.dot(v, np.linalg.inv(I - B_mod.values))
    diff   = x0 - indin

    total_diff = float(diff.sum())
    chn_diff   = float(diff[chn_idx].sum())
    row_diff   = total_diff - chn_diff

    Dind_fw     = total_diff + tC_S
    Dind_chn_fw = chn_diff   + DC_chn
    Dind_row_fw = row_diff   + DC_row

    # ── (6) 汇总 ─────────────────────────────────────────────────────────────
    Dind_total = Dind_bw  + Dind_fw
    Dind_chn   = Dind_chn_bw + Dind_chn_fw
    Dind_row   = Dind_row_bw + Dind_row_fw

    mB     = round(Dind_total / trade_total_100, 4) if trade_total_100 > 0 else np.nan
    mA     = round(Dind_total / trade_total_S,   4) if trade_total_S   > 0 else np.nan
    mA_chn = round(Dind_chn   / trade_total_S,   4) if trade_total_S   > 0 else np.nan
    mA_row = round(Dind_row   / trade_total_S,   4) if trade_total_S   > 0 else np.nan

    return {
        "scenario":         scenario,
        "trade_total_100":  trade_total_100,
        "trade_total_S":    trade_total_S,
        "no_alt_frac":      round(float(no_alt_frac), 4) if not np.isnan(no_alt_frac) else np.nan,
        "Dind_total":       Dind_total,
        "Dind_chn":         Dind_chn,
        "Dind_row":         Dind_row,
        "Dind_total_bw":    Dind_bw,
        "Dind_total_fw":    Dind_fw,
        "multiplier_B":     mB,
        "multiplier_A":     mA,
        "multiplier_A_chn": mA_chn,    # 新增：CHN 损失 / 情景下贸易冲击量
        "multiplier_A_row": mA_row,    # 新增：其他国家损失 / 情景下贸易冲击量
    }


# ── 处理单个方向的所有要道 ────────────────────────────────────────────────────

def _process_direction(
    direction: str,
    eora_data: dict,
    L_orig: np.ndarray,
) -> None:
    """遍历 CHOKEPOINTS_DIR 中的要道 SHP，对每个要道×每个情景运行 MRIO，
    汇总后保存长表 CSV 和宽表 XLSX。

    要道路径的识别方式：在函数内部对全量 GPKG 做空间相交（复用 step1 逻辑），
    但不过滤零流量行，保证 choke_pairs 集合完整，避免误判替代路线。
    """
    cfg = DIRECTION_CONFIG[direction]

    out_dir    = mrio(direction, "buffer")
    ports_path = os.path.join(mrio(direction, "input"), f"{direction}_ports_updated.csv")
    routes_gpkg = os.path.join(
        out(direction, "routes"),
        f"shortest_paths_{direction}_with_flows.gpkg",
    )

    filter_iso_col = cfg["filter_iso_col"]
    foreign_check  = cfg["foreign_check"]
    port_match_col = cfg["port_match_col"]

    # ── 检查前置文件 ─────────────────────────────────────────────────────────
    for path, label in [
        (CHOKEPOINTS_DIR, "要道SHP目录"),
        (ports_path,      "ports_updated.csv"),
        (routes_gpkg,     "全量路线GPKG"),
    ]:
        if not os.path.exists(path):
            _log(f"[{direction}] ⚠ {label} 不存在: {path}，跳过此方向。")
            return

    # ── 加载全量路线（含 geometry，用于空间相交 + 替代路线判断）──────────────
    _log(f"[{direction}] 加载全量路线 GPKG（含 geometry）...")
    route_cols = ["start_id", "end_id", "start_iso3", "end_iso3", "length"]
    full_routes_geo = gpd.read_file(routes_gpkg)
    full_routes_geo = full_routes_geo[
        full_routes_geo[filter_iso_col] == CHN_ISO3
    ].reset_index(drop=True)
    # 无 geometry 版本供 compute_alt_status 使用（纯属性比对，不需要几何）
    full_routes = full_routes_geo[route_cols].copy()
    _log(f"[{direction}] 全量路线: {len(full_routes):,} 条  "
         f"（替代路线距离阈值: {DETOUR_THRESHOLD}x）")

    # ── 加载港口贸易流量（只保留 port_export 行）────────────────────────────
    ports_df  = pd.read_csv(ports_path)
    ports_exp = ports_df[ports_df["flow"] == "port_export"].copy()
    _log(f"[{direction}] port_export 行数: {len(ports_exp):,}")

    # ── 遍历要道 SHP ─────────────────────────────────────────────────────────
    shp_files = sorted(f for f in os.listdir(CHOKEPOINTS_DIR) if f.lower().endswith(".shp"))
    _log(f"[{direction}] 发现 {len(shp_files)} 个要道，"
         f"共 {len(shp_files) * len(SCENARIOS)} 次 MRIO 计算")

    all_results = []

    for fname in shp_files:
        choke_name = os.path.splitext(fname)[0]
        _log(f"\n[{direction}] ▶ {choke_name}")

        try:
            # 1. 空间相交：筛选经过该要道的所有路径（不过滤零流量）
            points = gpd.read_file(os.path.join(CHOKEPOINTS_DIR, fname))
            if full_routes_geo.crs != points.crs:
                points = points.to_crs(full_routes_geo.crs)
            choke_routes = full_routes_geo[
                full_routes_geo.geometry.intersects(points.union_all())
            ].copy()
            choke_df = pd.DataFrame(choke_routes[route_cols])   # 去 geometry
            _log(f"     空间相交路径: {len(choke_df)} 条（含零流量）")

            if choke_df.empty:
                _log(f"     ⚠ 无路径与该要道相交，跳过")
                continue

            # 2. 替代路线判断（含逐国家诊断输出）
            _log(f"     替代路线判断（阈值={DETOUR_THRESHOLD}x）:")
            alt_status, no_alt_set = compute_alt_status(
                choke_df, full_routes, cfg, detour_threshold=DETOUR_THRESHOLD
            )
            _log(f"     ▷ 外国数={len(alt_status)}  "
                 f"有替代={len(alt_status) - len(no_alt_set)}  "
                 f"无替代={len(no_alt_set)}: {sorted(no_alt_set)}")

            # 3. 提取该要道涉及的 port_export 贸易流量
            choke_port_ids = choke_df[port_match_col].unique().tolist()
            sub = ports_exp[ports_exp["id"].isin(choke_port_ids)]

            if sub.empty:
                _log(f"     ⚠ 无匹配的 port_export 行，跳过")
                continue

            # 按 (iso3_O, iso3_D, Industries) 汇总，避免多港口重复计数
            all_flows_100 = (
                sub
                .groupby(["iso3_O", "iso3_D", "Industries"], as_index=False)["v_share_trade"]
                .sum()
            )
            _log(f"     匹配港口={sub['id'].nunique()}  流量行={len(all_flows_100)}")

            # 4. 逐情景计算
            for s in SCENARIOS:
                _log(f"     情景{int(s * 100):3d}% ... ", end="")
                res = run_scenario(
                    all_flows_100, alt_status, foreign_check, s, eora_data, L_orig
                )
                res.update({
                    "chokepoint":        choke_name,
                    "direction":         direction,
                    "n_countries":       len(alt_status),
                    "n_no_alt":          len(no_alt_set),
                    "no_alt_countries":  "|".join(sorted(no_alt_set)),
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
        "trade_total_100", "trade_total_S",
        "Dind_total", "Dind_chn", "Dind_row",
        "Dind_total_bw", "Dind_total_fw",
        "multiplier_B", "multiplier_A",
    ]
    df_long   = pd.DataFrame(all_results)[col_order]
    long_path = os.path.join(out_dir, f"{direction}_buffer_results.csv")
    df_long.to_csv(long_path, index=False, encoding="utf-8-sig")
    _log(f"\n[{direction}] ✅ 长表 → {long_path}")

    # ── 保存宽表 ─────────────────────────────────────────────────────────────
    fixed_cols  = ["chokepoint", "direction", "n_countries", "n_no_alt",
                   "no_alt_countries", "no_alt_frac", "trade_total_100"]
    metric_cols = ["trade_total_S", "Dind_total", "Dind_chn", "Dind_row",
                   "multiplier_B", "multiplier_A"]

    wide_rows = []
    for choke in df_long["chokepoint"].unique():
        sub_c = df_long[df_long["chokepoint"] == choke]
        row   = {c: sub_c.iloc[0][c] for c in fixed_cols}
        for s in SCENARIOS:
            lbl  = f"s{int(s * 100)}"
            sr   = sub_c[sub_c["scenario"] == s]
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
    """加载 EORA26 并返回预计算字典（与 step2 共用，避免重复加载）。"""
    return load_eora(EORA_PATH)


def run(direction: str, eora_data: dict | None = None) -> None:
    """
    运行 Phase 3 Step 5 缓冲情景分析。

    Parameters
    ----------
    direction  : "CHN2World" 或 "World2CHN"
    eora_data  : load_eora() 返回的预计算字典；若为 None 则在函数内部加载。
    """
    t0 = datetime.datetime.now()

    if eora_data is None:
        eora_data = load_eora_once()

    # 预计算 Leontief 逆（L_orig = (I - A0)^{-1}），用于 Y 矩阵冲击
    # 只需计算一次，在所有要道和情景间共用
    _log(f"[{direction}] 预计算 Leontief 逆 (L_orig)...")
    A0     = eora_data["A_orig"]
    I_full = eora_data["I_full"]
    L_orig = np.linalg.inv(I_full - A0.values)
    _log(f"[{direction}] L_orig 计算完毕")

    _process_direction(direction, eora_data, L_orig)

    _log(f"[{direction}] Step 5 完成，耗时 {datetime.datetime.now() - t0}")


if __name__ == "__main__":
    eora = load_eora_once()
    for d in ["CHN2World", "World2CHN"]:
        run(d, eora_data=eora)
