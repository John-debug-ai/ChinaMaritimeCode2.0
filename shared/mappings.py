"""
shared/mappings.py — 所有静态映射表

集中管理，避免在多个脚本中重复定义。
"""

# ─────────────────────────────────────────────────────────────────────────────
# ISO 数字编码修正
# 部分数据集使用非标准编码，此处统一修正为 ISO 3166 标准编码
# ─────────────────────────────────────────────────────────────────────────────
ISO_NUM_CORRECTIONS = {
    "757": "756",   # 瑞士 Switzerland
    "251": "250",   # 法国 France
    "579": "578",   # 挪威 Norway
    "842": "840",   # 美国 United States
    "926": "826",   # 英国 United Kingdom
}

# 整数版本（供 BACI 数据处理使用，BACI 的 i/j 列为整数）
ISO_NUM_CORRECTIONS_INT = {int(k): int(v) for k, v in ISO_NUM_CORRECTIONS.items()}

# ─────────────────────────────────────────────────────────────────────────────
# EORA 11 大类行业分类（基于 ISIC Rev.2 编码）
#
# 格式：{ (isic_code, ...): (sector_num_str, sector_name) }
# sector_num_str 是两位字符串，如 "01"、"11"
# ─────────────────────────────────────────────────────────────────────────────
SECTOR_MAPPING = {
    ("01", "02", "01,02", "02,15"): (
        "0-,1", "Agriculture"),
    ("05", "05,15"): (
        "02", "Fishing"),
    ("10", "11", "12", "13", "14", "11,14", "13,24", "14,36"): (
        "03", "Mining and Quarrying"),
    ("15", "16", "01,05,15", "01,15", "01,15,99,00"): (
        "04", "Food & Beverages"),
    ("17", "18", "19", "01,15,17", "01,17", "17,24", "17,26",
     "17,29", "17,36", "17,99", "18,25", "18,36"): (
        "05", "Textiles and Wearing Apparel"),
    ("20", "21", "22", "02,20", "02,20,99"): (
        "06", "Wood and Paper"),
    ("23", "24", "25", "26", "11,23", "14,24", "14,26", "15,24",
     "23,40", "24,26", "24,26,27"): (
        "07", "Petroleum, Chemical and Non-Metallic Mineral Products"),
    ("27", "28", "28,29"): (
        "08", "Metal Products"),
    ("29", "30", "31", "32", "33", "22,29", "23,28,29", "25,26,31",
     "26,31", "29,30", "29,31", "29,33", "31,33",
     "29,34,35", "29,34", "29,35"): (
        "09", "Electrical and Machinery"),
    ("34", "35", "34,35"): (
        "10", "Transport Equipment"),
    ("36", "01,15,99", "01,99", "05,36", "19,33", "19,99",
     "24,36", "25,26,31,00", "25,99"): (
        "11", "Other Manufacturing"),
}

# 展开为扁平字典：isic_code_str -> (sector_num_str, sector_name)
ISIC_TO_SECTOR: dict[str, tuple[str, str]] = {}
for _codes_tuple, _sector_info in SECTOR_MAPPING.items():
    for _code in _codes_tuple:
        ISIC_TO_SECTOR[_code] = _sector_info
