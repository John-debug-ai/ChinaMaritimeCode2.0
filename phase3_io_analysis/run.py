"""
phase3_io_analysis/run.py — Phase 3 投入产出分析入口

执行顺序：step1 → step2 → step3 → step4 → step5

步骤说明：
  step1: 港口流量更新（过滤 port_trade_network + 回填 TTD 行业统计）
  step2: MRIO 计算（产出乘数 + 进口系数，耗时较长）
  step3: 结果统计（CSV + GIS GeoPackage）
  step4: 要道港口加权乘数（基于 Phase 2 要道路线 + step2 乘数）
  step5: 缓冲情景 MRIO（25%/50%/75%/100% 四个中断情景，耗时较长）

注意：step2 与 step5 均需加载 EORA（约 1–2 分钟）。
      完整流程（run_full）只加载一次，两步共用同一份缓存。

用法示例：
  # 完整流程
  python phase3_io_analysis/run.py

  # 只运行某一步骤
  python phase3_io_analysis/run.py --step 2

  # 只运行某一方向
  python phase3_io_analysis/run.py --direction CHN2World

  # 跳过 step5（缓冲情景耗时极长，可单独运行）
  python phase3_io_analysis/run.py --skip-buffer
"""

import argparse
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from phase3_io_analysis import (  # noqa: E402
    step1_update_port_flows,
    step2_port_multipliers,
    step3_result_stats,
    step4_chokepoint_weights,
    step5_buffer_scenarios,
)

DIRECTIONS = ["CHN2World", "World2CHN"]


def _header(title: str) -> None:
    print(f"\n{'=' * 65}")
    print(f"  {title}")
    print("=" * 65)


def run_full(
    directions: list[str] = None,
    skip_buffer: bool = False,
) -> None:
    """执行 Phase 3 完整流程。"""
    if directions is None:
        directions = DIRECTIONS

    _header("P3 Step 1: 港口流量更新")
    for d in directions:
        step1_update_port_flows.run(d)

    _header("P3 Step 2: MRIO 计算（耗时较长）")
    # EORA 只加载一次，两方向共用
    eora_data = step2_port_multipliers.load_eora_once()
    for d in directions:
        step2_port_multipliers.run(d, eora_data=eora_data)

    _header("P3 Step 3: 结果统计")
    for d in directions:
        step3_result_stats.run(d)

    _header("P3 Step 4: 要道港口加权乘数")
    for d in directions:
        step4_chokepoint_weights.run(d)

    if not skip_buffer:
        _header("P3 Step 5: 缓冲情景 MRIO（耗时较长）")
        for d in directions:
            step5_buffer_scenarios.run(d, eora_data=eora_data)
    else:
        print("\n[跳过 Step 5 缓冲情景，可单独运行: python run.py --step 5]")

    print("\n✅ Phase 3 全部步骤完成！")


def run_single_step(step: int, directions: list[str]) -> None:
    """只运行指定步骤。"""
    if step == 1:
        for d in directions:
            step1_update_port_flows.run(d)

    elif step == 2:
        eora_data = step2_port_multipliers.load_eora_once()
        for d in directions:
            step2_port_multipliers.run(d, eora_data=eora_data)

    elif step == 3:
        for d in directions:
            step3_result_stats.run(d)

    elif step == 4:
        for d in directions:
            step4_chokepoint_weights.run(d)

    elif step == 5:
        eora_data = step5_buffer_scenarios.load_eora_once()
        for d in directions:
            step5_buffer_scenarios.run(d, eora_data=eora_data)

    else:
        print(f"无效步骤编号: {step}，有效范围: 1–5")
        sys.exit(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="中国海运投入产出分析管线 — Phase 3",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--step", type=int, default=None,
        help="只运行指定步骤编号（1–5）",
    )
    parser.add_argument(
        "--direction", choices=["CHN2World", "World2CHN"], default=None,
        help="只运行指定方向（默认两个方向都运行）",
    )
    parser.add_argument(
        "--skip-buffer", action="store_true",
        help="跳过 step5 缓冲情景（完整流程时有效）",
    )
    args = parser.parse_args()

    target_directions = [args.direction] if args.direction else DIRECTIONS

    if args.step is not None:
        run_single_step(args.step, target_directions)
    else:
        run_full(directions=target_directions, skip_buffer=args.skip_buffer)
