"""
Phase 4 / Step 3: 运输方式比例统计

依赖 step1 输出的基础贸易表，计算：
  1. 总体运输方式比例（CHN2World、World2CHN 及合并）
  2. 各要道的流量 vs 全量海运的比例（依赖 step2 的分类别 CSV）

输入依赖
--------
- output/trade_stats/base/CHN2World_trade.csv
- output/trade_stats/base/World2CHN_trade.csv
- output/trade_stats/chokepoint_flows/{direction}/{chokepoint}_by_sector.csv

输出
----
output/trade_stats/mode_stats/
  transport_mode_ratios.csv   — 总体比例（CHN2World、World2CHN、Combined 三行）
  chokepoint_shares.csv       — 各要道相对海运总量的比例
"""

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd

from phase4_trade_stats.helpers import trade_stats

DIRECTIONS = ["CHN2World", "World2CHN"]


def _load_base(direction: str) -> pd.DataFrame:
    base_path = os.path.join(trade_stats("base"), f"{direction}_trade.csv")
    if not os.path.exists(base_path):
        raise FileNotFoundError(
            f"[P4 Step 3] {direction} 基础贸易表不存在: {base_path}\n"
            "  请先运行 step1。"
        )
    return pd.read_csv(base_path, low_memory=False)


def _mode_ratios(df: pd.DataFrame, label: str) -> dict:
    """计算单个方向的运输方式比例，返回字典。"""
    air_v  = df["air_v"].sum()
    sea_v  = df["sea_v"].sum()
    land_v = df["land_v"].sum()
    total_v = air_v + sea_v + land_v

    air_q  = df["air_q"].sum()
    sea_q  = df["sea_q"].sum()
    land_q = df["land_q"].sum()
    total_q = air_q + sea_q + land_q

    return {
        "direction":    label,
        "air_v":        air_v,
        "sea_v":        sea_v,
        "land_v":       land_v,
        "total_v":      total_v,
        "air_v_ratio":  air_v  / total_v if total_v else 0,
        "sea_v_ratio":  sea_v  / total_v if total_v else 0,
        "land_v_ratio": land_v / total_v if total_v else 0,
        "air_q":        air_q,
        "sea_q":        sea_q,
        "land_q":       land_q,
        "total_q":      total_q,
        "air_q_ratio":  air_q  / total_q if total_q else 0,
        "sea_q_ratio":  sea_q  / total_q if total_q else 0,
        "land_q_ratio": land_q / total_q if total_q else 0,
    }


def run() -> None:
    """计算运输方式比例和要道份额，不区分方向（两个方向的 base 表都需存在）。"""
    out_dir = trade_stats("mode_stats")

    # ── Part 1: 总体运输比例 ──────────────────────────────────────────────
    records = []
    dfs = {}
    for d in DIRECTIONS:
        try:
            df = _load_base(d)
            dfs[d] = df
            records.append(_mode_ratios(df, d))
        except FileNotFoundError as e:
            print(e)
            return

    # 合并两个方向
    df_c2w = dfs["CHN2World"]
    df_w2c = dfs["World2CHN"]
    combined = pd.concat([df_c2w, df_w2c], ignore_index=True)
    records.append(_mode_ratios(combined, "Combined"))

    df_ratios = pd.DataFrame(records)
    ratios_path = os.path.join(out_dir, "transport_mode_ratios.csv")
    df_ratios.to_csv(ratios_path, index=False, encoding="utf-8-sig")
    print(f"[P4 Step 3] ✅ 运输比例 → {ratios_path}")

    # ── Part 2: 各要道份额 ────────────────────────────────────────────────
    share_records = []

    for d in DIRECTIONS:
        sea_total = dfs[d]["sea_v"].sum()
        sea_total_q = dfs[d]["sea_q"].sum()

        sector_dir = trade_stats("chokepoint_flows", d)
        if not os.path.isdir(sector_dir):
            print(f"[P4 Step 3] {d}: 要道流量目录不存在，跳过 → {sector_dir}")
            continue

        for fname in sorted(os.listdir(sector_dir)):
            if not fname.endswith("_by_sector.csv"):
                continue
            choke_name = fname.replace("_by_sector.csv", "")
            fp = os.path.join(sector_dir, fname)
            df_choke = pd.read_csv(fp)

            v_sum = df_choke["v_flow"].sum()
            q_sum = df_choke["q_flow"].sum()

            share_records.append({
                "direction":    d,
                "chokepoint":   choke_name,
                "v_flow_sum":   v_sum,
                "q_flow_sum":   q_sum,
                "v_share_sea":  v_sum / sea_total    if sea_total   else 0,
                "q_share_sea":  q_sum / sea_total_q  if sea_total_q else 0,
            })

    if share_records:
        df_shares = pd.DataFrame(share_records)
        shares_path = os.path.join(out_dir, "chokepoint_shares.csv")
        df_shares.to_csv(shares_path, index=False, encoding="utf-8-sig")
        print(f"[P4 Step 3] ✅ 要道份额 → {shares_path}")

    print(f"[P4 Step 3] ✅ 全部完成 → {out_dir}")


if __name__ == "__main__":
    run()
