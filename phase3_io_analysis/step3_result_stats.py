"""
Phase 3 / Step 3: 结果统计与 GIS 关联

对 step2 的四个输出文件做后处理，分两条主线（进口系数 + 产出乘数），
并将结果关联到港口矢量和国家边界矢量。

两个方向逻辑基本对称；World2CHN 额外生成：
  - ports_with_ratio_CHN/others.gpkg（分中国/非中国港口）
  - import_requirement_with_coef.csv（含排名与功能分类）

输出目录：output/mrio/{direction}/stats/
  import_requirement_ratio.csv        带比率的进口需求
  import_requirement_ratio_mean.csv   按国家均值 + ISO 信息
  import_multiplier_sum.csv           按国家汇总进口乘数
  import_coef_sector_max.csv          各国最关键行业
  ports_with_ratio.gpkg               港口矢量 + 进口比率
  Global_country_with_ratio.gpkg      国家边界 + 进口比率
  output_multiplier_mean.csv          产出乘数按国家均值
  Global_country_output.gpkg          国家边界 + 产出乘数
  [World2CHN 额外]
  ports_with_ratio_CHN.gpkg
  ports_with_ratio_others.gpkg
  import_requirement_with_coef.csv
"""

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
import geopandas as gpd

from shared.config import (
    RAW_DATA, mrio, GLOBAL_COUNTRY_SHP, EXCLUDE_ISO3,
)

# 产出乘数统计列（两个方向相同）
OUTPUT_MULT_COLS = [
    "trade_ind",
    "Dind_int_bw", "Dind_iso3_int_bw",
    "Dind_C_bw",   "Dind_iso3_C_bw",
    "Dind_total_bw", "Dind_iso3_bw",
    "Dind_total_fw", "Dind_iso3_fw",
    "Dind_total", "Dind_iso3", "Dind_row",
    "multiplier", "multiplier_dom", "multiplier_row",
    "frac_row_dom", "frac_bw_fw",
]


