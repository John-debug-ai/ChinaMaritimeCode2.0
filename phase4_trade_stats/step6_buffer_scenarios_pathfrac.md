# Phase 3 / Step 6：路径份额缩放版缓冲情景 MRIO 分析 — 算法文档

> 对应代码：`phase3_io_analysis/step6_buffer_scenarios_pathfrac.py`

---

## 1. 研究目的

回答以下问题：

> **如果某个海运要道发生 25%/50%/75%/100% 的贸易中断，
> 实际"物理上经过该要道的贸易"会对全球和中国的产出造成多大影响？**

### 与 Step 5 的区别

Step 5 使用 `ports_updated.csv` 的港口级聚合（`id.isin(要道港口列表)`）筛选经过要道的流量。
这一方法存在致命缺陷：对 CHN2World 方向，中国大型出口港全球通达，
"经过任意要道的中国港口集合"在不同要道间几乎完全重合，
导致各要道得到**几乎相同的** `trade_total` / `Dind` / `multiplier_B`。

Step 6 引入 **路径份额 chokefrac** 机制：利用 Phase 1 GPKG 中的逐路径物理流量数据，
为每个 `(iso3_O, iso3_D, Industries)` 组合精确计算经过特定要道的流量占比，
再用该比例缩放 `v_share_trade`。这使得 MRIO 冲击精确对应"实际经过此要道的贸易"，
各要道的乘数真正体现其地理位置的差异性。

---

## 2. 输入与输出

### 2.1 输入文件

| 文件 | 来源 | 用途 |
|---|---|---|
| `output/{direction}/routes/shortest_paths_{direction}_with_flows.gpkg` | Phase 1 Step 5 | 全量路线（含 geometry + v1..v11 行业 USD 流量） |
| `output/mrio/{direction}/input/{direction}_ports_updated.csv` | Phase 3 Step 1 | 港口×行业的贸易流量与份额 (`v_share_trade`) |
| `data/chokepoints/*.shp` | 外部数据 | 10 个海运要道的地理点位 |
| EORA26 (2019) | 外部数据库 | 全球 MRIO 系统的 A、Y、Z、x 矩阵 |

### 2.2 输出文件

`output/mrio/{direction}/buffer_pathfrac/`

| 文件 | 形态 | 内容 |
|---|---|---|
| `{direction}_buffer_results.csv` | **长表**：每要道 × 每情景一行 | 全部输出指标 |
| `{direction}_宽表汇总.xlsx` | **宽表**：每要道一行，4 个情景横向并列 | 便于跨情景横向对比 |

### 2.3 输出指标

| 字段 | 含义 |
|---|---|
| `V_choke_total` | 该要道在所有 (O,D,Industries) 上的 USD 流量之和 |
| `V_all_total` | 同 (O,D,Industries) 覆盖范围内的全量 USD（仅参与 V_choke>0 的子集） |
| `frac_avg` | v_share_trade 加权的全局平均 chokefrac |
| `no_alt_frac` | 无替代路线贸易占该要道 100% 基准贸易的比例 |
| `trade_total_100` | 100% 中断下的基准贸易损失 — 多情景共用分母 |
| `trade_total_S` | 当前情景实际贸易损失 |
| `Dind_total` | 全球绝对产出损失（USD），= Backward + Forward |
| `Dind_chn` / `Dind_row` | 中国 / 其他国家产出损失 |
| `Dind_total_bw` / `Dind_total_fw` | Backward / Forward 联系拆分 |
| `multiplier_B` | 主乘数 = Dind_total / trade_total_100（分母固定） |
| `multiplier_A` | 参考乘数 = Dind_total / trade_total_S（分母随情景变） |
| `multiplier_A_chn` / `multiplier_A_row` | 中国 / 其他国家的 multiplier_A 拆分 |

---

## 3. 核心概念：路径份额 chokefrac

### 3.1 定义

对每个 `(iso3_O, iso3_D, Industries)` 组合：

```
chokefrac = V_choke / V_all
```

