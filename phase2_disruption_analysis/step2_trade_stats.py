"""
Phase 2 / Step 2: 关键线路贸易量统计

对 step1 输出的每个海峡 CSV，
从 phase1 的流量目录（output/{direction}/flow/）中
匹配对应港口对的流量记录，聚合为：
  - 分国家贸易量（按伙伴国 ISO3 + 行业汇总）
  - 分行业贸易量（按 EORA 11 大类汇总）

并附加国家名称/地区/收入组（来自 iso3_with_region.csv）
和行业中英文名称（来自 eora_categories.xlsx）。

处理流程：
  1. 读取 step1 生成的海峡路径 CSV（包含 key = start_id_end_id）
  2. 遍历 flow/ 目录所有 CSV，按 key 匹配并聚合 q_flow / v_flow
  3. 按（伙伴国, 行业）分组输出分国家结果
  4. 按行业分组输出分类别结果
  5. 计算各海峡 v_flow 总量 / 全部路径总量 的比例（利用 routes gpkg 动态计算）

输出目录：output/disruption/{direction}/02_trade_stats/
  {海峡名称}_分国家.csv
  {海峡名称}_分类别.csv
  v_flow_ratio_summary.csv  （各海峡比例汇总）
"""

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from glob import glob

import geopandas as gpd
import pandas as pd

from shared.config import RAW_DATA, out, disrupt


def _load_lookup_tables():
    """加载国家/行业辅助映射表。"""
    iso_map  = pd.read_csv(RAW_DATA["iso3_with_region"], dtype=str)
    eora_map = pd.read_excel(RAW_DATA["eora_categories"])
    eora_map["Code"] = eora_map["Code"].astype(str).str.zfill(2)
    return iso_map, eora_map


def _compute_total_sea_v(direction: str) -> float:
    """从 routes gpkg 动态计算当前方向的总海运贸易额（v1~v11 之和）。"""
    routes_path = os.path.join(
        out(direction, "routes"),
        f"shortest_paths_{direction}_with_flows.gpkg",
    )
    if not os.path.exists(routes_path):
        return 1.0
    gdf = gpd.read_file(routes_path)
    v_cols = [f"v{i}" for i in range(1, 12) if f"v{i}" in gdf.columns]
    return float(gdf[v_cols].sum().sum()) if v_cols else 1.0


def run(direction: str) -> None:
    """
    direction: "CHN2World" 或 "World2CHN"
    """
    routes_csv_dir = disrupt(direction, "01_routes_csv")
    output_dir     = disrupt(direction, "02_trade_stats")
    flow_dir       = out(direction, "flow")

    iso_map, eora_map = _load_lookup_tables()

    # 确定伙伴国 ISO3 列（CHN2World → to_iso3，World2CHN → from_iso3）
    partner_iso_col = "to_iso3" if direction == "CHN2World" else "from_iso3"

    # 全量 sea_v 基准（用于比例计算）
    total_sea_v = _compute_total_sea_v(direction)

    csv_files = sorted([f for f in os.listdir(routes_csv_dir) if f.endswith(".csv")])
    if not csv_files:
        print(f"[P2 Step 2] {direction}: 未找到 step1 输出，请先运行 step1。")
        return

    # ── 预加载所有流量 CSV，建立 key → rows 映射 ───────────────────────────
    print(f"[P2 Step 2] {direction}: 读取流量目录 {flow_dir} ...")
    flow_records = []
    for fpath in glob(os.path.join(flow_dir, "*.csv")):
        if os.path.basename(fpath).startswith("missing_ports_"):
            continue
        try:
            df = pd.read_csv(fpath)
            df["key"] = df["export_port"].astype(str) + "_" + df["import_port"].astype(str)
            flow_records.append(df)
        except Exception as e:
            print(f"  ⚠ 读取失败: {fpath} — {e}")
    all_flow = pd.concat(flow_records, ignore_index=True) if flow_records else pd.DataFrame()

    ratio_records = []

    for csv_file in csv_files:
        base_name  = os.path.splitext(csv_file)[0]
        routes_csv = os.path.join(routes_csv_dir, csv_file)
        key_df     = pd.read_csv(routes_csv)

        if "key" not in key_df.columns:
            key_df["key"] = key_df["start_id"].astype(str) + "_" + key_df["end_id"].astype(str)

        key_set = set(key_df["key"].astype(str))

        # 筛选匹配到当前海峡的流量行
        if all_flow.empty:
            combined = pd.DataFrame()
        else:
            combined = all_flow[all_flow["key"].isin(key_set)].copy()

        if combined.empty:
            print(f"  {base_name}: 无匹配流量记录，跳过")
            continue

        # ── 聚合 ────────────────────────────────────────────────────────────
        grouped = (
            combined
            .groupby(["from_iso3", "to_iso3", "sector"], as_index=False)[["q_flow", "v_flow"]]
            .sum()
            .sort_values("v_flow", ascending=False)
        )

        # 添加国家信息（CHN2World → to_iso3，World2CHN → from_iso3）
        grouped[partner_iso_col] = grouped[partner_iso_col].astype(str)
        iso_map["iso3"] = iso_map["iso3"].astype(str)
        merged = grouped.merge(
            iso_map[["iso3", "EnglishName", "ChineseName", "Income group", "Region"]],
            left_on=partner_iso_col, right_on="iso3", how="left",
        ).drop(columns=["iso3"])

        # 添加行业信息
        merged["sector"] = merged["sector"].astype(str).str.zfill(2)
        merged2 = merged.merge(
            eora_map[["Code", "EORA_E", "EORA_C"]],
            left_on="sector", right_on="Code", how="left",
        ).drop(columns=["Code"])

        # 保存分国家结果
        country_path = os.path.join(output_dir, f"{base_name}_分国家.csv")
        merged2.to_csv(country_path, index=False, encoding="utf-8-sig")

        # 保存分类别结果
        by_sector = (
            merged2
            .groupby("sector", as_index=False)
            .agg({"q_flow": "sum", "v_flow": "sum", "EORA_E": "first", "EORA_C": "first"})
        )
        sector_path = os.path.join(output_dir, f"{base_name}_分类别.csv")
        by_sector.to_csv(sector_path, index=False, encoding="utf-8-sig")

        # 记录比例
        v_sum = float(merged2["v_flow"].sum())
        ratio_records.append({
            "chokepoint":   base_name,
            "v_flow_sum":   v_sum,
            "total_sea_v":  total_sea_v,
            "ratio":        v_sum / total_sea_v if total_sea_v > 0 else 0.0,
        })
        print(f"  {base_name}: v_flow={v_sum:,.0f}  ratio={v_sum/total_sea_v:.4f}")

    # ── 保存比例汇总 ──────────────────────────────────────────────────────
    if ratio_records:
        summary_path = os.path.join(output_dir, "v_flow_ratio_summary.csv")
        pd.DataFrame(ratio_records).to_csv(summary_path, index=False, encoding="utf-8-sig")
        print(f"\n[P2 Step 2] {direction}: 比例汇总已保存 → {summary_path}")

    print(f"[P2 Step 2] {direction}: 贸易统计完成，结果保存至 {output_dir}")


if __name__ == "__main__":
    for d in ["CHN2World", "World2CHN"]:
        run(d)
