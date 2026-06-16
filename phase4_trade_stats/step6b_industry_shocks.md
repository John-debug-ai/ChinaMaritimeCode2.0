# Phase 3 / Step 6b：逐行业隔离冲击分析 — 算法文档

> 对应代码：`phase3_io_analysis/step6b_industry_shocks.py`

---

## 1. 研究目的

回答以下问题：

> **在某个要道中断时，11 个 EORA 行业各自单独中断会造成多大的产出损失？
> 哪些行业的产出乘数最高？哪些行业对中国 vs 世界其他国家的影响不对称？**

### 与 Step 6 的关系

Step 6 计算的是 **11 个行业同时中断** 后的整体乘数。
Step 6b 将行业拆开，**逐个隔离冲击**：每次只中断一个行业的贸易流量，
运行完整 MRIO 计算（Backward + Forward），得到该行业单独中断时的产出损失。

这一拆分使得：
- 可以识别哪些行业是"高杠杆行业"（乘数远高于平均值）
- 可以比较同一行业在不同要道间的乘数差异（行业 × 要道交叉分析）
- 可以分析中国 vs 其他国家在行业维度上的不对称脆弱性

---

## 2. 输入与输出

### 2.1 输入文件

与 Step 6 完全相同：

| 文件 | 来源 | 用途 |
|---|---|---|
| `output/{direction}/routes/shortest_paths_{direction}_with_flows.gpkg` | Phase 1 Step 5 | 全量路线（含 geometry + v1..v11） |
| `output/mrio/{direction}/input/{direction}_ports_updated.csv` | Phase 3 Step 1 | 港口×行业的贸易流量与份额 |
| `data/chokepoints/*.shp` | 外部数据 | 10 个海运要道的地理点位 |
| EORA26 (2019) | 外部数据库 | 全球 MRIO 系统 |

### 2.2 输出文件

`output/mrio/{direction}/industry_shocks/`

| 文件 | 形态 | 内容 |
|---|---|---|
| `{direction}_industry_shocks.csv` | **长表**：每要道 × 情景 × 行业一行 | 全部输出指标 |
| `{direction}_industry_shocks.xlsx` | **宽表**：每要道 × 行业一行，情景横向展开 | 便于跨情景横向对比 |

### 2.3 输出指标

| 字段 | 含义 |
|---|---|
| `chokepoint` | 要道名称 |
| `direction` | CHN2World 或 World2CHN |
| `industry` | 行业编号（1~11） |
| `industry_name` | 行业英文名称 |
| `scenario` | 中断情景（0.25 / 0.50 / 0.75 / 1.00） |
| `ind_trade_100` | 该行业在 100% 情景下的基准贸易量（chokefrac 缩放后） |
| `trade_total_100` | 该行业 100% 中断基准贸易损失 |
| `trade_total_S` | 当前情景实际贸易损失 |
| `Dind_total` | 全球绝对产出损失（USD） |
| `Dind_chn` / `Dind_row` | 中国 / 其他国家产出损失 |
| `Dind_total_bw` / `Dind_total_fw` | Backward / Forward 联系拆分 |
| `multiplier_B` | 主乘数 = Dind_total / trade_total_100 |
| `multiplier_A` | 参考乘数 = Dind_total / trade_total_S |
| `multiplier_A_chn` / `multiplier_A_row` | 中国 / 其他国家的 multiplier_A 拆分 |

### 2.4 EORA 11 部门对照

| 编号 | 行业名称 | 缩写 |
|---|---|---|
| 1 | Agriculture | 农业 |
| 2 | Fishing | 渔业 |
| 3 | Mining and Quarrying | 矿业 |
| 4 | Food & Beverages | 食品饮料 |
| 5 | Textiles and Wearing Apparel | 纺织服装 |
| 6 | Wood and Paper | 木材纸制品 |
| 7 | Petroleum, Chemical and Non-Metallic Mineral Products | 石化 |
| 8 | Metal Products | 金属制品 |
| 9 | Electrical and Machinery | 电气机械 |
| 10 | Transport Equipment | 运输设备 |
| 11 | Other Manufacturing | 其他制造 |

---

## 3. 算法整体流程

```
对每个方向 (CHN2World / World2CHN)：
│
├── 加载 EORA → 预计算 Leontief 逆 L_orig
│
├── 加载全量路线 GPKG + 构造 V_all
├── 加载 ports_updated.csv（port_export 行）
│
└── 对每个要道 SHP：
    │
    ├── 步骤 ①  空间相交 → 经过要道的路径子集
    ├── 步骤 ②  替代路线判断（复用 step5）→ alt_status
    ├── 步骤 ③  计算 chokefrac（复用 step6）
    ├── 步骤 ④  缩放 v_share_trade × chokefrac
    │            → 聚合得 all_flows_100
    │
    └── 对每个行业 ind ∈ [1..11]：        ← 与 step6 的唯一区别
        │
        ├── 步骤 ⑤  过滤：flows_ind = all_flows_100[Industries == ind]
        │
        └── 对每个情景 s ∈ {0.25, 0.50, 0.75, 1.00}：
            │
            ├── 步骤 ⑥  将 flows_ind 单独传给 run_scenario
            │            → 仅该行业的贸易流参与 MRIO 冲击
            │
            └── 步骤 ⑦  记录结果（含行业编号和名称）
```

### 与 Step 6 的流程差异

```
Step 6:  all_flows_100（全行业） → run_scenario → 整体乘数
Step 6b: all_flows_100 → 拆分 11 个行业 → 逐个 run_scenario → 行业级乘数
```

