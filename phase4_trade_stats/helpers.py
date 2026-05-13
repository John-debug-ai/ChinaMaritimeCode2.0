"""
phase4_trade_stats/helpers.py — 共享工具函数

所有步骤共用的常量、映射和辅助函数，避免重复定义。
"""

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import geopandas as gpd
import pandas as pd

from shared.config import RAW_DATA, OUTPUT_ROOT, BACI_MANUAL_CORRECTIONS
from shared.mappings import ISO_NUM_CORRECTIONS, ISIC_TO_SECTOR

# ─────────────────────────────────────────────────────────────────────────────
# 常量
# ─────────────────────────────────────────────────────────────────────────────

# Phase 4 输出根目录
TRADE_STATS_ROOT = os.path.join(OUTPUT_ROOT, "trade_stats")

# TTD 运输方式代码
MODE_TOTAL = "00"
MODE_AIR   = "10"
MODE_SEA   = "21"
MODE_LAND  = ("31", "32")

# BACI 补充时的默认分配比例（value / quantity）
BACI_DEFAULT_SPLIT = {
    "air_v":  0.2, "sea_v":  0.7, "land_v": 0.1,
    "air_q":  0.1, "sea_q":  0.8, "land_q": 0.1,
}

# 海运零值修正的默认比例（当 air+sea+land 全为 0 时使用）
SEA_ZERO_DEFAULT = {
    "air_v": 0.2, "sea_v": 0.7, "land_v": 0.1,
    "air_q": 0.1, "sea_q": 0.8, "land_q": 0.1,
}

# EORA 行业编号列表（字符串，两位）
SECTORS = [str(i).zfill(2) for i in range(1, 12)]


# ─────────────────────────────────────────────────────────────────────────────
# 路径辅助
# ─────────────────────────────────────────────────────────────────────────────

def trade_stats(*parts: str) -> str:
    """构建 trade_stats 子目录路径并自动创建。"""
    path = os.path.join(TRADE_STATS_ROOT, *parts)
    os.makedirs(path, exist_ok=True)
    return path


# ─────────────────────────────────────────────────────────────────────────────
# ISO 映射与修正
# ─────────────────────────────────────────────────────────────────────────────

def load_iso_map() -> dict[str, str]:
    """读取 ISO3.csv，返回 {iso_num_str: iso3} 字典（数字编号补零为3位）。"""
    df = pd.read_csv(RAW_DATA["iso3_map"])
    df["number"] = df["number"].astype(str).str.zfill(3)
    return df.set_index("number")["iso3"].to_dict()


def load_iso_region() -> pd.DataFrame:
    """读取 ISO3_带收入和地区.csv，返回 DataFrame（列：iso3, EnglishName, ChineseName,
    Income group, Region）。"""
    df = pd.read_csv(RAW_DATA["iso3_with_region"])
    return df


def apply_iso_corrections(df: pd.DataFrame, cols: list[str]) -> pd.DataFrame:
    """对指定列（通常是 Origin/Destination 数字编码列）执行 ISO 修正。"""
    for col in cols:
        if col in df.columns:
            df[col] = df[col].replace(ISO_NUM_CORRECTIONS)
    return df


# ─────────────────────────────────────────────────────────────────────────────
# 行业映射
# ─────────────────────────────────────────────────────────────────────────────

def build_sector_map() -> dict[str, str]:
    """从 ISIC_TO_SECTOR 构建 {isic2_code: sector_num_str} 映射。"""
    return {k: v[0] for k, v in ISIC_TO_SECTOR.items()}


def load_hs4_to_isic() -> dict[str, str]:
    """
    读取 hs4_to_isic2_mapping.csv，返回 {hs4_str: isic2_padded_str} 字典。
    ISIC2 中多个编码用逗号分隔，每个编码补零为两位。
    """
    df = pd.read_csv(RAW_DATA["hs4_isic2_map"], encoding="utf-8")
    df["HS4"] = df["HS4"].astype(str).str.zfill(4)
    result = {}
    for _, row in df.iterrows():
        codes = str(row["ISIC2"]).split(",")
        padded = ",".join(c.zfill(2) for c in codes)
        result[row["HS4"]] = padded
    return result


