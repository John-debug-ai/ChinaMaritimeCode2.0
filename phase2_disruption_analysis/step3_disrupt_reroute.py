"""
Phase 2 / Step 3: 关键节点中断 + 重新寻路 + L_c 计算

对每个关键海峡：
  1. 从原始海运网络中删除经过该海峡的节点/边，得到"中断网络"
  2. 在中断网络上重新计算所有港口对的最短路径（绕行路径）
  3. 将绕行路径与 phase1 原始路径对比，计算额外绕行距离 L_c
     L_c = 绕行路径 length − 原始路径 length
  4. 将 q1~q11 / v1~v11 流量关联到绕行路径
  5. 最终输出带 L_c 和流量的 CSV（每个海峡一个文件）

输出目录：output/disruption/{direction}/03_reroute/
  {海峡名称}_reroute.gpkg      — 绕行路径（带流量 + L_c）
  {海峡名称}_Lc.csv            — 属性表（按 L_c 排序）
  {海峡名称}_miss.csv          — 无法绕行的流量记录
"""

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import geopandas as gpd
import pandas as pd
from shapely.geometry import Point

from shared.config import RAW_DATA, out, disrupt, CHOKEPOINTS_DIR, GRAPH_SNAP_DISTANCE_M, DIRECTION_PORTS
from shared.graph_utils import build_graph, complete_graph, calc_shortest_paths_pairs, match_flows_to_routes

CRS = "EPSG:4326"


