# ChinaMaritimeCode2.0

**中国海上贸易网络脆弱性分析——关键航运咽喉点中断的经济影响评估**

Economic Impact Assessment of Critical Shipping Chokepoint Disruptions on China's Maritime Trade Network

---

## 项目概述

本项目构建了一套完整的四阶段分析流水线，评估全球 10 个关键海运咽喉点中断对中国进出口贸易及全球经济的影响。

**核心研究问题**：当马六甲海峡、苏伊士运河等关键海运通道被中断时，全球贸易将如何改道？改道成本有多大？对全球和中国的产出损失乘数是多少？不同行业的脆弱性差异如何？

### 分析流水线

```
Phase 1                Phase 2                Phase 3                Phase 4
基准航线构建     →     咽喉点中断模拟     →     MRIO 经济影响     →     贸易统计汇总
                                                    │
                                               ┌────┴────┐
                                            Step 5    Step 6/6b
                                          缓冲情景    路径份额 +
                                            分析     行业隔离冲击
```

### 研究方向

所有分析均覆盖两个贸易方向：

| 方向 | 代码 | 含义 |
|---|---|---|
| 中国出口 | `CHN2World` | 中国港口 → 外国港口 |
| 中国进口 | `World2CHN` | 外国港口 → 中国港口 |

### 分析覆盖的咽喉点

马六甲海峡、苏伊士运河、霍尔木兹海峡、曼德海峡、英吉利海峡、直布罗陀海峡、博斯普鲁斯海峡、巴拿马运河、中国南海、中国东海（共 10 个）。

---

## 目录结构

```
ChinaMaritimeCode2.0/
│
├── shared/                              # 共享工具与全局配置
│   ├── config.py                       # 全局路径、常量、输出目录构建函数
│   ├── mappings.py                     # ISO 编码修正、HS→ISIC→EORA 行业分类映射
│   ├── utils.py                        # 数据加载、海运比例计算
│   ├── graph_utils.py                  # NetworkX 图构建、Dijkstra 最短路径算法
│   └── mrio_utils.py                   # EORA26 加载、A/Y/B 矩阵冲击、乘数计算
│
├── phase1_route_building/               # 阶段 1：基准航线构建
│   ├── run.py                          # 阶段 1 调度器
│   ├── step1_port_ratios.py            # 港口数据提取 + 流量比例计算
│   ├── step2_trade_sea.py              # TTD 处理 + 海运比例 + EORA 11 行业分类
│   ├── step3_flow_calc.py              # 港口对流量计算
│   ├── step4_shortest_path.py          # 海运网络 Dijkstra 最短路径
│   ├── step5_link_flow.py              # 将 11 行业贸易流量挂载到航线
│   └── step6_baci_supplement.py        # (可选) BACI 数据补充缺失国家
│
├── phase2_disruption_analysis/          # 阶段 2：咽喉点中断模拟
│   ├── run.py                          # 阶段 2 调度器
│   ├── step1_select_routes.py          # 空间相交：筛选经过咽喉点的航线
│   ├── step2_trade_stats.py            # 受影响贸易量统计（分国家、分行业）
│   ├── step3_disrupt_reroute.py        # 节点删除 + 改道路径 + L_c 计算
│   └── step4_cost_mc.py               # 改道成本 Monte Carlo 不确定性分析
│
├── phase3_io_analysis/                  # 阶段 3：MRIO 经济影响评估
│   ├── run.py                          # 阶段 3 调度器
│   ├── step1_update_port_flows.py      # 港口贸易数据与 MRIO 输入对接
│   ├── step2_port_multipliers.py       # 产出乘数 + 进口系数（前向 + 后向关联）
│   ├── step3_result_stats.py           # 按国家汇总结果，导出 GIS 数据
│   ├── step4_chokepoint_weights.py     # 按航线份额加权计算咽喉点乘数
│   ├── step5_buffer_scenarios.py       # 缓冲情景分析 (25%/50%/75%/100%)
│   ├── step5_buffer_scenarios.md       # Step 5 算法文档
│   ├── step6_buffer_scenarios_pathfrac.py  # 路径份额版缓冲情景（chokefrac 缩放）
│   ├── step6_buffer_scenarios_pathfrac.md  # Step 6 算法文档
│   ├── step6b_industry_shocks.py       # 逐行业隔离冲击分析（11 行业 × 10 咽喉点）
│   └── step6b_industry_shocks.md       # Step 6b 算法文档
│
├── phase4_trade_stats/                  # 阶段 4：贸易统计汇总
│   ├── run.py                          # 阶段 4 调度器
│   ├── helpers.py                      # 辅助函数
│   ├── step2_chokepoint_flows.py       # 要道流量统计（从 GPKG 按行业/国家聚合）
│   ├── step3_mode_stats.py             # 运输方式比例统计
│   ├── step4_country_stats.py          # 要道国家合并统计（双向合并）
│   └── step5_disruption_stats.py       # 中断断连流量统计
│
├── input/
│   └── chokepoints/                    # 10 个关键海运咽喉点 Shapefile
│
├── output/                             # 全部中间结果和最终输出
│
├── run_all.py                          # 顶层入口（Phase 1 + Phase 2）
└── README.md
```

