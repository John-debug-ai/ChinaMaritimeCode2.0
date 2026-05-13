"""
Phase 3 / Step 2: 港口 MRIO 系数计算

对 step1 输出的港口流量表，基于 EORA26 全球 MRIO，计算两类结果：

① 产出乘数（Output Multiplier）
   对每个港口节点，模拟港口贸易中断的产出冲击：
   - Backward A 冲击：修改技术系数矩阵 A → 重算 Leontief 逆 → 产出差
   - Backward Y 冲击：修改最终需求矩阵 Y → 用原始 Leontief 逆 → 产出差
   - Forward B 冲击：修改 Ghosian B 矩阵 → v(I-B)^{-1} 差
   - multiplier = (ΔBW + ΔFW) / (Δtrade_A + Δtrade_Y)

② 进口系数（Import Coefficient）
   对每个进口国 × 港口，计算从 EORA A 矩阵提取的进口依赖系数，
   再用 Leontief 逆传导，得到出口隐含进口需求和内需隐含进口需求。

输入：output/mrio/{direction}/input/{direction}_ports_updated.csv
输出：output/mrio/{direction}/multipliers/
  output_multiplier.csv     产出乘数（每港口一行）
  country_indout_C.csv      国家级产出与消费基准
  import_coef_sector.csv    进口系数（每国×港口×行业）
  import_multiplier.csv     进口乘数（每国×港口）
  import_requirement.csv    进口需求（出口端 + 需求端）
"""

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import datetime
import numpy as np
import pandas as pd
import geopandas as gpd

from shared.config import RAW_DATA, mrio, EORA_PATH
from shared.mrio_utils import (
    modify_A_matrix, modify_Y_matrix, modify_B_matrix,
    process_output, load_eora,
)


# ─────────────────────────────────────────────────────────────────────────────
# EORA 缓存入口（供 run.py 调用后传入，避免两方向重复加载）
# ─────────────────────────────────────────────────────────────────────────────

def load_eora_once() -> dict:
    """加载并返回 EORA 预计算字典，供多步骤共用。"""
    return load_eora(EORA_PATH)


# ─────────────────────────────────────────────────────────────────────────────
# 进口系数辅助函数
# ─────────────────────────────────────────────────────────────────────────────

def _get_country_io(eora_obj, country: str, sectors: list, list_countries: list):
    """提取指定国家的进口系数矩阵、国内需求向量和出口向量。

    Returns
    -------
    country_import : DataFrame  （外国 × 行业 rows）× （国内 11 行业 cols）
    demand_country : Series     11 个行业的国内最终需求（家庭+非盈利+政府）
    export_country : Series     11 个行业的对外出口总量
    """
    # 进口系数矩阵：A 的某国列 × 11 行业行 × 前 11 列
    country_import = (
        eora_obj.A[str(country)]
        [eora_obj.A[str(country)].index.get_level_values("sector").isin(sectors)]
        .iloc[:, :11]
    )

    # 国内最终需求（前 3 列：家庭消费 / 非盈利机构 / 政府消费）
    demand = eora_obj.Y[str(country)].iloc[:, [0, 1, 2]]
    demand = demand[demand.index.get_level_values("sector").isin(sectors)]
    sector_df = pd.DataFrame({"sector": sectors})
    demand_country = sector_df.merge(
        demand.sum(axis=1).groupby("sector").sum().reset_index(),
        on="sector",
    )[0]

    # 出口向量
    countries_df = pd.DataFrame({"c": list_countries})
    countries_df = countries_df[countries_df["c"] != str(country)]
    export_matrix = eora_obj.Z.loc[str(country)]
    export_matrix = export_matrix[
        export_matrix.index.get_level_values("sector").isin(sectors)
    ]
    export_country = export_matrix[countries_df["c"].tolist()].sum(axis=1)

    return country_import, demand_country, export_country


def _fill_imports_port(
    port_import_share: pd.DataFrame,
    country_import: pd.DataFrame,
    country: str,
    sectors: list,
    list_countries: list,
) -> pd.DataFrame:
    """用港口贸易份额填充进口系数矩阵（稀疏化）。"""
    country_import_append = country_import.copy() * 0.0
    for i in range(len(port_import_share)):
        c_imp = str(country)
        c_exp = port_import_share["iso3_O"].iloc[i]
        ind   = sectors[int(port_import_share["Industries"].iloc[i]) - 1]
        share = float(port_import_share["v_share_trade"].iloc[i])
        if c_imp not in list_countries or c_exp not in list_countries:
            continue
        new_row = country_import.loc[c_exp].loc[ind] * share
        country_import_append.loc[(c_exp), (ind)] = new_row.to_list()
    return country_import_append


def _port_import_coef(
    country_import_append: pd.DataFrame,
    country: str,
) -> np.ndarray:
    """汇总外国贡献，得到 (11×11) 进口系数矩阵。"""
    imp = country_import_append[
        country_import_append.index.get_level_values("region") != str(country)
    ]
    result = np.zeros((11, 11))
    for c in imp.index.get_level_values("region").unique():
        result += imp[imp.index.get_level_values("region") == c].values
    return result


