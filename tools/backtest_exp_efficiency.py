"""指级效率历史回测 CLI（#23 P2 / #35 P2）。

核心计算、报告生成与事件检测都在 :mod:`services.backtest_service`；本文件只负责
参数解析与文件输出，保持“命令行可复现”这一入口。

口径见 ``docs/指级效率算法优化方案_20261018.md`` §2/§7：

- walk-forward：origin ``i`` 只用 ``points[:i+1]``，不允许未来数据泄漏；
- 目标值：``t_i`` 之后首个跨度 ``>= H`` 天的快照的平均效率，跨度 ``<= H+3`` 天才收录；
- 工具只读数据库，不写库、不改常量；常量调整由人按报告决定。

用法::

    python tools/backtest_exp_efficiency.py --selftest
    python tools/backtest_exp_efficiency.py --db data/AzurLaneStatisticalOfficeDB.db \
        --report docs/20261025_指级效率回测报告.md
"""

import argparse
import os
import sys
from typing import List, Optional, Sequence, Tuple

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from services.backtest_service import Point, buildReport, selftest  # noqa: E402
from services.commander_service import CommanderService  # noqa: E402
from utils import time_source  # noqa: E402
from utils.constants import DEFAULT_DB_PATH  # noqa: E402
from utils.db_connection import DatabaseConnection  # noqa: E402


def loadPoints(db_path: str) -> Tuple[List[Point], int, int, int]:
    """
    设置数据库路径并读取有效快照点（CLI 专用）。

    Args:
        db_path: 数据库路径。

    Returns:
        (升序快照点, 无法换算条数, 异常隔离条数, 原始快照条数)。

    Raises:
        SystemExit: 数据库不存在或有效点不足两条时退出。
    """
    if not os.path.exists(db_path):
        raise SystemExit(f"数据库不存在：{db_path}")
    DatabaseConnection.setDbPath(db_path)
    service = CommanderService()
    raw_count = len(service.listSnapshots())
    points, skipped, invalid = service.collectAbsolutePoints()
    if len(points) < 2:
        raise SystemExit(f"有效快照不足两条（{len(points)} 条），无法回测")
    return points, skipped, invalid, raw_count


def main(argv: Optional[Sequence[str]] = None) -> int:
    """
    命令行入口。

    Args:
        argv: 参数列表；None 时取 ``sys.argv[1:]``。

    Returns:
        进程退出码。
    """
    parser = argparse.ArgumentParser(description="指级效率历史回测（#35，只读）")
    parser.add_argument("--db", default=DEFAULT_DB_PATH, help="数据库路径")
    parser.add_argument("--report", help="报告输出路径；省略则打印到标准输出")
    parser.add_argument("--selftest", action="store_true", help="用合成数据自检，不读库")
    args = parser.parse_args(argv)

    if args.selftest:
        selftest()
        return 0

    db_path = os.path.abspath(args.db)
    points, skipped, invalid, raw_count = loadPoints(db_path)
    generated_at = time_source.now()
    report, _summary = buildReport(
        points, skipped, invalid, raw_count, db_path, generated_at
    )

    if args.report:
        report_path = os.path.abspath(args.report)
        report_dir = os.path.dirname(report_path)
        if report_dir and not os.path.exists(report_dir):
            os.makedirs(report_dir, exist_ok=True)
        with open(report_path, "w", encoding="utf-8") as handle:
            handle.write(report)
        print(f"报告已写入：{report_path}")
    else:
        print(report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
