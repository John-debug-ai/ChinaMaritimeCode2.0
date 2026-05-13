"""
Phase 2 / Step 1: 关键线路选择

对每个关键海峡点文件（CHOKEPOINTS_DIR 中的 .shp），
与 phase1 输出的带流量路径 GeoPackage 做空间相交，
筛选出经过该海峡的所有路径，导出 CSV。

处理流程（每个方向独立运行）：
  1. 读取 shortest_paths_{direction}_with_flows.gpkg（phase1 step5 输出）
  2. 遍历 CHOKEPOINTS_DIR 中所有 .shp 点文件
  3. 选取与点集相交的路径
  4. 按 start_iso3 / end_iso3 方向过滤（CHN2World 保留 start_iso3=CHN，
     World2CHN 保留 end_iso3=CHN）
  5. 属性表导出为 CSV（去除 geometry）

输出目录：output/disruption/{direction}/01_routes_csv/
  文件命名：{海峡名称}.csv（来自 .shp 文件名）
"""

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import geopandas as gpd
import pandas as pd

from shared.config import out, disrupt, CHOKEPOINTS_DIR


def run(direction: str) -> None:
    """
    direction: "CHN2World" 或 "World2CHN"
    """
    # ── 读取带流量路径 ─────────────────────────────────────────────────────
    routes_path = os.path.join(
        out(direction, "routes"),
        f"shortest_paths_{direction}_with_flows.gpkg",
    )
    if not os.path.exists(routes_path):
        print(f"[P2 Step 1] {direction}: 路径文件不存在，请先运行 phase1 step5。")
        return

    lines = gpd.read_file(routes_path)

    # CHN2World → 保留 start_iso3=CHN；World2CHN → 保留 end_iso3=CHN
    iso_col = "start_iso3" if direction == "CHN2World" else "end_iso3"
    lines = lines[lines[iso_col] == "CHN"].copy()

    output_dir = disrupt(direction, "01_routes_csv")

    # ── 遍历关键海峡点文件 ─────────────────────────────────────────────────
    shp_files = [f for f in os.listdir(CHOKEPOINTS_DIR) if f.endswith(".shp")]
    if not shp_files:
        print(f"[P2 Step 1] {direction}: {CHOKEPOINTS_DIR} 中未找到 .shp 文件。")
        return

    processed = 0
    for filename in sorted(shp_files):
        shp_path  = os.path.join(CHOKEPOINTS_DIR, filename)
        base_name = os.path.splitext(filename)[0]

        points = gpd.read_file(shp_path)
        if lines.crs != points.crs:
            points = points.to_crs(lines.crs)

        # 与点集相交的路径
        selected = lines[lines.geometry.intersects(points.union_all())].copy()

        # 过滤 v1~v11 和 q1~q11 全为 0 的行（无贸易流量，无需参与中断计算）
        flow_cols = [f"v{i}" for i in range(1, 12)] + [f"q{i}" for i in range(1, 12)]
        existing  = [c for c in flow_cols if c in selected.columns]
        if existing:
            before   = len(selected)
            selected = selected[selected[existing].any(axis=1)]
            dropped  = before - len(selected)
            if dropped:
                print(f"    删除全零流量行: {dropped} 行")

        csv_path = os.path.join(output_dir, f"{base_name}.csv")
        selected.drop(columns="geometry").to_csv(csv_path, index=False, encoding="utf-8-sig")
        processed += 1
        print(f"  {direction} / {base_name}: {len(selected)} 条路径 → {csv_path}")

    print(f"[P2 Step 1] {direction}: {processed} 个海峡已处理，结果保存至 {output_dir}")


if __name__ == "__main__":
    for d in ["CHN2World", "World2CHN"]:
        run(d)