# ─────────────────────────────────────────────────────────────────────────────
# 产出乘数计算（逐港口）
# ─────────────────────────────────────────────────────────────────────────────

def _compute_output_multiplier(
    G: dict,
    ports_network: pd.DataFrame,
    nodes_port_trade: gpd.GeoDataFrame,
) -> pd.DataFrame:
    """对每个港口节点运行 Backward + Forward MRIO，返回产出乘数 DataFrame。"""
    A0    = G["A_orig"];  Y0    = G["Y_orig"];  Z0   = G["Z_orig"]
    B0    = G["B_orig"];  I     = G["I_full"]
    x0    = G["x_orig"];  v_nd  = G["v_ndarray"]
    lc    = G["list_countries"];  sc = G["sectors"]
    ri    = G["rows_index"]

    # 原始 Leontief 逆（Y 冲击使用原始 A，可预计算）
    L_orig = np.linalg.inv(I - A0.values)

    results = []
    n_ports  = len(nodes_port_trade)

    for i, port in nodes_port_trade.iterrows():
        country = port["iso3"]
        print(f"  [{i+1}/{n_ports}] {port['name']}  {datetime.datetime.now().strftime('%H:%M:%S')}")

        if country not in lc:
            continue

        # 该港口的贸易流量
        port_rows  = ports_network[ports_network["id"] == port["id"]]
        all_flows  = (
            port_rows
            .groupby(["iso3_O", "iso3_D", "Industries"])["v_share_trade"]
            .sum().reset_index()
        )
        if all_flows.empty:
            continue

        # 原始产出基准
        g0   = float(x0["indout"].sum())
        dom0 = float(x0.loc[str(country)].sum()[0])
        row0 = g0 - dom0
        gC0  = float(Y0.sum().sum())
        dC0  = float(Y0[str(country)].sum().sum())
        rC0  = gC0 - dC0
        chn_ri = ri[ri["region"] == str(country)].index

        # ── Backward A 冲击 ─────────────────────────────────────────────
        A_mod, trade_ind = modify_A_matrix(A0, Z0, all_flows, lc, sc)
        out_A = np.dot(np.linalg.inv(I - A_mod.values), Y0.values)
        g_A   = float(out_A.sum())
        dom_A = float(out_A.sum(axis=1)[chn_ri].sum())

        # ── Backward Y 冲击 ─────────────────────────────────────────────
        Y_mod, C_bil = modify_Y_matrix(Y0, all_flows, lc, sc)
        out_Y = np.dot(L_orig, Y_mod.values)
        g_Y   = float(out_Y.sum())
        dom_Y = float(out_Y.sum(axis=1)[chn_ri].sum())
        gC_new = float(Y_mod.sum().sum())
        dC_new = float(Y_mod[str(country)].sum().sum())

        # ── Forward B 冲击 ───────────────────────────────────────────────
        B_mod  = modify_B_matrix(B0, Z0, all_flows, lc, sc)
        indin  = np.dot(v_nd, np.linalg.inv(I - B_mod.values))
        diff   = x0["indout"].values - indin
        td_fw  = float(diff.sum())
        dom_fw = float(diff[chn_ri].sum())
        row_fw = td_fw - dom_fw

        rec = {
            "name":             port["name"],
            "id":               port["id"],
            "iso3":             country,
            "trade_ind":        trade_ind,
            "C":                C_bil,
            "Dind_int_bw":      g0   - g_A,
            "Dind_iso3_int_bw": dom0 - dom_A,
            "Dind_row_int_bw":  (row0) - (g_A - dom_A),
            "Dind_C_bw":        g0   - g_Y,
            "Dind_iso3_C_bw":   dom0 - dom_Y,
            "Dind_row_C_bw":    (row0) - (g_Y - dom_Y),
            "DC_iso3_fw":       dC0  - dC_new,
            "DC_row_fw":        rC0  - (gC_new - dC_new),
            "Dind_int_fw":      td_fw,
            "Dind_iso3_int_fw": dom_fw,
            "Dind_row_int_fw":  row_fw,
        }
        results.append(rec)

    df = pd.DataFrame(results)
    if df.empty:
        return df
    return process_output(df)


# ─────────────────────────────────────────────────────────────────────────────
# 进口系数计算（逐国家×港口）
# ─────────────────────────────────────────────────────────────────────────────

