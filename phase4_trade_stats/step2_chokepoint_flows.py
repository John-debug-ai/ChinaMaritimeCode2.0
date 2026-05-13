"""
Phase 4 / Step 2: 要道流量统计

读取 Phase 1 生成的带流量 GPKG 文件，将宽格式 v1~v11/q1~q11 转换为长格式，
与 Phase 2 step1 的要道路线 CSV 的 (start_id, end_id) 做匹配，
按行业和国家分别聚合，并生成 Top-N 摘要。

输入依赖
--------
- Phase 1 输出：output/{direction}/routes/shortest_paths_{direction}_with_flows.gpkg
- Phase 2 step1 输出：output/disruption/{direction}/01_routes_csv/*.csv
- ISO3 国家信息：RAW_DATA["iso3_with_region"]
- EORA 类别：RAW_DATA["eora_categories"]

输出
----
output/trade_stats/chokepoint_flows/
  {direction}/{chokepoint}_by_sector.csv   — 按行业聚合 (sector, EORA_E, EORA_C, q_flow, v_flow)
  {direction}/{chokepoint}_by_country.csv  — 按国家聚合 (iso3, EnglishName, ..., q_flow, v_flow)
  {direction}/top3_by_v.csv                — 所有要道×行业的价值前3统计
  {direction}/top3_by_q.csv                — 所有要道×行业的重量前3统计
"""

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd

from shared.config import RAW_DATA, out, disrupt
from phase4_trade_stats.helpers import (
    trade_stats, gpkg_to_flows, load_iso_region, top_n_by,
)

# CHN2World：外国是目的地（to_iso3=end_iso3）
# World2CHN：外国是来源地（from_iso3=start_iso3）
DIRECTION_CONFIG = {
    "CHN2World": {
        "gpkg_name":    "shortest_paths_CHN2World_with_flows.gpkg",
        "foreign_iso3": "end_iso3",   # 外国 ISO3 列
        "choke_filter": "start_iso3", # 要道 CSV 中代表 CHN 的列
    },
    "World2CHN": {
        "gpkg_name":    "shortest_paths_World2CHN_with_flows.gpkg",
        "foreign_iso3": "start_iso3",
        "choke_filter": "end_iso3",
    },
}


def _load_eora_map() -> pd.DataFrame:
    """读取 EORA 类别表，返回 DataFrame（列：Code, EORA_E, EORA_C）。"""
    df = pd.read_excel(RAW_DATA["eora_categories"])
    df["Code"] = df["Code"].astype(str).str.zfill(2)
    return df[["Code", "EORA_E", "EORA_C"]]