---

## 各阶段详细说明

### 阶段 1：基准航线构建 (Phase 1: Route Building)

**目标**：构建中国双向贸易（CHN→World / World→CHN）的基准海上航线，
将 11 个 EORA 行业的贸易量（重量 + 价值）挂载到每条航线上。

**数据流**：TTD/BACI 贸易数据 → 港口流量比例 → 港口对流量 → 海运网络最短路径 → 带流量航线

| 步骤 | 脚本 | 功能 | 输出 |
|---|---|---|---|
| Step 1 | `step1_port_ratios.py` | 从 Koks 港口网络提取中国/外国港口，计算各港口在各行业的进出口流量占比 | 港口 GeoPackage + 流量比例 CSV |
| Step 2 | `step2_trade_sea.py` | 处理 TTD 数据集，计算各国对华贸易的海运比例，按 HS4→ISIC2→EORA 映射到 11 个行业 | 分国家分行业贸易 CSV |
| Step 3 | `step3_flow_calc.py` | 组合港口比例 × 国家贸易量，计算港口对之间的流量：`q_flow = q_total × q_export_ratio × q_import_ratio` | 港口对流量矩阵 |
| Step 4 | `step4_shortest_path.py` | 在 Koks 海运网络（~60k 节点）上运行 Dijkstra 最短路径算法 | 最短路径航线 GeoPackage |
| Step 5 | `step5_link_flow.py` | 将 11 行业流量 (q1–q11 重量, v1–v11 价值) 挂载到航线 geometry 上 | 带流量的航线 GeoPackage |
| Step 6 | `step6_baci_supplement.py` | (可选) 用 BACI 数据补充 TTD 中缺失国家的贸易量，含手动校正 | 补充后的贸易 CSV |

**主要输出**：

```
output/{direction}/routes/shortest_paths_{direction}_with_flows.gpkg
```

每条航线包含：geometry (LineString WGS84)、start_id/end_id、start_iso3/end_iso3、length (m)、v1–v11 (USD)、q1–q11 (kg)。

### 阶段 2：咽喉点中断模拟 (Phase 2: Disruption Analysis)

**目标**：模拟 10 个关键海运咽喉点中断，筛选受影响航线、统计贸易损失、计算改道距离与成本。

**数据流**：Phase 1 航线 + 咽喉点 SHP → 空间相交 → 受影响贸易统计 → 节点删除重新寻路 → L_c + MC 成本