步骤 ①~④ 完全相同，步骤 ⑤ 是新增的行业过滤，步骤 ⑥~⑦ 的 MRIO 计算逻辑不变但输入仅为单行业流量。

---

## 4. 关键设计

### 4.1 隔离冲击 vs 整体冲击

**隔离冲击**意味着每次只中断一个行业，其余 10 个行业的贸易保持正常。
这与 Step 6 的"同时中断全部行业"不同。

因此：**11 个行业的隔离冲击 Dind 之和 ≠ Step 6 的整体 Dind**。
差异来自行业间的投入产出联系（非线性交叉效应）：
- 行业 A 中断会影响行业 B 的中间投入，反之亦然
- 同时中断时这些交叉效应叠加，导致整体损失 > 隔离损失之和

### 4.2 chokefrac 在行业维度的作用

chokefrac 是 (O, D, Industries) 三维的，因此同一要道中：
- 不同行业可能有不同的 chokefrac
- 例如马六甲海峡：石化行业（中东→中国）的 chokefrac 可能高于纺织行业

这意味着行业维度的乘数差异不仅反映 MRIO 传导结构，也反映各行业在特定要道上的**物理路径依赖度**。

### 4.3 替代路线的行业无关性

当前替代路线判断（alt_status）是**国家级、行业无关**的：
某国有替代路线 = 该国所有行业都有替代。
这是对现实的简化——实际上不同行业可能有不同的替代运输方案。

---

## 5. 计算量

| 维度 | 数量 |
|---|---|
| 要道 | 10 |
| 情景 | 4（25%/50%/75%/100%） |
| 行业 | 11 |
| **每方向 MRIO 次数** | **10 × 4 × 11 = 440** |
| 两方向合计 | 880 |

与 Step 6 的 40 次/方向相比，计算量增加 **11 倍**。
每次 MRIO 计算包含一次 Leontief 逆求解（Backward A 冲击）和一次 Ghosian 逆求解（Forward B 冲击），
总耗时约数小时。

---

## 6. 输出语义示例

假设要道 = 马六甲海峡，方向 = CHN2World，scenario = 1.0：

| 行业 | ind_trade_100 | Dind_total | multiplier_A | multiplier_A_chn | multiplier_A_row |
|---|---|---|---|---|---|
| Agriculture | 0.012 | 0.058B$ | 4.83 | 2.61 | 2.22 |
| Petroleum & Chem. | 0.089 | 0.398B$ | 4.47 | 2.38 | 2.09 |
| Electrical & Mach. | 0.154 | 0.781B$ | 5.07 | 2.85 | 2.22 |
| ... | ... | ... | ... | ... | ... |

解读：
- **Electrical & Mach. multiplier_A = 5.07**：每 1$ 电气机械贸易中断带来 5.07$ 的全球产出损失
- **multiplier_A_chn > multiplier_A_row**：中国在电气机械行业承受的产出损失大于世界其他国家
- 不同行业的 multiplier_A 差异反映了 EORA 投入产出结构中各行业的关联深度

---

## 7. 复用模块

Step 6b 不包含独立的核心算法，全部复用已有模块：

| 模块 | 来源 | 复用内容 |
|---|---|---|
| `compute_alt_status` | Step 5 | 替代路线判断 |
| `run_scenario` | Step 5 | 单情景 MRIO 计算（Backward + Forward） |
| `SCENARIOS`, `DETOUR_THRESHOLD`, `DIRECTION_CONFIG` | Step 5 | 全局常量 |
| `_build_v_table`, `_compute_chokefrac`, `V_COLS` | Step 6 | 路径份额计算 |

---

## 8. 已知限制与简化

| 项 | 简化方式 | 影响 |
|---|---|---|
| 行业间交叉效应 | 隔离冲击忽略多行业同时中断的非线性叠加 | 11 个行业隔离 Dind 之和 < 整体 Dind |
| 替代路线行业无关 | 国家级判断，不区分行业 | 不同行业可能有不同的实际替代能力 |
| 小行业流量 | 某些行业在特定要道上 flows_ind 可能极小 | multiplier_A 可能因分母过小而不稳定 |
| 空间相交精度 | 同 Step 6 | 路径擦过要道缓冲区也会被计入 |

---

## 9. 下游可视化

Step 6b 输出的 `{direction}_industry_shocks.csv` 是以下可视化分析的数据源：

`phase5_plot_and_stats/06-industry_analysis.ipynb`

| 图表 | 内容 |
|---|---|
| C2W-Fig1 / W2C-Fig1 | Heatmap：行业 × 要道的 multiplier_A |
| C2W-Fig2 / W2C-Fig2 | Bar：各行业的平均 multiplier_A |
| C2W-Fig3 / W2C-Fig3 | Bar：各要道的平均 multiplier_A |
| C2W-Fig4 / W2C-Fig4 | Grouped Bar：中国 vs 其他国家乘数（按行业） |
| C2W-Fig6 / W2C-Fig5 | Dominance Heatmap：中国−RoW 乘数差异 |
| C2W-Fig7 / W2C-Fig6 | Lines：multiplier_A 随情景变化趋势 |
| CMP-Fig1~3 | 进出口双向对比（按行业 / 按要道 / 散点图） |

---

## 10. 调用方式

```bash
# 直接运行（两个方向）
python phase3_io_analysis/step6b_industry_shocks.py

# 只跑一个方向
python phase3_io_analysis/step6b_industry_shocks.py CHN2World
```

> **注意**：Step 6b 尚未集成到 `run.py` 中，需直接运行脚本。
> 计算量约为 Step 6 的 11 倍（440 次 MRIO / 方向），耗时约数小时。
> 建议在 Step 6 运行验证无误后再运行 Step 6b。
