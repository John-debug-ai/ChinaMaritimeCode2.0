# Phase 3 / Step 5：缓冲情景 MRIO 分析 — 算法文档

> 对应代码：`phase3_io_analysis/step5_buffer_scenarios.py`

---

## 1. 研究目的

回答以下问题：

> **如果某个海运要道（如马六甲、霍尔木兹）发生 25%/50%/75%/100% 的贸易中断，
> 经过该要道的中国相关贸易会对全球和中国的产出造成多大影响？
> 当部分国家"有替代路线（绕行）"时，这些国家受到中断情景的影响应该被相应缓冲；
> 而"无替代路线"的国家则始终承受 100% 中断（情景缓冲对它们无效）。**

核心创新点：在传统 MRIO 中断分析基础上，**引入"替代路线缓冲"机制**，使得情景从抽象的"百分比中断"细化为更接近现实的"绕行能力分国家差异化"。

---

## 2. 输入与输出

### 2.1 输入文件

| 文件 | 来源 | 用途 |
|---|---|---|
| `output/disruption/{direction}/01_routes_csv/{要道}.csv` | Phase 2 Step 1 | 列出经过该要道的所有航线（港口对级别） |
| `output/{direction}/routes/shortest_paths_{direction}_with_flows.gpkg` | Phase 1 Step 5 | 全方向所有航线（替代路线判断的全集） |
| `output/mrio/{direction}/input/{direction}_ports_updated.csv` | Phase 3 Step 1 | 港口×行业的贸易流量与份额 (`v_share_trade`) |
| EORA26 (2019) | 外部数据库 | 全球 MRIO 系统的 A、Y、Z、x 矩阵 |

### 2.2 输出文件

`output/mrio/{direction}/buffer/`

| 文件 | 形态 | 内容 |
|---|---|---|
| `{direction}_buffer_results.csv` | **长表**：每要道 × 每情景一行 | 全部输出指标 |
| `{direction}_宽表汇总.xlsx` | **宽表**：每要道一行，4 个情景横向并列 | 便于跨情景横向对比 |

### 2.3 输出指标

| 字段 | 含义 |
|---|---|
| `no_alt_frac` | 无替代路线贸易 占该要道 100% 基准贸易的比例（缓冲下限） |
| `trade_total_100` | 100% 中断下的基准贸易损失（A+Y 合计）— 多情景**共用分母** |
| `trade_total_S` | 当前情景实际贸易损失（按 v_share 缩放后） |
| `Dind_total` | 全球绝对产出损失（USD），= Backward + Forward |
| `Dind_chn` | 中国产出损失 |
| `Dind_row` | 其他国家产出损失（= Dind_total − Dind_chn） |
| `Dind_total_bw` / `Dind_total_fw` | Backward / Forward 联系拆分 |
| `multiplier_B` | **主乘数** = Dind_total / **trade_total_100**（分母固定 → 体现情景缓冲效果） |
| `multiplier_A` | 参考乘数 = Dind_total / **trade_total_S**（分母随情景变化 → 接近常数） |

⚠ **multiplier_B 与 multiplier_A 的设计意图**：
- `multiplier_B`：分母是固定的 100% 基准 → 当情景从 25% 提升到 100%，**分子**（实际产出损失）会增加，所以 mB 也变大。它能反映"情景从轻到重，损失放大了多少"。
- `multiplier_A`：分子分母同步缩放 → 接近一个反映 MRIO 系统"传导效率"的常数。两者并存便于交叉验证。

---

## 3. 算法整体流程

```
对每个方向 (CHN2World / World2CHN)：
│
├── 加载 EORA → 预计算 Leontief 逆 L_orig = (I − A0)^{−1}
│
├── 加载全量路线 GPKG（替代路线判断的全集）
├── 加载 ports_updated.csv，仅保留 flow == "port_export"
│
└── 对每个要道 CSV：
    │
    ├── 步骤 ①  替代路线判断  →  alt_status = {iso3: True/False}
    │
    ├── 步骤 ②  提取经过该要道的 port_export 流量
    │           → 按 (iso3_O, iso3_D, Industries) 汇总 = all_flows_100
    │
    └── 对每个情景 s ∈ {0.25, 0.50, 0.75, 1.00}：
        │
        ├── 步骤 ③  缩放 v_share_trade：
        │            有替代国家：× s    无替代国家：保持 100%
        │
        ├── 步骤 ④  Backward 联系（A 冲击 + Y 冲击）
        │            ΔBW = ΔBW_A + ΔBW_Y
        │
        ├── 步骤 ⑤  Forward 联系（B 冲击）
        │            ΔFW = ΔFW_B + ΔC
        │
        └── 步骤 ⑥  汇总 → 写入 all_results
```

