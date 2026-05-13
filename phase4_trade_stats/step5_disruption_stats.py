"""
Phase 4 / Step 5: 中断断连流量统计

读取 Phase 2 step3 生成的 `{chokepoint}_miss.csv`（无法绕行的流量），
按行业、国家分别聚合，并与 step1 基础表匹配计算断连比例。

miss.csv 格式（Phase 2 step3 新增生成）
  start_id, end_id, start_iso3, end_iso3, sector(int), v_flow, q_flow

CHN2World：CHN 是 start，外国是 end（end_iso3 = 外国）
World2CHN：外国是 start，CHN 是 end（start_iso3 = 外国）

输入依赖
--------
- output/disruption/{direction}/03_reroute/{chokepoint}_miss.csv
- output/trade_stats/base/{direction}_trade.csv（含 sectors + iso 列）

输出
----
output/trade_stats/disruption/{direction}/
  {chokepoint}_miss_sector.csv   — 按行业聚合
  {chokepoint}_miss_iso3.csv     — 按国家聚合（含断连比例 miss_vr, miss_qr）
  {chokepoint}_miss_ratio.csv    — 按行业×国家聚合
"""

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd

from shared.config import disrupt, RAW_DATA
from phase4_trade_stats.helpers import trade_stats, load_iso_region

# ── 方向配置 ─────────────────────────────────────────────────────────────────
DIRECTION_CONFIG = {
    "CHN2World": {
        "foreign_iso_col":  "end_iso3",    # miss.csv 中代表外国的列
        "base_iso_col":     "iso_D",       # 基础表中的外国 ISO3 列
    },
    "World2CHN": {
        "foreign_iso_col":  "start_iso3",
        "base_iso_col":     "iso_O",
    },
}


def _load_base_totals(direction: str) -> pd.DataFrame | None:
    """
    从 step1 基础表中提取每个国家的海运贸易总量（sectors 不等于 "00" 的行汇总）。
    返回 DataFrame：{iso_col: iso3, total_v, total_q}
    """
    base_path = os.path.join(trade_stats("base"), f"{direction}_trade.csv")
    if not os.path.exists(base_path):
        print(f"[P4 Step 5] 基础表不存在: {base_path}，跳过比例计算")
        return None

    df = pd.read_csv(base_path, low_memory=False)
    iso_col = DIRECTION_CONFIG[direction]["base_iso_col"]

    # 只取 product=="TOTAL" 的汇总行
    df_total = df[df["product"] == "TOTAL"].copy()
    if df_total.empty:
        df_total = df.copy()

    agg = (
        df_total.groupby(iso_col, as_index=False)
                .agg(total_v=("sea_v", "sum"), total_q=("sea_q", "sum"))
    )
    agg.rename(columns={iso_col: "iso3"}, inplace=True)
    return agg


def run(direction: str) -> None:
    """
    direction: "CHN2World" 或 "World2CHN"
    """
    cfg         = DIRECTION_CONFIG[direction]
    foreign_col = cfg["foreign_iso_col"]
    reroute_dir = disrupt(direction, "03_reroute")
    out_dir     = trade_stats("disruption", direction)

    miss_files = sorted(
        f for f in os.listdir(reroute_dir)
        if f.lower().endswith("_miss.csv")
    ) if os.path.isdir(reroute_dir) else []

    if not miss_files:
        print(f"[P4 Step 5] {direction}: 未找到 miss CSV（请先运行 Phase 2 step3）")
        return

    print(f"[P4 Step 5] {direction}: 发现 {len(miss_files)} 个 miss CSV")

    # 读取基础表（用于计算比例）
    base_totals = _load_base_totals(direction)

    # 读取 EORA 类别
    eora_map = None
    try:
        eora_map = pd.read_excel(RAW_DATA["eora_categories"])
        eora_map["Code"] = eora_map["Code"].astype(str).str.zfill(2)
    except Exception:
        pass

    for fname in miss_files:
        # 从文件名提取要道名（去掉 _miss.csv 后缀）
        choke_name = fname[:-len("_miss.csv")]
        miss_path  = os.path.join(reroute_dir, fname)

        df = pd.read_csv(miss_path)
        if df.empty:
            print(f"  {choke_name}: miss CSV 为空，跳过")
            continue

        # CHN2World: 只保留 start_iso3 == CHN 的行
        # World2CHN: 只保留 end_iso3 == CHN 的行
        if direction == "CHN2World":
            if "start_iso3" in df.columns:
                df = df[df["start_iso3"] == "CHN"]
        else:
            if "end_iso3" in df.columns:
                df = df[df["end_iso3"] == "CHN"]

        if df.empty:
            print(f"  {choke_name}: 过滤后为空，跳过")
            continue

        # sector 列转为两位字符串
        df["sector"] = df["sector"].astype(str).str.zfill(2)

        # ────── 按行业聚合 ──────────────────────────────────────────────
        sector_df = (
            df.groupby("sector", as_index=False)[["q_flow", "v_flow"]].sum()
        )
        if eora_map is not None:
            sector_df = sector_df.merge(eora_map[["Code","EORA_E","EORA_C"]],
                                         left_on="sector", right_on="Code", how="left")
            sector_df.drop(columns=["Code"], inplace=True, errors="ignore")
        sector_df = sector_df.sort_values("v_flow", ascending=False)

        sector_path = os.path.join(out_dir, f"{choke_name}_miss_sector.csv")
        sector_df.to_csv(sector_path, index=False, encoding="utf-8-sig")

        # ────── 按国家聚合 ──────────────────────────────────────────────
        if foreign_col in df.columns:
            iso3_df = (
                df.groupby(foreign_col, as_index=False)[["q_flow", "v_flow"]].sum()
            )
            iso3_df.rename(columns={foreign_col: "iso3"}, inplace=True)

            # 合并比例
            if base_totals is not None:
                iso3_df = iso3_df.merge(base_totals, on="iso3", how="left")
                iso3_df["miss_vr"] = iso3_df["v_flow"] / iso3_df["total_v"]
                iso3_df["miss_qr"] = iso3_df["q_flow"] / iso3_df["total_q"]

            iso3_df = iso3_df.sort_values("v_flow", ascending=False)
            iso3_path = os.path.join(out_dir, f"{choke_name}_miss_iso3.csv")
            iso3_df.to_csv(iso3_path, index=False, encoding="utf-8-sig")

            # ────── 按行业×国家聚合 ──────────────────────────────────
            ratio_df = (
                df.groupby(["sector", foreign_col], as_index=False)[["q_flow", "v_flow"]].sum()
            )
            ratio_df.rename(columns={foreign_col: "iso3"}, inplace=True)

            if base_totals is not None:
                ratio_df = ratio_df.merge(base_totals, on="iso3", how="left")
                ratio_df["miss_vr"] = ratio_df["v_flow"] / ratio_df["total_v"]
                ratio_df["miss_qr"] = ratio_df["q_flow"] / ratio_df["total_q"]

            ratio_df = ratio_df.sort_values("v_flow", ascending=False)
            ratio_path = os.path.join(out_dir, f"{choke_name}_miss_ratio.csv")
            ratio_df.to_csv(ratio_path, index=False, encoding="utf-8-sig")

        print(f"  {choke_name}: 行业 {len(sector_df)} 行，完成")

    print(f"[P4 Step 5] {direction}: ✅ → {out_dir}")


if __name__ == "__main__":
    for d in ["CHN2World", "World2CHN"]:
        run(d)
