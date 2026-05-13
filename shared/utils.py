"""
shared/utils.py — 各步骤共用的工具函数
"""

import os
import numpy as np
import pandas as pd

from shared.config import RAW_DATA, SEA_V_DEFAULT_RATIO, SEA_Q_DEFAULT_RATIO
from shared.mappings import ISO_NUM_CORRECTIONS, SECTOR_MAPPING


# ─────────────────────────────────────────────────────────────────────────────
# 数据加载
# ─────────────────────────────────────────────────────────────────────────────

def load_iso_map() -> dict[str, str]:
    """加载 ISO 数字编码 → ISO3 字母编码映射字典。"""
    df = pd.read_csv(RAW_DATA["iso3_map"])
    df["number"] = df["number"].astype(str)
    df["iso3"]   = df["iso3"].astype(str)
    return df.set_index("number")["iso3"].to_dict()


def load_hs4_isic_map() -> dict[str, str]:
    """加载 HS4 产品编码 → ISIC2 行业编码映射字典。

    HS4 补零至 4 位；ISIC2 中多个编码以逗号分隔，每段补零至 2 位。
    示例返回：{"0101": "01", "2601": "13", "8471": "30", ...}
    """
    df = pd.read_csv(RAW_DATA["hs4_isic2_map"], encoding="utf-8")
    df["HS4"]  = df["HS4"].astype(str).str.zfill(4)
    df["ISIC2"] = df["ISIC2"].astype(str)

    result = {}
    for _, row in df.iterrows():
        padded = ",".join(c.strip().zfill(2) for c in row["ISIC2"].split(","))
        result[row["HS4"]] = padded
    return result


# ─────────────────────────────────────────────────────────────────────────────
# 数据清洗
# ─────────────────────────────────────────────────────────────────────────────

def fix_iso_codes(df: pd.DataFrame, cols: list[str]) -> pd.DataFrame:
    """对指定列应用 ISO 数字编码修正（字符串版本）。"""
    for col in cols:
        df[col] = df[col].astype(str).replace(ISO_NUM_CORRECTIONS)
    return df


def fill_sea_defaults(df: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    """当 total != 0 但 sea == 0 时，用默认比例填补 sea_v / sea_q。

    返回 (修改后的 DataFrame, 修改的总行数)。
    """
    df = df.copy()
    changes = 0

    v_mask = (df["total_v"] != 0) & (df["sea_v"] == 0)
    if v_mask.any():
        df.loc[v_mask, "sea_v"]       = df.loc[v_mask, "total_v"] * SEA_V_DEFAULT_RATIO
        df.loc[v_mask, "sea_v_ratio"] = SEA_V_DEFAULT_RATIO
        changes += int(v_mask.sum())

    q_mask = (df["total_q"] != 0) & (df["sea_q"] == 0)
    if q_mask.any():
        df.loc[q_mask, "sea_q"]       = df.loc[q_mask, "total_q"] * SEA_Q_DEFAULT_RATIO
        df.loc[q_mask, "sea_q_ratio"] = SEA_Q_DEFAULT_RATIO
        changes += int(q_mask.sum())

    return df, changes


# ─────────────────────────────────────────────────────────────────────────────
# 港口流量比例计算
# ─────────────────────────────────────────────────────────────────────────────

def compute_port_ratios(sub_df: pd.DataFrame) -> pd.DataFrame:
    """为单个 (country, industry) 数据块计算四种港口流量比例。

    对每种 flow 类型（port_import / port_export）分别计算：
      q_import_ratio, q_export_ratio, v_import_ratio, v_export_ratio
    非对应 flow 类型的行该比例列保持为 0。
    """
    sub_df = sub_df.copy()

    for flow_type, ratio_col, val_col in [
        ("port_import",  "q_import_ratio",  "q_sea_flow"),
        ("port_export",  "q_export_ratio",  "q_sea_flow"),
        ("port_import",  "v_import_ratio",  "v_sea_flow"),
        ("port_export",  "v_export_ratio",  "v_sea_flow"),
    ]:
        mask  = sub_df["flow"] == flow_type
        total = sub_df.loc[mask, val_col].sum()
        sub_df[ratio_col] = 0.0
        if total > 0:
            sub_df.loc[mask, ratio_col] = sub_df.loc[mask, val_col] / total

    return sub_df


# ─────────────────────────────────────────────────────────────────────────────
# 行业分类
# ─────────────────────────────────────────────────────────────────────────────

def classify_sectors(df: pd.DataFrame, output_dir: str) -> None:
    """按 ISIC2 → EORA 11 大类分类，将各类结果保存为独立 CSV。

    文件命名格式：{sector_num}_{sector_name}.csv，如 01_Agriculture.csv
    """
    os.makedirs(output_dir, exist_ok=True)
    df = df.copy()
    if "ISIC2" not in df.columns:
        return
    df["ISIC2"] = df["ISIC2"].astype(str)

    for codes_tuple, (sector_num, sector_name) in SECTOR_MAPPING.items():
        mask = df["ISIC2"].isin(codes_tuple)
        subset = df[mask]
        if not subset.empty:
            fname = f"{sector_num}_{sector_name}.csv"
            subset.to_csv(os.path.join(output_dir, fname),
                          index=False, encoding="utf-8-sig")


# ─────────────────────────────────────────────────────────────────────────────
# TTD 贸易数据处理
# ─────────────────────────────────────────────────────────────────────────────

def compute_sea_ratios(df: pd.DataFrame) -> pd.DataFrame:
    """从 TTD 数据中计算各 (origin, destination, product) 的海运量及比例。

    输入 df 需已筛选好方向（仅含一侧为中国的记录），且 TransportMode 已转为字符串。
    返回的 DataFrame 含列：
      origin, destination, product,
      total_v, total_q, sea_v, sea_q,
      sea_v_ratio, sea_q_ratio,
      iso_O, iso_D, ISIC2
    """
    iso_dict    = load_iso_map()
    hs4_to_isic = load_hs4_isic_map()

    # 利用 groupby + pivot 避免逐行循环，速度更快
    df = df.copy()
    df["TransportMode"] = df["TransportMode"].astype(str).replace({"00": "0", "01": "1"})

    # 分别聚合 total（mode=='0'）和 sea（mode=='21'）
    total_agg = (
        df[df["TransportMode"] == "0"]
        .groupby(["Origin", "Destination", "Product"])[["FOB value (US$)", "Kilograms"]]
        .sum()
        .rename(columns={"FOB value (US$)": "total_v", "Kilograms": "total_q"})
    )
    sea_agg = (
        df[df["TransportMode"] == "21"]
        .groupby(["Origin", "Destination", "Product"])[["FOB value (US$)", "Kilograms"]]
        .sum()
        .rename(columns={"FOB value (US$)": "sea_v", "Kilograms": "sea_q"})
    )

    result = total_agg.join(sea_agg, how="left").fillna(0).reset_index()
    result.rename(columns={
        "Origin": "origin", "Destination": "destination", "Product": "product"
    }, inplace=True)

    # 计算比例，避免除以零
    result["sea_v_ratio"] = np.where(
        result["total_v"] != 0, result["sea_v"] / result["total_v"], 0.0)
    result["sea_q_ratio"] = np.where(
        result["total_q"] != 0, result["sea_q"] / result["total_q"], 0.0)

    # 映射 ISO3 编码
    result["iso_O"] = result["origin"].astype(str).map(iso_dict)
    result["iso_D"] = result["destination"].astype(str).map(iso_dict)

    # 映射 ISIC2 行业编码
    result["ISIC2"] = result["product"].astype(str).map(hs4_to_isic)

    return result
