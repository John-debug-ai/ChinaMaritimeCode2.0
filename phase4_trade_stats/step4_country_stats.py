"""
Phase 4 / Step 4: 要道国家合并统计

对每个要道，将 CHN2World（按外国 to_iso3 统计）和 World2CHN（按外国 from_iso3 统计）
的国家流量做合并（同一国家进出口相加），并更新 Region/Income group 信息。

输入依赖
--------
- output/trade_stats/chokepoint_flows/CHN2World/{chokepoint}_by_country.csv
- output/trade_stats/chokepoint_flows/World2CHN/{chokepoint}_by_country.csv
- RAW_DATA["iso3_with_region"]

输出
----
output/trade_stats/country_combined/
  {chokepoint}_combined.csv  — 列：iso3, EnglishName, ChineseName,
                                    Income group, Region, q_flow, v_flow
"""

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd

from phase4_trade_stats.helpers import trade_stats, load_iso_region


def run() -> None:
    """合并两个方向的国家统计。"""
    c2w_dir = trade_stats("chokepoint_flows", "CHN2World")
    w2c_dir = trade_stats("chokepoint_flows", "World2CHN")
    out_dir = trade_stats("country_combined")

    # 收集两个方向下的所有要道名
    def _get_names(directory: str) -> set[str]:
        return {
            f.replace("_by_country.csv", "")
            for f in os.listdir(directory)
            if f.endswith("_by_country.csv")
        } if os.path.isdir(directory) else set()

    c2w_names = _get_names(c2w_dir)
    w2c_names = _get_names(w2c_dir)
    all_names = c2w_names | w2c_names

    if not all_names:
        print("[P4 Step 4] 未找到任何要道国家 CSV，请先运行 step2。")
        return

    iso_region = load_iso_region()
    # 确保只保留必要列
    keep_cols = [c for c in ["iso3", "EnglishName", "ChineseName", "Income group", "Region"]
                 if c in iso_region.columns]
    iso_region = iso_region[keep_cols]

    print(f"[P4 Step 4] 发现 {len(all_names)} 个要道，开始合并...")

    for choke_name in sorted(all_names):
        parts = []

        c2w_path = os.path.join(c2w_dir, f"{choke_name}_by_country.csv")
        if os.path.exists(c2w_path):
            df_c2w = pd.read_csv(c2w_path)
            # 统一使用 iso3 列名
            if "iso3" not in df_c2w.columns:
                # 可能有 to_iso3 或 from_iso3
                for alt in ("to_iso3", "from_iso3", "end_iso3", "start_iso3"):
                    if alt in df_c2w.columns:
                        df_c2w = df_c2w.rename(columns={alt: "iso3"})
                        break
            parts.append(df_c2w[["iso3", "q_flow", "v_flow"]].copy())

        w2c_path = os.path.join(w2c_dir, f"{choke_name}_by_country.csv")
        if os.path.exists(w2c_path):
            df_w2c = pd.read_csv(w2c_path)
            if "iso3" not in df_w2c.columns:
                for alt in ("from_iso3", "to_iso3", "start_iso3", "end_iso3"):
                    if alt in df_w2c.columns:
                        df_w2c = df_w2c.rename(columns={alt: "iso3"})
                        break
            parts.append(df_w2c[["iso3", "q_flow", "v_flow"]].copy())

        if not parts:
            continue

        combined = (
            pd.concat(parts, ignore_index=True)
              .groupby("iso3", as_index=False)[["q_flow", "v_flow"]]
              .sum()
        )

        # 合并 Region / Income group（覆盖 CSV 中的旧值）
        combined = combined.merge(iso_region, on="iso3", how="left")
        combined = combined.sort_values("v_flow", ascending=False)

        out_path = os.path.join(out_dir, f"{choke_name}_combined.csv")
        combined.to_csv(out_path, index=False, encoding="utf-8-sig")
        print(f"  {choke_name}: {len(combined)} 个国家 → {out_path}")

    print(f"[P4 Step 4] ✅ 全部完成 → {out_dir}")


if __name__ == "__main__":
    run()