| 步骤 | 脚本 | 功能 | 输出 |
|---|---|---|---|
| Step 1 | `step1_select_routes.py` | 用 Shapely 空间相交判断哪些航线经过各咽喉点 | 受影响航线 CSV（按咽喉点分文件） |
| Step 2 | `step2_trade_stats.py` | 统计经过各咽喉点的贸易量（分国家、分行业） | 贸易统计 CSV |
| Step 3 | `step3_disrupt_reroute.py` | 从 NetworkX 图中删除咽喉点节点，重新计算最短路径，得到额外距离 L_c | 改道路径 GeoPackage + L_c CSV |
| Step 4 | `step4_cost_mc.py` | 对改道成本进行 1000 次 Monte Carlo 模拟，输出 P5/P25/P50/P75/P95 分位数 | 成本分布 CSV + 行业维度成本 |

**Step 3 核心算法**：

1. 删除网络中咽喉点涉及的所有边和节点
2. 对原本经过该咽喉点的每个港口对，在残缺网络上重新 Dijkstra 寻路
3. `L_c = 新路径距离 − 原路径距离`（额外绕行距离）
4. 无法找到替代路径的记录为 "miss"（完全断连）

**主要输出**：

```
output/disruption/{direction}/
├── 01_routes_csv/{咽喉点}.csv        # 经过该咽喉点的航线列表
├── 02_trade_stats/{咽喉点}_*.csv     # 受影响贸易统计
├── 03_reroute/{咽喉点}_Lc.csv        # 改道额外距离
├── 03_reroute/{咽喉点}_reroute.gpkg  # 改道航线 GIS
├── 03_reroute/{咽喉点}_miss.csv      # 完全断连的港口对
└── 04_cost_mc/mc_samples_{咽喉点}.csv # MC 成本样本
```

### 阶段 3：MRIO 经济影响评估 (Phase 3: IO Analysis)

**目标**：利用 EORA26 多区域投入产出模型（26 国 × 11 行业 = 14,872 维），
量化咽喉点中断对全球及中国经济的产出损失。

**数据流**：Phase 1/2 输出 + EORA26 → 港口-MRIO 对接 → A/Y/B 矩阵冲击 → Backward + Forward 联系 → 产出乘数

| 步骤 | 脚本 | 功能 | 输出 |
|---|---|---|---|
| Step 1 | `step1_update_port_flows.py` | 将港口贸易数据转换为 MRIO 输入格式（v_share_trade） | 港口-行业流量矩阵 |
| Step 2 | `step2_port_multipliers.py` | 逐港口计算产出乘数和进口系数（修改 A/Y/B 矩阵 → Leontief 逆 → ΔOutput） | 乘数 CSV |
| Step 3 | `step3_result_stats.py` | 按国家汇总乘数，导出 GIS GeoPackage | 国家级结果 CSV + GeoPackage |
| Step 4 | `step4_chokepoint_weights.py` | 按航线贸易份额加权，计算咽喉点级综合乘数 | 加权乘数 CSV |
| Step 5 | `step5_buffer_scenarios.py` | 缓冲情景分析：区分"有/无替代路线"国家，25%~100% 四档中断 | 情景结果长表/宽表 |
| Step 6 | `step6_buffer_scenarios_pathfrac.py` | 路径份额版缓冲情景：用 GPKG 物理路径计算 chokefrac 精确区分要道 | 情景结果长表/宽表 |
| Step 6b | `step6b_industry_shocks.py` | 逐行业隔离冲击：11 个行业分别中断，计算行业级乘数 | 行业冲击长表/宽表 |

**MRIO 冲击方法**：

```
对每个港口/要道:
  # Backward 联系（需求侧）
  A_mod = A_orig × (1 − v_share_trade)     # 中间投入减少
  Y_mod = Y_orig × (1 − v_share_trade)     # 最终需求减少
  L_mod = (I − A_mod)^{−1}                 # 重算 Leontief 逆
  ΔBW = (L_orig @ Y_orig − L_mod @ Y_mod)  # 后向产出损失

  # Forward 联系（供给侧，Ghosian 模型）
  B_mod = B_orig × (1 − v_share_trade)     # 分配系数减少
  ΔFW = v @ (I − B_orig)^{−1} − v @ (I − B_mod)^{−1}

  # 汇总
  Dind_total = ΔBW + ΔFW                   # 全球产出损失
  multiplier = Dind_total / trade_shock      # 产出损失乘数
```

