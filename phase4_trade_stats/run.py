"""
phase4_trade_stats/run.py — Phase 4 贸易统计分析入口

步骤说明：
  step1: 基础贸易统计表（TTD + BACI 补充 + 海运修正）
  step2: 要道流量统计（从 Phase 1 GPKG 读取，按行业/国家聚合）
  step3: 运输方式比例统计（总体比例 + 要道份额）
  step4: 要道国家合并统计（CHN2World + World2CHN 双向合并）
  step5: 中断断连流量统计（读取 Phase 2 miss CSV，聚合 + 比例）

注意：
  - 本模块独立于主管线，不在 run_all.py 中执行
  - step2 依赖 Phase 1 GPKG（最短路径带流量文件）
  - step5 依赖 Phase 2 step3 生成的 _miss.csv
  - step3/step4 依赖 step1/step2 输出

用法示例：
  # 完整流程（两个方向）
  python phase4_trade_stats/run.py

  # 只运行某一步骤
  python phase4_trade_stats/run.py --step 2

  # 只运行某一方向（step1/2/5 支持方向参数；step3/4 合并两方向，不区分）
  python phase4_trade_stats/run.py --step 1 --direction CHN2World

  # step3/step4 不需要方向参数
  python phase4_trade_stats/run.py --step 3
"""

import argparse
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from phase4_trade_stats import (  # noqa: E402
    step1_base_tables,
    step2_chokepoint_flows,
    step3_mode_stats,
    step4_country_stats,
    step5_disruption_stats,
)

DIRECTIONS = ["CHN2World", "World2CHN"]


def _header(title: str) -> None:
    print(f"\n{'=' * 65}")
    print(f"  {title}")
    print("=" * 65)


def run_full(directions: list[str] | None = None) -> None:
    """执行 Phase 4 完整流程。"""
    if directions is None:
        directions = DIRECTIONS

    _header("P4 Step 1: 基础贸易统计表")
    for d in directions:
        step1_base_tables.run(d)

    _header("P4 Step 2: 要道流量统计")
    for d in directions:
        step2_chokepoint_flows.run(d)

    _header("P4 Step 3: 运输方式比例统计")
    step3_mode_stats.run()

    _header("P4 Step 4: 要道国家合并统计")
    step4_country_stats.run()

    _header("P4 Step 5: 中断断连流量统计")
    for d in directions:
        step5_disruption_stats.run(d)

    print("\n✅ Phase 4 全部步骤完成！")


def run_single_step(step: int, directions: list[str]) -> None:
    """只运行指定步骤。"""
    if step == 1:
        for d in directions:
            step1_base_tables.run(d)

    elif step == 2:
        for d in directions:
            step2_chokepoint_flows.run(d)

    elif step == 3:
        step3_mode_stats.run()

    elif step == 4:
        step4_country_stats.run()

    elif step == 5:
        for d in directions:
            step5_disruption_stats.run(d)

    else:
        print(f"无效步骤编号: {step}，有效范围: 1–5")
        sys.exit(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="中国海运贸易统计分析管线 — Phase 4",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--step", type=int, default=None,
        help="只运行指定步骤编号（1–5）",
    )
    parser.add_argument(
        "--direction", choices=["CHN2World", "World2CHN"], default=None,
        help="只运行指定方向（默认两个方向都运行；step3/step4 忽略此参数）",
    )
    args = parser.parse_args()

    target_directions = [args.direction] if args.direction else DIRECTIONS

    if args.step is not None:
        run_single_step(args.step, target_directions)
    else:
        run_full(directions=target_directions)
