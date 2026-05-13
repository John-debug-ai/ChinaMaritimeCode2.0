"""
Phase 2 / Step 4: 额外运输成本不确定性分析（蒙特卡洛模拟）

读取 step3 生成的 *_Lc.csv（含 L_c 和 q1~q11 / v1~v11），
对每条绕行路径运行 N_SAMPLES 次蒙特卡洛模拟：
  - 在各行业的船型比例约束区间内随机采样
  - 计算每次采样下的额外运输成本和平均延误时间

输出三项指标（均带不确定性区间）：
  t_mean      — 每条路由货量加权平均延误时间（小时）
  cost_total  — 每条路由所有 Sector 成本之和（路由总额外成本）
  strait_total_cost — 海峡总额外成本（所有路由 cost_total 之和）

成本公式：
  t_i      = L_c / 1000 / speed_i
  cost_i   = q_i/1000 * L_c/1000 * dist_cost_i
           + t_i * q_i/1000 * time_cost_i
           + VOT_i * v_i * t_i / 24

输出目录：output/disruption/{direction}/04_cost_mc/
  route_uncertainty_{海峡名称}.csv  — 路由级结果（含分位数）
  mc_samples_{海峡名称}.csv         — MC 原始样本（total_cost / avg_t）
  海峡不确定性汇总.xlsx              — 所有海峡汇总
  不确定性区间_总览.png              — 可视化
  不确定性_变异系数排序.png          — CV 排序图
"""

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import time
import warnings
warnings.filterwarnings("ignore")

import matplotlib
matplotlib.use("Agg")   # 非交互后端，适合脚本运行
import matplotlib.pyplot as plt
from matplotlib.patches import Patch
from matplotlib.lines import Line2D
import numpy as np
import pandas as pd

from shared.config import disrupt

plt.rcParams["font.sans-serif"] = ["SimHei", "Microsoft YaHei", "Arial Unicode MS"]
plt.rcParams["axes.unicode_minus"] = False


# ─────────────────────────────────────────────────────────────────────────────
# 参数配置
# ─────────────────────────────────────────────────────────────────────────────

# 船型固定参数（来自 05-01）
SHIP_SPEEDS     = np.array([30.0, 20.0, 22.0, 28.0, 20.0])        # km/h
SHIP_DIST_COSTS = np.array([0.002, 0.004, 0.002, 0.001, 0.006])    # 距离成本
SHIP_TIME_COSTS = np.array([0.03,  0.06,  0.03,  0.03,  0.11])     # 时间成本

# 11 个 Sector 的船型比例约束区间（%），格式：(下限, 上限)
BOUNDS = {
    1:  [(20, 30), (70, 80), (0, 10), (0,  5), (0,  5)],
    2:  [(80, 90), (0,   5), (10,20), (0,  5), (0,  5)],
    3:  [(0,  10), (70, 80), (0,  5), (0,  5), (20, 30)],
    4:  [(70, 80), (10, 20), (0, 10), (0,  5), (0, 10)],
    5:  [(80, 90), (0,   5), (0, 10), (0,  5), (0,  5)],
    6:  [(50, 60), (30, 40), (0, 10), (0,  5), (0,  5)],
    7:  [(10, 20), (10, 20), (0,  5), (0,  5), (50, 60)],
    8:  [(30, 40), (40, 50), (10,20), (0,  5), (0,  5)],
    9:  [(80, 90), (0,   5), (0, 10), (0,  5), (0,  5)],
    10: [(10, 20), (0,   5), (0, 10), (80,90), (0,  5)],
    11: [(80, 90), (0,   5), (0, 10), (0,  5), (0,  5)],
}

# VOT（价值时间系数，按行业固定，不参与不确定性采样）
VOT_LIST = np.array([0.010, 0.031, 0.005, 0.031, 0.010, 0.010,
                     0.010, 0.010, 0.020, 0.043, 0.020])

# 蒙特卡洛设置
N_SAMPLES   = 1000    # 采样次数（增大可提高精度）
BATCH_SIZE  = 500    # 批大小（平衡速度与内存，建议 200–1000）
RANDOM_SEED = 42

QUANTILES = [0.05, 0.25, 0.50, 0.75, 0.95]
Q_LABELS  = ["P5", "P25", "P50", "P75", "P95"]


# ─────────────────────────────────────────────────────────────────────────────
# 约束采样器
# ─────────────────────────────────────────────────────────────────────────────

