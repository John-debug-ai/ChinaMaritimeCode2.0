ChinaMaritimeCode2.0
中国海上贸易网络脆弱性分析——关键航运咽喉点中断的经济影响评估

China's maritime trade network vulnerability analysis — Economic impact assessment of critical shipping chokepoint disruptions.

项目概述 / Overview
本项目构建了一个完整的四阶段分析流水线，用于：

构建中国进出口海上贸易路径网络
模拟关键海峡/咽喉点中断后的航线改道
基于 EORA26 多区域投入产出 (MRIO) 模型量化经济影响
汇总贸易统计
核心研究问题：当马六甲海峡、苏伊士运河等关键海运通道被中断时，全球贸易将如何改道？改道距离和经济损失有多大？

目录结构 / Directory Structure
ChinaMaritimeCode2.0/
├── shared/                          # 共享工具与配置
│   ├── config.py                   # 全局路径、常量、输出目录构建
│   ├── mappings.py                 # ISO 修正、行业分类映射
│   ├── utils.py                    # 数据加载、海运比例计算
│   ├── graph_utils.py              # 图构建、最短路径算法
│   └── mrio_utils.py               # MRIO 矩阵修改、乘数计算
│
├── phase1_route_building/           # 阶段1：基准航线构建
│   ├── run.py                      # 阶段1 调度器
│   ├── step1_port_ratios.py        # 港口数据提取 + 流量比例
│   ├── step2_trade_sea.py          # TTD 处理 + 海运比例 + 行业分类
│   ├── step3_flow_calc.py          # 港口对流量计算
│   ├── step4_shortest_path.py      # 海运网络 Dijkstra 最短路径
│   ├── step5_link_flow.py          # 将贸易流量挂载到航线上
│   └── step6_baci_supplement.py    # (可选) BACI 数据补充与修正
│
├── phase2_disruption_analysis/      # 阶段2：咽喉点中断模拟
│   ├── run.py                      # 阶段2 调度器
│   ├── step1_select_routes.py      # 空间相交：筛选经过咽喉点的航线
│   ├── step2_trade_stats.py        # 受影响贸易量统计（分国家、分行业）
│   ├── step3_disrupt_reroute.py    # 节点删除 + 改道路径 + L_c 计算
│   └── step4_cost_mc.py            # 改道成本 Monte Carlo 不确定性分析
│
├── phase3_io_analysis/              # 阶段3：MRIO 经济影响评估
│   ├── run.py                      # 阶段3 调度器
│   ├── step1_update_port_flows.py  # 港口数据与 MRIO 输入合并
│   ├── step2_port_multipliers.py   # 产出乘数、进口系数计算
│   ├── step3_result_stats.py       # 结果汇总 + GIS 导出
│   ├── step4_chokepoint_weights.py # 咽喉点加权乘数
│   ├── step5_buffer_scenarios.py   # 缓冲情景分析 (25%/50%/75%/100%)
│   └── step5_buffer_scenarios.md   # 缓冲情景算法文档
│
├── phase4_trade_stats/              # 阶段4：贸易统计汇总
│
├── input/
│   └── chokepoints/                # 13 个关键海运咽喉点 Shapefile
│
├── output/                         # 全部中间结果和最终输出
│
├── run_all.py                      # 总入口
└── README.md
运行方式 / How to Run
环境依赖 / Dependencies
pandas, numpy
geopandas, shapely
networkx, scipy
geopy
pymrio
openpyxl
tqdm
argparse
运行全部流程
python run_all.py
分阶段运行
# 阶段1：航线构建（含 BACI 补充）
python phase1_route_building/run.py --with-baci

# 阶段1：仅运行某一步
python phase1_route_building/run.py --step 4 --direction CHN2World

# 阶段2：中断分析
python phase2_disruption_analysis/run.py

# 阶段3：MRIO 经济影响（跳过耗时的缓冲情景）
python phase3_io_analysis/run.py --skip-buffer

# 阶段3：仅运行缓冲情景
python phase3_io_analysis/run.py --step 5 --direction World2CHN

各阶段详细说明 / Phase Details
阶段1：基准航线构建 (Phase 1: Route Building)
目标：构建中国双向贸易（CHN→World / World→CHN）的基准海上航线。

步骤	脚本	功能	输出
Step 1	step1_port_ratios.py	提取港口数据，计算各港口在各行业的进出口流量占比	港口 GeoPackage + 流量比例 CSV
Step 2	step2_trade_sea.py	处理 TTD 数据，计算海运比例，按 EORA 11 行业分类	分国家分行业贸易 CSV
Step 3	step3_flow_calc.py	计算港口对之间的流量：q_flow = q_total × q_export_ratio × q_import_ratio	港口对流量矩阵
Step 4	step4_shortest_path.py	在海运网络上运行 Dijkstra 最短路径算法	最短路径航线 GeoPackage
Step 5	step5_link_flow.py	将 11 行业流量 (q1–q11, v1–v11) 挂载到航线	带流量的航线 GeoPackage
Step 6	step6_baci_supplement.py	(可选) 用 BACI 数据补充 TTD 中缺失的国家	补充后的贸易 CSV
主要输出：output/{direction}/routes/shortest_paths_{direction}_with_flows.gpkg

阶段2：咽喉点中断模拟 (Phase 2: Disruption Analysis)
目标：模拟 13 个关键海运咽喉点中断，计算改道距离。

