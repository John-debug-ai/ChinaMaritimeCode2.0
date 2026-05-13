"""
shared/graph_utils.py — 海运网络图构建与路径计算工具

phase1（step4）和 phase2（step3）共用的图算法函数：

  build_graph(roads_gdf)
      从海运网络 GeoDataFrame 构建 NetworkX 无向图。

  complete_graph(G, node_list, max_dist_m)
      用 KDTree 在 max_dist_m 范围内补全近邻边，提升连通性。

  build_node_gdf(node_pos, crs)
      将节点位置字典转为 GeoDataFrame，用于 snap_to_graph。

  snap_to_graph(points_gdf, node_gdf)
      将港口点 snap 到图中最近节点，返回节点 ID 列表。

  calc_shortest_paths(G, starts, ends, node_pos)
      为所有（起点港 × 终点港）对计算 Dijkstra 最短路径。

  match_flows_to_routes(gdf, flow_dir, n_sectors)
      将流量 CSV 按（出口港, 进口港）匹配到路径 GeoDataFrame，
      累加写入 q1~qN / v1~vN 列。
"""

import os
from glob import glob

import geopandas as gpd
import networkx as nx
import numpy as np
import pandas as pd
from geopy.distance import geodesic
from networkx.exception import NetworkXNoPath, NodeNotFound
from scipy.spatial import cKDTree
from shapely.geometry import LineString, Point
from tqdm import tqdm

CRS = "EPSG:4326"


# ─────────────────────────────────────────────────────────────────────────────
# 图构建
# ─────────────────────────────────────────────────────────────────────────────

def build_graph(roads_gdf) -> tuple[nx.Graph, list, dict]:
    """从海运网络 GeoDataFrame 构建 NetworkX 无向图。

    返回：(图, 节点坐标列表, {node_id: Point})
    """
    nodes_set = set()
    edges = []

    for line in roads_gdf.geometry:
        coords = list(line.coords)
        for coord in coords:
            nodes_set.add(coord)
        start_ll = (coords[0][1],  coords[0][0])
        end_ll   = (coords[-1][1], coords[-1][0])
        edges.append((coords[0], coords[-1], geodesic(start_ll, end_ll).meters))

    node_list   = list(nodes_set)
    coord_to_id = {c: i for i, c in enumerate(node_list)}
    node_pos    = {i: Point(x, y) for i, (x, y) in enumerate(node_list)}

    G = nx.Graph()
    for u_coord, v_coord, length in edges:
        G.add_edge(coord_to_id[u_coord], coord_to_id[v_coord], length=length)

    return G, node_list, node_pos


def complete_graph(G: nx.Graph, node_list: list, max_dist_m: float) -> nx.Graph:
    """用 KDTree 在 max_dist_m 范围内补全近邻边，提升图的连通性。"""
    coords   = np.array([(x, y) for x, y in node_list])
    tree     = cKDTree(coords)
    existing = set(G.edges())
    new_edges = []

    for i in tqdm(range(len(node_list)), desc="  补全图连通性"):
        for j in tree.query_ball_point(coords[i], max_dist_m / 111_000):
            if i >= j:
                continue
            if (i, j) in existing or (j, i) in existing:
                continue
            pt1 = (coords[i][1], coords[i][0])
            pt2 = (coords[j][1], coords[j][0])
            new_edges.append((i, j, geodesic(pt1, pt2).meters))

    G.add_weighted_edges_from(new_edges, weight="length")
    return G


def build_node_gdf(node_pos: dict, crs: str = CRS) -> gpd.GeoDataFrame:
    """将节点位置字典转为 GeoDataFrame，用于 snap_to_graph。"""
    return gpd.GeoDataFrame(
        {"node": list(node_pos.keys()), "geometry": list(node_pos.values())},
        crs=crs,
    )


def snap_to_graph(
    points_gdf: gpd.GeoDataFrame,
    node_gdf: gpd.GeoDataFrame,
) -> list:
    """将港口点 snap 到图中最近节点，返回节点 ID 列表。"""
    snap_tree = cKDTree([pt.coords[0] for pt in node_gdf.geometry])

    def nearest(pt):
        _, idx = snap_tree.query(pt.coords[0])
        return node_gdf.iloc[idx]["node"]

    return [nearest(pt) for pt in points_gdf.geometry]


# ─────────────────────────────────────────────────────────────────────────────
# 最短路径计算
# ─────────────────────────────────────────────────────────────────────────────

