"""魔方任务看板 —— 上线期初对齐脚本（Plan A，一次性）。

做两件事：

1. **历史签到改名**：把 `每日签到`（历史事件名，实为每月 4 档）改为 `每月签到`，
   并同步事件字典，使新看板与历史统计落在同一条线上；
2. **期初对齐**：扫描「今天 / 本周 / 本月 / 本期」内已手工记账的魔方收入，
   按「类别 + 金额 + 时间顺序」匹配到对应任务，生成完成记录并关联原明细，
   避免上线后第一次点看板就重复记账。

匹配不上的记录（例如历史聚合笔误的 3 / 6 / 27）不会被改动，只在报告里列出供人工核对。

用法::

    python tools/align_cube_task_completions.py --dry-run   # 只报告不写库
    python tools/align_cube_task_completions.py             # 正式对齐
    python tools/align_cube_task_completions.py --date 2026-10-17 --report docs/对齐报告.md

脚本可重复执行：已存在的完成记录会被跳过。
"""

import argparse
import io
import os
import sqlite3
import sys
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Dict, List, Optional, Tuple

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from services.cube_task_service import buildPeriodKey, periodRange  # noqa: E402
from utils.constants import (  # noqa: E402
    DEFAULT_DB_PATH, RECORD_DATE_FORMAT, RESOURCE_TYPE_CUBE, TASK_CATEGORY_SIGNIN,
    TASK_CATEGORY_SIGNIN_LEGACY,
)
from utils.db_connection import DatabaseConnection  # noqa: E402
from utils.db_schema import ensureResourceStatisticsSchema  # noqa: E402


@dataclass
class AlignStats:
    """对齐结果统计。"""

    renamed: int = 0
    matched: List[Tuple[str, str, int, int]] = field(default_factory=list)
    skipped_existing: List[str] = field(default_factory=list)
    unmatched: List[Tuple[str, str, int]] = field(default_factory=list)
    dry_run: bool = False


def renameSigninCategory(conn: sqlite3.Connection, stats: AlignStats) -> None:
    """
    把历史「每日签到」改为「每月签到」，并同步事件字典。

    Args:
        conn: 数据库连接。
        stats: 统计对象。
    """
    cursor = conn.execute(
        "UPDATE resource_transaction SET category = ?"
        " WHERE resource_type = ? AND direction = 'income' AND category = ?",
        (TASK_CATEGORY_SIGNIN, RESOURCE_TYPE_CUBE, TASK_CATEGORY_SIGNIN_LEGACY),
    )
    stats.renamed = cursor.rowcount

    legacy = conn.execute(
        "SELECT id FROM resource_category WHERE resource_type = ? AND direction = 'income' AND name = ?",
        (RESOURCE_TYPE_CUBE, TASK_CATEGORY_SIGNIN_LEGACY),
    ).fetchone()
    if legacy is None:
        return

    current = conn.execute(
        "SELECT id FROM resource_category WHERE resource_type = ? AND direction = 'income' AND name = ?",
        (RESOURCE_TYPE_CUBE, TASK_CATEGORY_SIGNIN),
    ).fetchone()
    if current is None:
        conn.execute(
            "UPDATE resource_category SET name = ? WHERE id = ?",
            (TASK_CATEGORY_SIGNIN, legacy[0]),
        )
    else:
        conn.execute("DELETE FROM resource_category WHERE id = ?", (legacy[0],))