def assign_sectors(df: pd.DataFrame, product_col: str = "product") -> pd.DataFrame:
    """
    给 DataFrame 添加 ISIC2 和 sectors 两列。
    sectors 是 "01"~"11" 的字符串，未匹配到的填 "00"。
    """
    hs4_to_isic = load_hs4_to_isic()
    sector_map  = build_sector_map()

    df = df.copy()
    df["ISIC2"]   = df[product_col].map(hs4_to_isic)
    df["sectors"] = df["ISIC2"].apply(
        lambda x: sector_map.get(str(x), "00") if pd.notna(x) else "00"
    )
    return df


# ─────────────────────────────────────────────────────────────────────────────
# BACI 补充
# ─────────────────────────────────────────────────────────────────────────────

def load_baci_missing_countries(chn_iso_num: int, missing_j: list[int]) -> pd.DataFrame:
    """
    从 BACI_HS17_Y2019 中读取 i==chn_iso_num 且 j in missing_j 的行，
    按 HS2 聚合，添加默认运输分配比例，返回与主表格式相同的 DataFrame。

    返回列：origin, destination, iso_O, iso_D, product(HS2),
            total_v, total_q, air_v, sea_v, land_v,
            air_q, sea_q, land_q,
            air_v_ratio, sea_v_ratio, land_v_ratio,
            air_q_ratio, sea_q_ratio, land_q_ratio
    """
    iso_map = load_iso_map()

    usecols = ["i", "j", "k", "v", "q"]
    df = pd.read_csv(RAW_DATA["baci"], usecols=usecols)
    df = df[(df["i"] == chn_iso_num) & (df["j"].isin(missing_j))].copy()

    # 重命名，单位换算
    df.rename(columns={"i": "origin", "j": "destination", "k": "product",
                        "v": "total_v", "q": "total_q"}, inplace=True)
    df["product"]   = df["product"].astype(str).str.zfill(6).str[:4]
    df["total_v"]  *= 1000
    df["total_q"]  *= 1000

    # 默认运输分配
    for key, ratio in BACI_DEFAULT_SPLIT.items():
        base = "total_v" if key.endswith("_v") else "total_q"
        df[key] = df[base] * ratio

    # 比例列
    for mode in ("air", "sea", "land"):
        df[f"{mode}_v_ratio"] = BACI_DEFAULT_SPLIT[f"{mode}_v"]
        df[f"{mode}_q_ratio"] = BACI_DEFAULT_SPLIT[f"{mode}_q"]

    # ISO3 映射
    df["iso_O"] = df["origin"].astype(str).str.zfill(3).map(iso_map)
    df["iso_D"] = df["destination"].astype(str).str.zfill(3).map(iso_map)

    # HS2 聚合
    df["HS2"] = df["product"].str[:2]
    agg_cols = ["total_v","total_q","air_v","sea_v","land_v","air_q","sea_q","land_q"]
    grouped = (
        df.groupby(["origin","destination","iso_O","iso_D","HS2"], as_index=False)
          .agg({c: "sum" for c in agg_cols})
    )
    grouped.rename(columns={"HS2": "product"}, inplace=True)

    # 重新计算比例（聚合后比例不变，但统一计算）
    for mode in ("air", "sea", "land"):
        grouped[f"{mode}_v_ratio"] = BACI_DEFAULT_SPLIT[f"{mode}_v"]
        grouped[f"{mode}_q_ratio"] = BACI_DEFAULT_SPLIT[f"{mode}_q"]

    # TOTAL 行
    total_agg = (
        grouped.groupby(["origin","destination","iso_O","iso_D"], as_index=False)
               .agg({c: "sum" for c in agg_cols})
    )
    for mode in ("air", "sea", "land"):
        total_agg[f"{mode}_v_ratio"] = total_agg[f"{mode}_v"] / total_agg["total_v"]
        total_agg[f"{mode}_q_ratio"] = total_agg[f"{mode}_q"] / total_agg["total_q"]
    total_agg["product"] = "TOTAL"

    result = pd.concat([grouped, total_agg], ignore_index=True)
    return result


# ─────────────────────────────────────────────────────────────────────────────
# 海运零值修正
# ─────────────────────────────────────────────────────────────────────────────