def sample_proportions(sector_bounds: list, n_samples: int, rng) -> np.ndarray:
    """在约束区间内采样船型比例向量，返回 shape (n_samples, 5)。

    算法：比例缩放 + 拒绝采样
      1. 从 U(0, slack_k) 采样原始值
      2. 等比例缩放至恰好填满 remaining = 100 - Σlow_k
      3. 检验是否超出 slack_k，超出则丢弃重采
    """
    lows      = np.array([b[0] for b in sector_bounds], dtype=np.float64)
    highs     = np.array([b[1] for b in sector_bounds], dtype=np.float64)
    slacks    = highs - lows
    remaining = 100.0 - lows.sum()

    if remaining < -1e-9:
        raise ValueError(f"下限之和超过100: {lows.sum()}")
    if remaining < 1e-9:
        return np.tile(lows, (n_samples, 1))

    results = []
    while sum(len(r) for r in results) < n_samples:
        batch     = max(n_samples * 6, 5000)
        raw       = rng.uniform(0.0, 1.0, size=(batch, len(lows))) * slacks
        row_sums  = raw.sum(axis=1, keepdims=True)
        row_sums  = np.where(row_sums < 1e-15, 1e-15, row_sums)
        scaled    = raw / row_sums * remaining
        valid     = np.all(scaled <= slacks + 1e-9, axis=1)
        results.append(lows + scaled[valid])

    return np.vstack(results)[:n_samples]


# ─────────────────────────────────────────────────────────────────────────────
# 预计算 11 个 Sector 的 N 组参数样本
# ─────────────────────────────────────────────────────────────────────────────

def precompute_samples() -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """为 11 个 Sector 各生成 N_SAMPLES 组采样，返回 (speed_s, dist_s, time_s)。"""
    print(f"正在为 11 个 Sector 各生成 {N_SAMPLES:,} 组采样...")
    t0  = time.time()
    rng = np.random.default_rng(RANDOM_SEED)

    speed_s = np.zeros((11, N_SAMPLES))
    dist_s  = np.zeros((11, N_SAMPLES))
    time_s  = np.zeros((11, N_SAMPLES))

    for idx in range(11):
        props         = sample_proportions(BOUNDS[idx + 1], N_SAMPLES, rng)  # (N, 5)
        frac          = props / 100.0
        speed_s[idx]  = frac @ SHIP_SPEEDS
        dist_s[idx]   = frac @ SHIP_DIST_COSTS
        time_s[idx]   = frac @ SHIP_TIME_COSTS

    print(f"采样完成，耗时 {time.time()-t0:.2f}s")
    print(f"\n{'Sector':<8} {'速度范围(km/h)':<26}")
    print("-" * 36)
    for idx in range(11):
        s = speed_s[idx]
        print(f"{idx+1:<8} [{s.min():.2f}, {s.max():.2f}]  mean={s.mean():.2f}")

    return speed_s, dist_s, time_s


# ─────────────────────────────────────────────────────────────────────────────
# 核心 MC 计算
# ─────────────────────────────────────────────────────────────────────────────