def run(direction: str) -> None:
    """
    direction: "CHN2World" 或 "World2CHN"
    """
    cfg       = DIRECTION_CONFIG[direction]
    out_dir   = trade_stats("chokepoint_flows", direction)
    choke_dir = disrupt(direction, "01_routes_csv")

    # ── 读取 Phase 1 GPKG ────────────────────────────────────────────────
    gpkg_path = os.path.join(
        out(direction, "routes"),
        cfg["gpkg_name"],
    )
    if not os.path.exists(gpkg_path):
        print(f"[P4 Step 2] {direction}: GPKG 不存在 → {gpkg_path}")
        print("  请先运行 Phase 1 step5。")
        return

    print(f"[P4 Step 2] {direction}: 读取 GPKG ...")
    flows_df = gpkg_to_flows(gpkg_path)
    print(f"  流量长表: {len(flows_df):,} 行")

    # ── 读取辅助表 ────────────────────────────────────────────────────────
    eora_map   = _load_eora_map()
    iso_region = load_iso_region()

    # ── 遍历要道 CSV ──────────────────────────────────────────────────────
    if not os.path.isdir(choke_dir):
        print(f"[P4 Step 2] {direction}: 要道 CSV 目录不存在 → {choke_dir}")
        print("  请先运行 Phase 2 step1。")
        return

    csv_files = sorted(f for f in os.listdir(choke_dir) if f.lower().endswith(".csv"))
    print(f"[P4 Step 2] {direction}: 发现 {len(csv_files)} 个要道 CSV")

    all_sector_records  = []  # for top3 摘要
    all_country_records = []

    for fname in csv_files:
        choke_name = os.path.splitext(fname)[0]
        choke_df   = pd.read_csv(os.path.join(choke_dir, fname))

        # 筛选属于该要道的 key（start_id_end_id）
        choke_keys = set(
            choke_df["start_id"].astype(str) + "_" + choke_df["end_id"].astype(str)
        )

        matched = flows_df[
            (flows_df["start_id"].astype(str) + "_" + flows_df["end_id"].astype(str))
            .isin(choke_keys)
        ].copy()

        if matched.empty:
            print(f"  {choke_name}: 无匹配流量，跳过")
            continue

        foreign_col = cfg["foreign_iso3"]

        # ────── 按行业聚合 ──────────────────────────────────────────────
        sector_df = (
            matched.groupby("sector", as_index=False)[["q_flow", "v_flow"]].sum()
        )
        sector_df["sector"] = sector_df["sector"].astype(str).str.zfill(2)
        sector_df = sector_df.merge(eora_map, left_on="sector", right_on="Code", how="left")
        sector_df.drop(columns=["Code"], inplace=True, errors="ignore")
        sector_df = sector_df.sort_values("v_flow", ascending=False)

        out_s = os.path.join(out_dir, f"{choke_name}_by_sector.csv")
        sector_df.to_csv(out_s, index=False, encoding="utf-8-sig")

        # 收集摘要
        for _, row in sector_df.iterrows():
            all_sector_records.append({
                "chokepoint": choke_name,
                "sector": row["sector"],
                "EORA_E": row.get("EORA_E"),
                "EORA_C": row.get("EORA_C"),
                "v_flow": row["v_flow"],
                "q_flow": row["q_flow"],
            })

        # ────── 按国家聚合 ──────────────────────────────────────────────
        if foreign_col not in matched.columns:
            print(f"  ⚠ {choke_name}: 缺少 {foreign_col} 列，跳过国家统计")
        else:
            country_df = (
                matched.groupby(foreign_col, as_index=False)[["q_flow", "v_flow"]].sum()
            )
            country_df.rename(columns={foreign_col: "iso3"}, inplace=True)

            # 合并国家信息
            country_df = country_df.merge(
                iso_region.rename(columns={"iso3": "iso3"}),
                on="iso3", how="left"
            )
            country_df = country_df.sort_values("v_flow", ascending=False)

            out_c = os.path.join(out_dir, f"{choke_name}_by_country.csv")
            country_df.to_csv(out_c, index=False, encoding="utf-8-sig")

            for _, row in country_df.iterrows():
                all_country_records.append({
                    "chokepoint": choke_name,
                    "iso3": row["iso3"],
                    "v_flow": row["v_flow"],
                    "q_flow": row["q_flow"],
                })

        print(f"  {choke_name}: 行业 {len(sector_df)} 行，已保存")

    # ── Top-3 摘要（按价值 / 重量）────────────────────────────────────────
    if all_sector_records:
        df_all_s = pd.DataFrame(all_sector_records)

        for metric, label in [("v_flow", "v"), ("q_flow", "q")]:
            top3 = _build_top3_summary(df_all_s, eora_map, metric)
            top3_path = os.path.join(out_dir, f"top3_by_{label}.csv")
            top3.to_csv(top3_path, index=False, encoding="utf-8-sig")
            print(f"[P4 Step 2] {direction}: top3_by_{label} → {top3_path}")

    print(f"[P4 Step 2] {direction}: ✅ 全部完成 → {out_dir}")


def _build_top3_summary(df_sectors: pd.DataFrame, eora_map: pd.DataFrame,
                         metric: str) -> pd.DataFrame:
    """
    构建"每个要道 × Top-3 行业 + 各行业Top-3国家"的宽摘要表。

    返回 DataFrame，每行代表 (chokepoint, 行业排名, 国家排名)。
    """
    records = []
    total_col = f"total_{metric}"

    for choke_name, grp in df_sectors.groupby("chokepoint"):
        total_flow = grp[metric].sum()
        top_sectors = grp.nlargest(3, metric)

        for rank_s, (_, s_row) in enumerate(top_sectors.iterrows(), 1):
            records.append({
                "chokepoint":  choke_name,
                f"total_{metric}": total_flow,
                "sector_rank": rank_s,
                "sector":      s_row.get("sector"),
                "EORA_C":      s_row.get("EORA_C"),
                "EORA_E":      s_row.get("EORA_E"),
                metric:        s_row[metric],
                f"{metric}_ratio": s_row[metric] / total_flow if total_flow else 0,
            })

    return pd.DataFrame(records)


if __name__ == "__main__":
    for d in ["CHN2World", "World2CHN"]:
        run(d)
