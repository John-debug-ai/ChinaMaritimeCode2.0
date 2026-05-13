"""
Phase 4 / Step 1: 基础贸易统计表

从 TTD 数据提取中国相关的进出口贸易，赋予行业分类，
用 BACI 补充 TTD 未覆盖的国家，修正海运零值，
最终输出 CHN2World 和 World2CHN 两张基础表。

数据处理逻辑
------------
1. 读取 TTD，按方向过滤（Origin==CHN 或 Destination==CHN）
2. 修正 ISO 数字编码（757→756 等）
3. 分组汇总 air/sea/land 贸易值量及比例
4. CHN2World：对 MAC/MOZ/HKG 做总量替换修正
5. 用 BACI 补充 TTD 未覆盖的目的/来源国
6. 赋予 ISIC2 和 sectors 行业分类
7. 修正海运零值行
8. 输出到 output/trade_stats/base/

输出
----
output/trade_stats/base/
  CHN2World_trade.csv
  World2CHN_trade.csv
"""

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd

from shared.config import RAW_DATA, BACI_MANUAL_CORRECTIONS
from phase4_trade_stats.helpers import (
    trade_stats, load_iso_map, apply_iso_corrections,
    assign_sectors, load_baci_missing_countries, fill_sea_zeros,
    BACI_DEFAULT_SPLIT,
)

# ── 方向配置 ─────────────────────────────────────────────────────────────────
# chn_filter_col : TTD 中代表中国的那一列（数字编码）
# foreign_iso_col: 外国一侧的列名（数字编码）
# foreign_iso3_col: 输出表中外国 ISO3 列名
# chn_iso3_col   : 输出表中中国 ISO3 列名
DIRECTION_CONFIG = {
    "CHN2World": {
        "chn_filter_col":   "Origin",       # Origin == CHN（156）
        "foreign_iso_col":  "Destination",
        "foreign_iso3_col": "iso_D",
        "chn_iso3_col":     "iso_O",
        "apply_mac_fix":    True,           # CHN2World 才做 MAC/MOZ/HKG 修正
    },
    "World2CHN": {
        "chn_filter_col":   "Destination",  # Destination == CHN（156）
        "foreign_iso_col":  "Origin",
        "foreign_iso3_col": "iso_O",
        "chn_iso3_col":     "iso_D",
        "apply_mac_fix":    False,
    },
}

CHN_ISO_NUM_STR = "156"   # TTD 中中国的数字编码（字符串，修正后）
CHN_ISO_NUM_INT = 156      # BACI 中中国编码（整数）


def _process_ttd(direction: str) -> pd.DataFrame:
    """从 TTD 提取、汇总该方向的贸易数据，返回 DataFrame。"""
    cfg = DIRECTION_CONFIG[direction]
    chn_col     = cfg["chn_filter_col"]
    foreign_col = cfg["foreign_iso_col"]

    print(f"[P4 Step 1] {direction}: 读取 TTD ...")
    cols = ["Year", "Origin", "Destination", "Product", "TransportMode",
            "FOB value (US$)", "Kilograms"]
    dtype_spec = {c: (str if c in ("Year","Origin","Destination","Product","TransportMode")
                      else float)
                  for c in cols}
    df = pd.read_csv(RAW_DATA["ttd"], usecols=cols, dtype=dtype_spec)

    # ISO 编码修正
    df = apply_iso_corrections(df, ["Origin", "Destination"])

    # 过滤中国方向
    df = df[df[chn_col] == CHN_ISO_NUM_STR].copy()
    print(f"  TTD 过滤后: {len(df):,} 行")

    # ISO3 映射
    iso_map = load_iso_map()
    df["iso_O"] = df["Origin"].map(iso_map)
    df["iso_D"] = df["Destination"].map(iso_map)

    # 按 origin/destination/product 分组汇总
    results = []
    for (origin, destination, product), group in df.groupby(
            ["Origin", "Destination", "Product"]):
        total_v = group.loc[group["TransportMode"] == "00", "FOB value (US$)"].sum()
        total_q = group.loc[group["TransportMode"] == "00", "Kilograms"].sum()
        air_v   = group.loc[group["TransportMode"] == "10", "FOB value (US$)"].sum()
        air_q   = group.loc[group["TransportMode"] == "10", "Kilograms"].sum()
        sea_v   = group.loc[group["TransportMode"] == "21", "FOB value (US$)"].sum()
        sea_q   = group.loc[group["TransportMode"] == "21", "Kilograms"].sum()
        land_mask = group["TransportMode"].isin(["31", "32"])
        land_v  = group.loc[land_mask, "FOB value (US$)"].sum()
        land_q  = group.loc[land_mask, "Kilograms"].sum()

        results.append({
            "origin":      origin,
            "destination": destination,
            "iso_O":       iso_map.get(origin),
            "iso_D":       iso_map.get(destination),
            "product":     product,
            "total_v":     total_v,  "total_q": total_q,
            "air_v":       air_v,    "air_q":   air_q,
            "sea_v":       sea_v,    "sea_q":   sea_q,
            "land_v":      land_v,   "land_q":  land_q,
            "air_v_ratio":  air_v / total_v  if total_v != 0 else 0.0,
            "air_q_ratio":  air_q / total_q  if total_q != 0 else 0.0,
            "sea_v_ratio":  sea_v / total_v  if total_v != 0 else 0.0,
            "sea_q_ratio":  sea_q / total_q  if total_q != 0 else 0.0,
            "land_v_ratio": land_v / total_v if total_v != 0 else 0.0,
            "land_q_ratio": land_q / total_q if total_q != 0 else 0.0,
        })

    return pd.DataFrame(results)


