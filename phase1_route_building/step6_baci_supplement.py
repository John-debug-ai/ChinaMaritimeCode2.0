"""
Step 6（可选）: 用 BACI 数据补充 TTD 缺失国家 + 修正大误差国家

功能：
  A. 补充（supplement）：
     对在 BACI 中有贸易记录、但在 TTD 输出中缺失的国家，
     用 BACI 数据构建贸易量，并为其匹配港口数据，重新计算流量。

  B. 校正（correction）：
     对 TTD 与 BACI 误差过大的特定国家，
     用 BACI 总量等比例重新标定 TTD 贸易量，重新计算流量。

  C. 合并（merge）：
     对在 A/B 步骤后仍无端口数据的极少数小地区（如 NFK、SPM），
     将其 BACI 贸易量合并到地理/行政上关联的国家，
     借用该国家的港口分布来分配流量。
     映射关系在 config.MERGE_INTO_COUNTRY 中配置。

每种功能均可独立调用，支持任意方向（CHN2World / World2CHN）。

端口数据匹配优先级（适用于 A）：
  1. 同向已有端口数据（直接复制）
  2. 反向端口数据（对调 import/export 后使用）
  3. 均无 → 跳过该国家并警告（C 负责处理这类情况）

A/B/C 的所有结果均直接写入主输出目录（ports / trade / flow），再次运行 step5 即可生效。
"""

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import shutil
from itertools import product as cartesian

import pandas as pd

from shared.config import RAW_DATA, out, CHN_ISO3, CHN_ISO_NUM, BACI_MANUAL_CORRECTIONS, MERGE_INTO_COUNTRY
from shared.mappings import ISO_NUM_CORRECTIONS_INT
from shared.utils import (
    load_iso_map, load_hs4_isic_map,
    fill_sea_defaults, classify_sectors, compute_port_ratios,
)


# ─────────────────────────────────────────────────────────────────────────────
# A. 补充功能
# ─────────────────────────────────────────────────────────────────────────────

def find_missing_countries(direction: str) -> list[str]:
    """对比 BACI 与 TTD 输出，返回 BACI 有记录但 TTD 缺失的国家 ISO3 列表。"""
    iso_map = load_iso_map()

    # 从 BACI 原始文件中读取涉及中国的国家集合
    df = pd.read_csv(RAW_DATA["baci"], usecols=["i", "j"])
    df["i"] = df["i"].replace(ISO_NUM_CORRECTIONS_INT)
    df["j"] = df["j"].replace(ISO_NUM_CORRECTIONS_INT)
    chn_num = 156

    if direction == "CHN2World":
        partner_nums = df[df["i"] == chn_num]["j"].unique()
    else:
        partner_nums = df[df["j"] == chn_num]["i"].unique()

    baci_iso3s = {iso_map.get(str(n)) for n in partner_nums} - {None, CHN_ISO3}

    # TTD 已有输出的国家
    trade_dir = os.path.join(out(direction, "trade"))
    ttd_iso3s = {f[:-4] for f in os.listdir(trade_dir) if f.endswith(".csv")}

    missing = sorted(baci_iso3s - ttd_iso3s)
    print(f"[Step 6] {direction}: BACI 有但 TTD 缺失的国家 ({len(missing)} 个): {missing}")
    return missing


def _get_port_source(direction: str, iso3: str) -> tuple[str | None, bool]:
    """寻找可用的港口数据目录。

    返回：(目录路径, 是否为反向数据)
    优先使用同向数据，其次使用对向数据（需后续对调列）。
    """
    same_dir = os.path.join(out(direction, "ports"), iso3)
    if os.path.isdir(same_dir) and os.listdir(same_dir):
        return same_dir, False

    opposite = "World2CHN" if direction == "CHN2World" else "CHN2World"
    opp_dir  = os.path.join(out(opposite, "ports"), iso3)
    if os.path.isdir(opp_dir) and os.listdir(opp_dir):
        return opp_dir, True

    return None, False


def _invert_port_df(df: pd.DataFrame) -> pd.DataFrame:
    """对调反向端口数据的列值，使其适用于当前方向。

    对调规则：
      from_id   ↔ to_id
      from_iso3 ↔ to_iso3
      iso3_O    ↔ iso3_D
      q/v_import_ratio ↔ q/v_export_ratio
      port_export ↔ port_import（flow 列）
    """
    df = df.copy()

    swap_pairs = [
        ("from_id",        "to_id"),
        ("from_iso3",      "to_iso3"),
        ("iso3_O",         "iso3_D"),
        ("q_import_ratio", "q_export_ratio"),
        ("v_import_ratio", "v_export_ratio"),
    ]
    for col_a, col_b in swap_pairs:
        if col_a in df.columns and col_b in df.columns:
            df[col_a], df[col_b] = df[col_b].values.copy(), df[col_a].values.copy()

    if "flow" in df.columns:
        df["flow"] = df["flow"].map({
            "port_export": "port_import",
            "port_import": "port_export",
        }).fillna(df["flow"])

    return df


