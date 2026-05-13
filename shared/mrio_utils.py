"""
shared/mrio_utils.py — MRIO 矩阵操作与数据加载工具

phase3_io_analysis/step2 和 step5 共用的核心函数：

  modify_A_matrix   缩减技术系数矩阵 A（Backward 中间投入冲击）
  modify_Y_matrix   缩减最终需求矩阵 Y（Backward 消费冲击）
  modify_B_matrix   缩减 Ghosian 分配系数矩阵 B（Forward 供给冲击）
  process_output    汇总 backward/forward 产出差，计算乘数列
  load_eora         加载 EORA26 并预计算所有衍生量，返回字典
"""

import warnings
import numpy as np
import pandas as pd
import pymrio

warnings.filterwarnings("ignore")


# ─────────────────────────────────────────────────────────────────────────────
# 矩阵修改函数
# ─────────────────────────────────────────────────────────────────────────────

def modify_A_matrix(
    A_matrix: pd.DataFrame,
    Z_matrix: pd.DataFrame,
    flows: pd.DataFrame,
    list_countries: list,
    sectors: list,
) -> tuple[pd.DataFrame, float]:
    """缩减技术系数矩阵 A，剔除港口贸易份额。

    Parameters
    ----------
    A_matrix       : EORA 技术系数矩阵（MultiIndex: region × sector）
    Z_matrix       : EORA 中间投入矩阵（同结构）
    flows          : 港口贸易流量，含 iso3_O / iso3_D / Industries / v_share_trade
    list_countries : EORA 区域列表
    sectors        : 11 个行业名称列表（顺序与 EORA 一致）

    Returns
    -------
    (修改后的 A_matrix 副本, 中间投入贸易损失总量)
    """
    A_app = A_matrix.copy()
    total = 0.0
    for i in range(len(flows)):
        c_imp = flows["iso3_D"].iloc[i]
        c_exp = flows["iso3_O"].iloc[i]
        ind   = sectors[int(flows["Industries"].iloc[i]) - 1]
        share = float(flows["v_share_trade"].iloc[i])
        if c_imp not in list_countries or c_exp not in list_countries:
            continue
        new_row = A_app.loc[(c_exp, ind), c_imp] * (1.0 - share)
        A_app.loc[(c_exp, ind), c_imp] = new_row.to_list()
        total += Z_matrix.loc[(c_exp, ind), c_imp].sum() * share
    return A_app, total


def modify_Y_matrix(
    Y_matrix: pd.DataFrame,
    flows: pd.DataFrame,
    list_countries: list,
    sectors: list,
) -> tuple[pd.DataFrame, float]:
    """缩减最终需求矩阵 Y，剔除港口贸易份额。

    Returns
    -------
    (修改后的 Y_matrix 副本, 最终消费贸易损失总量)
    """
    Y_app = Y_matrix.copy()
    total = 0.0
    for i in range(len(flows)):
        c_imp = flows["iso3_D"].iloc[i]
        c_exp = flows["iso3_O"].iloc[i]
        ind   = sectors[int(flows["Industries"].iloc[i]) - 1]
        share = float(flows["v_share_trade"].iloc[i])
        if c_imp not in list_countries or c_exp not in list_countries:
            continue
        new_row = Y_app.loc[(c_exp, ind), c_imp] * (1.0 - share)
        Y_app.loc[(c_exp, ind), c_imp] = new_row.to_list()
        total += Y_matrix.loc[(c_exp, ind), c_imp].sum() * share
    return Y_app, total


def modify_B_matrix(
    B_matrix: pd.DataFrame,
    Z_matrix: pd.DataFrame,
    flows: pd.DataFrame,
    list_countries: list,
    sectors: list,
) -> pd.DataFrame:
    """缩减 Ghosian 分配系数矩阵 B，用于 Forward 联系计算。

    Returns
    -------
    修改后的 B_matrix 副本（不返回贸易损失，Forward 用 Y 矩阵的 total 代替）
    """
    B_app = B_matrix.copy()
    for i in range(len(flows)):
        c_imp = flows["iso3_D"].iloc[i]
        c_exp = flows["iso3_O"].iloc[i]
        ind   = sectors[int(flows["Industries"].iloc[i]) - 1]
        share = float(flows["v_share_trade"].iloc[i])
        if c_imp not in list_countries or c_exp not in list_countries:
            continue
        new_row = B_app.loc[(c_exp, ind), c_imp] * (1.0 - share)
        B_app.loc[(c_exp, ind), c_imp] = new_row.to_list()
    return B_app


