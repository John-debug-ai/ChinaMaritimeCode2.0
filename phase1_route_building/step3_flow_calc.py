"""
Step 3: 港口对间流量计算

将行业贸易总量（sea_q / sea_v）乘以港口进出口流量比例，
生成每对（出口港, 进口港）的预期流量 CSV。

计算公式：
  q_flow = q_sea_flow_sum × q_export_ratio(起点港) × q_import_ratio(终点港)
  v_flow = v_sea_flow_sum × v_export_ratio(起点港) × v_import_ratio(终点港)

输入：
  - output/{direction}/trade/sectors/{country}/{sector_num}_{sector_name}.csv
  - output/{direction}/ports/{country}/{country}_{sector_num}.csv
输出：
  - output/{direction}/flow/{country}_{sector_num}.csv

若某国家×行业有海运贸易量但找不到港口文件，会在运行结束时汇总打印警告，
这类国家可在 step6 中通过 MERGE_INTO_COUNTRY 合并到就近国家处理。
"""

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from itertools import product as cartesian

import pandas as pd

from shared.config import out


def _calc_country_sector(
    country: str,
    sector_file: str,
    sector_path: str,
    port_path: str,
    flow_dir: str,
    missing_log: list,
) -> None:
    """计算单个（国家 × 行业）的港口对间流量并保存。

    若端口文件不存在且有实际海运贸易量，将 (country, sector, lost_q, lost_v) 追加到 missing_log。
    """
    sector_code = sector_file.split("_")[0]
    port_file   = os.path.join(port_path, f"{country}_{sector_code}.csv")

    if not os.path.exists(port_file):
        sector_df = pd.read_csv(os.path.join(sector_path, sector_file))
        lost_q = sector_df["sea_q"].sum()
        lost_v = sector_df["sea_v"].sum()
        if lost_q > 0 or lost_v > 0:
            missing_log.append((country, sector_code, lost_q, lost_v))
        return

    ports_df  = pd.read_csv(port_file)
    sector_df = pd.read_csv(os.path.join(sector_path, sector_file))

    exports = ports_df[ports_df["flow"] == "port_export"]
    imports = ports_df[ports_df["flow"] == "port_import"]

    if exports.empty or imports.empty:
        return

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
        pd.DataFrame(rows).to_csv(
            os.path.join(flow_dir, f"{country}_{sector_code}.csv"),
            index=False,
        )


def run(direction: str) -> None:
    """
    direction: "CHN2World" 或 "World2CHN"
    """
    sectors_root = out(direction, "trade", "sectors")
    ports_root   = out(direction, "ports")
    flow_dir     = out(direction, "flow")

    missing_log = []
    total       = 0

    for country in os.listdir(sectors_root):
        sector_country_path = os.path.join(sectors_root, country)
        port_country_path   = os.path.join(ports_root, country)

        if not os.path.isdir(sector_country_path):
            continue

        # 整个国家在两向均无港口数据
        if not os.path.isdir(port_country_path):
            for sector_file in os.listdir(sector_country_path):
                if not sector_file.endswith(".csv"):
                    continue
                sector_df = pd.read_csv(os.path.join(sector_country_path, sector_file))
                lost_q = sector_df["sea_q"].sum()
                lost_v = sector_df["sea_v"].sum()
                if lost_q > 0 or lost_v > 0:
                    missing_log.append(
                        (country, sector_file.split("_")[0], lost_q, lost_v)
                    )
            continue

        for sector_file in os.listdir(sector_country_path):
            if not sector_file.endswith(".csv"):
                continue
            _calc_country_sector(
                country, sector_file,
                sector_country_path, port_country_path,
                flow_dir, missing_log,
            )
            total += 1

    print(f"[Step 3] {direction}: {total} 个（国家×行业）流量文件已生成")

    if missing_log:
        missing_df = (
            pd.DataFrame(missing_log, columns=["country", "sector", "lost_sea_q_kg", "lost_sea_v_usd"])
            .sort_values(["country", "sector"])
            .reset_index(drop=True)
        )

        # ── 按国家汇总打印 ────────────────────────────────────────────────
        total_lost_q = missing_df["lost_sea_q_kg"].sum()
        total_lost_v = missing_df["lost_sea_v_usd"].sum()
        print(f"\n[Step 3] {direction}: ⚠ {len(missing_df)} 个国家×行业有海运贸易但无港口数据"
              f"（合计 sea_q={total_lost_q:,.0f} kg，sea_v={total_lost_v:,.0f} USD）")
        print(f"{'国家':<8} {'行业':>4}  {'sea_q (kg)':>18}  {'sea_v (USD)':>18}")
        print("─" * 56)
        for country, grp in missing_df.groupby("country"):
            for _, row in grp.iterrows():
                print(f"  {row['country']:<6} 行业 {row['sector']:>2}  "
                      f"{row['lost_sea_q_kg']:>18,.0f}  {row['lost_sea_v_usd']:>18,.0f}")
            sub_q = grp["lost_sea_q_kg"].sum()
            sub_v = grp["lost_sea_v_usd"].sum()
            if len(grp) > 1:
                print(f"  {'':6} 小计    {sub_q:>18,.0f}  {sub_v:>18,.0f}")
        print("─" * 56)
        print(f"  {'合计':<10}  {total_lost_q:>18,.0f}  {total_lost_v:>18,.0f}")

        # ── 导出 CSV ──────────────────────────────────────────────────────
        csv_path = os.path.join(out(direction, "flow"), f"missing_ports_{direction}.csv")
        missing_df.to_csv(csv_path, index=False, encoding="utf-8-sig")
        print(f"\n  → 详情已导出：{csv_path}")
        print(f"  → 可在 config.py 的 MERGE_INTO_COUNTRY 中配置就近合并，由 step6 处理")


if __name__ == "__main__":
    for d in ["CHN2World", "World2CHN"]:
        run(d)
