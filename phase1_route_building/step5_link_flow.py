"""
Step 5: 将流量数据关联到最短路径

遍历 step3 生成的所有流量 CSV，按（出口港 ID, 进口港 ID）组合
匹配到 step4 生成的路径 GeoPackage，将 11 个行业的 q/v 值
分别累加写入 q1~q11、v1~v11 列，输出 GeoPackage 格式。

输出：output/{direction}/routes/shortest_paths_{direction}_with_flows.gpkg
"""

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from shared.config import out
from shared.graph_utils import match_flows_to_routes
import geopandas as gpd


def run(direction: str) -> None:
    """
    direction: "CHN2World" 或 "World2CHN"
    """
    routes_dir = out(direction, "routes")
    gpkg_path  = os.path.join(routes_dir, f"shortest_paths_{direction}.gpkg")
    flow_dir   = out(direction, "flow")

    if not os.path.exists(gpkg_path):
        print(f"[Step 5] {direction}: 路径 GeoPackage 不存在，请先运行 step4。")
        return

    gdf = gpd.read_file(gpkg_path)
    gdf = match_flows_to_routes(gdf, flow_dir, n_sectors=11)

    out_path = os.path.join(routes_dir, f"shortest_paths_{direction}_with_flows.gpkg")
    gdf.to_file(out_path, driver="GPKG", encoding="utf-8")

    print(f"[Step 5] {direction}: 流量已关联 → {out_path}")


if __name__ == "__main__":
    for d in ["CHN2World", "World2CHN"]:
        run(d)
