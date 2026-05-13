"""
Step 2: 贸易数据处理 — 海运比例计算 + 行业分类

处理 TTD（Trade and Transport Dataset）数据：
  1. 筛选中国作为出口方（CHN2World）或进口方（World2CHN）的记录
  2. 按 (origin, destination, product) 分组，计算海运量及占比
  3. 将 HS4 产品编码映射到 ISIC2 行业编码
  4. 按国家导出 CSV：output/{direction}/trade/{country_iso3}.csv
  5. 补齐海运空值（total != 0 但 sea == 0 时用默认比例填补）
  6. 按 EORA 11 大类行业分类：output/{direction}/trade/sectors/{country_iso3}/

可与 step1 独立运行，两者无依赖关系。
"""

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd

from shared.config import RAW_DATA, out, CHN_ISO_NUM
from shared.utils import fix_iso_codes, compute_sea_ratios, fill_sea_defaults, classify_sectors


def run(direction: str) -> None:
    """
    direction: "CHN2World" 或 "World2CHN"
    """
    # ── 分块读取 TTD 数据，边读边过滤，避免全量载入内存 ───────────────────
    columns_needed = [
        "Year", "Origin", "Destination", "Product",
        "TransportMode", "FOB value (US$)", "Kilograms",
    ]
    filter_col = "Origin" if direction == "CHN2World" else "Destination"
    group_col  = "iso_D"  if direction == "CHN2World" else "iso_O"

    chunks = []
    for chunk in pd.read_csv(
        RAW_DATA["ttd"], usecols=columns_needed,
        chunksize=200_000, low_memory=False,
    ):
        chunk = fix_iso_codes(chunk, ["Origin", "Destination"])
        sub   = chunk[chunk[filter_col] == CHN_ISO_NUM]
        if not sub.empty:
            chunks.append(sub)

    df = pd.concat(chunks, ignore_index=True) if chunks else pd.DataFrame(columns=columns_needed)

    # ── 计算海运比例 + 映射 ISIC2 ──────────────────────────────────────────
    final_df  = compute_sea_ratios(df)
    trade_dir = out(direction, "trade")

    # ── 按国家导出 CSV ─────────────────────────────────────────────────────
    exported = 0
    for iso3, group in final_df.groupby(group_col):
        if pd.notna(iso3):
            group.to_csv(
                os.path.join(trade_dir, f"{iso3}.csv"),
                index=False, encoding="utf-8-sig",
            )
            exported += 1

    print(f"[Step 2] {direction}: {exported} 个国家贸易数据已导出")

    # ── 补齐海运空值 + 行业分类 ────────────────────────────────────────────
    filled_count = 0
    for fname in os.listdir(trade_dir):
        if not fname.endswith(".csv"):
            continue
        fp      = os.path.join(trade_dir, fname)
        df_c    = pd.read_csv(fp, dtype={"ISIC2": str})
        df_c, n = fill_sea_defaults(df_c)
        if n > 0:
            df_c.to_csv(fp, index=False, encoding="utf-8-sig")
            filled_count += n

        country = fname[:-4]
        classify_sectors(df_c, out(direction, "trade", "sectors", country))

    print(f"[Step 2] {direction}: 海运空值已补齐 {filled_count} 行，行业分类完成")


if __name__ == "__main__":
    for d in ["CHN2World", "World2CHN"]:
        run(d)
