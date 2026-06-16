"""
Phase 3 / Step 1: 港口流量更新

两步合一：
  ① 从 Koks port_trade_network.csv 按方向过滤，得到各方向的港口底表
  ② 用 Phase 1 step2 输出的行业贸易统计（output/{direction}/trade/sectors/*.csv）
     回填海运总量、海运占比，并计算每个港口对应的贸易值/量和比重

核心计算：
  share_mar     = sea_v_sum / total_v_sum           （该行业该国家对的海运占比）
  v_sea_flow    = v_share_port × v_sea_flow_sum     （港口的海运贸易值）
  q_sea_flow    = q_share_port × q_sea_flow_sum     （港口的海运贸易量，单位转换 /1000）
  v_share_trade = v_share_port × share_mar          （港口份额 × 行业海运占比）
  q_share_trade = q_share_port × share_mar

最后清理非 CHN 方向的冗余记录：
  CHN2World: 删除 flow==port_export 且 from_iso3≠CHN 的行
  World2CHN: 删除 flow==port_import 且 to_iso3≠CHN 的行

输出目录：output/mrio/{direction}/input/
  {direction}_ports_updated.csv
"""

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd

from shared.config import RAW_DATA, out, mrio, CHN_ISO3, WUHAN_TO_SHANGHAI

# ── 方向配置 ─────────────────────────────────────────────────────────────────
# filter_col       : 从 port_trade_network 过滤中国方向的列名
# cleanup_flow     : 需要清理的 flow 类型
# cleanup_iso_col  : 该 flow 类型中判断是否属于 CHN 的列名
DIRECTION_CONFIG = {
    "CHN2World": {
        "filter_col":      "iso3_O",        # 出口方 = CHN
        "cleanup_flow":    "port_export",
        "cleanup_iso_col": "from_iso3",
    },
    "World2CHN": {
        "filter_col":      "iso3_D",        # 进口方 = CHN
        "cleanup_flow":    "port_import",
        "cleanup_iso_col": "to_iso3",
    },
}


def run(direction: str) -> None:
    """
    direction: "CHN2World" 或 "World2CHN"
    """
    cfg = DIRECTION_CONFIG[direction]
    output_path = os.path.join(
        mrio(direction, "input"),
        f"{direction}_ports_updated.csv",
    )

    # ── Step A: 从 port_trade_network 过滤方向 ──────────────────────────────
    print(f"[P3 Step 1] {direction}: 读取 port_trade_network.csv ...")
    ports_df = pd.read_csv(RAW_DATA["port_trade_network"])
    ports_df = ports_df[ports_df[cfg["filter_col"]] == CHN_ISO3].copy()
    print(f"  方向过滤后: {len(ports_df):,} 行")

    # ── Step B: 武汉港 → 上海港 ID 替换，并派生 id 列 ──────────────────────
    for col, mapping in WUHAN_TO_SHANGHAI.items():
        if col in ports_df.columns:
            ports_df[col] = ports_df[col].replace(mapping)

    if "from_id" in ports_df.columns:
        ports_df["id"] = ports_df["from_id"].str.split("_", n=1, expand=True)[0]

    # ── Step C: 遍历 sectors/*.csv，回填行业贸易统计 ─────────────────────────
    sectors_dir = out(direction, "trade", "sectors")
    if not os.path.exists(sectors_dir):
        print(f"  ⚠ sectors 目录不存在: {sectors_dir}")
        print("     请先运行 Phase 1 step2")
        return

    ports_df["matched"] = False

    for root, _, files in os.walk(sectors_dir):
        for fname in sorted(files):
            if not fname.endswith(".csv"):
                continue

            # 从文件名提取行业编号（如 "01_xxx.csv" → 1）
            industry_str = fname.split("_")[0]
            industry = int(industry_str.lstrip("0")) if industry_str.lstrip("0") else 0

            df = pd.read_csv(os.path.join(root, fname))
            v_sea_sum = df["sea_v"].sum()
            q_sea_sum = df["sea_q"].sum()
            total_v   = df["total_v"].sum()
            share_mar = v_sea_sum / total_v if total_v != 0 else 0.0

            for _, row in df.iterrows():
                mask = (
                    (ports_df["iso3_O"] == row["iso_O"]) &
                    (ports_df["iso3_D"] == row["iso_D"]) &
                    (ports_df["Industries"] == industry)
                )
                if mask.any():
                    ports_df.loc[mask, "v_sea_flow_sum"] = v_sea_sum
                    ports_df.loc[mask, "q_sea_flow_sum"] = q_sea_sum / 1000
                    ports_df.loc[mask, "share_mar"]      = share_mar
                    ports_df.loc[mask, "matched"]        = True

    before = len(ports_df)
    ports_df = ports_df[ports_df["matched"]].drop(columns=["matched"])
    print(f"  删除未匹配行: {before - len(ports_df):,}  保留: {len(ports_df):,} 行")

    # ── Step D: 计算港口级贸易值/量和比重 ────────────────────────────────────
    ports_df["v_sea_flow"]    = ports_df["v_share_port"] * ports_df["v_sea_flow_sum"]
    ports_df["q_sea_flow"]    = ports_df["q_share_port"] * ports_df["q_sea_flow_sum"]
    ports_df["v_share_trade"] = ports_df["v_share_port"] * ports_df["share_mar"]
    ports_df["q_share_trade"] = ports_df["q_share_port"] * ports_df["share_mar"]

    # ── Step E: 清理非 CHN 方向的冗余记录 ────────────────────────────────────
    before = len(ports_df)
    drop_mask = (
        (ports_df["flow"] == cfg["cleanup_flow"]) &
        (ports_df[cfg["cleanup_iso_col"]] != CHN_ISO3)
    )
    ports_df = ports_df[~drop_mask]
    print(f"  清理非CHN方向: {before - len(ports_df):,} 行  剩余: {len(ports_df):,} 行")

    # ── 保存 ────────────────────────────────────────────────────────────────
    ports_df.to_csv(output_path, index=False, encoding="utf-8-sig")
    print(f"[P3 Step 1] {direction}: ✅ → {output_path}")


if __name__ == "__main__":
    for d in ["CHN2World", "World2CHN"]:
        run(d)
