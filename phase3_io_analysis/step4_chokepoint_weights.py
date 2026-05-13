"""
Phase 3 / Step 4: 要道港口加权乘数

对 Phase 2 / Step 1 输出的每个要道路线 CSV，识别涉及的港口 ID，
从 output_multiplier.csv 中筛选对应行，并以路线频次为权重计算加权平均乘数。

处理逻辑
--------
1. 读取 disrupt(direction, "01_routes_csv") 下每个要道 CSV
2. 按方向过滤（CHN2World: start_iso3==CHN；World2CHN: end_iso3==CHN）
3. 合并 start_id + end_id 两列，统计各 port_id 出现频次
4. 从 output_multiplier.csv 中筛选这些 port_id 并关联频次
5. 保存各要道的筛选结果 CSV
6. 另外：从 ports_updated.csv 统计全部港口频次，同样筛选并保存
7. 最终：对所有筛选 CSV 计算频次加权平均乘数，输出汇总 Excel

输出目录：output/mrio/{direction}/chokepoints/
  {choke_name}_filtered.csv            — 每个要道的港口乘数表（含 frequency）
  {direction}_ports_filtered.csv       — 全部港口的乘数表（含 frequency）
  {C2W|W2C}_要道加权平均结果.xlsx       — 汇总（每要道一行，频次加权平均乘数）
"""

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd

from shared.config import CHN_ISO3, mrio, disrupt

# ── 方向配置 ─────────────────────────────────────────────────────────────────
# filter_iso_col : 要道 CSV 中判断是否属于 CHN 的列（CHN 是哪一端）
# excel_prefix   : 输出 Excel 文件名前缀
DIRECTION_CONFIG = {
    "CHN2World": {
        "filter_iso_col": "start_iso3",   # CHN 是起点
        "excel_prefix":   "C2W",
    },
    "World2CHN": {
        "filter_iso_col": "end_iso3",     # CHN 是终点
        "excel_prefix":   "W2C",
    },
}

# 加权平均所需的乘数列
MULT_COLS = ["frequency", "multiplier", "multiplier_dom", "multiplier_row"]


def _build_freq(df_route: pd.DataFrame, filter_col: str) -> pd.DataFrame:
    """从要道路线 DataFrame 中提取港口 ID 及其出现频次。

    只保留 filter_col == CHN_ISO3 的行（对于已过滤的 Phase 2 CSV
    此步骤等同于保留全部行），然后合并 start_id 与 end_id 计频次。
    """
    df_chn = df_route[df_route[filter_col] == CHN_ISO3]
    freq_s = (
        pd.concat([df_chn["start_id"], df_chn["end_id"]])
        .value_counts()
        .rename_axis("id")
        .reset_index(name="frequency")
    )
    return freq_s


def _weighted_mean(df: pd.DataFrame) -> dict | None:
    """对 df 中的三个乘数列计算频次加权平均，返回结果字典；数据不足返回 None。"""
    sub = (
        df
        .replace([np.inf, -np.inf], np.nan)
        .dropna(subset=MULT_COLS)
    )
    sub = sub[sub["frequency"] > 0]
    if sub.empty:
        return None
    wmean = lambda col: float(np.average(sub[col], weights=sub["frequency"]))
    return {
        "n_ports":        len(df),
        "multiplier":     wmean("multiplier"),
        "multiplier_dom": wmean("multiplier_dom"),
        "multiplier_row": wmean("multiplier_row"),
    }


def run(direction: str) -> None:
    """
    direction: "CHN2World" 或 "World2CHN"
    """
    cfg          = DIRECTION_CONFIG[direction]
    filter_col   = cfg["filter_iso_col"]
    excel_prefix = cfg["excel_prefix"]

    choke_dir  = disrupt(direction, "01_routes_csv")
    out_dir    = mrio(direction, "chokepoints")
    mult_path  = os.path.join(mrio(direction, "multipliers"), "output_multiplier.csv")
    ports_path = os.path.join(mrio(direction, "input"), f"{direction}_ports_updated.csv")

    # ── 前置检查 ─────────────────────────────────────────────────────────────
    if not os.path.exists(mult_path):
        print(f"[P3 Step 4] {direction}: output_multiplier.csv 不存在，请先运行 step2。")
        return
    if not os.path.isdir(choke_dir):
        print(f"[P3 Step 4] {direction}: 要道CSV目录不存在 → {choke_dir}")
        print("  请先运行 Phase 2 step1。")
        return

    # ── 读取乘数表 ────────────────────────────────────────────────────────────
    df_multi     = pd.read_csv(mult_path)
    csv_files    = sorted(f for f in os.listdir(choke_dir) if f.lower().endswith(".csv"))
    results_list = []

    print(f"[P3 Step 4] {direction}: 发现 {len(csv_files)} 个要道 CSV")

    # ── Part A: 逐要道处理 ────────────────────────────────────────────────────
    for fname in csv_files:
        choke_name = os.path.splitext(fname)[0]
        df_route   = pd.read_csv(os.path.join(choke_dir, fname))
        freq_df    = _build_freq(df_route, filter_col)

        df_filtered = df_multi[df_multi["id"].isin(freq_df["id"])].copy()
        df_filtered = df_filtered.merge(freq_df, on="id", how="left")

        out_path = os.path.join(out_dir, f"{choke_name}_filtered.csv")
        df_filtered.to_csv(out_path, index=False, encoding="utf-8-sig")
        print(f"  {choke_name}: {len(df_filtered)} 行 → {out_path}")

        wm = _weighted_mean(df_filtered)
        if wm is not None:
            wm["chokepoint"] = choke_name
            results_list.append(wm)
        else:
            print(f"  ⚠ {choke_name}: 缺少必要列或无有效数据，跳过汇总。")

    # ── Part B: 全部港口汇总 ──────────────────────────────────────────────────
    if os.path.exists(ports_path):
        df_ports  = pd.read_csv(ports_path)
        freq_all  = (
            df_ports["id"]
            .value_counts()
            .rename_axis("id")
            .reset_index(name="frequency")
        )
        df_all = df_multi[df_multi["id"].isin(freq_all["id"])].copy()
        df_all = df_all.merge(freq_all, on="id", how="left")

        all_path = os.path.join(out_dir, f"{direction}_ports_filtered.csv")
        df_all.to_csv(all_path, index=False, encoding="utf-8-sig")
        print(f"[P3 Step 4] {direction}: 全部港口 {len(df_all)} 行 → {all_path}")

        wm_all = _weighted_mean(df_all)
        if wm_all is not None:
            wm_all["chokepoint"] = f"{direction}_ALL"
            results_list.insert(0, wm_all)
    else:
        print(f"[P3 Step 4] {direction}: ports_updated.csv 不存在，跳过全部港口汇总。")

    # ── 保存汇总 Excel ────────────────────────────────────────────────────────
    if not results_list:
        print(f"[P3 Step 4] {direction}: 无有效结果，未生成 Excel。")
        return

    col_order = ["chokepoint", "n_ports", "multiplier", "multiplier_dom", "multiplier_row"]
    df_result = pd.DataFrame(results_list)[col_order]

    xlsx_path = os.path.join(out_dir, f"{excel_prefix}_要道加权平均结果.xlsx")
    df_result.to_excel(xlsx_path, index=False, engine="openpyxl")
    print(f"[P3 Step 4] {direction}: ✅ 汇总 Excel → {xlsx_path}")


if __name__ == "__main__":
    for d in ["CHN2World", "World2CHN"]:
        run(d)