def fill_sea_zeros(df: pd.DataFrame) -> pd.DataFrame:
    """
    对 sea_v==0 或 sea_q==0 的行做修正：
      - 若 air/land 全为 0 → 按 SEA_ZERO_DEFAULT 比例重分配
      - 否则 → sea = total - air - land（仅当结果 > 0 时写入）
    最后重新计算所有比例列。
    """
    df = df.copy()

    cond_sea_zero = (df["sea_v"] == 0) | (df["sea_q"] == 0)
    cond_all_zero = (
        (df["air_v"] == 0) & (df["air_q"] == 0) &
        (df["land_v"] == 0) & (df["land_q"] == 0)
    )

    # 情形 1：全部为零
    cond1 = cond_sea_zero & cond_all_zero
    for key, ratio in SEA_ZERO_DEFAULT.items():
        base = "total_v" if key.endswith("_v") else "total_q"
        df.loc[cond1, key] = df.loc[cond1, base] * ratio

    # 情形 2：非全零
    cond2 = cond_sea_zero & (~cond_all_zero)
    sea_v_new = df.loc[cond2, "total_v"] - df.loc[cond2, "land_v"] - df.loc[cond2, "air_v"]
    sea_q_new = df.loc[cond2, "total_q"] - df.loc[cond2, "land_q"] - df.loc[cond2, "air_q"]
    df.loc[cond2 & (sea_v_new > 0), "sea_v"] = sea_v_new[sea_v_new > 0]
    df.loc[cond2 & (sea_q_new > 0), "sea_q"] = sea_q_new[sea_q_new > 0]

    # 重新计算比例
    for mode in ("air", "sea", "land"):
        df[f"{mode}_v_ratio"] = df[f"{mode}_v"] / df["total_v"].replace(0, float("nan"))
        df[f"{mode}_q_ratio"] = df[f"{mode}_q"] / df["total_q"].replace(0, float("nan"))

    return df


# ─────────────────────────────────────────────────────────────────────────────
# Phase 1 GPKG 读取
# ─────────────────────────────────────────────────────────────────────────────

def gpkg_to_flows(gpkg_path: str) -> pd.DataFrame:
    """
    读取 Phase 1 输出的 GPKG 文件（shortest_paths_{direction}_with_flows.gpkg），
    将宽格式的 v1~v11 / q1~q11 转换为长格式。

    返回 DataFrame，列：
        start_id, end_id, start_iso3, end_iso3, sector(int 1-11), v_flow, q_flow
    """
    gdf = gpd.read_file(gpkg_path)
    df  = pd.DataFrame(gdf.drop(columns=["geometry"], errors="ignore"))

    id_cols = [c for c in ["start_id", "end_id", "start_iso3", "end_iso3"] if c in df.columns]
    v_cols  = [f"v{i}" for i in range(1, 12) if f"v{i}" in df.columns]
    q_cols  = [f"q{i}" for i in range(1, 12) if f"q{i}" in df.columns]

    df_v = df[id_cols + v_cols].melt(id_vars=id_cols, var_name="sector", value_name="v_flow")
    df_q = df[id_cols + q_cols].melt(id_vars=id_cols, var_name="sector", value_name="q_flow")

    df_v["sector"] = df_v["sector"].str[1:].astype(int)
    df_q["sector"] = df_q["sector"].str[1:].astype(int)

    result = df_v.merge(df_q, on=id_cols + ["sector"])
    result = result[(result["v_flow"] > 0) | (result["q_flow"] > 0)].copy()
    return result


# ─────────────────────────────────────────────────────────────────────────────
# Top-N 摘要
# ─────────────────────────────────────────────────────────────────────────────

def top_n_by(df: pd.DataFrame, group_col: str, value_col: str,
             n: int = 3) -> pd.DataFrame:
    """
    对 df 按 group_col 分组后，在每组内按 value_col 降序取前 n 行。
    适用于"每个海峡 top-N 行业"或"每个行业 top-N 国家"等场景。
    """
    return (
        df.sort_values(value_col, ascending=False)
          .groupby(group_col, sort=False)
          .head(n)
          .reset_index(drop=True)
    )
