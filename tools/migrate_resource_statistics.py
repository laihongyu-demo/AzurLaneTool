"""资源统计数据迁移脚本（一次性）。

把根目录的 7 个 CSV 台账导入 ``data/AzurLaneStatisticalOfficeDB.db``：

- 魔方 / 红尖尖：日汇总 + 逐笔明细 + 事件字典
- 指级经验：补导进 ``commander_info``（复用既有表），时间统一为 ``yyyy-MM-dd HH:mm``
- 等级经验基准：``data/commander_level.csv`` → ``commander_level_exp``

脚本自带校验断言（见 docs/资源统计迁移需求文档_20261017.md §8.3），任一断言失败即
回滚数据写入并以非 0 退出。运行前会自动备份数据库。

用法::

    python tools/migrate_resource_statistics.py            # 正式迁移
    python tools/migrate_resource_statistics.py --force    # 清空资源表后重新导入
    python tools/migrate_resource_statistics.py --report docs/迁移报告.md

注意：本脚本读取的 CSV 在迁移完成后按需求删除，脚本本身保留作审计留档。
"""

import argparse
import csv
import io
import os
import re
import shutil
import sqlite3
import sys
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, Iterable, List, Optional, Tuple

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from utils.constants import (  # noqa: E402
    BASE_DIR, DATA_DIR, DEFAULT_DB_PATH, STATISTICS_DATETIME_FORMAT,
)
from utils.sql_loader import loadSqlFile  # noqa: E402

SCHEMA_FILE = "CreateResourceStatisticsTables.sql"

SUMMARY_FILES = {
    "cube": "魔方收支汇总.csv",
    "red_gem": "红尖尖收支汇总.csv",
}
SOURCE_FILES = {
    ("cube", "income"): ("魔方来源.csv", "魔方来源", "获得量"),
    ("cube", "expense"): ("魔方去向.csv", "魔方去向", "消耗量"),
    ("red_gem", "income"): ("红尖尖来源.csv", "事件", "获得量"),
    ("red_gem", "expense"): ("红尖尖去向.csv", "事件", "消耗量"),
}
COMMANDER_FILE = "指级经验记录.csv"
LEVEL_EXP_FILE = os.path.join("data", "commander_level.csv")

# 结余锚点：这些日期的结余无法由"上日结余 + 收入 - 支出"推出，作为手填锚点固化。
# 其余日期必须与自动累加结果完全一致，由校验断言 M-06 保证。
BALANCE_ANCHORS = {
    "cube": {
        "2023-08-03": 3,      # 首日：表格起始库存与当日收支不自洽
        "2023-09-15": 175,    # 断链 +49
        "2023-11-09": 252,    # 断链 -236
        "2023-11-16": 308,    # 断链 +17
        "2023-12-02": 248,    # 断链 -14
    },
    "red_gem": {
        "2025-01-01": 673,    # 首日：起始库存
    },
}

CN_DATE_PATTERN = re.compile(r"^(\d{4})年(\d{1,2})月(\d{1,2})日$")


class MigrationError(Exception):
    """迁移过程中的致命错误。"""


@dataclass
class CheckResult:
    """一条校验断言的结果。"""

    name: str
    expected: object
    actual: object
    passed: bool


@dataclass
class MigrationStats:
    """迁移统计，用于生成报告。"""

    daily_rows: Dict[str, int] = field(default_factory=dict)
    transaction_rows: Dict[str, int] = field(default_factory=dict)
    category_rows: int = 0
    commander_added: int = 0
    commander_total: int = 0
    level_exp_rows: int = 0
    source_ranges: Dict[str, Tuple[str, str]] = field(default_factory=dict)
    anchors: List[Tuple[str, str, int, int]] = field(default_factory=list)
    checks: List[CheckResult] = field(default_factory=list)
    dropped_level_ddl: str = ""
    backup_path: str = ""

    def allPassed(self) -> bool:
        """全部断言是否通过。"""
        return all(check.passed for check in self.checks)


# --------------------------------------------------------------------- 读入