def _prepare_supplement_ports(direction: str, iso3: str) -> str | None:
    """为补充国家准备端口数据，返回目标端口数据目录。"""
    dest_dir = out(direction, "ports", iso3)

    # 同向数据已存在（如 step1 已生成），直接复用，无需任何操作
    if os.path.isdir(dest_dir) and os.listdir(dest_dir):
        return dest_dir

    src_path, is_inverted = _get_port_source(direction, iso3)
    if src_path is None:
        print(f"  ⚠ {iso3}: 找不到任何端口数据，跳过")
        return None

    if not is_inverted:
        shutil.copytree(src_path, dest_dir, dirs_exist_ok=True)
    else:
        # 对调列后重新计算比例并保存
        for fname in os.listdir(src_path):
            if not fname.endswith(".csv"):
                continue
            df = pd.read_csv(os.path.join(src_path, fname))
            df = _invert_port_df(df)
            df = compute_port_ratios(df)
            df.to_csv(os.path.join(dest_dir, fname), index=False, encoding="utf-8-sig")
        print(f"  ↔ {iso3}: 使用反向端口数据（已对调）")

    return dest_dir


def _build_baci_trade(direction: str, iso3: str) -> pd.DataFrame | None:
    """从 BACI 原始数据构建某国家的贸易 DataFrame（格式与 step2 输出一致）。

    注意：BACI 无运输方式分类，sea_v/sea_q 初始为 0，
    后续由 fill_sea_defaults 填补默认比例。
    BACI v 单位为千美元，q 单位为公吨（与 TTD 同单位保持一致，不做转换）。
    """
    iso_map     = load_iso_map()
    hs4_to_isic = load_hs4_isic_map()

    # 反查 iso3 → 数字编码
    iso3_to_num = {v: int(k) for k, v in iso_map.items() if k.isdigit()}
    partner_num = iso3_to_num.get(iso3)
    if partner_num is None:
        print(f"  ✗ {iso3}: 找不到对应的数字编码")
        return None

    df = pd.read_csv(RAW_DATA["baci"], usecols=["i", "j", "k", "v", "q"])
    df["i"] = df["i"].replace(ISO_NUM_CORRECTIONS_INT)
    df["j"] = df["j"].replace(ISO_NUM_CORRECTIONS_INT)
    chn_num = int(CHN_ISO_NUM)

    if direction == "CHN2World":
        df      = df[(df["i"] == chn_num) & (df["j"] == partner_num)].copy()
        iso_O, iso_D = CHN_ISO3, iso3
        origin_num, dest_num = chn_num, partner_num
    else:
        df      = df[(df["i"] == partner_num) & (df["j"] == chn_num)].copy()
        iso_O, iso_D = iso3, CHN_ISO3
        origin_num, dest_num = partner_num, chn_num

    if df.empty:
        print(f"  ✗ {iso3}: BACI 中无贸易数据")
        return None

    # HS6 → HS4（取前 4 位）
    df["k"] = df["k"].astype(str).str.zfill(6).str[:4]

    # 按产品汇总
    agg = df.groupby("k")[["v", "q"]].sum().reset_index()
    agg["ISIC2"]    = agg["k"].map(hs4_to_isic)
    agg["origin"]   = str(origin_num)
    agg["destination"] = str(dest_num)
    agg.rename(columns={"k": "product", "v": "total_v", "q": "total_q"}, inplace=True)

    agg["sea_v"]       = 0.0
    agg["sea_q"]       = 0.0
    agg["sea_v_ratio"] = 0.0
    agg["sea_q_ratio"] = 0.0
    agg["iso_O"]       = iso_O
    agg["iso_D"]       = iso_D

    # 填补默认海运比例
    agg, _ = fill_sea_defaults(agg)
    return agg