def collectCandidates(
    conn: sqlite3.Connection,
    period_type: str,
    category: str,
    reward: int,
    reference: date,
    claimed: set,
) -> List[Tuple[int, str, int]]:
    """
    收集某个任务在本周期内可接管的明细。

    Args:
        conn: 数据库连接。
        period_type: 周期类型。
        category: 明细来源名。
        reward: 任务奖励（按金额匹配）。
        reference: 参考日期。
        claimed: 已被占用的明细 ID 集合。

    Returns:
        ``[(transaction_id, record_time, amount)]``，按时间升序。
    """
    start, end = periodRange(period_type, reference)
    rows = conn.execute(
        "SELECT id, record_time, amount FROM resource_transaction"
        " WHERE resource_type = ? AND direction = 'income' AND category = ?"
        "   AND substr(record_time, 1, 10) BETWEEN ? AND ?"
        " ORDER BY record_time, id",
        (RESOURCE_TYPE_CUBE, category, start.strftime(RECORD_DATE_FORMAT),
         end.strftime(RECORD_DATE_FORMAT)),
    ).fetchall()
    return [
        (row[0], row[1], row[2])
        for row in rows
        if row[0] not in claimed and row[2] == reward
    ]


def align(conn: sqlite3.Connection, reference: date, stats: AlignStats) -> None:
    """
    按任务顺序把当期已有明细接管为完成记录。

    Args:
        conn: 数据库连接。
        reference: 参考日期（默认今天）。
        stats: 统计对象。
    """
    tasks = conn.execute(
        "SELECT code, grp, name, reward, period_type, category, sort_order"
        " FROM cube_task WHERE active = 1 ORDER BY sort_order"
    ).fetchall()

    claimed = {
        row[0] for row in conn.execute(
            "SELECT transaction_id FROM cube_task_completion WHERE transaction_id IS NOT NULL"
        )
    }

    for code, _grp, name, reward, period_type, category, _sort in tasks:
        period_key = buildPeriodKey(period_type, reference)
        existing = conn.execute(
            "SELECT 1 FROM cube_task_completion WHERE task_code = ? AND period_key = ?",
            (code, period_key),
        ).fetchone()
        if existing is not None:
            stats.skipped_existing.append(f"{name}（{period_key}）")
            continue

        class _TaskRef:
            """把查询行包装成 collectCandidates 需要的属性访问对象。"""

            def __init__(self):
                self.period_type = period_type
                self.category = category
                self.reward = reward

        candidates = collectCandidates(
            conn, period_type, category, reward, reference, claimed
        )
        if not candidates:
            continue

        tx_id, record_time, amount = candidates[0]
        conn.execute(
            "INSERT INTO cube_task_completion (task_code, period_key, completed_at, transaction_id)"
            " VALUES (?, ?, ?, ?)"
            " ON CONFLICT(task_code, period_key) DO NOTHING",
            (code, period_key, record_time, tx_id),
        )
        claimed.add(tx_id)
        stats.matched.append((name, period_key, amount, tx_id))


def collectUnmatched(
    conn: sqlite3.Connection, reference: date
) -> List[Tuple[str, str, int]]:
    """
    收集当期未被任何任务接管的同类明细（供人工核对）。

    只检查「当前周期」：日常看今天、周常看本周、签到看本月、巡游看本期；
    其它日期的历史记录属于各自周期，不在本次核对范围内。

    Args:
        conn: 数据库连接。
        reference: 参考日期。

    Returns:
        ``[(record_time, category, amount)]``。
    """
    claimed = {
        row[0] for row in conn.execute(
            "SELECT transaction_id FROM cube_task_completion WHERE transaction_id IS NOT NULL"
        )
    }
    results: List[Tuple[str, str, int]] = []
    seen = set()

    definitions = conn.execute(
        "SELECT DISTINCT category, period_type FROM cube_task WHERE active = 1"
    ).fetchall()

    for category, period_type in definitions:
        start, end = periodRange(period_type, reference)
        rows = conn.execute(
            "SELECT id, record_time, amount FROM resource_transaction"
            " WHERE resource_type = ? AND direction = 'income' AND category = ?"
            "   AND substr(record_time, 1, 10) BETWEEN ? AND ?"
            " ORDER BY record_time",
            (RESOURCE_TYPE_CUBE, category,
             start.strftime(RECORD_DATE_FORMAT), end.strftime(RECORD_DATE_FORMAT)),
        ).fetchall()
        for tx_id, record_time, amount in rows:
            if tx_id in claimed or tx_id in seen:
                continue
            seen.add(tx_id)
            results.append((record_time, category, amount))
    return sorted(results)