def _apply_mac_correction(df: pd.DataFrame) -> pd.DataFrame:
    """
    CHN2World 专用：对 MAC/MOZ/HKG 按总量目标值做等比例缩放修正。
    BACI_MANUAL_CORRECTIONS = { iso3: (target_q, target_v) }
    """
    df = df.copy()
    for iso3, (target_q, target_v) in BACI_MANUAL_CORRECTIONS.items():
        mask = df["iso_D"] == iso3
        if not mask.any():
            continue
        total_mask = mask & (df["product"] == "TOTAL")
        if not total_mask.any():
            continue
        base_q = df.loc[total_mask, "total_q"].values[0]
        base_v = df.loc[total_mask, "total_v"].values[0]
        if base_q == 0 or base_v == 0:
            continue

        df.loc[mask, "total_q"] = target_q * (df.loc[mask, "total_q"] / base_q)
        df.loc[mask, "total_v"] = target_v * (df.loc[mask, "total_v"] / base_v)
        # 重新计算分类别值
        for mode in ("air", "sea", "land"):
            df.loc[mask, f"{mode}_v"] = df.loc[mask, "total_v"] * df.loc[mask, f"{mode}_v_ratio"]
            df.loc[mask, f"{mode}_q"] = df.loc[mask, "total_q"] * df.loc[mask, f"{mode}_q_ratio"]

        print(f"  MAC/MOZ/HKG 修正：{iso3} → Q={target_q:,}, V={target_v:,}")

    return df


def _find_missing_countries(df: pd.DataFrame, direction: str) -> list[int]:
    """
    找出 BACI 中有但 TTD 中没有的目的/来源国，返回其整数编码列表。
    只针对 CHN2World (iso_D) 或 World2CHN (iso_O)。
    """
    foreign_col = "iso_D" if direction == "CHN2World" else "iso_O"
    ttd_countries = set(df[foreign_col].dropna().unique())

    # 读取 BACI，筛选 CHN 的交易对手
    usecols = ["i", "j", "v"]
    baci = pd.read_csv(RAW_DATA["baci"], usecols=usecols)
    if direction == "CHN2World":
        baci_partners = set(baci.loc[baci["i"] == CHN_ISO_NUM_INT, "j"].unique())
    else:
        baci_partners = set(baci.loc[baci["j"] == CHN_ISO_NUM_INT, "i"].unique())

    # 将 BACI 整数编码转为 ISO3
    iso_map_int_to_iso3 = load_iso_map()  # key 是 3 位字符串
    baci_iso3 = set()
    for j_int in baci_partners:
        iso3 = iso_map_int_to_iso3.get(str(j_int).zfill(3))
        if iso3:
            baci_iso3.add(iso3)

    missing_iso3 = baci_iso3 - ttd_countries

    # 回转为整数编码列表
    iso3_to_num = {v: int(k) for k, v in iso_map_int_to_iso3.items()}
    missing_j = [iso3_to_num[iso3] for iso3 in missing_iso3 if iso3 in iso3_to_num]
    print(f"  BACI 补充：{len(missing_j)} 个 TTD 未覆盖国家")
    return missing_j


