"""
run_all.py — 顶层入口，串联 Phase 1 + Phase 2 完整流程

用法示例：
  # 完整流程（Phase 1 不含 BACI，Phase 2 完整）
  python run_all.py

  # Phase 1 包含 BACI 补充与校正
  python run_all.py --with-baci

  # 只运行 Phase 1
  python run_all.py --phase 1

  # 只运行 Phase 2
  python run_all.py --phase 2

  # Phase 1 指定方向 + 步骤
  python run_all.py --phase 1 --step 4 --direction CHN2World

  # Phase 1 step4 使用自定义网络
  python run_all.py --phase 1 --step 4 --network E:\\path\\to\\network.shp
"""

import argparse
import os
import sys

# 确保项目根目录在 sys.path 中
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import phase1_route_building.run as p1
import phase2_disruption_analysis.run as p2

DIRECTIONS = ["CHN2World", "World2CHN"]


def _header(title: str) -> None:
    print(f"\n{'#' * 65}")
    print(f"  {title}")
    print("#" * 65)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="中国海运贸易与中断分析 — 完整管线",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--phase", type=int, choices=[1, 2], default=None,
        help="只运行指定阶段（1=路由构建, 2=中断分析；默认两个都运行）",
    )
    parser.add_argument(
        "--with-baci", action="store_true",
        help="Phase 1 包含 BACI 补充与校正步骤（step6）",
    )
    parser.add_argument(
        "--step", type=int, default=None,
        help="在指定 phase 内只运行某一步骤（需配合 --phase）",
    )
    parser.add_argument(
        "--direction", choices=["CHN2World", "World2CHN"], default=None,
        help="只运行指定方向（默认两个方向都运行）",
    )
    parser.add_argument(
        "--network", type=str, default=None,
        help="Phase 1 step4 使用的自定义海运网络 shp 路径（场景分析用）",
    )
    args = parser.parse_args()

    target_directions = [args.direction] if args.direction else DIRECTIONS

    if args.phase == 1 or args.phase is None:
        _header("Phase 1: 路由构建管线")
        if args.step is not None:
            p1.run_single_step(args.step, target_directions, network_shp=args.network)
        else:
            p1.run_full(
                directions=target_directions,
                with_baci=args.with_baci,
                network_shp=args.network,
            )

    if args.phase == 2 or args.phase is None:
        _header("Phase 2: 中断分析管线")
        if args.step is not None:
            p2.run_single_step(args.step, target_directions)
        else:
            p2.run_full(directions=target_directions)

    print("\n✅ 全部阶段完成！")