def calc_shortest_paths(
    G: nx.Graph,
    starts: gpd.GeoDataFrame,
    ends: gpd.GeoDataFrame,
    node_pos: dict,
    label: str = "",
) -> tuple[list, int]:
    """为所有（起点港 × 终点港）对计算 Dijkstra 最短路径。

    返回：(paths_list, failed_count)
    paths_list 中每项为含 geometry/start_id/end_id/length 等字段的字典。
    """
    node_gdf    = build_node_gdf(node_pos)
    start_nodes = snap_to_graph(starts, node_gdf)
    end_nodes   = snap_to_graph(ends,   node_gdf)

    paths, failed = [], 0
    desc = f"  计算路径{' (' + label + ')' if label else ''}"

    for i, sn in enumerate(tqdm(start_nodes, desc=desc)):
        print(f"  起点 {i + 1}/{len(start_nodes)}: {starts.iloc[i]['name']}")
        for j, en in enumerate(end_nodes):
            if sn == en:
                continue
            try:
                path_nodes = nx.shortest_path(G, sn, en, weight="length")
                coords = [node_pos[n].coords[0] for n in path_nodes]
                length = sum(
                    geodesic((coords[k][1],   coords[k][0]),
                             (coords[k+1][1], coords[k+1][0])).meters
                    for k in range(len(coords) - 1)
                )
                paths.append({
                    "geometry":   LineString(coords),
                    "start_id":   starts.iloc[i]["id"],
                    "end_id":     ends.iloc[j]["id"],
                    "start_name": starts.iloc[i]["name"],
                    "end_name":   ends.iloc[j]["name"],
                    "start_iso3": starts.iloc[i]["iso3"],
                    "end_iso3":   ends.iloc[j]["iso3"],
                    "length":     length,
                })
            except (NetworkXNoPath, NodeNotFound):
                failed += 1

    return paths, failed


# ─────────────────────────────────────────────────────────────────────────────
# 精确配对最短路径计算（用于 Phase 2 中断绕行，仅计算 step1 筛出的港口对）
# ─────────────────────────────────────────────────────────────────────────────

def calc_shortest_paths_pairs(
    G: nx.Graph,
    starts: gpd.GeoDataFrame,
    ends: gpd.GeoDataFrame,
    node_pos: dict,
    pairs: list[tuple[str, str]],
    label: str = "",
) -> tuple[list, int]:
    """仅对指定港口对列表计算中断网络上的最短路径。

    与 calc_shortest_paths 的区别：
      - 输入 pairs 是 [(start_id, end_id), ...] 的精确配对列表
      - 对每个唯一起点只运行一次 single_source_dijkstra，
        再从结果中提取该起点的所有目标终点路径
      - 计算量从「所有起点 × 所有终点」降为「唯一起点数次 Dijkstra」

    返回：(paths_list, failed_count)，格式与 calc_shortest_paths 完全相同。
    """
    if not pairs:
        return [], 0

    # ── 1. 按起点分组 ─────────────────────────────────────────────────────
    pairs_by_start: dict[str, list[str]] = {}
    for s_id, e_id in pairs:
        pairs_by_start.setdefault(str(s_id), []).append(str(e_id))

    unique_start_ids = set(pairs_by_start.keys())
    unique_end_ids   = {str(e) for ends_list in pairs_by_start.values()
                        for e in ends_list}

    # ── 2. 过滤港口 GDF，只保留本要道涉及的港口 ─────────────────────────
    starts_sub = starts[starts["id"].astype(str).isin(unique_start_ids)].copy()
    ends_sub   = ends[ends["id"].astype(str).isin(unique_end_ids)].copy()

    if starts_sub.empty:
        print(f"  ⚠ [{label}] 没有找到匹配的起点港口，跳过")
        return [], len(pairs)

    # ── 3. 一次性 snap 所有涉及港口到图节点 ─────────────────────────────
    node_gdf = build_node_gdf(node_pos)
    start_nodes = snap_to_graph(starts_sub, node_gdf)
    end_nodes   = snap_to_graph(ends_sub,   node_gdf)

    # 建立 id → graph_node 查找表
    start_snap = {
        str(row["id"]): start_nodes[i]
        for i, (_, row) in enumerate(starts_sub.iterrows())
    }
    end_snap = {
        str(row["id"]): end_nodes[i]
        for i, (_, row) in enumerate(ends_sub.iterrows())
    }

    # 建立 id → 港口属性行 查找表（用于填写结果字段）
    start_info = {str(row["id"]): row for _, row in starts_sub.iterrows()}
    end_info   = {str(row["id"]): row for _, row in ends_sub.iterrows()}

    # ── 4. 逐起点跑单源 Dijkstra，提取目标终点路径 ───────────────────────
    paths  = []
    failed = 0

    # 分类收集失败原因
    # port_not_in_gdf : 港口 ID 在 GeoDataFrame 中找不到（数据不匹配）
    # source_isolated : 起点节点不在中断图中（snap 到的节点被删边后孤立）
    # disconnected    : 中断网络中起点→终点无路径（真正断连）
    # same_node       : 起终点 snap 到同一图节点
    fail_port_not_in_gdf: list[str] = []   # 记录具体 ID，方便排查
    fail_source_isolated: list[str] = []
    fail_disconnected:    int = 0          # 数量多，只统计
    fail_same_node:       list[tuple] = []

    desc = f"  计算路径{' (' + label + ')' if label else ''}"
    start_id_list = list(pairs_by_start.keys())

    for idx, start_id in enumerate(tqdm(start_id_list, desc=desc)):
        print(f"  起点 {idx + 1}/{len(start_id_list)}: "
              f"{start_info.get(start_id, {}).get('name', start_id)}")

        # ── 起点 ID 在 GDF 中找不到 ────────────────────────────────────
        sn = start_snap.get(start_id)
        if sn is None:
            for end_id in pairs_by_start[start_id]:
                fail_port_not_in_gdf.append(f"start={start_id}")
            failed += len(pairs_by_start[start_id])
            continue

        # ── 单源 Dijkstra（起点节点不在图中会抛 NodeNotFound）──────────
        try:
            _, path_dict = nx.single_source_dijkstra(G, sn, weight="length")
        except NodeNotFound:
            s_name = start_info.get(start_id, {}).get("name", start_id)
            fail_source_isolated.append(f"{start_id}({s_name})")
            failed += len(pairs_by_start[start_id])
            continue
        except Exception as exc:
            s_name = start_info.get(start_id, {}).get("name", start_id)
            fail_source_isolated.append(f"{start_id}({s_name})[{exc}]")
            failed += len(pairs_by_start[start_id])
            continue

        # ── 逐终点提取路径 ──────────────────────────────────────────────
        for end_id in pairs_by_start[start_id]:
            en = end_snap.get(end_id)

            if en is None:
                fail_port_not_in_gdf.append(f"end={end_id}")
                failed += 1
                continue

            if sn == en:
                fail_same_node.append((start_id, end_id))
                failed += 1
                continue

            if en not in path_dict:
                fail_disconnected += 1
                failed += 1
                continue

            path_nodes = path_dict[en]
            coords = [node_pos[n].coords[0] for n in path_nodes]
            length = sum(
                geodesic((coords[k][1],   coords[k][0]),
                         (coords[k+1][1], coords[k+1][0])).meters
                for k in range(len(coords) - 1)
            )
            s_row = start_info[start_id]
            e_row = end_info[end_id]
            paths.append({
                "geometry":   LineString(coords),
                "start_id":   s_row["id"],
                "end_id":     e_row["id"],
                "start_name": s_row.get("name", ""),
                "end_name":   e_row.get("name", ""),
                "start_iso3": s_row.get("iso3", ""),
                "end_iso3":   e_row.get("iso3", ""),
                "length":     length,
            })

    # ── 5. 打印失败汇总 ───────────────────────────────────────────────────
    if failed:
        tag = f"[{label}] " if label else ""
        print(f"  {tag}失败汇总（共 {failed} 对）：")
        if fail_disconnected:
            print(f"    · 中断后无路径（断连）    : {fail_disconnected} 对"
                  f"  ← 中断网络中真正不可达，已记入 miss.csv")
        if fail_source_isolated:
            print(f"    · 起点节点孤立（被删边）  : {len(fail_source_isolated)} 个起点")
            for s in fail_source_isolated:
                print(f"        {s}")
        if fail_same_node:
            print(f"    · 起终点 snap 到同一节点  : {len(fail_same_node)} 对")
            for s, e in fail_same_node:
                print(f"        start={s}  end={e}")
        if fail_port_not_in_gdf:
            print(f"    · 港口 ID 在 GDF 中找不到 : {len(fail_port_not_in_gdf)} 项（数据不匹配）")
            for item in fail_port_not_in_gdf:
                print(f"        {item}")

    return paths, failed