def run(direction: str) -> None:
    """
    direction: "CHN2World" 或 "World2CHN"
    """
    cfg = DIRECTION_CONFIG[direction]
    out_dir = trade_stats("base")
    out_path = os.path.join(out_dir, f"{direction}_trade.csv")

    # ── Step A: TTD 处理 ──────────────────────────────────────────────────
    df = _process_ttd(direction)

    # ── Step B: MAC/MOZ/HKG 修正（仅 CHN2World）─────────────────────────
    if cfg["apply_mac_fix"]:
        df = _apply_mac_correction(df)

    # ── Step C: BACI 补充 ─────────────────────────────────────────────────
    # missing_countries 为未被 TTD 覆盖的外国整数编码列表
    missing_countries = _find_missing_countries(df, direction)
    if missing_countries:
        if direction == "CHN2World":
            # i=CHN(156), j=外国：使用 helpers 中的通用函数
            baci_supp = load_baci_missing_countries(CHN_ISO_NUM_INT, missing_countries)
        else:
            # World2CHN：i=外国, j=CHN(156)，使用专用函数
            baci_supp = load_baci_missing_countries_w2c(missing_countries)
        df = pd.concat([df, baci_supp], ignore_index=True)

    # ── Step D: 赋予行业分类 ──────────────────────────────────────────────
    df = assign_sectors(df, product_col="product")

    # ── Step E: 修正海运零值 ──────────────────────────────────────────────
    df = fill_sea_zeros(df)

    # ── 保存 ──────────────────────────────────────────────────────────────
    df.to_csv(out_path, index=False, encoding="utf-8-sig")
    print(f"[P4 Step 1] {direction}: ✅ → {out_path}（{len(df):,} 行）")


def load_baci_missing_countries_w2c(missing_i: list[int]) -> pd.DataFrame:
    """
    World2CHN 的 BACI 补充：i=外国, j=156（中国）。
    返回与主表格式相同的 DataFrame，iso_O=外国, iso_D=CHN。
    """
    iso_map = load_iso_map()

    usecols = ["i", "j", "k", "v", "q"]
    df = pd.read_csv(RAW_DATA["baci"], usecols=usecols)
    df = df[(df["j"] == CHN_ISO_NUM_INT) & (df["i"].isin(missing_i))].copy()

    df.rename(columns={"i": "origin", "j": "destination", "k": "product",
                        "v": "total_v", "q": "total_q"}, inplace=True)
    df["product"]  = df["product"].astype(str).str.zfill(6).str[:4]
    df["total_v"] *= 1000
    df["total_q"] *= 1000

    for key, ratio in BACI_DEFAULT_SPLIT.items():
        base = "total_v" if key.endswith("_v") else "total_q"
        df[key] = df[base] * ratio

    for mode in ("air", "sea", "land"):
        df[f"{mode}_v_ratio"] = BACI_DEFAULT_SPLIT[f"{mode}_v"]
        df[f"{mode}_q_ratio"] = BACI_DEFAULT_SPLIT[f"{mode}_q"]

    df["iso_O"] = df["origin"].astype(str).str.zfill(3).map(iso_map)
    df["iso_D"] = df["destination"].astype(str).str.zfill(3).map(iso_map)

    df["HS2"] = df["product"].str[:2]
    agg_cols = ["total_v","total_q","air_v","sea_v","land_v","air_q","sea_q","land_q"]
    grouped = (
        df.groupby(["origin","destination","iso_O","iso_D","HS2"], as_index=False)
          .agg({c: "sum" for c in agg_cols})
    )
    grouped.rename(columns={"HS2": "product"}, inplace=True)
    for mode in ("air", "sea", "land"):
        grouped[f"{mode}_v_ratio"] = BACI_DEFAULT_SPLIT[f"{mode}_v"]
        grouped[f"{mode}_q_ratio"] = BACI_DEFAULT_SPLIT[f"{mode}_q"]

    total_agg = (
        grouped.groupby(["origin","destination","iso_O","iso_D"], as_index=False)
               .agg({c: "sum" for c in agg_cols})
    )
    for mode in ("air", "sea", "land"):
        total_agg[f"{mode}_v_ratio"] = total_agg[f"{mode}_v"] / total_agg["total_v"]
        total_agg[f"{mode}_q_ratio"] = total_agg[f"{mode}_q"] / total_agg["total_q"]
    total_agg["product"] = "TOTAL"

    return pd.concat([grouped, total_agg], ignore_index=True)


if __name__ == "__main__":
    for d in ["CHN2World", "World2CHN"]:
        run(d)