# ─────────────────────────────────────────────────────────────────────────────
# 产出统计汇总
# ─────────────────────────────────────────────────────────────────────────────

def process_output(df: pd.DataFrame) -> pd.DataFrame:
    """汇总 backward / forward 联系各分量，计算产出乘数列。

    输入 df 须含列：
      trade_ind, C,
      Dind_int_bw, Dind_iso3_int_bw, Dind_row_int_bw,
      Dind_C_bw,   Dind_iso3_C_bw,   Dind_row_C_bw,
      DC_iso3_fw,  DC_row_fw,
      Dind_int_fw, Dind_iso3_int_fw, Dind_row_int_fw

    新增列：
      trade_total, Dind_total_bw/fw, Dind_iso3_bw/fw, Dind_row_bw/fw,
      Dind_total, Dind_iso3, Dind_row,
      multiplier, multiplier_dom, multiplier_row,
      frac_row_dom, frac_bw_fw
    """
    df = df.copy()
    df["trade_total"]   = df["trade_ind"] + df["C"]

    # Backward
    df["Dind_total_bw"] = df["Dind_int_bw"]      + df["Dind_C_bw"]
    df["Dind_iso3_bw"]  = df["Dind_iso3_int_bw"] + df["Dind_iso3_C_bw"]
    df["Dind_row_bw"]   = df["Dind_row_int_bw"]  + df["Dind_row_C_bw"]

    # Forward
    df["Dind_total_fw"] = df["Dind_int_fw"]      + df["C"]
    df["Dind_iso3_fw"]  = df["Dind_iso3_int_fw"] + df["DC_iso3_fw"]
    df["Dind_row_fw"]   = df["Dind_row_int_fw"]  + df["DC_row_fw"]

    # Total
    df["Dind_total"]    = df["Dind_total_bw"] + df["Dind_total_fw"]
    df["Dind_iso3"]     = df["Dind_iso3_bw"]  + df["Dind_iso3_fw"]
    df["Dind_row"]      = df["Dind_row_bw"]   + df["Dind_row_fw"]

    # Multipliers
    df["multiplier"]     = np.round(df["Dind_total"] / df["trade_total"], 3)
    df["multiplier_dom"] = np.round(df["Dind_iso3"]  / df["trade_total"], 3)
    df["multiplier_row"] = np.round(df["Dind_row"]   / df["trade_total"], 3)
    df["frac_row_dom"]   = df["Dind_row"]      / df["Dind_iso3"]
    df["frac_bw_fw"]     = df["Dind_total_bw"] / df["Dind_total_fw"]
    return df


# ─────────────────────────────────────────────────────────────────────────────
# EORA 加载与预计算
# ─────────────────────────────────────────────────────────────────────────────