---

## 4. 关键算法详解

### 4.1 替代路线判断（`compute_alt_status`）

**问题**：要道关闭后，某外国是否还能通过其他路线到达 / 来自中国？

**方法（端口级 → 国家 fallback）**：

设要道中的"本侧—对侧"港口对集合为 `choke_pairs`（例如对 World2CHN，本侧 = 外国出口港 `start_id`，对侧 = 中国进口港 `end_id`）。

对每个外国 `country`：
```
对该国所有港口 p：
    via_choke = {p2 | (p, p2) ∈ choke_pairs}     ← 通过该要道才能到达的对侧港口
    all_dest  = 全量路线中 p 的所有对侧目的地
    if all_dest − via_choke 非空：
        ⇒ 存在不经过该要道的路径，has_alt = True，break
该国 alt_status = has_alt
```

**关键设计**：判断单位是"港口"，但赋值粒度是"国家"——只要该国**任意一个**港口有替代路线，整个国家就被判为有替代。这是一个比较宽松的判定（有缓冲倾向）。

### 4.2 流量提取与汇总

```python
# 仅取 port_export，避免 port_export / port_trans / port_import 三重计数
ports_exp = ports_df[ports_df["flow"] == "port_export"]

# 按要道 CSV 的港口 ID 列匹配
sub = ports_exp[ports_exp["id"].isin(choke_port_ids)]

# 按 (iso3_O, iso3_D, Industries) 聚合
all_flows_100 = sub.groupby(...).sum()
```

**为什么只取 port_export？** ports_df 中每条贸易会被记三行（出口港、转运港、进口港），全部累加会三重计数。`port_export` 一行代表完整的一次贸易，最干净。

### 4.3 v_share_trade 的情景缩放

```python
flows_S = all_flows_100.copy()
has_alt = flows_S[foreign_check].map(lambda x: alt_status.get(x, True))
flows_S.loc[has_alt, "v_share_trade"] *= scenario   # 有替代：按情景缩放
# 无替代：保持原值（始终 100% 中断）
```

这一步是缓冲机制的数学体现：**只有有替代路线的国家才享受情景缓冲红利**。

### 4.4 Backward 联系：A 矩阵冲击 + Y 矩阵冲击

借助 `shared/mrio_utils.py` 的两个函数：

#### A 冲击 — 中间投入减少
```
A_mod[(c_exp, ind), c_imp] = A0[(c_exp, ind), c_imp] × (1 − v_share_trade)
trade_ind_loss = Σ Z0[(c_exp, ind), c_imp].sum() × v_share_trade

L_mod = (I − A_mod)^{−1}
out_A = L_mod @ Y0
ΔBW_A_global = global_out_0 − out_A.sum()
ΔBW_A_chn    = chn_out_0    − out_A.sum(axis=1)[chn_idx].sum()
```

#### Y 冲击 — 最终消费减少
```
Y_mod[(c_exp, ind), c_imp] = Y0[(c_exp, ind), c_imp] × (1 − v_share_trade)
trade_C_loss = Σ Y0[(c_exp, ind), c_imp].sum() × v_share_trade

# A 不变 → 复用预计算的 L_orig（性能优化）
out_Y = L_orig @ Y_mod
ΔBW_Y_global = global_out_0 − out_Y.sum()
ΔBW_Y_chn    = chn_out_0    − out_Y.sum(axis=1)[chn_idx].sum()
```

**Backward 总产出损失：**
```
Dind_total_bw = ΔBW_A_global + ΔBW_Y_global
Dind_chn_bw   = ΔBW_A_chn    + ΔBW_Y_chn
Dind_row_bw   = Dind_total_bw − Dind_chn_bw
```

### 4.5 Forward 联系：B 矩阵冲击（Ghosian 模型）

```
B_mod[(c_exp, ind), c_imp] = B0[(c_exp, ind), c_imp] × (1 − v_share_trade)
indin = v_ndarray @ (I − B_mod)^{−1}        # 受冲击后的"理论总投入"
diff  = x0 − indin                          # 与原始总产出的差

total_diff = diff.sum()                     # 全球供给链前向收缩
chn_diff   = diff[chn_idx].sum()
row_diff   = total_diff − chn_diff
```

其中 `v_ndarray = x0 (I − B0)` 是在 EORA 加载时预计算的常量（Forward 中"增加值向量"）。

