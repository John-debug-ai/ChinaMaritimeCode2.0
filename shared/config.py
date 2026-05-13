"""
shared/config.py — 全局路径与常量配置

修改说明：
  - RAW_DATA 中的路径指向原始输入数据，请根据实际位置调整
  - OUTPUT_ROOT 及子目录由程序自动创建，无需手动建文件夹
"""

import os

# ─────────────────────────────────────────────────────────────────────────────
# 原始输入数据路径
# ─────────────────────────────────────────────────────────────────────────────
RAW_DATA = {
    # 全球港口间贸易网络（Koks 数据集）
    "port_trade_network": r"E:\02-Trade\00-Koks\01-Global port supply-chains\Global port supply-chains\Port_to_port_network\port_trade_network.csv",
    # 全球港口矢量点数据
    "ports_shp":          r"E:\02-Trade\01-Data\MaritimeNet\Koks\ports.shp",
    # 海运网络线数据（用于最短路径计算）
    "maritime_network":   r"E:\02-Trade\01-Data\MaritimeNet\Koks\main_edges_maritime.shp",
    # 海运网络节点 GeoPackage（含 infra 字段，用于筛选港口节点）
    "nodes_maritime":     r"E:\02-Trade\World&CHN_new\MRIO_combine\Input\nodes_maritime.gpkg",
    # TTD 贸易运输数据集（含运输方式）
    "ttd":                r"E:\02-Trade\01-Data\Trade-and-Transport Dataset\filtered_output2_2019.csv",
    # BACI 贸易数据（仅含总量，无运输方式）
    "baci":               r"E:\02-Trade\01-Data\BACI\BACI_HS17_V202501\BACI_HS17_Y2019_V202501.csv",
    # ISO 数字编码 → ISO3 字母编码映射表
    "iso3_map":           r"E:\ISO3.csv",
    # ISO3 → 国家名称 / 收入组 / 地区（中断分析统计用）
    "iso3_with_region":   r"E:\ISO3_带收入和地区.csv",
    # HS4 产品编码 → ISIC Rev.2 行业编码映射表
    "hs4_isic2_map":      r"E:\02-Trade\01-Data\EORA\hs4_to_isic2_mapping.csv",
    # EORA 11 大类行业中英文名称（中断分析统计用）
    "eora_categories":    r"E:\EORA类别.xlsx",
    # 港口吞吐量利用率（含港口名称，用于 Phase 3 结果统计）
    "port_utilization":   r"E:\02-Trade\00-Koks\01-Port_supply_chains-main\Port_supply_chains-main\Maritime_transport_model\Input\Maritime_network\port_utilization.csv",
}

# ─────────────────────────────────────────────────────────────────────────────
# 关键海峡点文件目录（13 个 SHP，用于 phase2 分析）
# ─────────────────────────────────────────────────────────────────────────────
CHOKEPOINTS_DIR = r"E:\02-Trade\07-ChinaMaritimeCode2.0\input\chokepoints"

# ─────────────────────────────────────────────────────────────────────────────
# Phase 3 — MRIO 投入产出分析专用路径与常量
# ─────────────────────────────────────────────────────────────────────────────
# EORA26 2019 年基准价格数据库目录
EORA_PATH = r"E:\02-Trade\World&CHN_new\MRIO_combine\Input\Eora26_2019_bp"

# 全球国家边界矢量（用于结果 GIS 关联）
GLOBAL_COUNTRY_SHP = r"E:\gadm36_shp全球矢量边界\gadm36_shp\国家级\Global_country.shp"

# 结果统计时排除的特殊 ISO3（澳门、香港单独统计口径与 EORA 不一致）
EXCLUDE_ISO3 = ["MAC", "HKG"]

# 武汉港 → 上海港的 ID 替换映射（Koks 网络中武汉被编为内陆港，统一归入上海）
WUHAN_TO_SHANGHAI = {
    "from_id": {"port451_in": "port1188_in", "port451_land": "port1188_land"},
    "to_id":   {"port451_land": "port1188_land", "port451_out": "port1188_out"},
}

# ─────────────────────────────────────────────────────────────────────────────
# 输出目录
# ─────────────────────────────────────────────────────────────────────────────
PROJECT_ROOT     = r"E:\02-Trade\07-ChinaMaritimeCode2.0"
OUTPUT_ROOT      = os.path.join(PROJECT_ROOT, "output")
DISRUPTION_ROOT  = os.path.join(OUTPUT_ROOT, "disruption")


def out(*parts: str) -> str:
    """构建 phase1 输出路径并自动创建目录。

    示例：out("CHN2World", "ports", "DEU") → output/CHN2World/ports/DEU/
    """
    path = os.path.join(OUTPUT_ROOT, *parts)
    os.makedirs(path, exist_ok=True)
    return path


def mrio(direction: str, *parts: str) -> str:
    """构建 Phase 3（MRIO 投入产出分析）输出路径并自动创建目录。

    示例：mrio("CHN2World", "input") → output/mrio/CHN2World/input/
    """
    path = os.path.join(OUTPUT_ROOT, "mrio", direction, *parts)
    os.makedirs(path, exist_ok=True)
    return path


def disrupt(direction: str, *parts: str) -> str:
    """构建 phase2（中断分析）输出路径并自动创建目录。

    示例：disrupt("CHN2World", "01_routes_csv") → output/disruption/CHN2World/01_routes_csv/
    """
    path = os.path.join(DISRUPTION_ROOT, direction, *parts)
    os.makedirs(path, exist_ok=True)
    return path


# ─────────────────────────────────────────────────────────────────────────────
# 常量
# ─────────────────────────────────────────────────────────────────────────────

# 中国的 ISO3 字母编码和 ISO 数字编码
CHN_ISO3    = "CHN"
CHN_ISO_NUM = "156"

# 数据年份
YEAR = 2019

# 最短路径图构建：港口点 snap 到海运网络节点的最大距离（米）
GRAPH_SNAP_DISTANCE_M = 100_000

# 海运比例空值填补默认值
SEA_V_DEFAULT_RATIO = 0.7
SEA_Q_DEFAULT_RATIO = 0.8

# 每个方向的起/终点港口 GeoPackage 文件名（phase1 step1 生成，phase2 step3 读取）
DIRECTION_PORTS = {
    "CHN2World": ("CHNstartports.gpkg", "WORLDendports.gpkg"),
    "World2CHN": ("WORLDstartports.gpkg", "CHNendports.gpkg"),
}

# ─────────────────────────────────────────────────────────────────────────────
# BACI 手动校正配置（用于 phase1 step6）
# ─────────────────────────────────────────────────────────────────────────────
BACI_MANUAL_CORRECTIONS = {
    "MAC": (51_655_855_088,   3_361_996_000),
    "MOZ": ( 6_085_898_952,   1_504_353_929),
    "HKG": (72_475_212_317, 267_125_744_358),
}

# ─────────────────────────────────────────────────────────────────────────────
# 无端口记录国家的合并映射（用于 phase1 step6）
# ─────────────────────────────────────────────────────────────────────────────
MERGE_INTO_COUNTRY = {
    "NFK": "CAN",
    "SPM": "NCL",
    "ATG": "KNA",
    "BWA": "ZAF",
    "GRL": "DNK",
    "KIR": "FJI",
    "LSO": "ZAF",
    "LUX": "BEL",
    "NAM": "ZAF",
    "SWZ": "MOZ",
}
