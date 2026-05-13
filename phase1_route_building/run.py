"""
phase1_route_building/run.py — Phase 1 主流程入口

执行顺序：step1 → step2 → step3 → step4 → step5，可选执行 step6（BACI 补充与校正）。

步骤说明：
  step1: 提取港口 GeoPackage + 计算港口流量比例（含跨方向补全）
  step2: TTD 贸易数据 → 海运比例 → 行业分类
  step3: 港口对间流量计算
  step4: 最短路径计算（耗时较长）
  step5: 将流量关联到路径
  step6: （可选）BACI 补充缺失国家 + 校正大误差国家 + 合并无端口国家

用法示例：
  # 运行完整流程（不含 step6）
  python phase1_route_building/run.py

  # 包含 BACI 补充与校正
  python phase1_route_building/run.py --with-baci

  # 只运行某一步骤（两个方向都运行）
  python phase1_route_building/run.py --step 3

  # 只运行某一步骤的某一方向
  python phase1_route_building/run.py --step 3 --direction CHN2World

  # 场景分析：step4 使用自定义网络（如删除某条航道）
  python phase1_route_building/run.py --step 4 --network E:\\path\\to\\custom_network.shp
"""

import argparse
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from phase1_route_building import (  # noqa: E402
    step1_port_ratios,
    step2_trade_sea,
    step3_flow_calc,
    step4_shortest_path,
    step5_link_flow,
    step6_baci_supplement,
)

DIRECTIONS = ["CHN2World", "World2CHN"]


def run_full(
    directions: list[str] = None,
    with_baci: bool = False,
    network_shp: str = None,
) -> None:
    """执行完整流程。"""
    if directions is None:
        directions = DIRECTIONS

    _header("Step 1: 提取港口数据 + 计算港口流量比例")
    for d in directions:
        step1_port_ratios.run(d)

    _header("Step 2: 贸易数据处理 + 行业分类")
    for d in directions:
        step2_trade_sea.run(d)

    _header("Step 3: 计算港口对间流量")
    for d in directions:
        step3_flow_calc.run(d)

    _header("Step 4: 最短路径计算（耗时较长）")
    for d in directions:
        step4_shortest_path.run(d, network_shp=network_shp)

    _header("Step 5: 关联流量至路径")
    for d in directions:
        step5_link_flow.run(d)

    if with_baci:
        _header("Step 6: BACI 补充与误差校正")
        for d in directions:
            step6_baci_supplement.run(d)
            step6_baci_supplement.apply_corrections(d)

        # step6 改变了流量数据，需重新执行 step5
        _header("Step 5（再次执行）: 重新关联补充后的流量")
        for d in directions:
            step5_link_flow.run(d)

    print("\n✅ Phase 1 全部步骤完成！")


def run_single_step(
    step: int,
    directions: list[str],
    network_shp: str = None,
) -> None:
    """只运行指定步骤。"""
    if step == 1:
        for d in directions:
            step1_port_ratios.run(d)
    elif step == 2:
        for d in directions:
            step2_trade_sea.run(d)
    elif step == 3:
        for d in directions:
            step3_flow_calc.run(d)
    elif step == 4:
        for d in directions:
            step4_shortest_path.run(d, network_shp=network_shp)
    elif step == 5:
        for d in directions:
            step5_link_flow.run(d)
    elif step == 6:
        for d in directions:
            step6_baci_supplement.run(d)
            step6_baci_supplement.apply_corrections(d)
    else:
        print(f"无效步骤编号: {step}，有效范围: 1–6")
        sys.exit(1)


def _header(title: str) -> None:
    print(f"\n{'=' * 60}")
    print(title)
    print("=" * 60)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="中国海运贸易流量分析管线 — Phase 1",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--with-baci", action="store_true",
        help="包含 BACI 补充与校正步骤（step6）",
    )
    parser.add_argument(
        "--step", type=int, default=None,
        help="只运行指定步骤编号（1–6）",
    )
    parser.add_argument(
        "--direction", choices=["CHN2World", "World2CHN"], default=None,
        help="只运行指定方向（默认两个方向都运行）",
    )
    parser.add_argument(
        "--network", type=str, default=None,
        help="step4 使用的自定义海运网络 shp 路径（场景分析用）",
    )
    args = parser.parse_args()

    target_directions = [args.direction] if args.direction else DIRECTIONS

    if args.step is not None:
        run_single_step(args.step, target_directions, network_shp=args.network)
    else:
        run_full(
            directions=target_directions,
            with_baci=args.with_baci,
            network_shp=args.network,
        )