def load_eora(eora_path: str) -> dict:
    """加载 EORA26 2019 年数据库并预计算所有衍生矩阵和基准量。

    约需 1–2 分钟。建议在 run.py 中只调用一次，将结果缓存后传给 step2 / step5。

    返回字典键说明
    ──────────────
    A_orig, Y_orig, Z_orig, x_orig
        原始 EORA 矩阵（DataFrame，MultiIndex: region × sector）
    v_va : ndarray
        增加值行向量（eora.VA.F 各类增加值纵向求和）
    B_orig : DataFrame
        Ghosian 分配系数矩阵（与 A 同形）
    v_ndarray : ndarray
        Forward 计算用的 v 向量：v = x(I−B)
    x_indout : ndarray
        总产出一维数组
    I_full : ndarray
        (n×n) 单位矩阵
    sectors : list[str]
        11 个行业名称（顺序与 EORA 一致）
    list_countries : list[str]
        EORA 区域列表
    rows_index : DataFrame
        x_orig.reset_index()，用于按 region 定位行号
    chn_idx : Index
        CHN 在 rows_index 中的整数位置索引
    output_country : DataFrame
        国家级统计（iso3, indout, C_dom, C_com_dom）
    global_out_0, chn_out_0 : float
        全球 / 中国 原始总产出
    global_C_0, chn_C_0, row_C_0 : float
        全球 / 中国 / 其他国家 原始最终需求
    eora : IOSystem
        pymrio 原始对象（import coefficient 计算时直接使用 eora.A[country]）
    """
    print("加载 EORA26（约需 1–2 分钟）...")
    eora = pymrio.parse_eora26(year=2019, path=eora_path)
    eora.calc_all()
    print("EORA 加载完毕")

    A0 = eora.A
    Y0 = eora.Y
    Z0 = eora.Z
    x0 = eora.x
    v_va = eora.VA.F.values.sum(axis=0)

    sectors        = A0.columns[:11].get_level_values("sector").tolist()
    list_countries = eora.get_regions().to_list()
    n              = A0.shape[0]
    I_full         = np.eye(n)

    # ── Ghosian B 矩阵 ────────────────────────────────────────────────────
    col_vec = np.array(x0.indout.to_list()).T
    d_diag  = np.diag(col_vec)
    x_inv   = np.nan_to_num(I_full / d_diag)
    B_arr   = np.dot(x_inv, Z0.values)
    B0      = A0.copy()
    B0[:]   = B_arr

    # v = x(I−B)，Forward 计算固定量
    v_ndarray = np.dot(np.array(x0.indout.to_list()), (I_full - B_arr))
    x_indout  = np.array(x0.indout.to_list(), dtype=float)

    # ── 行索引与 CHN 位置 ──────────────────────────────────────────────────
    rows_index = x0.reset_index()
    chn_idx    = rows_index[rows_index["region"] == "CHN"].index

    # ── 基准量 ────────────────────────────────────────────────────────────
    global_out_0 = float(x0["indout"].sum())
    chn_out_0    = float(x0.loc["CHN"].sum()[0])
    global_C_0   = float(Y0.sum().sum())
    chn_C_0      = float(Y0["CHN"].sum().sum())
    row_C_0      = global_C_0 - chn_C_0

    # ── 国家级统计（step2 输出 country_indout_C.csv 用）────────────────────
    C_countries = (
        Y0.sum(axis=0).reset_index()
        .groupby("region")[0].sum().reset_index()
        .rename(columns={0: "C_dom", "region": "iso3"})
    )
    Y0_com = Y0.reset_index()
    Y0_com = Y0_com[Y0_com["sector"].isin(sectors)]
    C_com_countries = (
        Y0_com.drop(columns=["region", "sector"])
        .sum(axis=0).reset_index()
        .groupby("region")[0].sum().reset_index()
        .rename(columns={0: "C_com_dom", "region": "iso3"})
    )
    output_country = (
        rows_index.groupby("region")[["indout"]].sum().reset_index()
        .rename(columns={"region": "iso3"})
        .merge(C_countries,     on="iso3")
        .merge(C_com_countries, on="iso3")
    )

    print(f"全球产出基准: {global_out_0/1e12:.3f} 万亿$  |  CHN: {chn_out_0/1e12:.3f} 万亿$")

    return dict(
        A_orig=A0, Y_orig=Y0, Z_orig=Z0, x_orig=x0, v_va=v_va,
        B_orig=B0,
        v_ndarray=v_ndarray,
        x_indout=x_indout,
        I_full=I_full,
        sectors=sectors,
        list_countries=list_countries,
        rows_index=rows_index,
        chn_idx=chn_idx,
        output_country=output_country,
        global_out_0=global_out_0, chn_out_0=chn_out_0,
        global_C_0=global_C_0, chn_C_0=chn_C_0, row_C_0=row_C_0,
        eora=eora,
    )
