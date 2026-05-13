"""
Step 1: 提取港口数据 + 计算港口流量比例

合并原 step0（提取港口 GeoPackage）和原 step1（计算港口比例）功能：

  1. 从 port_trade_network.csv 筛选涉及中国的记录
  2. 导出起/终点港口 GeoPackage（供 step4 最短路径使用）
     - 合并两个方向的港口，覆盖度优于仅用单向数据
  3. 按（伙伴国家 × 行业）计算港口流量比例
     - 优先使用同向数据
     - 同向缺失的行业，自动从反向数据倒推（对调 flow/from/to 后重新计算比例）

输出：
  output/{direction}/ports/00ports/{start_gpkg}.gpkg
  output/{direction}/ports/00ports/{end_gpkg}.gpkg
  output/{direction}/ports/{iso3}/{iso3}_{sector:02d}.csv

CHN2World 按目的国（iso3_D）分组；World2CHN 按来源国（iso3_O）分组。
"""

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
import geopandas as gpd

from shared.config import RAW_DATA, out, CHN_ISO3
from shared.utils import compute_port_ratios

CRS = "EPSG:4326"

# 每个方向的过滤列、分组列及 GeoPackage 文件名
DIRECTION_CONFIG = {
    "CHN2World": dict(
        same_filter="iso3_O",       # 同向：CHN 为起点
        opp_filter="iso3_D",        # 反向：CHN 为终点
        partner_col="iso3_D",       # 同向伙伴列
        opp_partner_col="iso3_O",   # 反向伙伴列
        start_gpkg="CHNstartports",
        end_gpkg="WORLDendports",
    ),
    "World2CHN": dict(
        same_filter="iso3_D",       # 同向：CHN 为终点
        opp_filter="iso3_O",        # 反向：CHN 为起点
        partner_col="iso3_O",       # 同向伙伴列
        opp_partner_col="iso3_D",   # 反向伙伴列
        start_gpkg="WORLDstartports",
        end_gpkg="CHNendports",
    ),
}


def _invert_raw(df: pd.DataFrame) -> pd.DataFrame:
    """对调反向原始港口数据的方向列，使其适用于当前方向。

    在计算比例之前调用（ratio 列此时尚不存在）。
    对调：from_id ↔ to_id，from_iso3 ↔ to_iso3，
          iso3_O ↔ iso3_D，port_export ↔ port_import
    """
    df = df.copy()
    for col_a, col_b in [
        ("from_id",   "to_id"),
        ("from_iso3", "to_iso3"),
        ("iso3_O",    "iso3_D"),
    ]:
        if col_a in df.columns and col_b in df.columns:
            df[col_a], df[col_b] = df[col_b].values.copy(), df[col_a].values.copy()
    if "flow" in df.columns:
        df["flow"] = df["flow"].map(
            {"port_export": "port_import", "port_import": "port_export"}
        ).fillna(df["flow"])
    return df


def run(direction: str) -> None:
    """
    direction: "CHN2World" 或 "World2CHN"
    """
    cfg = DIRECTION_CONFIG[direction]

    # ── 读取原始数据 ───────────────────────────────────────────────────────
    all_df    = pd.read_csv(RAW_DATA["port_trade_network"])
    gdf_ports = gpd.read_file(RAW_DATA["ports_shp"]).to_crs(CRS)

    same_df = all_df[all_df[cfg["same_filter"]] == CHN_ISO3].copy()
    opp_df  = all_df[all_df[cfg["opp_filter"]]  == CHN_ISO3].copy()

    # ── 导出 GeoPackage（两向合并，提升港口覆盖度）────────────────────────
    # 同向 port_export + 反向 port_import 的并集 = 起点港
    # 同向 port_import + 反向 port_export 的并集 = 终点港
    gpkg_dir  = out(direction, "ports", "00ports")
    start_ids = (
        set(same_df[same_df["flow"] == "port_export"]["id"].unique()) |
        set(opp_df [opp_df ["flow"] == "port_import"]["id"].unique())
    )
    end_ids = (
        set(same_df[same_df["flow"] == "port_import"]["id"].unique()) |
        set(opp_df [opp_df ["flow"] == "port_export"]["id"].unique())
    )
    gdf_ports[gdf_ports["id"].isin(start_ids)].to_file(
        os.path.join(gpkg_dir, f"{cfg['start_gpkg']}.gpkg"), driver="GPKG")
    gdf_ports[gdf_ports["id"].isin(end_ids)].to_file(
        os.path.join(gpkg_dir, f"{cfg['end_gpkg']}.gpkg"), driver="GPKG")
    print(f"[Step 1] {direction}: GeoPackage 已导出"
          f"（{len(start_ids)} 起点港, {len(end_ids)} 终点港）")

    # ── 计算港口比例 ───────────────────────────────────────────────────────
    partner_col     = cfg["partner_col"]
    opp_partner_col = cfg["opp_partner_col"]

    all_partners = (
        set(same_df[partner_col].dropna().unique()) |
        set(opp_df[opp_partner_col].dropna().unique())
    ) - {CHN_ISO3}

    total    = 0
    fallback = 0

    for iso3 in sorted(all_partners):
        out_dir   = out(direction, "ports", str(iso3))
        iso3_same = same_df[same_df[partner_col] == iso3]
        iso3_opp  = opp_df [opp_df [opp_partner_col] == iso3]

        same_sectors = set(iso3_same["Industries"].dropna().unique())
        opp_sectors  = set(iso3_opp["Industries"].dropna().unique())

        # 同向有数据的行业：直接计算
        for sector in same_sectors:
            sub = iso3_same[iso3_same["Industries"] == sector].copy()
            sub = compute_port_ratios(sub)
            sub.to_csv(
                os.path.join(out_dir, f"{iso3}_{int(sector):02d}.csv"),
                index=False, encoding="utf-8-sig",
            )
            total += 1

        # 同向缺失、反向有数据的行业：对调方向后补全
        for sector in (opp_sectors - same_sectors):
            sub = iso3_opp[iso3_opp["Industries"] == sector].copy()
            sub = _invert_raw(sub)
            sub = compute_port_ratios(sub)
            sub.to_csv(
                os.path.join(out_dir, f"{iso3}_{int(sector):02d}.csv"),
                index=False, encoding="utf-8-sig",
            )
            total    += 1
            fallback += 1

    print(f"[Step 1] {direction}: {len(all_partners)} 个国家, "
          f"{total} 个行业港口文件（其中 {fallback} 个由反向数据补全）")


if __name__ == "__main__":
    for d in ["CHN2World", "World2CHN"]:
        run(d)