def _rebuild_network(roads_gdf: gpd.GeoDataFrame, points_gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """从原始网络中删除包含关键节点的边，返回中断后的网络 GeoDataFrame。"""
    if roads_gdf.crs != points_gdf.crs:
        points_gdf = points_gdf.to_crs(roads_gdf.crs)

    point_union = points_gdf.union_all()

    def _edge_contains_point(geom) -> bool:
        coords = list(geom.coords)
        for pt in [Point(coords[0]), Point(coords[-1])]:
            if pt.within(point_union):
                return True
        return False

    mask = roads_gdf.geometry.apply(_edge_contains_point)
    filtered = roads_gdf[~mask].copy()
    return filtered


def run(direction: str) -> None:
    """
    direction: "CHN2World" 或 "World2CHN"
    """
    # ── 读取原始路径（含流量）用于 L_c 计算 ──────────────────────────────
    orig_path = os.path.join(
        out(direction, "routes"),
        f"shortest_paths_{direction}_with_flows.gpkg",
    )
    if not os.path.exists(orig_path):
        print(f"[P2 Step 3] {direction}: 原始路径文件不存在，请先运行 phase1。")
        return

    gdf_orig = gpd.read_file(orig_path)
    orig_length_map = (
        gdf_orig.set_index(
            gdf_orig["start_id"].astype(str) + "_" + gdf_orig["end_id"].astype(str)
        )["length"]
    )

    # ── 读取港口 ──────────────────────────────────────────────────────────
    ports_dir = out(direction, "ports", "00ports")
    start_fname, end_fname = DIRECTION_PORTS[direction]
    starts = gpd.read_file(os.path.join(ports_dir, start_fname)).to_crs(CRS)
    ends   = gpd.read_file(os.path.join(ports_dir, end_fname)).to_crs(CRS)

    # ── 读取原始网络 ──────────────────────────────────────────────────────
    roads_orig = gpd.read_file(RAW_DATA["maritime_network"]).to_crs(CRS)

    flow_dir   = out(direction, "flow")
    output_dir = disrupt(direction, "03_reroute")

    shp_files = sorted([f for f in os.listdir(CHOKEPOINTS_DIR) if f.endswith(".shp")])
    if not shp_files:
        print(f"[P2 Step 3] {direction}: {CHOKEPOINTS_DIR} 中未找到 .shp 文件。")
        return

    for filename in shp_files:
        shp_path  = os.path.join(CHOKEPOINTS_DIR, filename)
        base_name = os.path.splitext(filename)[0]
        print(f"\n[P2 Step 3] {direction} / {base_name}: 删除节点并重新构建图...")

        # 1. 删除关键节点后构建中断网络
        points_gdf   = gpd.read_file(shp_path)
        roads_broken = _rebuild_network(roads_orig, points_gdf)
        print(f"  原路网 {len(roads_orig)} 条边 → 中断后 {len(roads_broken)} 条边")

        # 2. 在中断网络上构建图
        G, node_list, node_pos = build_graph(roads_broken)
        G = complete_graph(G, node_list, GRAPH_SNAP_DISTANCE_M)

        # 3. 从 step1 CSV 读取该要道的精确港口对
        step1_csv = os.path.join(disrupt(direction, "01_routes_csv"), f"{base_name}.csv")
        if not os.path.exists(step1_csv):
            print(f"  ⚠ {base_name}: step1 CSV 不存在，跳过（请先运行 step1）")
            continue
        df_step1 = pd.read_csv(step1_csv)
        if df_step1.empty:
            print(f"  ⚠ {base_name}: step1 CSV 为空（零流量过滤后无路线），跳过")
            continue
        pairs = list(zip(df_step1["start_id"].astype(str),
                         df_step1["end_id"].astype(str)))
        print(f"  {base_name}: 需计算 {len(pairs)} 对（{df_step1['start_id'].nunique()} 个唯一起点）")

        # 4. 仅对 step1 筛出的港口对重新计算最短路径
        paths, failed = calc_shortest_paths_pairs(G, starts, ends, node_pos,
                                                  pairs, label=base_name)
        print(f"  重新计算完成: {len(paths)} 条成功, {failed} 条失败（原因见上方汇总）")

        # 5. 关联流量 + 计算 L_c（仅当有成功绕行路径时）
        gdf_reroute = None
        if paths:
            gdf_reroute = gpd.GeoDataFrame(paths, crs=CRS)
            gdf_reroute = match_flows_to_routes(gdf_reroute, flow_dir, n_sectors=11)

            gdf_reroute["key"] = (
                gdf_reroute["start_id"].astype(str) + "_" +
                gdf_reroute["end_id"].astype(str)
            )
            gdf_reroute["L_c"] = gdf_reroute["length"] - gdf_reroute["key"].map(orig_length_map)
            gdf_reroute = gdf_reroute.dropna(subset=["L_c"])
            gdf_reroute["L_c_abs"] = gdf_reroute["L_c"].abs()

            iso_col = "start_iso3" if direction == "CHN2World" else "end_iso3"
            gdf_reroute = gdf_reroute[gdf_reroute[iso_col] == "CHN"].copy()

        # 6. 保存 GeoPackage（仅当有绕行结果时）
        if gdf_reroute is not None and not gdf_reroute.empty:
            gpkg_path = os.path.join(output_dir, f"{base_name}_reroute.gpkg")
            gdf_reroute.to_file(gpkg_path, driver="GPKG", encoding="utf-8")

            attr_df = pd.DataFrame(gdf_reroute.drop(columns="geometry"))
            attr_df = attr_df.sort_values("L_c_abs", ascending=False)
            lc_path = os.path.join(output_dir, f"{base_name}_Lc.csv")
            attr_df.to_csv(lc_path, index=False, encoding="utf-8-sig")

            print(f"  → GPKG: {gpkg_path}")
            print(f"  → Lc:   {lc_path}")
        else:
            print(f"  → 无绕行路径，跳过 GPKG / Lc.csv 输出")

        # 7. 生成 miss.csv（无论是否有绕行路径，均需生成）
        # rerouted_keys：已成功绕行的配对；若无绕行结果则为空集，即全部视为断连
        rerouted_keys = (
            set(gdf_reroute["start_id"].astype(str) + "_" + gdf_reroute["end_id"].astype(str))
            if gdf_reroute is not None and not gdf_reroute.empty
            else set()
        )
        df_miss_wide = df_step1[
            ~(df_step1["start_id"].astype(str) + "_" + df_step1["end_id"].astype(str))
            .isin(rerouted_keys)
        ].copy()

        if df_miss_wide.empty:
            print(f"  → Miss: 无断连路线")
        else:
            id_cols = [c for c in ["start_id", "end_id", "start_iso3", "end_iso3"] if c in df_miss_wide.columns]
            v_cols  = [f"v{i}" for i in range(1, 12) if f"v{i}" in df_miss_wide.columns]
            q_cols  = [f"q{i}" for i in range(1, 12) if f"q{i}" in df_miss_wide.columns]

            df_v = df_miss_wide[id_cols + v_cols].melt(id_vars=id_cols, var_name="sector", value_name="v_flow")
            df_q = df_miss_wide[id_cols + q_cols].melt(id_vars=id_cols, var_name="sector", value_name="q_flow")
            df_v["sector"] = df_v["sector"].str[1:].astype(int)
            df_q["sector"] = df_q["sector"].str[1:].astype(int)

            df_long = df_v.merge(df_q, on=id_cols + ["sector"])
            df_long = df_long[(df_long["v_flow"] > 0) | (df_long["q_flow"] > 0)]

            miss_path = os.path.join(output_dir, f"{base_name}_miss.csv")
            df_long.to_csv(miss_path, index=False, encoding="utf-8-sig")
            print(f"  → Miss: {miss_path}（{len(df_long)} 行，{df_miss_wide['start_id'].nunique()} 个断连港口对）")

    print(f"\n[P2 Step 3] {direction}: 全部海峡处理完成 → {output_dir}")


if __name__ == "__main__":
    for d in ["CHN2World", "World2CHN"]:
        run(d)
