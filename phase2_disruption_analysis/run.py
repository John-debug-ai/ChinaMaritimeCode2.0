"""
phase2_disruption_analysis/run.py — Phase 2 中断分析入口

执行顺序：step1 → step2 → step3 → step4

步骤说明：
  step1: 关键线路选择（空间相交筛选经过海峡的路径）
  step2: 贸易量统计（分国家 / 分行业）
  step3: 关键节点中断 + 重新寻路 + L_c 计算（耗时较长）
  step4: 额外成本蒙特卡洛不确定性分析

用法示例：
  # 运行完整流程
  python phase2_disruption_analysis/run.py

  # 只运行某一步骤
  python phase2_disruption_analysis/run.py --step 3

  # 只运行某一方向
  python phase2_disruption_analysis/run.py --direction CHN2World
"""

import argparse
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from phase2_disruption_analysis import (  # noqa: E402
    step1_select_routes,
    step2_trade_stats,
    step3_disrupt_reroute,
    step4_cost_mc,
)

DIRECTIONS = ["CHN2World", "World2CHN"]


def run_full(directions: list[str] = None) -> None:
    """执行 Phase 2 完整流程。"""
    if directions is None:
        directions = DIRECTIONS

    _header("P2 Step 1: 关键线路选择")
    for d in directions:
        step1_select_routes.run(d)

    _header("P2 Step 2: 贸易量统计")
    for d in directions:
        step2_trade_stats.run(d)

    _header("P2 Step 3: 中断 + 重新寻路 + L_c（耗时较长）")
    for d in directions:
        step3_disrupt_reroute.run(d)

    _header("P2 Step 4: 蒙特卡洛成本不确定性分析")
    for d in directions:
        step4_cost_mc.run(d)

    print("\n✅ Phase 2 全部步骤完成！")


def run_single_step(step: int, directions: list[str]) -> None:
    """只运行指定步骤。"""
    if step == 1:
        for d in directions:
            step1_select_routes.run(d)
    elif step == 2:
        for d in directions:
            step2_trade_stats.run(d)
    elif step == 3:
        for d in directions:
            step3_disrupt_reroute.run(d)
    elif step == 4:
        for d in directions:
            step4_cost_mc.run(d)
    else:
        print(f"无效步骤编号: {step}，有效范围: 1–4")
        sys.exit(1)


def _header(title: str) -> None:
    print(f"\n{'=' * 60}")
    print(title)
    print("=" * 60)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="中国海运中断分析管线 — Phase 2",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--step", type=int, default=None,
        help="只运行指定步骤编号（1–4）",
    )
    parser.add_argument(
        "--direction", choices=["CHN2World", "World2CHN"], default=None,
        help="只运行指定方向（默认两个方向都运行）",
    )
    args = parser.parse_args()

    target_directions = [args.direction] if args.direction else DIRECTIONS

    if args.step is not None:
        run_single_step(args.step, target_directions)
    else:
        run_full(directions=target_directions)