其中：
- **V_all** = 全量 GPKG 中该 (O, D, Ind) 的路径级 USD 流量之和
- **V_choke** = 仅经过特定要道的路径子集对应的 USD 流量之和

chokefrac 的值域 [0, 1]，含义为"该国家对到该行业的贸易中，物理上经过此要道的比例"。

### 3.2 为什么需要 chokefrac

以 CHN2World 方向为例：

| 步骤 | Step 5 做法 | Step 6 做法 |
|---|---|---|
| 筛选流量 | `ports_exp["id"].isin(要道港口)` | 空间相交 → chokefrac 逐 (O,D,Ind) 缩放 |
| 结果 | 马六甲和苏伊士的贸易集合几乎相同 | 马六甲偏东南亚，苏伊士偏欧洲/中东 |
| 乘数差异 | 各要道 multiplier 几乎一样 | 各要道体现地理差异 |

---

## 4. 算法整体流程

```
对每个方向 (CHN2World / World2CHN)：
│
├── 加载 EORA → 预计算 Leontief 逆 L_orig = (I − A0)^{−1}
│
├── 加载全量路线 GPKG（含 geometry + v1..v11）
├── 一次性聚合 V_all（全量 O×D×Industries USD 流量）
├── 加载 ports_updated.csv，仅保留 flow == "port_export"
│
└── 对每个要道 SHP：
    │
    ├── 步骤 ①  空间相交：全量路线 geometry × 要道点
    │            → choke_routes_geo（经过该要道的路径子集）
    │
    ├── 步骤 ②  替代路线判断（复用 step5 的 compute_alt_status）
    │            → alt_status = {iso3: True/False}, no_alt_set
    │
    ├── 步骤 ③  计算 chokefrac：
    │            V_choke = 要道路径子集按 (O,D,Ind) 汇总 USD
    │            chokefrac = V_choke / V_all，clip 到 [0, 1]
    │
    ├── 步骤 ④  缩放 ports_exp.v_share_trade：
    │            v_share_trade_new = v_share_trade × chokefrac(O, D, Ind)
    │            → 按 (O, D, Ind) 聚合得 all_flows_100
    │
    └── 对每个情景 s ∈ {0.25, 0.50, 0.75, 1.00}：
        │
        ├── 步骤 ⑤  情景缩放（复用 step5 的 run_scenario）：
        │            有替代国家：v_share_trade × s
        │            无替代国家：保持 100% 中断
        │
        ├── 步骤 ⑥  Backward 联系（A 冲击 + Y 冲击）
        ├── 步骤 ⑦  Forward 联系（B 冲击 + C 冲击）
        └── 步骤 ⑧  汇总乘数 → 写入 all_results
```

---

## 5. 关键算法详解

### 5.1 空间相交（步骤 ①）

```python
# 加载要道地理点
points = gpd.read_file("chokepoints/马六甲海峡.shp")

# GPKG 路线 geometry 与要道点做相交判断
choke_routes_geo = full_routes_geo[
    full_routes_geo.geometry.intersects(points.union_all())
]
```

相交判断在 GPKG 的 LineString 几何上进行（Phase 1 Step 5 输出的最短路径），
这确保筛选的是真正在物理上经过该要道的航线，而非"端点港口曾出现在该要道列表"的航线。

### 5.2 路径份额计算（步骤 ③）

```
1. melt：GPKG 的 v1..v11 → 长表 (iso3_O, iso3_D, Industries, v_usd)
         两个方向均有 start_iso3 → iso3_O，end_iso3 → iso3_D
2. V_all  = 全量路线按 (O, D, Ind) 聚合的 USD 总流量
3. V_choke = 要道路径子集按 (O, D, Ind) 聚合的 USD 流量
4. chokefrac = V_choke / V_all，缺失填 0，clip [0, 1]
```

### 5.3 两层冲击逻辑叠加

Step 6 的冲击是三层缩放的复合：