def run(direction: str) -> None:
    """
    direction: "CHN2World" 或 "World2CHN"
    """
    mult_dir  = mrio(direction, "multipliers")
    stats_dir = mrio(direction, "stats")

    iso_file = RAW_DATA["iso3_with_region"]
    df_iso   = pd.read_csv(iso_file, dtype=str)
    iso_cols = ["iso3", "EnglishName", "Region", "Income group", "CONTINENT"]

    # ────────────────────────────────────────────────────────────────────────
    # A. 进口系数统计
    # ────────────────────────────────────────────────────────────────────────

    # ── A1. 进口需求 → 比率 + 国家均值 ──────────────────────────────────────
    req_path = os.path.join(mult_dir, "import_requirement.csv")
    if os.path.exists(req_path):
        df_req = pd.read_csv(req_path)
        df_req = df_req[~df_req["iso3_import"].isin(EXCLUDE_ISO3)].copy()
        df_req["Import_export_ratio"] = (
            df_req["Import_export"] / df_req["Total_export"]
        )
        df_req["Import_demand_ratio"] = (
            df_req["Import_demand"] / df_req["Total_demand"]
        )

        # World2CHN：额外合并港口名称
        if direction == "World2CHN" and os.path.exists(RAW_DATA["port_utilization"]):
            df_port_name = pd.read_csv(
                RAW_DATA["port_utilization"], usecols=["id", "port-name"]
            )
            df_port_name = (
                df_port_name.drop_duplicates()
                .groupby("id")["port-name"].agg(";".join).reset_index()
            )
            df_req = df_req.merge(df_port_name, on="id", how="left")

        df_req.to_csv(
            os.path.join(stats_dir, "import_requirement_ratio.csv"),
            index=False, encoding="utf-8-sig",
        )

        # 按国家均值
        df_mean = (
            df_req.groupby("iso3_import")[
                ["Import_export_ratio", "Import_demand_ratio"]
            ].mean().reset_index()
            .merge(
                df_iso[iso_cols],
                left_on="iso3_import", right_on="iso3", how="left",
            )
            .drop(columns=["iso3"])
        )
        df_mean.to_csv(
            os.path.join(stats_dir, "import_requirement_ratio_mean.csv"),
            index=False, encoding="utf-8-sig",
        )
        print(f"  [A1] import_requirement_ratio* 已生成")

    # ── A2. 进口乘数 → 按国家求和 ────────────────────────────────────────────
    mult_path = os.path.join(mult_dir, "import_multiplier.csv")
    if os.path.exists(mult_path):
        df_mult = pd.read_csv(mult_path)
        df_mult = df_mult[~df_mult["iso3_import"].isin(EXCLUDE_ISO3)]

        # World2CHN：剔除非中国港口（如果 ports_with_ratio_others 已生成）
        if direction == "World2CHN":
            others_csv = os.path.join(stats_dir, "ports_with_ratio_others.csv")
            if os.path.exists(others_csv):
                others_ids = pd.read_csv(others_csv)["id"].astype(str).tolist()
                df_mult = df_mult[~df_mult["id"].astype(str).isin(others_ids)]

        df_sum = (
            df_mult.groupby("iso3_import")["Import_multiplier"].sum()
            .reset_index()
            .merge(df_iso[iso_cols], left_on="iso3_import", right_on="iso3", how="left")
            .drop(columns=["iso3"])
        )
        df_sum.to_csv(
            os.path.join(stats_dir, "import_multiplier_sum.csv"),
            index=False, encoding="utf-8-sig",
        )
        print(f"  [A2] import_multiplier_sum.csv 已生成")

    # ── A3. 进口系数 → 最关键行业 ────────────────────────────────────────────
    coef_path = os.path.join(mult_dir, "import_coef_sector.csv")
    if os.path.exists(coef_path):
        df_coef = pd.read_csv(coef_path)

        # CHN2World：按 iso3_import 找最大行业
        if direction == "CHN2World":
            grouped = (
                df_coef
                .groupby(["iso3_import", "Industries", "sector"], as_index=False)
                ["Import_coef"].sum()
            )
            max_rows = (
                grouped.loc[grouped.groupby("iso3_import")["Import_coef"].idxmax()]
                .reset_index(drop=True)
            )
        else:
            # World2CHN：直接按 id 找最大
            df_coef["Import_coef"] = pd.to_numeric(
                df_coef["Import_coef"], errors="coerce"
            )
            valid = df_coef.dropna(subset=["id", "Import_coef"])
            idx   = valid.groupby("id")["Import_coef"].idxmax()
            max_rows = valid.loc[idx].reset_index(drop=True)

        max_rows.to_csv(
            os.path.join(stats_dir, "import_coef_sector_max.csv"),
            index=False, encoding="utf-8-sig",
        )
        print(f"  [A3] import_coef_sector_max.csv 已生成")

    # ── A4. 关联到港口矢量 ───────────────────────────────────────────────────
    ratio_csv = os.path.join(stats_dir, "import_requirement_ratio.csv")
    coef_max_csv = os.path.join(stats_dir, "import_coef_sector_max.csv")
    if os.path.exists(ratio_csv) and os.path.exists(coef_max_csv):
        gdf_ports = gpd.read_file(RAW_DATA["ports_shp"])
        gdf_ports["id"] = gdf_ports["id"].astype(str)

        df_ratio = pd.read_csv(ratio_csv)
        df_ratio["id"] = df_ratio["id"].astype(str)

        gdf_ports = gdf_ports.merge(
            df_ratio[["id", "Import_export_ratio", "Import_demand_ratio"]],
            on="id", how="left",
        )
        gdf_ports["Import_export_ratio"] = gdf_ports["Import_export_ratio"].fillna(0)
        gdf_ports["Import_demand_ratio"] = gdf_ports["Import_demand_ratio"].fillna(0)

        # 最关键行业
        df_max = pd.read_csv(coef_max_csv)
        df_max["Import_coef"] = pd.to_numeric(df_max["Import_coef"], errors="coerce")
        join_col = "iso3_import" if direction == "CHN2World" else "id"
        valid_max = df_max.dropna(subset=[join_col, "Import_coef"])
        idx = valid_max.groupby(join_col)["Import_coef"].idxmax()
        top = valid_max.loc[idx, [join_col, "Industries", "Import_coef"]].copy()
        top = top.rename(columns={"Import_coef": "industry_value"})

        merge_col = "iso3" if direction == "CHN2World" else "id"
        gdf_ports = gdf_ports.merge(
            top.rename(columns={join_col: merge_col}),
            on=merge_col, how="left",
        )

        if direction == "World2CHN":
            # 只保留两个比率均 > 0 的港口，并分中国/其他
            gdf_ports = gdf_ports[
                (gdf_ports["Import_export_ratio"] > 0) &
                (gdf_ports["Import_demand_ratio"] > 0)
            ]
            gdf_chn    = gdf_ports[gdf_ports["iso3"] == "CHN"].copy()
            gdf_others = gdf_ports[gdf_ports["iso3"] != "CHN"].copy()

            gdf_ports.to_file(
                os.path.join(stats_dir, "ports_with_ratio.gpkg"),
                driver="GPKG",
            )
            gdf_chn.to_file(
                os.path.join(stats_dir, "ports_with_ratio_CHN.gpkg"),
                driver="GPKG",
            )
            gdf_others.to_file(
                os.path.join(stats_dir, "ports_with_ratio_others.gpkg"),
                driver="GPKG",
            )
            gdf_others.drop(columns="geometry").to_csv(
                os.path.join(stats_dir, "ports_with_ratio_others.csv"),
                index=False, encoding="utf-8-sig",
            )
        else:
            gdf_ports.to_file(
                os.path.join(stats_dir, "ports_with_ratio.gpkg"),
                driver="GPKG",
            )

        print(f"  [A4] ports_with_ratio.gpkg 已生成")

    # ── A5. 关联到国家矢量 ───────────────────────────────────────────────────
    mean_csv    = os.path.join(stats_dir, "import_requirement_ratio_mean.csv")
    sum_csv     = os.path.join(stats_dir, "import_multiplier_sum.csv")
    sec_max_csv = os.path.join(stats_dir, "import_coef_sector_max.csv")
    if all(os.path.exists(p) for p in [mean_csv, sum_csv, sec_max_csv]):
        gdf_country = gpd.read_file(GLOBAL_COUNTRY_SHP)
        gdf_country["GID_0"] = gdf_country["GID_0"].astype(str)

        df_mean_c = pd.read_csv(mean_csv)
        df_mean_c["iso3_import"] = df_mean_c["iso3_import"].astype(str)

        df_sum_c  = pd.read_csv(sum_csv)
        df_sum_c["iso3_import"] = df_sum_c["iso3_import"].astype(str)

        df_sec_c  = pd.read_csv(sec_max_csv)
        join_col  = "iso3_import" if direction == "CHN2World" else "id"

        gdf_m = gdf_country.merge(
            df_mean_c[["iso3_import", "Import_export_ratio", "Import_demand_ratio"]],
            left_on="GID_0", right_on="iso3_import", how="left",
        ).drop(columns=["iso3_import"])

        gdf_m = gdf_m.merge(
            df_sum_c[["iso3_import", "Import_multiplier"]],
            left_on="GID_0", right_on="iso3_import", how="left",
        ).drop(columns=["iso3_import"])

        gdf_m = gdf_m.merge(
            df_sec_c[[join_col, "Industries", "Import_coef"]],
            left_on="GID_0", right_on=join_col, how="left",
        ).drop(columns=[join_col], errors="ignore")

        for col in ["Import_export_ratio", "Import_demand_ratio",
                    "Import_multiplier", "Import_coef", "Industries"]:
            if col in gdf_m.columns:
                gdf_m[col] = gdf_m[col].fillna(0)

        gdf_m.to_file(
            os.path.join(stats_dir, "Global_country_with_ratio.gpkg"),
            driver="GPKG",
        )
        print(f"  [A5] Global_country_with_ratio.gpkg 已生成")

    # ── A6. World2CHN 额外：功能分类文件 ─────────────────────────────────────
    if direction == "World2CHN":
        ratio_csv2   = os.path.join(stats_dir, "import_requirement_ratio.csv")
        others_csv   = os.path.join(stats_dir, "ports_with_ratio_others.csv")
        sec_max_csv2 = os.path.join(stats_dir, "import_coef_sector_max.csv")
        if all(os.path.exists(p) for p in [ratio_csv2, sec_max_csv2]):
            df_r = pd.read_csv(ratio_csv2)

            # 剔除非中国港口（若 others 文件已生成）
            if os.path.exists(others_csv):
                others_ids = pd.read_csv(others_csv)["id"].astype(str).tolist()
                df_r = df_r[~df_r["id"].astype(str).isin(others_ids)]

            cols_keep = ["id", "Import_export_ratio", "Import_demand_ratio"]
            if "port-name" in df_r.columns:
                cols_keep.insert(1, "port-name")
            df_r = df_r[cols_keep].copy()

            df_r["er_rank"] = df_r["Import_export_ratio"].rank(
                method="dense", ascending=False
            ).astype(int)
            df_r["dr_rank"] = df_r["Import_demand_ratio"].rank(
                method="dense", ascending=False
            ).astype(int)

            def _classify(row):
                if row["er_rank"] == row["dr_rank"]:
                    return "both"
                elif row["er_rank"] > row["dr_rank"]:
                    return "demand"
                else:
                    return "export"

            df_r["function"]  = df_r.apply(_classify, axis=1)
            df_r["dif_rank"]  = df_r["er_rank"] - df_r["dr_rank"]
            df_r["dif_value"] = (
                df_r["Import_export_ratio"] - df_r["Import_demand_ratio"]
            )

            df_sec = pd.read_csv(sec_max_csv2)
            merged = df_r.merge(
                df_sec[["id", "Industries", "sector", "Import_coef"]],
                on="id", how="left",
            )
            merged.to_csv(
                os.path.join(stats_dir, "import_requirement_with_coef.csv"),
                index=False, encoding="utf-8-sig",
            )
            print(f"  [A6] import_requirement_with_coef.csv 已生成")

    # ────────────────────────────────────────────────────────────────────────
    # B. 产出乘数统计
    # ────────────────────────────────────────────────────────────────────────

    out_mult_path = os.path.join(mult_dir, "output_multiplier.csv")
    if os.path.exists(out_mult_path):
        df_om = pd.read_csv(out_mult_path)
        df_om = df_om[~df_om["iso3"].isin(EXCLUDE_ISO3)]

        # ── B1. 按国家均值 + ISO 信息 ──────────────────────────────────────
        cols_avg = [c for c in OUTPUT_MULT_COLS if c in df_om.columns]
        df_om_mean = (
            df_om.groupby("iso3", as_index=False)[cols_avg].mean()
            .merge(df_iso[iso_cols], on="iso3", how="left")
        )
        df_om_mean.replace([float("inf"), float("-inf")], pd.NA, inplace=True)
        df_om_mean.to_csv(
            os.path.join(stats_dir, "output_multiplier_mean.csv"),
            index=False, encoding="utf-8-sig",
        )
        print(f"  [B1] output_multiplier_mean.csv 已生成")

        # ── B2. 关联到国家矢量 ─────────────────────────────────────────────
        gdf_country = gpd.read_file(GLOBAL_COUNTRY_SHP)
        gdf_country["GID_0"] = gdf_country["GID_0"].astype(str)

        merge_cols = ["iso3"] + [c for c in cols_avg if c in df_om_mean.columns]
        gdf_out = gdf_country.merge(
            df_om_mean[merge_cols],
            left_on="GID_0", right_on="iso3", how="left",
        ).drop(columns=["iso3"], errors="ignore")

        gdf_out.to_file(
            os.path.join(stats_dir, "Global_country_output.gpkg"),
            driver="GPKG",
        )
        print(f"  [B2] Global_country_output.gpkg 已生成")

    print(f"\n[P3 Step 3] {direction}: ✅ → {stats_dir}")


if __name__ == "__main__":
    for d in ["CHN2World", "World2CHN"]:
        run(d)