# ─────────────────────────────────────────────────────────────────────────────
# 流量匹配
# ─────────────────────────────────────────────────────────────────────────────

def match_flows_to_routes(
    gdf: gpd.GeoDataFrame,
    flow_dir: str,
    n_sectors: int = 11,
    exclude_prefix: str = "missing_ports_",
) -> gpd.GeoDataFrame:
    """将流量 CSV 按（出口港, 进口港）匹配到路径 GeoDataFrame，
    累加写入 q1~q{n} / v1~v{n} 列。

    返回：带流量列的 GeoDataFrame（reset_index 后，key 作为普通列）
    """
    gdf = gdf.copy()
    for i in range(1, n_sectors + 1):
        gdf[f"q{i}"] = 0.0
        gdf[f"v{i}"] = 0.0

    gdf["key"] = gdf["start_id"].astype(str) + "_" + gdf["end_id"].astype(str)
    gdf.set_index("key", inplace=True)

    csv_files = [
        f for f in glob(os.path.join(flow_dir, "*.csv"))
        if not os.path.basename(f).startswith(exclude_prefix)
    ]
    unmatched  = 0
    total_rows = 0

    for csv_file in csv_files:
        df = pd.read_csv(csv_file)
        for _, row in df.iterrows():
            key = f"{row['export_port']}_{row['import_port']}"
            s   = int(row["sector"])
            total_rows += 1
            if key in gdf.index:
                gdf.at[key, f"q{s}"] += row["q_flow"]
                gdf.at[key, f"v{s}"] += row["v_flow"]
            elif str(row["export_port"]) != str(row["import_port"]):
                unmatched += 1

    if unmatched:
        print(f"  ⚠ {unmatched}/{total_rows} 行未匹配到路径")

    gdf.reset_index(inplace=True)
    return gdf