def run_mc_simulation(
    df: pd.DataFrame,
    speed_s: np.ndarray,
    dist_s: np.ndarray,
    time_s: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    """对给定 DataFrame 运行 N_SAMPLES 次蒙特卡洛模拟（批处理）。

    Returns:
        t_mean_all:     (R, N_SAMPLES)
        cost_total_all: (R, N_SAMPLES)
    """
    R   = len(df)
    L_c = df["L_c"].values.astype(np.float64)
    q   = df[[f"q{i}" for i in range(1, 12)]].values.astype(np.float64)
    v   = df[[f"v{i}" for i in range(1, 12)]].values.astype(np.float64)

    q_sum       = q.sum(axis=1)
    safe_qsum   = np.where(q_sum == 0, 1.0, q_sum)
    L_c_div1000 = L_c / 1000.0
    q_div1000   = q / 1000.0
    vot_v_div24 = VOT_LIST[None, :] * v / 24.0     # (R, 11)

    t_mean_all     = np.zeros((R, N_SAMPLES), dtype=np.float64)
    cost_total_all = np.zeros((R, N_SAMPLES), dtype=np.float64)

    for b_start in range(0, N_SAMPLES, BATCH_SIZE):
        b_end = min(b_start + BATCH_SIZE, N_SAMPLES)

        spd    = speed_s[:, b_start:b_end]    # (11, B)
        dist   = dist_s[:, b_start:b_end]     # (11, B)
        time_c = time_s[:, b_start:b_end]     # (11, B)

        # t_mat[r, i, n] = L_c[r]/1000 / speed[i, n]
        t_mat = L_c_div1000[:, None, None] / spd[None, :, :]   # (R, 11, B)

        # cost_i = q/1000 * L_c/1000 * dist_i  +  t_i * (q/1000 * time_i + VOT*v/24)
        time_factor = q_div1000[:, :, None] * time_c[None, :, :] + vot_v_div24[:, :, None]
        cost_mat = (
            (q_div1000[:, :, None] * L_c_div1000[:, None, None]) * dist[None, :, :]
            + t_mat * time_factor
        )   # (R, 11, B)

        t_mean_all[:, b_start:b_end]     = (t_mat * q[:, :, None]).sum(axis=1) / safe_qsum[:, None]
        cost_total_all[:, b_start:b_end] = cost_mat.sum(axis=1)

    return t_mean_all, cost_total_all


# ─────────────────────────────────────────────────────────────────────────────
# 主循环：逐文件处理
# ─────────────────────────────────────────────────────────────────────────────

def process_all_files(
    direction: str,
    speed_s: np.ndarray,
    dist_s: np.ndarray,
    time_s: np.ndarray,
) -> pd.DataFrame:
    input_dir  = disrupt(direction, "03_reroute")
    output_dir = disrupt(direction, "04_cost_mc")

    csv_files = sorted([f for f in os.listdir(input_dir) if f.endswith("_Lc.csv")])
    print(f"\n共找到 {len(csv_files)} 个 L_c CSV 文件\n")

    strait_summary_rows = []

    for file in csv_files:
        strait_name = file.replace("_Lc.csv", "")
        file_path   = os.path.join(input_dir, file)

        df_raw = pd.read_csv(file_path)

        # 删除 q1~q11 / v1~v11 全为 0 的行
        check_cols = [f"q{i}" for i in range(1, 12)] + [f"v{i}" for i in range(1, 12)]
        df = df_raw[~(df_raw[check_cols].sum(axis=1) == 0)].copy().reset_index(drop=True)

        # 截断负 L_c（网络差异导致的虚假"捷径"，视为零额外绕行距离）
        df["L_c"] = df["L_c"].clip(lower=0)

        print(f"▶ {strait_name}  ({len(df)} 条路由)")
        t0 = time.time()

        # 蒙特卡洛模拟
        t_mc, cost_mc = run_mc_simulation(df, speed_s, dist_s, time_s)   # (R, N)

        q_sum = df[[f"q{i}" for i in range(1, 12)]].sum(axis=1).values

        # ── 路由级统计 ────────────────────────────────────────────────────
        id_cols = [c for c in ["key", "start_name", "end_name",
                               "start_iso3", "end_iso3", "L_c"] if c in df.columns]
        route_stats = df[id_cols].copy()
        route_stats["q_total"] = q_sum

        t_q = np.quantile(t_mc, QUANTILES, axis=1).T       # (R, 5)
        c_q = np.quantile(cost_mc, QUANTILES, axis=1).T    # (R, 5)

        for j, lbl in enumerate(Q_LABELS):
            route_stats[f"t_mean_{lbl}"]     = t_q[:, j]
            route_stats[f"cost_total_{lbl}"] = c_q[:, j]

        route_stats["t_mean_avg"]    = t_mc.mean(axis=1)
        route_stats["t_mean_std"]    = t_mc.std(axis=1)
        route_stats["cost_total_avg"] = cost_mc.mean(axis=1)
        route_stats["cost_total_std"] = cost_mc.std(axis=1)

        route_stats["t_mean_range"]     = (route_stats["t_mean_P95"]
                                           - route_stats["t_mean_P5"])
        route_stats["cost_total_range"] = (route_stats["cost_total_P95"]
                                           - route_stats["cost_total_P5"])

        out_csv = os.path.join(output_dir, f"route_uncertainty_{strait_name}.csv")
        route_stats.to_csv(out_csv, index=False, encoding="utf-8-sig")

        # ── 海峡级统计 ────────────────────────────────────────────────────
        total_q      = q_sum.sum()
        safe_total_q = total_q if total_q > 0 else 1.0

        strait_cost_mc = cost_mc.sum(axis=0)                                       # (N,)
        strait_t_mc    = (t_mc * q_sum[:, None]).sum(axis=0) / safe_total_q       # (N,)

        row = {
            "strait_name":      strait_name,
            "n_routes":         len(df),
            "total_cargo_tons": total_q,
        }
        for q_val, lbl in zip(QUANTILES, Q_LABELS):
            row[f"total_cost_{lbl}"] = np.quantile(strait_cost_mc, q_val)
            row[f"avg_t_{lbl}"]      = np.quantile(strait_t_mc,    q_val)

        row["total_cost_avg"] = strait_cost_mc.mean()
        row["total_cost_std"] = strait_cost_mc.std()
        row["total_cost_cv"]  = (
            strait_cost_mc.std() / abs(strait_cost_mc.mean())
            if strait_cost_mc.mean() != 0 else np.nan
        )
        row["avg_t_avg"] = strait_t_mc.mean()
        row["avg_t_std"] = strait_t_mc.std()

        strait_summary_rows.append(row)

        # 保存该海峡的 MC 原始样本
        pd.DataFrame({"total_cost": strait_cost_mc, "avg_t": strait_t_mc}).to_csv(
            os.path.join(output_dir, f"mc_samples_{strait_name}.csv"),
            index=False, encoding="utf-8-sig",
        )

        elapsed = time.time() - t0
        print(f"   完成 {elapsed:.1f}s | "
              f"total_cost P50={row['total_cost_P50']:.4f}  "
              f"CV={row['total_cost_cv']:.3f}")

        del t_mc, cost_mc   # 释放内存

    return pd.DataFrame(strait_summary_rows)


# ─────────────────────────────────────────────────────────────────────────────
# 汇总 Excel 输出
# ─────────────────────────────────────────────────────────────────────────────

def save_summary(df_summary: pd.DataFrame, output_dir: str) -> None:
    display_cols = [
        "strait_name", "n_routes", "total_cargo_tons",
        "total_cost_P5", "total_cost_P25", "total_cost_P50",
        "total_cost_P75", "total_cost_P95",
        "total_cost_avg", "total_cost_std", "total_cost_cv",
        "avg_t_P5", "avg_t_P25", "avg_t_P50",
        "avg_t_P75", "avg_t_P95",
        "avg_t_avg", "avg_t_std",
    ]
    display_cols = [c for c in display_cols if c in df_summary.columns]
    summary_path = os.path.join(output_dir, "海峡不确定性汇总.xlsx")
    with pd.ExcelWriter(summary_path, engine="openpyxl") as writer:
        df_summary[display_cols].to_excel(writer, sheet_name="海峡汇总", index=False)
    print(f"\n汇总表已保存：{summary_path}")


# ─────────────────────────────────────────────────────────────────────────────
# 可视化
# ─────────────────────────────────────────────────────────────────────────────

def plot_overview(df_summary: pd.DataFrame, output_dir: str) -> None:
    """绘制各海峡总额外成本 + 平均延误时间不确定性区间总览图。"""
    straits = df_summary["strait_name"].tolist()
    x = np.arange(len(straits))
    w = 0.45

    fig, axes = plt.subplots(2, 1, figsize=(14, 11))

    # ── 上图：总额外成本不确定性区间 ─────────────────────────────────────
    ax   = axes[0]
    p5   = df_summary["total_cost_P5"].values
    p25  = df_summary["total_cost_P25"].values
    p50  = df_summary["total_cost_P50"].values
    p75  = df_summary["total_cost_P75"].values
    p95  = df_summary["total_cost_P95"].values

    for i in range(len(straits)):
        ax.plot([x[i], x[i]], [p5[i], p95[i]], color="steelblue", linewidth=2, alpha=0.6)
        ax.bar(x[i], p75[i] - p25[i], bottom=p25[i], width=w,
               color="steelblue", alpha=0.55, zorder=2)
        ax.plot(x[i], p50[i], "o", color="white", markersize=7,
                markeredgecolor="navy", markeredgewidth=1.5, zorder=4)

    ax.set_xticks(x)
    ax.set_xticklabels(straits, rotation=40, ha="right", fontsize=9)
    ax.set_title("各关键海峡 — 总额外成本不确定性区间（P5–P95）",
                 fontsize=12, fontweight="bold")
    ax.set_ylabel("总额外成本")
    ax.grid(axis="y", alpha=0.3)
    ax.legend(handles=[
        Patch(facecolor="steelblue", alpha=0.55, label="P25–P75（四分位范围）"),
        Line2D([0],[0], marker="o", color="w", markerfacecolor="white",
               markeredgecolor="navy", markersize=7, label="P50 中位数"),
        Line2D([0],[0], color="steelblue", linewidth=2, alpha=0.6, label="P5–P95 区间"),
    ], loc="upper right", fontsize=8)

    # ── 下图：平均延误时间不确定性区间 ───────────────────────────────────
    ax2  = axes[1]
    t5   = df_summary["avg_t_P5"].values
    t25  = df_summary["avg_t_P25"].values
    t50  = df_summary["avg_t_P50"].values
    t75  = df_summary["avg_t_P75"].values
    t95  = df_summary["avg_t_P95"].values

    for i in range(len(straits)):
        ax2.plot([x[i], x[i]], [t5[i], t95[i]], color="seagreen", linewidth=2, alpha=0.6)
        ax2.bar(x[i], t75[i] - t25[i], bottom=t25[i], width=w,
                color="seagreen", alpha=0.55, zorder=2)
        ax2.plot(x[i], t50[i], "o", color="white", markersize=7,
                 markeredgecolor="darkgreen", markeredgewidth=1.5, zorder=4)

    ax2.set_xticks(x)
    ax2.set_xticklabels(straits, rotation=40, ha="right", fontsize=9)
    ax2.set_title("各关键海峡 — 货量加权平均延误时间不确定性区间（P5–P95）",
                  fontsize=12, fontweight="bold")
    ax2.set_ylabel("加权平均延误时间（小时）")
    ax2.grid(axis="y", alpha=0.3)
    ax2.legend(handles=[
        Patch(facecolor="seagreen", alpha=0.55, label="P25–P75（四分位范围）"),
        Line2D([0],[0], marker="o", color="w", markerfacecolor="white",
               markeredgecolor="darkgreen", markersize=7, label="P50 中位数"),
        Line2D([0],[0], color="seagreen", linewidth=2, alpha=0.6, label="P5–P95 区间"),
    ], loc="upper right", fontsize=8)

    plt.tight_layout()
    fig_path = os.path.join(output_dir, "不确定性区间_总览.png")
    plt.savefig(fig_path, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"总览图已保存：{fig_path}")


def plot_cv(df_summary: pd.DataFrame, output_dir: str) -> None:
    """绘制各海峡总额外成本变异系数排序图。"""
    df_cv = df_summary[["strait_name", "total_cost_cv"]].sort_values(
        "total_cost_cv", ascending=False)

    fig, ax = plt.subplots(figsize=(10, 5))
    bars = ax.barh(df_cv["strait_name"], df_cv["total_cost_cv"],
                   color="darkorange", alpha=0.75)
    ax.bar_label(bars, fmt="%.3f", padding=3, fontsize=9)
    ax.set_xlabel("变异系数（CV = 标准差 / 均值）")
    ax.set_title("各关键海峡总额外成本不确定性强度（变异系数排序）",
                 fontsize=11, fontweight="bold")
    ax.grid(axis="x", alpha=0.3)
    plt.tight_layout()
    cv_path = os.path.join(output_dir, "不确定性_变异系数排序.png")
    plt.savefig(cv_path, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"变异系数图已保存：{cv_path}")


# ─────────────────────────────────────────────────────────────────────────────
# 主函数入口
# ─────────────────────────────────────────────────────────────────────────────

def run(direction: str) -> None:
    """
    direction: "CHN2World" 或 "World2CHN"
    """
    total_t0 = time.time()
    output_dir = disrupt(direction, "04_cost_mc")

    # Step 1：预计算采样（两个方向共用同一组参数）
    speed_s, dist_s, time_s = precompute_samples()

    # Step 2：逐文件运行 MC，保存路由级结果
    df_summary = process_all_files(direction, speed_s, dist_s, time_s)

    if df_summary.empty:
        print(f"[P2 Step 4] {direction}: 无结果，请先运行 step3。")
        return

    # Step 3：保存汇总 Excel
    save_summary(df_summary, output_dir)

    # Step 4：可视化
    plot_overview(df_summary, output_dir)
    plot_cv(df_summary, output_dir)

    print(f"\n[P2 Step 4] {direction}: 全部完成，总耗时 {time.time()-total_t0:.1f}s")
    print(f"输出目录：{output_dir}")


if __name__ == "__main__":
    for d in ["CHN2World", "World2CHN"]:
        run(d)