**Step 5 → 6 → 6b 的演进关系**：

| 维度 | Step 5 | Step 6 | Step 6b |
|---|---|---|---|
| 流量筛选 | 港口 ID 匹配 | chokefrac 路径份额缩放 | 同 Step 6 |
| 行业粒度 | 11 行业同时中断 | 11 行业同时中断 | **逐行业隔离冲击** |
| 要道区分度 | 低（各要道高度重叠） | 高（精确到物理路径） | 同 Step 6 |
| MRIO 次数/方向 | 40 | 40 | **440**（×11 行业） |
| 输出目录 | `buffer/` | `buffer_pathfrac/` | `industry_shocks/` |

详细算法文档见：
- [step5_buffer_scenarios.md](phase3_io_analysis/step5_buffer_scenarios.md)
- [step6_buffer_scenarios_pathfrac.md](phase3_io_analysis/step6_buffer_scenarios_pathfrac.md)
- [step6b_industry_shocks.md](phase3_io_analysis/step6b_industry_shocks.md)

**主要输出**：

```
output/mrio/{direction}/
├── input/{direction}_ports_updated.csv           # MRIO 输入
├── multipliers/output_multiplier.csv             # 港口级乘数
├── buffer/{direction}_buffer_results.csv         # Step 5 缓冲情景
├── buffer_pathfrac/{direction}_buffer_results.csv # Step 6 路径份额版
└── industry_shocks/{direction}_industry_shocks.csv # Step 6b 行业级
```

### 阶段 4：贸易统计汇总 (Phase 4: Trade Statistics)

**目标**：从 Phase 1/2 输出中聚合贸易统计数据，供下游可视化和分析使用。

| 步骤 | 脚本 | 功能 | 输出 |
|---|---|---|---|
| Step 2 | `step2_chokepoint_flows.py` | 从 Phase 1 GPKG 读取并按行业/国家聚合各咽喉点流量 | 咽喉点流量 CSV |
| Step 3 | `step3_mode_stats.py` | 统计海运/空运/陆运比例及各咽喉点的海运份额 | 运输方式比例 CSV |
| Step 4 | `step4_country_stats.py` | 合并 CHN2World + World2CHN 双向，生成国家级咽喉点统计 | 合并统计 CSV |
| Step 5 | `step5_disruption_stats.py` | 统计 Phase 2 中完全断连 (Complete_miss) 的流量，含路径级分母 | 断连统计 CSV |

> Phase 4 独立于主管线（不在 `run_all.py` 中），需单独运行。Step 1 已废弃。

**主要输出**：

```
output/trade_stats/
├── chokepoint_flows/{direction}/{咽喉点}_by_country.csv
├── chokepoint_flows/{direction}/{咽喉点}_by_sector.csv
├── mode_stats/transport_mode_ratios.csv
├── country_combined/{咽喉点}_combined.csv
└── disruption/{direction}/{咽喉点}_miss_iso3.csv
```

---

## 运行方式

### 环境依赖

```
pandas, numpy, scipy
geopandas, shapely
networkx
geopy
openpyxl
tqdm
```

Phase 3 额外依赖 EORA26 数据库（需在 `shared/config.py` 中配置 `EORA_PATH`）。

### 运行全部流程

```bash
# Phase 1 + Phase 2（完整管线）
python run_all.py

# Phase 1 包含 BACI 补充
python run_all.py --with-baci

# 只运行 Phase 1
python run_all.py --phase 1

# 只运行 Phase 2
python run_all.py --phase 2

# Phase 1 指定方向 + 步骤
python run_all.py --phase 1 --step 4 --direction CHN2World
```

### 分阶段运行

```bash
# Phase 3：MRIO 经济影响（跳过耗时的缓冲情景）
python phase3_io_analysis/run.py --skip-buffer

# Phase 3：完整流程（含 Step 5 缓冲情景）
python phase3_io_analysis/run.py

# Phase 3：Step 6 路径份额版缓冲情景
python phase3_io_analysis/run.py --step 6

# Phase 3：Step 6b 逐行业隔离冲击
python phase3_io_analysis/step6b_industry_shocks.py

# Phase 4：贸易统计
python phase4_trade_stats/run.py

# Phase 4：只运行某一步骤
python phase4_trade_stats/run.py --step 2 --direction CHN2World
```