def _compute_import_coef(
    G: dict,
    ports_network: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """对每个进口国及其各港口计算进口系数、进口乘数和进口需求。

    Returns
    -------
    import_coef_all, import_multiplier_all, import_requirement_all
    """
    lc  = G["list_countries"];  sc = G["sectors"]
    eora_obj = G["eora"]

    country_list = ports_network["iso3_D"].unique().tolist()

    coef_rows = [];  mult_rows = [];  req_rows = []

    for country in country_list:
        if country not in lc:
            continue
        print(f"  进口系数: {country}")

        # 国家级 IO 数据
        A_country = eora_obj.A[str(country)].loc[str(country)].iloc[:11, :11]
        sectors_c  = A_country.columns[:11].tolist()
        I11        = np.eye(11)

        country_import, demand_country, export_country = _get_country_io(
            eora_obj, country, sectors_c, lc
        )

        # 该国的进口流量（port_import 行）
        sub = ports_network[
            (ports_network["iso3_D"] == str(country)) &
            (ports_network["flow"] == "port_import")
        ]
        country_ports = sub["id"].unique()

        for port in country_ports:
            port_share = sub[sub["id"] == str(port)]
            country_import_append = _fill_imports_port(
                port_share, country_import, country, sectors_c, lc
            )
            import_coef = _port_import_coef(country_import_append, country)

            step1 = np.dot(np.ones(11), import_coef)
            step2 = np.dot(step1, np.linalg.inv(I11 - A_country.values))
            multiplier = float(step2.sum())

            req_export = float(np.dot(step2, export_country.values))
            req_demand = float(np.dot(step2, demand_country.values))

            # 行业系数行
            for j, s in enumerate(sectors_c):
                coef_rows.append({
                    "iso3_import": country,
                    "id":          str(port),
                    "Industries":  j + 1,
                    "sector":      s,
                    "Import_coef": float(step2[j]),
                })

            mult_rows.append({
                "iso3_import":     country,
                "id":              str(port),
                "Import_multiplier": multiplier,
            })

            req_rows.append({
                "iso3_import":  country,
                "id":           str(port),
                "Import_export": req_export,
                "Total_export":  float(export_country.values.sum()),
                "Import_demand": req_demand,
                "Total_demand":  float(demand_country.values.sum()),
            })

    return (
        pd.DataFrame(coef_rows),
        pd.DataFrame(mult_rows),
        pd.DataFrame(req_rows),
    )


# ─────────────────────────────────────────────────────────────────────────────
# 主入口
# ─────────────────────────────────────────────────────────────────────────────

def run(direction: str, eora_data: dict = None) -> None:
    """
    direction  : "CHN2World" 或 "World2CHN"
    eora_data  : 可选，预先加载的 EORA 字典（避免重复加载）
    """
    # 加载 EORA（若未传入则自行加载）
    G = eora_data if eora_data is not None else load_eora(EORA_PATH)

    out_dir = mrio(direction, "multipliers")

    # ── 读取港口流量表 ──────────────────────────────────────────────────────
    ports_path = os.path.join(
        mrio(direction, "input"),
        f"{direction}_ports_updated.csv",
    )
    if not os.path.exists(ports_path):
        print(f"[P3 Step 2] {direction}: 输入文件不存在，请先运行 step1。")
        return

    ports_network = pd.read_csv(ports_path)
    print(f"[P3 Step 2] {direction}: 读取 {len(ports_network):,} 行港口数据")

    # ── 获取参与贸易的港口节点列表 ──────────────────────────────────────────
    nodes_maritime = gpd.read_file(RAW_DATA["nodes_maritime"])
    nodes_port = nodes_maritime[nodes_maritime["infra"] == "port"]

    port_ids = ports_network["id"].unique()
    nodes_port_trade = (
        nodes_port[nodes_port["id"].isin(port_ids)]
        .reset_index(drop=True)
    )
    print(f"  有效港口节点: {len(nodes_port_trade):,} 个")

    # ── 产出乘数 ────────────────────────────────────────────────────────────
    print(f"\n[P3 Step 2] {direction}: 开始产出乘数计算...")
    t0 = datetime.datetime.now()
    multiplier_ports = _compute_output_multiplier(G, ports_network, nodes_port_trade)
    print(f"  产出乘数完成，耗时 {datetime.datetime.now()-t0}")

    if not multiplier_ports.empty:
        multiplier_ports.to_csv(
            os.path.join(out_dir, "output_multiplier.csv"),
            index=False,
        )
        G["output_country"].to_csv(
            os.path.join(out_dir, "country_indout_C.csv"),
            index=False,
        )
        print(f"  → output_multiplier.csv  ({len(multiplier_ports):,} 行)")

    # ── 进口系数 ─────────────────────────────────────────────────────────────
    print(f"\n[P3 Step 2] {direction}: 开始进口系数计算...")
    t1 = datetime.datetime.now()
    coef_df, mult_df, req_df = _compute_import_coef(G, ports_network)
    print(f"  进口系数完成，耗时 {datetime.datetime.now()-t1}")

    coef_df.to_csv(os.path.join(out_dir, "import_coef_sector.csv"), index=False)
    mult_df.to_csv(os.path.join(out_dir, "import_multiplier.csv"), index=False)
    req_df.to_csv( os.path.join(out_dir, "import_requirement.csv"), index=False)
    print(f"  → import_coef_sector.csv  ({len(coef_df):,} 行)")
    print(f"  → import_multiplier.csv  ({len(mult_df):,} 行)")
    print(f"  → import_requirement.csv  ({len(req_df):,} 行)")

    print(f"\n[P3 Step 2] {direction}: ✅ 全部完成 → {out_dir}")


if __name__ == "__main__":
    eora_data = load_eora_once()
    for d in ["CHN2World", "World2CHN"]:
        run(d, eora_data=eora_data)