def renderReport(stats: AlignStats, reference: date) -> str:
    """
    生成 Markdown 报告。

    Args:
        stats: 统计对象。
        reference: 参考日期。

    Returns:
        报告文本。
    """
    buffer = io.StringIO()
    buffer.write("# 魔方任务看板 —— 期初对齐报告\n\n")
    buffer.write(f"> 生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
    buffer.write(f"- 参考日期：{reference.strftime(RECORD_DATE_FORMAT)}\n")
    buffer.write(f"- 模式：{'预演（未写库）' if stats.dry_run else '正式执行'}\n")
    buffer.write(f"- 历史签到改名：{stats.renamed} 笔\n")
    buffer.write(f"- 接管完成记录：{len(stats.matched)} 条\n")
    buffer.write(f"- 跳过（本期已存在完成记录）：{len(stats.skipped_existing)} 条\n\n")

    buffer.write("## 一、接管的完成记录\n\n")
    if stats.matched:
        buffer.write("| 任务 | 周期键 | 金额 | 明细 ID |\n| --- | --- | --- | --- |\n")
        for name, period_key, amount, tx_id in stats.matched:
            buffer.write(f"| {name} | {period_key} | {amount} | {tx_id} |\n")
    else:
        buffer.write("（无）\n")
    buffer.write("\n")

    buffer.write("## 二、跳过项（本期已完成）\n\n")
    buffer.write("\n".join(f"- {item}" for item in stats.skipped_existing) or "（无）")
    buffer.write("\n\n")

    buffer.write("## 三、未匹配的同类明细（请人工核对）\n\n")
    if stats.unmatched:
        buffer.write("| 记录时刻 | 来源 | 金额 |\n| --- | --- | --- |\n")
        for record_time, category, amount in stats.unmatched:
            buffer.write(f"| {record_time} | {category} | {amount} |\n")
        buffer.write("\n> 这些记录不会被改动：可能是历史上把多档合并成一笔（如 3 / 6 / 27），"
                     "或确实还没有对应任务。\n")
    else:
        buffer.write("（无）\n")
    return buffer.getvalue()


def main(argv: Optional[List[str]] = None) -> int:
    """
    命令行入口。

    Args:
        argv: 参数列表，默认取 ``sys.argv[1:]``。

    Returns:
        进程退出码：0 成功。
    """
    parser = argparse.ArgumentParser(description="魔方任务看板期初对齐（一次性）")
    parser.add_argument("--db", default=DEFAULT_DB_PATH, help="目标数据库路径")
    parser.add_argument("--date", default=None, help="参考日期 yyyy-MM-dd，默认今天")
    parser.add_argument("--report", default=None, help="报告输出路径（Markdown）")
    parser.add_argument("--dry-run", action="store_true", help="只统计与出报告，不写库")
    args = parser.parse_args(argv)

    reference = (
        datetime.strptime(args.date, RECORD_DATE_FORMAT).date() if args.date else date.today()
    )
    DatabaseConnection.setDbPath(args.db)
    ensureResourceStatisticsSchema(args.db)

    stats = AlignStats(dry_run=args.dry_run)
    conn = sqlite3.connect(args.db)
    conn.isolation_level = None
    try:
        conn.execute("BEGIN")
        try:
            renameSigninCategory(conn, stats)
            align(conn, reference, stats)
            stats.unmatched = collectUnmatched(conn, reference)
            if args.dry_run:
                conn.execute("ROLLBACK")
            else:
                conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
    finally:
        conn.close()

    report = renderReport(stats, reference)
    if args.report:
        os.makedirs(os.path.dirname(os.path.abspath(args.report)), exist_ok=True)
        with open(args.report, "w", encoding="utf-8") as handle:
            handle.write(report)

    print(report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