**Forward 总产出损失（含最终消费变化）：**
```
ΔC_chn = chn_C_0 − Y_mod["CHN"].sum().sum()        # 中国消费损失
ΔC_row = row_C_0 − (Y_mod.sum().sum() − Y_mod["CHN"].sum().sum())

Dind_total_fw = total_diff + trade_C_loss
Dind_chn_fw   = chn_diff   + ΔC_chn
Dind_row_fw   = row_diff   + ΔC_row
```

### 4.6 汇总与乘数

```
Dind_total = Dind_total_bw + Dind_total_fw
Dind_chn   = Dind_chn_bw   + Dind_chn_fw
Dind_row   = Dind_row_bw   + Dind_row_fw

multiplier_B = Dind_total / trade_total_100   ← 分母固定
multiplier_A = Dind_total / trade_total_S     ← 分母随情景变
```

---

## 5. 方向配置（DIRECTION_CONFIG）

两个方向的列名映射：

| 配置项 | World2CHN | CHN2World | 说明 |
|---|---|---|---|
| `filter_iso_col` | `end_iso3` | `start_iso3` | 全量路线中 CHN 所在列 |
| `foreign_check` | `iso3_O` | `iso3_D` | 流量汇总中外国 ISO3 列 |
| `port_match_col` | `start_id` | `start_id` | 要道 CSV 中匹配 `ports_exp["id"]` 的列 |
| `alt_foreign_col` | `start_iso3` | `end_iso3` | 替代路线判断时外国 ISO3 列 |
| `alt_port_col` | `start_id` | `end_id` | 外国港口 ID 列 |
| `alt_other_col` | `end_id` | `start_id` | 中国港口 ID 列 |

**逻辑要点**：
- 对 World2CHN（外国进口至中国），外国是 origin，所以 `foreign_check = iso3_O`、外国港口在 `start_id`
- 对 CHN2World（中国出口至外国），外国是 destination，所以 `foreign_check = iso3_D`、外国港口在 `end_id`

---

## 6. 性能优化点

| 优化 | 描述 | 收益 |
|---|---|---|
| `L_orig` 预计算 | A0 不变 → `(I−A0)^{−1}` 在循环外算一次 | 每个情景节省一次 14000² 矩阵求逆 |
| `v_ndarray` 预计算 | `v = x(I−B0)` 在 EORA 加载时算 | 每次 Forward 计算节省一次大矩阵乘法 |
| EORA 加载缓存 | `load_eora_once()` 在 run.py 调用一次后传入 | 两个方向共用，节省 1–2 分钟 |

---

## 7. 输出语义示例

假设要道 = 马六甲海峡，方向 = World2CHN，结果如下：

| 情景 | trade_total_100 | trade_total_S | Dind_total | multiplier_B | no_alt_frac |
|---|---|---|---|---|---|
| 25% | 1000B$ | 350B$ | 800B$ | 0.80 | 0.20 |
| 50% | 1000B$ | 600B$ | 1300B$ | 1.30 | 0.20 |
| 75% | 1000B$ | 850B$ | 1800B$ | 1.80 | 0.20 |
| 100% | 1000B$ | 1000B$ | 2200B$ | 2.20 | 0.20 |

解读：
- `no_alt_frac = 0.20` → 经马六甲的贸易中，**20% 来自无替代路线的国家**（这部分始终全损）
- 即使是 25% 情景，`trade_total_S = 350B$` 也至少包含 200B$（来自无替代国家的全损）+ 150B$（其余 80% 国家按 25% 缩放后的损失）
- `multiplier_B` 从 0.80 → 2.20，反映情景加重后 MRIO 传导的总损失放大

---

## 8. 已知限制与简化

| 项 | 简化方式 | 影响 |
|---|---|---|
| 替代路线判断 | 仅看是否"存在"绕行港口对，不计算绕行距离 | 同一国内远距离绕行也会被判为"有替代"，可能高估缓冲效果 |
| 替代路线赋值粒度 | 国家级，一个港口有替代→全国都有 | 实际可能只有沿海港口有，内陆港口无 |
| 情景缓冲机制 | 线性缩放 v_share_trade | 真实贸易反应可能非线性（弹性、价格效应未建模） |
| Forward C 项处理 | `Dind_total_fw = total_diff + tC_S` | 与 Phase 3 Step 2 中的 `+ C` 字段含义相同（消费下降也算 forward 影响） |

---

## 9. 调用方式

```bash
# 完整运行（两个方向）
python phase3_io_analysis/run.py --step 5

# 只跑一个方向
python phase3_io_analysis/run.py --step 5 --direction World2CHN

# Phase 3 全流程时跳过本步（步骤耗时较长，约 N_要道 × N_情景 × 单次 MRIO ≈ 数十分钟）
python phase3_io_analysis/run.py --skip-buffer
```