| 层 | 机制 | 作用域 |
|---|---|---|
| **chokefrac 层**（物理） | (O,D,Ind) 贸易中物理上经过该要道的比例 | 逐 (O,D,Ind) |
| **alt_status 层**（可替代） | 经过该要道的国家是否有替代路线（含 1.5x 距离阈值） | 逐国家 |
| **scenario 层**（情景） | 有替代国家按 s% 缩放，无替代国家保持 100% 中断 | 逐情景 |

最终有效冲击率 = `chokefrac × (has_alt ? scenario : 1.0)`

### 5.4 MRIO 计算

Backward / Forward 联系的 MRIO 计算与 Step 5 完全相同（通过 `import run_scenario` 复用），
详见 [step5_buffer_scenarios.md](step5_buffer_scenarios.md) 第 4.4–4.6 节。

---

## 6. 诊断输出

每个要道的日志和结果中包含 chokefrac 诊断信息：

| 指标 | 含义 | 用途 |
|---|---|---|
| `V_choke_total` | 该要道截获的 USD 流量总和 | 评估要道的贸易量级 |
| `V_all_total` | 对应 (O,D,Ind) 子集的全量 USD | V_choke 的参照总量 |
| `frac_avg` | v_share_trade 加权的全局平均 chokefrac | 快速判断要道的"拦截率" |

典型值：马六甲 frac_avg ≈ 0.3–0.5（亚洲方向贸易大部分经过），
直布罗陀 frac_avg ≈ 0.05–0.15（仅地中海沿岸贸易经过）。

---

## 7. 与 Step 5 的异同总结

| 维度 | Step 5 | Step 6 |
|---|---|---|
| 流量筛选 | 港口 ID 匹配（`id.isin`） | 空间相交 + chokefrac 缩放 |
| 要道区分度 | 低（各要道流量高度重叠） | 高（精确到路径级物理经过） |
| 替代路线判断 | compute_alt_status（国家级） | 相同（复用 step5） |
| MRIO 计算 | run_scenario | 相同（复用 step5） |
| 输出目录 | `buffer/` | `buffer_pathfrac/` |
| 计算量 | 10 要道 × 4 情景 = 40 次 | 相同 |

---

## 8. 性能优化点

| 优化 | 描述 | 收益 |
|---|---|---|
| V_all 一次计算 | 全量 (O,D,Ind) 汇总在要道循环外完成 | 避免 10 次全量 melt + groupby |
| L_orig 预计算 | `(I−A0)^{−1}` 在循环外算一次 | 每个情景节省一次 14000² 矩阵求逆 |
| EORA 加载缓存 | `load_eora_once()` 两方向共用 | 节省 1–2 分钟 |
| 复用 step5 | alt_status / run_scenario 直接 import | 零冗余代码 |

---

## 9. 已知限制与简化

| 项 | 简化方式 | 影响 |
|---|---|---|
| 空间相交精度 | 使用 `intersects`（接触即算经过） | GPKG 路径如果仅擦过要道缓冲区也会被计入 |
| chokefrac 上限 | clip 到 1.0 | 路径重复或浮点误差导致 >1 时截断 |
| chokefrac 缺失填 0 | V_all 中存在但 V_choke 中缺失的 (O,D,Ind) 填 0 | 假设不在空间相交结果中 = 不经过该要道 |
| 替代路线判断粒度 | 国家级（同 step5） | 同 step5 的局限性 |
| 情景缩放 | 线性（同 step5） | 真实贸易反应可能非线性 |

---

## 10. 调用方式

```bash
# 通过 run.py（推荐）
python phase3_io_analysis/run.py --step 6

# 只跑一个方向
python phase3_io_analysis/run.py --step 6 --direction World2CHN

# 直接运行（两个方向）
python phase3_io_analysis/step6_buffer_scenarios_pathfrac.py
```

> **注意**：Step 6 不在 `run_full` 默认流程中，需用 `--step 6` 显式指定。
> 计算量与 Step 5 相同（10 要道 × 4 情景 = 40 次 MRIO），耗时约数十分钟。
