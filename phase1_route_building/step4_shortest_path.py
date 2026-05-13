"""
Step 4: 海运最短路径计算

在海运网络图上，为每对（起点港, 终点港）计算 Dijkstra 最短路径。

算法流程：
  1. 读取海运网络 shapefile，构建带权无向图（权重 = 球面距离/米）
  2. 用 KDTree 补全近邻边（max_dist 内的孤立节点互联），确保连通性
  3. 将港口点 snap 到图中最近节点
  4. 对所有起终点对求最短路径，输出路径 GeoPackage

输出：output/{direction}/routes/shortest_paths_{direction}.gpkg

支持传入自定义网络（如删除某条航道的场景分析）。
"""

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import geopandas as gpd

from shared.config import RAW_DATA, out, GRAPH_SNAP_DISTANCE_M, DIRECTION_PORTS
from shared.graph_utils import build_graph, complete_graph, calc_shortest_paths

CRS = "EPSG:4326"


def run(direction: str, network_shp: str = None) -> None:
    """
    direction:   "CHN2World" 或 "World2CHN"
    network_shp: 可选，自定义海运网络路径（默认用 config.RAW_DATA["maritime_network"]）
                 适用于删除关键航道的场景分析（如封锁苏伊士运河）
    """
    network_path = network_shp or RAW_DATA["maritime_network"]

    # 读取网络和港口
    roads     = gpd.read_file(network_path).to_crs(CRS)
    ports_dir = out(direction, "ports", "00ports")
    start_fname, end_fname = DIRECTION_PORTS[direction]
    starts = gpd.read_file(os.path.join(ports_dir, start_fname)).to_crs(CRS)
    ends   = gpd.read_file(os.path.join(ports_dir, end_fname)).to_crs(CRS)

    print(f"[Step 4] {direction}: 构建图（{len(roads)} 条边）...")
    G, node_list, node_pos = build_graph(roads)
    G = complete_graph(G, node_list, GRAPH_SNAP_DISTANCE_M)

    paths, failed = calc_shortest_paths(G, starts, ends, node_pos, label=direction)

    # 保存结果
    routes_dir = out(direction, "routes")
    out_path   = os.path.join(routes_dir, f"shortest_paths_{direction}.gpkg")
    gpd.GeoDataFrame(paths, crs=CRS).to_file(out_path, driver="GPKG")

    print(f"[Step 4] {direction}: {len(paths)} 条路径已保存，{failed} 条无法计算 → {out_path}")


if __name__ == "__main__":
    for d in ["CHN2World", "World2CHN"]:
        run(d)