def _calc_flow(
    country: str,
    ports_root: str,
    sectors_root: str,
    flow_dir: str,
) -> int:
    """为单个国家的所有行业计算流量并保存（与 step3 逻辑相同）。"""
    port_path   = os.path.join(ports_root, country)
    sector_path = os.path.join(sectors_root, country)

    if not os.path.isdir(port_path) or not os.path.isdir(sector_path):
        return 0

    count = 0
    for sector_file in os.listdir(sector_path):
        if not sector_file.endswith(".csv"):
            continue
        sector_code = sector_file.split("_")[0]
        port_file   = os.path.join(port_path, f"{country}_{sector_code}.csv")
        if not os.path.exists(port_file):
            continue

        ports_df  = pd.read_csv(port_file)
        sector_df = pd.read_csv(os.path.join(sector_path, sector_file))

        exports = ports_df[ports_df["flow"] == "port_export"]
        imports = ports_df[ports_df["flow"] == "port_import"]
        if exports.empty or imports.empty:
            continue

        q_total = sector_df["sea_q"].sum()
        v_total = sector_df["sea_v"].sum()

        rows = []
        for ex_id, im_id in cartesian(exports["id"], imports["id"]):
            ex = exports[exports["id"] == ex_id].iloc[0]
            im = imports[imports["id"] == im_id].iloc[0]
            rows.append({
                "export_port":    ex_id,
                "import_port":    im_id,
                "from_iso3":      ex["from_iso3"],
                "to_iso3":        im["to_iso3"],
                "sector":         sector_code,
                "q_sea_flow_sum": q_total,
                "v_sea_flow_sum": v_total,
                "q_export_ratio": ex["q_export_ratio"],
                "q_import_ratio": im["q_import_ratio"],
                "v_export_ratio": ex["v_export_ratio"],
                "v_import_ratio": im["v_import_ratio"],
                "q_flow":         q_total * ex["q_export_ratio"] * im["q_import_ratio"],
                "v_flow":         v_total * ex["v_export_ratio"] * im["v_import_ratio"],
            })

        if rows:
            os.makedirs(flow_dir, exist_ok=True)
            pd.DataFrame(rows).to_csv(
                os.path.join(flow_dir, f"{country}_{sector_code}.csv"), index=False)
            count += 1

    return count


def run(direction: str, country_codes: list[str] = None) -> list[str]:
    """
    补充 TTD 中缺失的国家贸易数据。

    direction:     "CHN2World" 或 "World2CHN"
    country_codes: 指定要补充的 ISO3 列表；None 时自动与 BACI 对比检测
    返回：成功处理的国家 ISO3 列表
    """
    if country_codes is None:
        country_codes = find_missing_countries(direction)
    if not country_codes:
        print(f"[Step 6] {direction}: 无需补充")
        return []

    ports_dir   = out(direction, "ports")
    sectors_dir = out(direction, "trade", "sectors")
    flow_dir    = out(direction, "flow")
    trade_dir   = out(direction, "trade")

    processed = []
    for iso3 in country_codes:
        print(f"\n  补充 {direction}: {iso3}")

        # 1. 端口数据（直接写入主 ports 目录）
        port_dir = _prepare_supplement_ports(direction, iso3)
        if port_dir is None:
            continue

        # 2. BACI 贸易数据
        trade_df = _build_baci_trade(direction, iso3)
        if trade_df is None:
            continue

        # 3. 保存贸易数据并分类（直接写入主 trade 目录）
        trade_df.to_csv(
            os.path.join(trade_dir, f"{iso3}.csv"), index=False, encoding="utf-8-sig")
        classify_sectors(trade_df, out(direction, "trade", "sectors", iso3))

        # 4. 计算流量（直接写入主 flow 目录）
        n = _calc_flow(iso3, ports_dir, sectors_dir, flow_dir)
        print(f"  ✓ {iso3}: 已生成 {n} 个行业流量文件")
        processed.append(iso3)

    print(f"\n[Step 6] {direction}: 补充完成，{len(processed)} 个国家已处理")

    # 合并无端口国家（如 NFK→CAN, SPM→NCL）
    merge_no_port_countries(direction)

    return processed


# ─────────────────────────────────────────────────────────────────────────────
# B. 校正功能
# ─────────────────────────────────────────────────────────────────────────────