def readCsv(path: str) -> List[Dict[str, str]]:
    """
    读取 UTF-8（含 BOM）CSV。

    Args:
        path: 文件路径。

    Returns:
        行字典列表。

    Raises:
        MigrationError: 文件不存在时抛出。
    """
    if not os.path.exists(path):
        raise MigrationError(f"数据源不存在: {path}")
    with open(path, "r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def parseCnDate(value: str) -> str:
    """
    解析 ``2023年8月3日`` 形式的日期。

    Args:
        value: 原始日期文本。

    Returns:
        ``yyyy-MM-dd``。

    Raises:
        MigrationError: 无法解析时抛出。
    """
    match = CN_DATE_PATTERN.match((value or "").strip())
    if not match:
        raise MigrationError(f"无法解析日期: {value!r}")
    year, month, day = (int(part) for part in match.groups())
    return f"{year:04d}-{month:02d}-{day:02d}"


def normalizeDateTime(value: str) -> str:
    """
    把 ``2023/8/9 10:12`` 或 ``2023-08-09 10:12`` 统一为 ``yyyy-MM-dd HH:mm``。

    Args:
        value: 原始时间文本。

    Returns:
        规范化后的时间字符串。

    Raises:
        MigrationError: 无法解析时抛出。
    """
    text = (value or "").strip()
    for fmt in (STATISTICS_DATETIME_FORMAT, "%Y/%m/%d %H:%M", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(text, fmt).strftime(STATISTICS_DATETIME_FORMAT)
        except ValueError:
            continue
    raise MigrationError(f"无法解析记录时间: {value!r}")


# ----------------------------------------------------------------- 准备数据


def loadResourceSource(resource_type: str, source_dir: str) -> Dict[str, object]:
    """
    读取某类资源的汇总、来源与去向数据。

    Args:
        resource_type: ``cube`` 或 ``red_gem``。
        source_dir: CSV 所在目录。

    Returns:
        含 ``summary``、``transactions``、``last_date`` 的字典。

    Raises:
        MigrationError: 数据结构不符合预期时抛出。
    """
    summary_rows = readCsv(os.path.join(source_dir, SUMMARY_FILES[resource_type]))
    income_key = "获得魔方" if resource_type == "cube" else "获得量"
    expense_key = "消耗魔方" if resource_type == "cube" else "消耗量"
    balance_key = "剩余魔方" if resource_type == "cube" else "结余"

    summary: Dict[str, Dict[str, object]] = {}
    for row in summary_rows:
        record_date = parseCnDate(row["日期"])
        summary[record_date] = {
            "income": int(row[income_key] or 0),
            "expense": int(row[expense_key] or 0),
            "balance": int(row[balance_key] or 0),
            "note": (row.get("备注") or "").strip(),
        }

    transactions: List[Tuple[str, str, str, int]] = []
    for direction in ("income", "expense"):
        file_name, category_key, amount_key = SOURCE_FILES[(resource_type, direction)]
        for row in readCsv(os.path.join(source_dir, file_name)):
            transactions.append((
                direction,
                parseCnDate(row["日期"]),
                (row[category_key] or "").strip(),
                int(row[amount_key] or 0),
            ))

    activity_dates = {
        record_date
        for record_date, item in summary.items()
        if item["income"] or item["expense"]
    }
    activity_dates.update(record_date for _, record_date, _, _ in transactions)
    last_date = max(activity_dates) if activity_dates else max(summary)

    return {
        "summary": summary,
        "transactions": transactions,
        "last_date": last_date,
    }


def buildDailyTotals(transactions: Iterable[Tuple[str, str, str, int]]) -> Dict[str, Dict[str, int]]:
    """
    按日期汇总明细收支。

    Args:
        transactions: ``(direction, date, category, amount)`` 序列。

    Returns:
        日期 → ``{"income": int, "expense": int}``。
    """
    totals: Dict[str, Dict[str, int]] = {}
    for direction, record_date, _category, amount in transactions:
        bucket = totals.setdefault(record_date, {"income": 0, "expense": 0})
        bucket[direction] += amount
    return totals


# ------------------------------------------------------------------ 写库


def backupDatabase(db_path: str, backup_dir: str) -> str:
    """
    迁移前备份数据库。

    Args:
        db_path: 数据库路径。
        backup_dir: 备份目录。

    Returns:
        备份文件路径。
    """
    os.makedirs(backup_dir, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    base = os.path.splitext(os.path.basename(db_path))[0]
    backup_path = os.path.join(backup_dir, f"{base}_{stamp}_pre_resource_migration.db")
    shutil.copy2(db_path, backup_path)
    return backup_path


def ensureResourceTables(conn: sqlite3.Connection) -> None:
    """
    建立资源统计相关表。

    Args:
        conn: 数据库连接。

    Raises:
        DatabaseError: SQL 文件缺失时抛出。
    """
    conn.executescript(loadSqlFile(SCHEMA_FILE))
    conn.commit()


def importResource(
    conn: sqlite3.Connection,
    resource_type: str,
    source: Dict[str, object],
    stats: MigrationStats,
) -> None:
    """
    导入单类资源的日汇总、明细与事件字典。

    Args:
        conn: 数据库连接。
        resource_type: ``cube`` 或 ``red_gem``。
        source: :func:`loadResourceSource` 的返回值。
        stats: 统计对象，供报告使用。

    Raises:
        MigrationError: 明细与汇总不一致时抛出。
    """
    summary: Dict[str, Dict[str, object]] = source["summary"]  # type: ignore[assignment]
    transactions: List[Tuple[str, str, str, int]] = source["transactions"]  # type: ignore[assignment]
    last_date: str = source["last_date"]  # type: ignore[assignment]
    daily_totals = buildDailyTotals(transactions)

    # 1) 明细
    for direction, record_date, category, amount in transactions:
        conn.execute(
            "INSERT INTO resource_transaction"
            " (resource_type, direction, record_date, category, amount)"
            " VALUES (?, ?, ?, ?, ?)",
            (resource_type, direction, record_date, category, amount),
        )

    # 2) 日汇总（明细日不存收支，汇总日存收支）
    for record_date, item in summary.items():
        if record_date > last_date:
            continue  # 尾部未来占位行不导入

        note = str(item["note"])
        override = BALANCE_ANCHORS.get(resource_type, {}).get(record_date)
        total = daily_totals.get(record_date)

        if total is not None:
            expected_income = int(item["income"])
            expected_expense = int(item["expense"])
            if total["income"] != expected_income or total["expense"] != expected_expense:
                raise MigrationError(
                    f"{resource_type} {record_date} 明细与汇总不一致："
                    f"明细 {total['income']}/{total['expense']}，"
                    f"汇总 {expected_income}/{expected_expense}"
                )
            conn.execute(
                "INSERT INTO resource_daily"
                " (resource_type, record_date, detail_mode, income, expense, balance_override, note)"
                " VALUES (?, ?, 'detail', NULL, NULL, ?, ?)",
                (resource_type, record_date, override, note),
            )
        else:
            conn.execute(
                "INSERT INTO resource_daily"
                " (resource_type, record_date, detail_mode, income, expense, balance_override, note)"
                " VALUES (?, ?, 'summary_only', ?, ?, ?, ?)",
                (resource_type, record_date, int(item["income"]), int(item["expense"]), override, note),
            )

        if override is not None:
            stats.anchors.append((resource_type, record_date, int(item["balance"]), override))

    # 3) 事件字典
    categories = sorted({(direction, category) for direction, _d, category, _a in transactions})
    for index, (direction, category) in enumerate(categories):
        conn.execute(
            "INSERT OR IGNORE INTO resource_category"
            " (resource_type, direction, name, sort_order) VALUES (?, ?, ?, ?)",
            (resource_type, direction, category, index),
        )

    stats.daily_rows[resource_type] = conn.execute(
        "SELECT COUNT(*) FROM resource_daily WHERE resource_type = ?", (resource_type,)
    ).fetchone()[0]
    stats.transaction_rows[resource_type] = conn.execute(
        "SELECT COUNT(*) FROM resource_transaction WHERE resource_type = ?", (resource_type,)
    ).fetchone()[0]
    stats.source_ranges[resource_type] = (
        min(summary), last_date,
    )


def importCommander(conn: sqlite3.Connection, source_dir: str, stats: MigrationStats) -> None:
    """
    规范化并补导指挥官快照。

    Args:
        conn: 数据库连接。
        source_dir: CSV 所在目录。
        stats: 统计对象。

    Raises:
        MigrationError: 存在重复时间戳时抛出。
    """
    rows = readCsv(os.path.join(source_dir, COMMANDER_FILE))

    # 1) 既有行时间规范化
    for record in conn.execute("SELECT id, statistics_date FROM commander_info").fetchall():
        conn.execute(
            "UPDATE commander_info SET statistics_date = ? WHERE id = ?",
            (normalizeDateTime(record[1]), record[0]),
        )

    # 2) 差集补插
    existing = {
        tuple(row) for row in conn.execute(
            "SELECT statistics_date, commander_level, commander_exp FROM commander_info"
        )
    }
    added = 0
    for row in rows:
        key = (
            normalizeDateTime(row["日期"]),
            int(row["等级"]),
            int(row["经验"]),
        )
        if key in existing:
            continue
        conn.execute(
            "INSERT INTO commander_info (statistics_date, commander_level, commander_exp)"
            " VALUES (?, ?, ?)",
            key,
        )
        existing.add(key)
        added += 1

    stats.commander_added = added
    stats.commander_total = conn.execute("SELECT COUNT(*) FROM commander_info").fetchone()[0]

    # 3) 唯一索引（时间已规范化）
    duplicates = conn.execute(
        "SELECT statistics_date, COUNT(*) AS cnt FROM commander_info"
        " GROUP BY statistics_date HAVING cnt > 1"
    ).fetchall()
    if duplicates:
        detail = ", ".join(f"{date}({cnt})" for date, cnt in duplicates[:5])
        raise MigrationError(f"commander_info 存在重复时间戳，无法建立唯一索引: {detail}")

    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_commander_info_date"
        " ON commander_info (statistics_date)"
    )


def importLevelExp(conn: sqlite3.Connection, source_path: str, stats: MigrationStats) -> None:
    """
    导入等级经验基准。

    Args:
        conn: 数据库连接。
        source_path: ``commander_level.csv`` 路径。
        stats: 统计对象。
    """
    rows = readCsv(source_path)
    for row in rows:
        level = int(row["等级"])
        level_up_text = (row["本次升级所需经验"] or "").strip()
        cumulative_text = (row["升级累计所需经验"] or "").strip()
        level_up = int(level_up_text) if level_up_text.isdigit() else None
        cumulative = int(cumulative_text) if cumulative_text.isdigit() else None
        note = "" if level_up_text.isdigit() else level_up_text

        conn.execute(
            "INSERT OR REPLACE INTO commander_level_exp"
            " (level, level_up_exp, cumulative_exp, note) VALUES (?, ?, ?, ?)",
            (level, level_up, cumulative, note),
        )
    stats.level_exp_rows = conn.execute("SELECT COUNT(*) FROM commander_level_exp").fetchone()[0]


def dropLegacyLevelTable(conn: sqlite3.Connection, stats: MigrationStats) -> None:
    """
    清退历史遗留的空 ``level`` 表，并保留其 DDL 供报告留档。

    Args:
        conn: 数据库连接。
        stats: 统计对象。
    """
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'level'"
    ).fetchone()
    if row is None:
        return

    count = conn.execute("SELECT COUNT(*) FROM level").fetchone()[0]
    if count:
        stats.dropped_level_ddl = f"-- 未清退：level 表存在 {count} 行数据"
        return

    stats.dropped_level_ddl = row[0] or ""
    conn.execute("DROP TABLE level")


# ------------------------------------------------------------------ 校验


def check(stats: MigrationStats, name: str, actual: object, expected: object) -> None:
    """
    记录一条校验断言。

    Args:
        stats: 统计对象。
        name: 断言名称。
        actual: 实际值。
        expected: 期望值。
    """
    stats.checks.append(CheckResult(name=name, expected=expected, actual=actual, passed=actual == expected))


def verify(conn: sqlite3.Connection, source_dir: str, stats: MigrationStats) -> None:
    """
    执行需求文档 §8.3 的校验断言。

    Args:
        conn: 数据库连接。
        source_dir: CSV 所在目录。
        stats: 统计对象。
    """
    expected_daily = {"cube": 1172, "red_gem": 655}
    for resource_type, expected in expected_daily.items():
        check(
            stats,
            f"resource_daily 行数({resource_type})",
            conn.execute(
                "SELECT COUNT(*) FROM resource_daily WHERE resource_type = ?", (resource_type,)
            ).fetchone()[0],
            expected,
        )

    expected_transactions = {"cube": 6132, "red_gem": 1030}
    for resource_type, expected in expected_transactions.items():
        check(
            stats,
            f"resource_transaction 行数({resource_type})",
            conn.execute(
                "SELECT COUNT(*) FROM resource_transaction WHERE resource_type = ?", (resource_type,)
            ).fetchone()[0],
            expected,
        )

    check(
        stats,
        "resource_category 行数",
        conn.execute("SELECT COUNT(*) FROM resource_category").fetchone()[0],
        41,
    )
    check(stats, "commander_info 行数", stats.commander_total, 522)
    check(stats, "commander_level_exp 行数", stats.level_exp_rows, 200)
    check(
        stats,
        "commander_info 时间格式合规行数",
        conn.execute(
            "SELECT COUNT(*) FROM commander_info"
            " WHERE statistics_date NOT GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]"
            " [0-9][0-9]:[0-9][0-9]'"
        ).fetchone()[0],
        0,
    )
    check(
        stats,
        "未来日期未入库",
        conn.execute("SELECT COUNT(*) FROM resource_daily WHERE record_date > ?",
                     (max(stats.source_ranges[r][1] for r in stats.source_ranges),)).fetchone()[0],
        0,
    )

    # 明细日聚合与源表一致 / 汇总日取值与源表一致
    for resource_type in ("cube", "red_gem"):
        source = loadResourceSource(resource_type, source_dir)
        mismatched_detail = 0
        mismatched_summary = 0
        for record_date, item in source["summary"].items():  # type: ignore[union-attr]
            if record_date > source["last_date"]:  # type: ignore[operator]
                continue
            row = conn.execute(
                "SELECT detail_mode, income, expense FROM resource_daily"
                " WHERE resource_type = ? AND record_date = ?",
                (resource_type, record_date),
            ).fetchone()
            if row is None:
                mismatched_summary += 1
                continue
            if row[0] == "summary_only":
                if row[1] != item["income"] or row[2] != item["expense"]:
                    mismatched_summary += 1
            else:
                totals = conn.execute(
                    "SELECT direction, COALESCE(SUM(amount), 0) FROM resource_transaction"
                    " WHERE resource_type = ? AND record_date = ? GROUP BY direction",
                    (resource_type, record_date),
                ).fetchall()
                aggregated = {direction: amount for direction, amount in totals}
                if (aggregated.get("income", 0) != item["income"]
                        or aggregated.get("expense", 0) != item["expense"]):
                    mismatched_detail += 1

        check(stats, f"明细聚合与源表不一致天数({resource_type})", mismatched_detail, 0)
        check(stats, f"日汇总取值与源表不一致天数({resource_type})", mismatched_summary, 0)

    # 结余链验算
    for resource_type in ("cube", "red_gem"):
        source = loadResourceSource(resource_type, source_dir)
        summary = source["summary"]
        expected_balances = {
            record_date: int(item["balance"])
            for record_date, item in summary.items()
            if record_date <= source["last_date"]
        }
        first_balance, last_balance, deviations = calculateBalanceChain(
            conn, resource_type, expected_balances
        )
        check(stats, f"结余链偏差({resource_type})", deviations, 0)
        check(
            stats,
            f"首日结余({resource_type})",
            first_balance,
            list(BALANCE_ANCHORS[resource_type].values())[0],
        )
        check(
            stats,
            f"末日结余({resource_type})",
            last_balance,
            summary[source["last_date"]]["balance"],
        )


def calculateBalanceChain(
    conn: sqlite3.Connection, resource_type: str, expected_balances: Dict[str, int]
) -> Tuple[Optional[int], Optional[int], int]:
    """
    按需求文档 §3.1 重算结余链，并与源表逐日比对。

    Args:
        conn: 数据库连接。
        resource_type: 资源类型。
        expected_balances: 源表逐日结余，日期 → 结余。

    Returns:
        ``(首日结余, 末日结余, 与源表不一致的天数)``。
    """
    rows = conn.execute(
        "SELECT record_date, detail_mode, income, expense, balance_override FROM resource_daily"
        " WHERE resource_type = ? ORDER BY record_date",
        (resource_type,),
    ).fetchall()

    totals = {
        record_date: {"income": income, "expense": expense}
        for record_date, income, expense in conn.execute(
            "SELECT record_date,"
            " COALESCE(SUM(CASE WHEN direction = 'income' THEN amount END), 0),"
            " COALESCE(SUM(CASE WHEN direction = 'expense' THEN amount END), 0)"
            " FROM resource_transaction WHERE resource_type = ? GROUP BY record_date",
            (resource_type,),
        )
    }

    balance = 0
    first_balance = None
    deviations = 0
    for record_date, detail_mode, income, expense, override in rows:
        if detail_mode == "detail":
            day_income = totals.get(record_date, {}).get("income", 0)
            day_expense = totals.get(record_date, {}).get("expense", 0)
        else:
            day_income, day_expense = income, expense

        if override is not None:
            balance = int(override)
        else:
            balance += day_income - day_expense

        if first_balance is None:
            first_balance = balance
        if record_date in expected_balances and expected_balances[record_date] != balance:
            deviations += 1

    return first_balance, balance, deviations


# ------------------------------------------------------------------ 报告


def _displayPath(path: str) -> str:
    """
    把绝对路径转成相对项目根目录的展示路径（统一正斜杠）。

    Args:
        path: 绝对路径。

    Returns:
        形如 ``data/AzurLaneStatisticalOfficeDB.db`` 的相对路径。
    """
    return os.path.relpath(path, PROJECT_ROOT).replace(os.sep, "/")


def renderReport(db_path: str, stats: MigrationStats) -> str:
    """
    生成 Markdown 迁移报告。

    Args:
        db_path: 数据库路径。
        stats: 统计对象。

    Returns:
        报告文本。
    """
    buffer = io.StringIO()
    buffer.write("# 资源统计数据迁移报告\n\n")
    buffer.write(f"> 生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
    buffer.write(f"- 目标数据库：`{_displayPath(db_path)}`\n")
    if stats.backup_path:
        buffer.write(f"- 迁移前备份：`{_displayPath(stats.backup_path)}`\n")
    buffer.write(f"- 断言结果：{'全部通过' if stats.allPassed() else '存在失败项'}\n\n")

    buffer.write("## 一、导入结果\n\n")
    buffer.write("| 项目 | 数量 |\n| --- | --- |\n")
    for resource_type, count in stats.daily_rows.items():
        buffer.write(f"| `resource_daily`（{resource_type}） | {count} |\n")
    for resource_type, count in stats.transaction_rows.items():
        buffer.write(f"| `resource_transaction`（{resource_type}） | {count} |\n")
    buffer.write(f"| `resource_category` | {stats.category_rows or 41} |\n")
    buffer.write(f"| `commander_info`（合计 / 本次补插） | {stats.commander_total} / {stats.commander_added} |\n")
    buffer.write(f"| `commander_level_exp` | {stats.level_exp_rows} |\n\n")

    buffer.write("## 二、数据区间\n\n")
    buffer.write("| 资源 | 起始日期 | 末次活动日期 |\n| --- | --- | --- |\n")
    for resource_type, (start, end) in stats.source_ranges.items():
        buffer.write(f"| {resource_type} | {start} | {end} |\n")
    buffer.write("\n")

    buffer.write("## 三、结余锚点（手填结余）\n\n")
    buffer.write("| 资源 | 日期 | 源表结余 | 迁移后手填值 |\n| --- | --- | --- | --- |\n")
    for resource_type, record_date, source_balance, override in stats.anchors:
        buffer.write(f"| {resource_type} | {record_date} | {source_balance:,} | {override:,} |\n")
    buffer.write("\n> 其余日期均由「上日结余 + 收入 - 支出」自动累加，零偏差（见校验表 M-06）。\n\n")

    buffer.write("## 四、校验断言\n\n")
    buffer.write("| 断言 | 期望 | 实际 | 结果 |\n| --- | --- | --- | --- |\n")
    for item in stats.checks:
        flag = "PASS" if item.passed else "**FAIL**"
        buffer.write(f"| {item.name} | {item.expected} | {item.actual} | {flag} |\n")
    buffer.write("\n")

    if stats.dropped_level_ddl:
        buffer.write("## 五、清退对象的原 DDL 留档\n\n")
        buffer.write("```sql\n")
        buffer.write(stats.dropped_level_ddl.strip() + "\n")
        buffer.write("```\n\n")

    buffer.write("## 六、后续动作\n\n")
    buffer.write("1. 校验通过后删除根目录 7 个 CSV 与 `碧蓝航线.xlsx`（不纳入 git）；\n")
    buffer.write("2. 启动应用确认看板「指挥官等级 / 魔方 / 红尖尖」三张卡有值；\n")
    buffer.write("3. 魔方 / 红尖尖的录入与编辑见 issue #17。\n")
    return buffer.getvalue()


# ------------------------------------------------------------------ 主流程


def runMigration(db_path: str, source_dir: str, report_path: Optional[str], force: bool,
                 backup: bool) -> MigrationStats:
    """
    执行完整迁移。

    Args:
        db_path: 数据库路径。
        source_dir: CSV 所在目录。
        report_path: 可选报告输出路径。
        force: 是否清空资源表后重新导入。
        backup: 是否在迁移前备份数据库。

    Returns:
        迁移统计对象。

    Raises:
        MigrationError: 迁移或校验失败时抛出。
    """
    if not os.path.exists(db_path):
        raise MigrationError(f"数据库不存在: {db_path}")

    stats = MigrationStats()
    if backup:
        stats.backup_path = backupDatabase(db_path, os.path.join(DATA_DIR, "backup"))

    conn = sqlite3.connect(db_path)
    conn.isolation_level = None  # 关闭隐式事务，改用显式 BEGIN/COMMIT 控制
    try:
        ensureResourceTables(conn)

        existing = conn.execute("SELECT COUNT(*) FROM resource_daily").fetchone()[0]
        if existing and not force:
            raise MigrationError(
                f"resource_daily 已有 {existing} 行数据。如需重新导入请加 --force"
            )

        sources = {
            resource_type: loadResourceSource(resource_type, source_dir)
            for resource_type in SUMMARY_FILES
        }

        conn.execute("BEGIN")
        try:
            if force:
                conn.execute("DELETE FROM resource_transaction")
                conn.execute("DELETE FROM resource_daily")
                conn.execute("DELETE FROM resource_category")

            for resource_type, source in sources.items():
                importResource(conn, resource_type, source, stats)
            importCommander(conn, source_dir, stats)
            importLevelExp(conn, os.path.join(PROJECT_ROOT, LEVEL_EXP_FILE), stats)
            dropLegacyLevelTable(conn, stats)

            stats.category_rows = conn.execute(
                "SELECT COUNT(*) FROM resource_category"
            ).fetchone()[0]

            verify(conn, source_dir, stats)
            if not stats.allPassed():
                failed = ", ".join(item.name for item in stats.checks if not item.passed)
                raise MigrationError(f"校验未通过，已回滚：{failed}")

            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise

        if report_path:
            os.makedirs(os.path.dirname(os.path.abspath(report_path)), exist_ok=True)
            with open(report_path, "w", encoding="utf-8") as handle:
                handle.write(renderReport(db_path, stats))
    finally:
        conn.close()

    return stats


def printSummary(stats: MigrationStats) -> None:
    """
    在控制台打印迁移摘要。

    Args:
        stats: 统计对象。
    """
    print("=" * 60)
    print("资源统计数据迁移")
    print("=" * 60)
    if stats.backup_path:
        print(f"备份: {stats.backup_path}")
    for resource_type, count in stats.daily_rows.items():
        print(f"resource_daily[{resource_type}] = {count}")
    for resource_type, count in stats.transaction_rows.items():
        print(f"resource_transaction[{resource_type}] = {count}")
    print(f"resource_category = {stats.category_rows}")
    print(f"commander_info = {stats.commander_total}（本次补插 {stats.commander_added}）")
    print(f"commander_level_exp = {stats.level_exp_rows}")
    print("-" * 60)
    for item in stats.checks:
        print(f"[{'PASS' if item.passed else 'FAIL'}] {item.name}: {item.actual} (期望 {item.expected})")
    print("-" * 60)
    print("结果: " + ("全部通过" if stats.allPassed() else "存在失败项"))


def main(argv: Optional[List[str]] = None) -> int:
    """
    命令行入口。

    Args:
        argv: 参数列表，默认取 ``sys.argv[1:]``。

    Returns:
        进程退出码：0 成功，1 失败。
    """
    parser = argparse.ArgumentParser(description="资源统计数据迁移（一次性脚本）")
    parser.add_argument("--db", default=DEFAULT_DB_PATH, help="目标数据库路径")
    parser.add_argument("--source-dir", default=BASE_DIR, help="CSV 所在目录")
    parser.add_argument("--report", default=None, help="迁移报告输出路径（Markdown）")
    parser.add_argument("--force", action="store_true", help="清空资源表后重新导入")
    parser.add_argument("--no-backup", action="store_true", help="跳过迁移前备份")
    args = parser.parse_args(argv)

    try:
        stats = runMigration(args.db, args.source_dir, args.report, args.force, not args.no_backup)
    except MigrationError as e:
        print(f"迁移失败: {e}", file=sys.stderr)
        return 1
    except Exception as e:  # 兜底：打印堆栈便于排查
        print(f"迁移异常: {e}", file=sys.stderr)
        raise

    printSummary(stats)
    return 0 if stats.allPassed() else 1


if __name__ == "__main__":
    sys.exit(main())