步骤	脚本	功能	输出
Step 1	step1_select_routes.py	空间相交，筛选经过各咽喉点的航线	受影响航线 CSV
Step 2	step2_trade_stats.py	统计经过各咽喉点的贸易量（分国家、分行业）	贸易统计 CSV
Step 3	step3_disrupt_reroute.py	从网络中删除咽喉点节点，重新计算最短路径，得到 L_c（额外距离）	改道路径 GeoPackage + L_c CSV
Step 4	step4_cost_mc.py	对改道成本进行 Monte Carlo 模拟	成本分布
核心算法 (Step 3)：

删除网络中咽喉点涉及的所有边
对原本经过该咽喉点的每个港口对，在残缺网络上重新寻路
L_c = 新路径距离 − 原路径距离
无法找到替代路径的流量记录为 "miss"
主要输出：output/disruption/{direction}/03_reroute/{chokepoint}_Lc.csv

阶段3：MRIO 经济影响评估 (Phase 3: IO Analysis)
目标：利用 EORA26 投入产出模型量化中断对全球经济的影响。

步骤	脚本	功能	输出
Step 1	step1_update_port_flows.py	将港口贸易数据与 MRIO 输入对接	港口-行业流量矩阵
Step 2	step2_port_multipliers.py	计算产出乘数和进口系数（前向+后向关联）	乘数 CSV
Step 3	step3_result_stats.py	按国家汇总结果，导出 GIS 数据	国家级结果 CSV + GeoPackage
Step 4	step4_chokepoint_weights.py	按航线份额加权计算咽喉点乘数	加权乘数 CSV
Step 5	step5_buffer_scenarios.py	缓冲情景分析 (25%/50%/75%/100% 中断)	情景结果宽表/长表 CSV
产出乘数计算方法 (Step 2)：

对每个港口:
  A_mod = A_orig × (1 − v_share_trade)     # 中间投入冲击
  Y_mod = Y_orig × (1 − v_share_trade)     # 最终需求冲击
  后向: ΔBW = (L_mod − L_orig) @ Y_orig
  前向: ΔFW = v(I − B_mod)^{-1} − x_orig
  multiplier = (ΔBW + ΔFW) / trade_value
主要输出：

output/mrio/{direction}/multipliers/output_multiplier.csv
output/mrio/{direction}/buffer/{direction}_buffer_results.csv
输入数据要求 / Input Data Requirements
在 shared/config.py 中配置以下数据路径：

数据	说明
port_trade_network	Koks 全球港口间贸易矩阵
ports_shp	全球港口位置 (点要素)
maritime_network	全球海运网络 (线要素)
ttd	Trade & Transport Dataset (2019)
baci	BACI 贸易数据 (HS17, 2019, 可选)
iso3_map	ISO 数字 ↔ ISO3 对照表
iso3_with_region	国家属性 (区域、收入组)
hs4_isic2_map	HS4 → ISIC2 产品分类映射
eora_categories	EORA 11 行业标签
EORA26 数据库	EORA_PATH 指向 EORA26 (2019) 基本价格表
咽喉点 Shapefile	input/chokepoints/ 下 13 个咽喉点
关键常量：

CHN_ISO3 = "CHN", YEAR = 2019
GRAPH_SNAP_DISTANCE_M = 100,000 m — 港口吸附到图节点的容差
SEA_V_DEFAULT_RATIO = 0.7 — 海运价值比例默认填充值
SEA_Q_DEFAULT_RATIO = 0.8 — 海运重量比例默认填充值
输出数据字段说明 / Output Data Dictionary
流量表字段：

export_port, import_port — 港口 ID
from_iso3, to_iso3 — 起止国家
sector — EORA 行业 (1–11)
q_flow, v_flow — 海运量 (kg) 和价值 (USD)
航线表字段：

geometry — LineString (WGS84)
start_id, end_id — 起止港口 ID
length — 航线距离 (m)
q1–q11, v1–v11 — 分行业流量
乘数表字段：

port_id, iso3, name — 港口标识
multiplier — 总产出乘数
multiplier_dom — 国内乘数
multiplier_row — 其余世界乘数
Dind_total, Dind_chn, Dind_row — 绝对产出损失 (USD)
Dind_total_bw, Dind_total_fw — 后向/前向分解
运行时间参考 / Performance Notes
阶段	耗时
Phase 1 Step 4 (最短路径)	~30–60 min
Phase 2 Step 3 (13 咽喉点改道)	~1–3 hours
Phase 3 Step 2 (MRIO 乘数)	~1–2 hours/方向
Phase 3 Step 5 (缓冲情景)	~2–4 hours/方向
优化说明：EORA 数据在 run.py 中一次性加载后传递给各步骤；Leontief 逆矩阵预计算；calc_shortest_paths_pairs() 针对稀疏港口对进行了优化。

输出示例 / Example Output Structure
output/
├── CHN2World/
│   ├── routes/shortest_paths_CHN2World_with_flows.gpkg
│   ├── flow/USA_01.csv, DEU_02.csv, ...
│   └── ports/{ISO3}/{ISO3}_01.csv, ...
├── World2CHN/
│   └── ...
├── disruption/
│   ├── CHN2World/
│   │   ├── 01_routes_csv/马六甲.csv, 霍尔木兹.csv, ...
│   │   ├── 02_trade_stats/马六甲_分国家.csv, ...
│   │   └── 03_reroute/马六甲_Lc.csv, 马六甲_reroute.gpkg
│   └── World2CHN/...
└── mrio/
    ├── CHN2World/
    │   ├── input/CHN2World_ports_updated.csv
    │   ├── multipliers/output_multiplier.csv
    │   └── buffer/CHN2World_buffer_results.csv
    └── World2CHN/...