---

## 输入数据要求

在 `shared/config.py` 中配置以下数据路径：

| 数据 | 配置键 | 说明 |
|---|---|---|
| Koks 港口贸易网络 | `port_trade_network` | 全球港口间贸易矩阵（港口对 × 行业） |
| 港口位置 | `ports_shp` | 全球港口点矢量 (Koks) |
| 海运网络 | `maritime_network` | 全球海运边矢量 (Koks)，~60k 节点 |
| 海运网络节点 | `nodes_maritime` | 含 infra 字段的节点 GeoPackage |
| TTD | `ttd` | Trade & Transport Dataset (2019)，含运输方式 |
| BACI | `baci` | BACI HS17 贸易数据 (2019)，可选补充用 |
| ISO 映射 | `iso3_map` | ISO 数字编码 ↔ ISO3 字母编码 |
| 国家属性 | `iso3_with_region` | 国家名称、区域、收入组 |
| 行业映射 | `hs4_isic2_map` | HS4 → ISIC Rev.2 映射表 |
| EORA 行业标签 | `eora_categories` | EORA 11 大类行业中英文名称 |
| EORA26 数据库 | `EORA_PATH` | EORA26 (2019) 基本价格表目录 |
| 咽喉点 SHP | `CHOKEPOINTS_DIR` | `input/chokepoints/` 下 10 个咽喉点 Shapefile |
| 全球国家边界 | `GLOBAL_COUNTRY_SHP` | 用于 Phase 3 GIS 关联 |

### 关键常量

| 常量 | 值 | 说明 |
|---|---|---|
| `CHN_ISO3` | `"CHN"` | 中国 ISO3 编码 |
| `YEAR` | `2019` | 数据年份 |
| `GRAPH_SNAP_DISTANCE_M` | `100,000` m | 港口吸附到图节点的最大距离 |
| `SEA_V_DEFAULT_RATIO` | `0.7` | 海运价值比例默认填充值 |
| `SEA_Q_DEFAULT_RATIO` | `0.8` | 海运重量比例默认填充值 |
| `DETOUR_THRESHOLD` | `1.5` | 替代路线判定阈值（≤1.5x 原距离算有替代） |
| `SCENARIOS` | `[1.0, 0.75, 0.5, 0.25]` | 缓冲情景中断比例 |

---

## 输出数据字段说明

### 航线表（Phase 1 GPKG）

| 字段 | 类型 | 说明 |
|---|---|---|
| `geometry` | LineString | WGS84 航线几何 |
| `start_id` / `end_id` | str | 起止港口 ID (Koks 编码) |
| `start_iso3` / `end_iso3` | str | 起止国家 ISO3 |
| `length` | float | 航线距离 (m) |
| `v1`–`v11` | float | 分行业价值流量 (USD) |
| `q1`–`q11` | float | 分行业重量流量 (kg) |

### 改道距离表（Phase 2 L_c）

| 字段 | 类型 | 说明 |
|---|---|---|
| `start_id` / `end_id` | str | 港口对 |
| `original_length` | float | 原航线距离 (m) |
| `reroute_length` | float | 改道航线距离 (m) |
| `L_c` | float | 额外绕行距离 (m) = reroute − original |

### 产出乘数表（Phase 3）

| 字段 | 类型 | 说明 |
|---|---|---|
| `port_id` / `iso3` | str | 港口/国家标识 |
| `multiplier` | float | 总产出乘数 |
| `multiplier_dom` / `multiplier_row` | float | 国内/其余世界乘数 |
| `Dind_total` | float | 全球绝对产出损失 (USD) |
| `Dind_chn` / `Dind_row` | float | 中国/其余国家产出损失 |
| `Dind_total_bw` / `Dind_total_fw` | float | 后向/前向分解 |