def apply_corrections(
    direction: str,
    corrections: dict[str, tuple[float, float]] = None,
) -> None:
    """
    对误差过大的国家，用 BACI 总量重新标定 TTD 贸易量，并重新计算流量。

    direction:   "CHN2World" 或 "World2CHN"
    corrections: { "ISO3": (baci_total_q, baci_total_v) }
                 None 时使用 config.BACI_MANUAL_CORRECTIONS

    说明：仅缩放贸易总量，海运比例保持不变；
    适用于 TTD 与 BACI 在数量级上存在系统性偏差的国家。
    """
    if corrections is None:
        corrections = BACI_MANUAL_CORRECTIONS
    if not corrections:
        return

    trade_dir   = out(direction, "trade")
    sectors_dir = os.path.join(trade_dir, "sectors")
    flow_dir    = out(direction, "flow")
    ports_dir   = out(direction, "ports")

    for iso3, (baci_q, baci_v) in corrections.items():
        csv_path = os.path.join(trade_dir, f"{iso3}.csv")
        if not os.path.exists(csv_path):
            print(f"  ✗ {iso3}: 贸易 CSV 不存在，跳过")
            continue

        df = pd.read_csv(csv_path)
        df["product"] = df["product"].astype(str)

        total_row = df[df["product"] == "TOTAL"]
        if total_row.empty:
            print(f"  ✗ {iso3}: 找不到 TOTAL 行，跳过")
            continue

        ttd_q = total_row["total_q"].values[0]
        ttd_v = total_row["total_v"].values[0]

        scale_q = baci_q / ttd_q if ttd_q else 1.0
        scale_v = baci_v / ttd_v if ttd_v else 1.0

        df["total_q"] *= scale_q
        df["total_v"] *= scale_v
        df["sea_q"]    = df["total_q"] * df["sea_q_ratio"]
        df["sea_v"]    = df["total_v"] * df["sea_v_ratio"]

        df.to_csv(csv_path, index=False, encoding="utf-8-sig")

        # 重新分类并计算流量
        classify_sectors(df, os.path.join(sectors_dir, iso3))
        _calc_flow(iso3, ports_dir, sectors_dir, flow_dir)

        print(f"  ✓ {iso3}: 已校正 (scale_q={scale_q:.3f}, scale_v={scale_v:.3f})")

    print(f"[Step 6] {direction}: BACI 校正完成")


# ─────────────────────────────────────────────────────────────────────────────
# C. 无端口国家合并
# ─────────────────────────────────────────────────────────────────────────────

def merge_no_port_countries(
    direction: str,
    merge_map: dict[str, str] = None,
) -> None:
    """将无端口数据的小地区贸易量合并到关联国家，借用该国家的港口分布计算流量。

    merge_map: { "源ISO3": "目标ISO3" }
               None 时使用 config.MERGE_INTO_COUNTRY（如 NFK→CAN, SPM→NCL）

    逻辑：
      1. 用 BACI 数据为源国家构建贸易量
      2. 将贸易量分类到目标国家的 sectors 目录中（追加合并）
      3. 用目标国家的港口分布重新计算流量
    """
    if merge_map is None:
        merge_map = MERGE_INTO_COUNTRY
    if not merge_map:
        return

    ports_dir   = out(direction, "ports")
    sectors_dir = out(direction, "trade", "sectors")
    flow_dir    = out(direction, "flow")

    for src_iso3, dst_iso3 in merge_map.items():
        print(f"\n  合并 {src_iso3} → {dst_iso3} ({direction})")

        trade_df = _build_baci_trade(direction, src_iso3)
        if trade_df is None:
            continue

        # 将贸易量分类写入临时目录，再追加到目标国家 sectors 目录
        tmp_dir     = out(direction, "_tmp_merge", src_iso3)
        classify_sectors(trade_df, tmp_dir)

        dst_sectors = os.path.join(sectors_dir, dst_iso3)
        if not os.path.isdir(dst_sectors):
            print(f"  ✗ 目标国家 {dst_iso3} 的 sectors 目录不存在，跳过")
            continue

        for sector_file in os.listdir(tmp_dir):
            if not sector_file.endswith(".csv"):
                continue
            src_path = os.path.join(tmp_dir, sector_file)
            dst_path = os.path.join(dst_sectors, sector_file)
            src_df   = pd.read_csv(src_path)
            if os.path.exists(dst_path):
                dst_df   = pd.read_csv(dst_path)
                combined = pd.concat([dst_df, src_df], ignore_index=True)
            else:
                combined = src_df
            combined.to_csv(dst_path, index=False)

        print(f"  ✓ {src_iso3} 的行业数据已合并到 {dst_iso3}")

        n = _calc_flow(dst_iso3, ports_dir, sectors_dir, flow_dir)
        print(f"  ✓ {dst_iso3} 流量已重新计算（{n} 个行业文件）")

    print(f"[Step 6] {direction}: 无端口国家合并完成")


# ─────────────────────────────────────────────────────────────────────────────
# 入口
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    for d in ["CHN2World", "World2CHN"]:
        run(d)                    # 自动检测并补充缺失国家
        apply_corrections(d)      # 应用手动校正