### 缓冲情景表（Phase 3 Step 5/6）

| 字段 | 类型 | 说明 |
|---|---|---|
| `chokepoint` | str | 咽喉点名称 |
| `scenario` | float | 中断比例 (0.25–1.0) |
| `no_alt_frac` | float | 无替代路线贸易占比 |
| `trade_total_S` | float | 当前情景贸易损失 (USD) |
| `multiplier_B` | float | 主乘数（分母固定为 100% 基准） |
| `multiplier_A` | float | 参考乘数（分母随情景变化） |
| `multiplier_A_chn` / `multiplier_A_row` | float | 中国/其余国家 multiplier_A |

### 行业冲击表（Phase 3 Step 6b）

在缓冲情景表基础上增加：

| 字段 | 类型 | 说明 |
|---|---|---|
| `industry` | int | EORA 行业编号 (1–11) |
| `industry_name` | str | 行业英文名称 |
| `ind_trade_100` | float | 该行业 100% 基准贸易量 |

---

## EORA 11 行业分类

| 编号 | 英文名称 | 中文 |
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

## 运行时间参考

| 阶段 | 步骤 | 耗时 | 说明 |
|---|---|---|---|
| Phase 1 | Step 4 (最短路径) | ~30–60 min | Dijkstra 遍历 ~60k 节点网络 |
| Phase 2 | Step 3 (10 咽喉点改道) | ~1–3 hours | 每咽喉点需重建残缺图 + 重寻路 |
| Phase 3 | Step 2 (MRIO 乘数) | ~1–2 hours/方向 | 逐港口 Leontief 逆 |
| Phase 3 | Step 5 (缓冲情景) | ~2–4 hours/方向 | 40 次 MRIO |
| Phase 3 | Step 6 (路径份额版) | ~2–4 hours/方向 | 40 次 MRIO + GPKG 空间相交 |
| Phase 3 | Step 6b (行业冲击) | ~20–40 hours/方向 | 440 次 MRIO（×11 行业） |

**性能优化**：
- EORA 数据在 `run.py` 中一次性加载后传递给各步骤
- Leontief 逆矩阵 `L_orig = (I−A0)^{−1}` 在循环外预计算
- Forward 联系的 `v_ndarray = x(I−B0)` 在 EORA 加载时预计算
- V_all（全量路径流量）在要道循环外一次性聚合

---

## 输出目录结构

```
output/
├── CHN2World/
│   ├── routes/shortest_paths_CHN2World_with_flows.gpkg
│   ├── flow/{ISO3}_{sector}.csv
│   └── ports/{ISO3}/{ISO3}_{sector}.csv
├── World2CHN/
│   └── (同上)
│
├── disruption/
│   ├── CHN2World/
│   │   ├── 01_routes_csv/{咽喉点}.csv
│   │   ├── 02_trade_stats/{咽喉点}_by_country.csv, _by_sector.csv
│   │   ├── 03_reroute/{咽喉点}_Lc.csv, _reroute.gpkg, _miss.csv
│   │   └── 04_cost_mc/mc_samples_{咽喉点}.csv, route_uncertainty_{咽喉点}.csv
│   └── World2CHN/
│       └── (同上)
│
├── mrio/
│   ├── CHN2World/
│   │   ├── input/CHN2World_ports_updated.csv
│   │   ├── multipliers/output_multiplier.csv, import_coef_sector.csv
│   │   ├── buffer/CHN2World_buffer_results.csv
│   │   ├── buffer_pathfrac/CHN2World_buffer_results.csv
│   │   └── industry_shocks/CHN2World_industry_shocks.csv
│   └── World2CHN/
│       └── (同上)
│
└── trade_stats/
    ├── chokepoint_flows/{direction}/{咽喉点}_by_country.csv, _by_sector.csv
    ├── mode_stats/transport_mode_ratios.csv, chokepoint_shares.csv
    ├── country_combined/{咽喉点}_combined.csv
    └── disruption/{direction}/{咽喉点}_miss_iso3.csv, _miss_sector.csv
```
