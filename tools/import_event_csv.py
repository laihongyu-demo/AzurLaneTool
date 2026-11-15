"""活动记录一次性导入脚本。

把根目录 ``event.csv`` 的历史活动统计导入 ``event_record`` 表。

口径（见 docs/20261022_活动记录方案与导入报告.md）：

- CSV 的 ``抽数`` 列导入为 ``build_count``（建造次数）；其中的 ``0`` 表示
  「没有统计到具体次数」，导入为 NULL（未统计），0 次与未统计在界面上分开展示；
- 空活动名、空状态、空备注原样保留；
- 同一活动拆成多个卡池时按行独立导入，不做合并；
- 整批写入在同一个事务里完成，任一行校验失败则整批回滚。

用法::

    python tools/import_event_csv.py                 # 预演：只解析与统计，不写库
    python tools/import_event_csv.py --apply         # 正式导入（自动备份数据库）
    python tools/import_event_csv.py --csv event.csv --db data/AzurLaneStatisticalOfficeDB.db --apply

脚本只在 ``event_record`` 为空时写入；已有数据时直接退出，避免重复导入。
"""

import argparse
import csv
import io
import os
import re
import shutil
import sys
from collections import Counter
from datetime import date, datetime
from typing import Dict, List, Optional, Tuple

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from models.event_model import EventRecordModel  # noqa: E402
from services.event_record_service import EventRecordService  # noqa: E402
from utils.constants import (  # noqa: E402
    DEFAULT_DB_PATH, EVENT_STATUS_GRADUATED, EVENT_STATUS_MISSING, EVENT_STATUS_ONGOING,
    RECORD_DATE_FORMAT,
)
from utils.db_connection import DatabaseConnection  # noqa: E402
from utils.db_schema import ensureResourceStatisticsSchema  # noqa: E402

CSV_HEADERS = ("活动日期", "类型", "活动", "状态", "状态备注", "备注")
# 建造次数列的兼容写法：新表可能用「建造次数」，历史 CSV 用「抽数」
BUILD_COUNT_HEADERS = ("建造次数", "抽数")
DATE_PATTERN = re.compile(r"^(\d{4})/(\d{1,2})/(\d{1,2})$")


class EventImportError(Exception):
    """导入前的数据校验错误。"""


def parseDate(text: str) -> str:
    """
    把 ``yyyy/M/d`` 转成 ``yyyy-MM-dd``。

    Args:
        text: CSV 中的日期文本。

    Returns:
        规范化日期。

    Raises:
        ValueError: 格式或日期非法时抛出。
    """
    matched = DATE_PATTERN.match((text or "").strip())
    if not matched:
        raise ValueError(f"日期格式应为 yyyy/M/d：{text!r}")
    year, month, day = (int(value) for value in matched.groups())
    return date(year, month, day).strftime(RECORD_DATE_FORMAT)


def parseEventCsv(path: str) -> Tuple[List[EventRecordModel], List[str]]:
    """
    解析活动 CSV。

    Args:
        path: CSV 路径（UTF-8，允许 BOM）。

    Returns:
        ``(记录列表, 问题列表)``；问题列表非空时调用方应放弃导入。

    Raises:
        EventImportError: 文件不存在或表头不匹配时抛出。
    """
    if not os.path.exists(path):
        raise EventImportError(f"CSV 文件不存在：{path}")

    with io.open(path, "r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        headers = tuple(reader.fieldnames or ())
        missing = [name for name in CSV_HEADERS if name not in headers]
        if not any(name in headers for name in BUILD_COUNT_HEADERS):
            missing.append("建造次数（兼容旧列名「抽数」）")
        if missing:
            raise EventImportError(f"CSV 缺少列：{'、'.join(missing)}")

        records: List[EventRecordModel] = []
        issues: List[str] = []
        for line_no, row in enumerate(reader, start=2):
            try:
                event_date = parseDate(row.get("活动日期", ""))
            except ValueError as e:
                issues.append(f"第 {line_no} 行：{e}")
                continue

            build_count_text = (
                row.get("建造次数") or row.get("抽数") or ""
            ).strip()
            build_count: Optional[int]
            if not build_count_text:
                build_count = None
            else:
                try:
                    build_count = int(build_count_text)
                except ValueError:
                    issues.append(
                        f"第 {line_no} 行：建造次数不是整数：{build_count_text!r}"
                    )
                    continue
                if build_count < 0:
                    issues.append(f"第 {line_no} 行：建造次数为负数：{build_count}")
                    continue
                # CSV 的 0 表示「没有统计到具体次数」，按未统计导入
                if build_count == 0:
                    build_count = None

            records.append(
                EventRecordModel(
                    event_date=event_date,
                    event_type=(row.get("类型") or "").strip(),
                    name=(row.get("活动") or "").strip(),
                    status=(row.get("状态") or "").strip(),
                    status_note=(row.get("状态备注") or "").strip(),
                    build_count=build_count,
                    note=(row.get("备注") or "").strip(),
                )
            )

    return records, issues


def describe(records: List[EventRecordModel]) -> str:
    """
    生成导入内容摘要（用于预演与结果核对）。

    Args:
        records: 解析后的记录。

    Returns:
        多行摘要文本。
    """
    statuses = Counter(record.status or "未标记" for record in records)
    dates = [record.event_date for record in records]
    build_counts = [
        record.build_count for record in records if record.build_count is not None
    ]
    blank_names = sum(1 for record in records if not record.name)
    lines = [
        f"记录数：{len(records)}",
        f"日期范围：{min(dates)} ~ {max(dates)}" if dates else "日期范围：-",
        f"状态分布：毕业 {statuses.get(EVENT_STATUS_GRADUATED, 0)}｜"
        f"缺 {statuses.get(EVENT_STATUS_MISSING, 0)}｜"
        f"进行中 {statuses.get(EVENT_STATUS_ONGOING, 0)}｜"
        f"未标记 {statuses.get('未标记', 0)}",
        f"建造次数：已统计 {len(build_counts)} 条 / 合计 {sum(build_counts)}；"
        f"未统计 {len(records) - len(build_counts)} 条",
        f"空活动名：{blank_names} 条",
    ]
    return "\n".join(lines)


def backupDatabase(db_path: str) -> Optional[str]:
    """
    把数据库复制到 ``data/backup`` 下，文件名带时间戳。

    Args:
        db_path: 数据库路径。

    Returns:
        备份文件路径；数据库不存在时返回 None。
    """
    if not os.path.exists(db_path):
        return None
    backup_dir = os.path.join(PROJECT_ROOT, "data", "backup")
    os.makedirs(backup_dir, exist_ok=True)
    stem = os.path.splitext(os.path.basename(db_path))[0]
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = os.path.join(backup_dir, f"{stem}_event_import_{stamp}.db")
    shutil.copy2(db_path, backup_path)
    return backup_path


def verifyImport(db_path: str, expected: List[EventRecordModel]) -> Dict[str, object]:
    """
    从库里回读并核对导入结果。

    Args:
        db_path: 数据库路径。
        expected: 解析出的期望记录。

    Returns:
        核对结果字典。

    Raises:
        EventImportError: 数量或建造次数合计不一致时抛出。
    """
    import sqlite3

    conn = sqlite3.connect(db_path)
    try:
        total = conn.execute("SELECT COUNT(*) FROM event_record").fetchone()[0]
        date_range = conn.execute(
            "SELECT MIN(event_date), MAX(event_date) FROM event_record"
        ).fetchone()
        build_count_total = conn.execute(
            "SELECT COALESCE(SUM(build_count), 0), COUNT(build_count) FROM event_record"
        ).fetchone()
        statuses = dict(
            conn.execute("SELECT status, COUNT(*) FROM event_record GROUP BY status")
        )
    finally:
        conn.close()

    expected_build_count = sum(
        record.build_count for record in expected if record.build_count is not None
    )
    expected_known = sum(1 for record in expected if record.build_count is not None)
    if total != len(expected):
        raise EventImportError(f"导入数量不一致：期望 {len(expected)}，实际 {total}")
    if (
        int(build_count_total[0]) != expected_build_count
        or int(build_count_total[1]) != expected_known
    ):
        raise EventImportError(
            f"建造次数核对不一致：期望合计 {expected_build_count} / {expected_known} 条，"
            f"实际 {build_count_total[0]} / {build_count_total[1]} 条"
        )

    return {
        "total": total,
        "date_range": date_range,
        "build_count_total": int(build_count_total[0]),
        "build_count_known": int(build_count_total[1]),
        "statuses": statuses,
    }


def main() -> int:
    """
    脚本入口。

    Returns:
        进程退出码：0 成功 / 1 数据或库状态不满足 / 2 参数或 CSV 错误。
    """
    parser = argparse.ArgumentParser(description="导入 event.csv 到活动记录表")
    parser.add_argument(
        "--csv", default=os.path.join(PROJECT_ROOT, "event.csv"), help="活动 CSV 路径"
    )
    parser.add_argument("--db", default=DEFAULT_DB_PATH, help="目标数据库路径")
    parser.add_argument(
        "--apply", action="store_true", help="正式写入；不加时只预演解析结果"
    )
    args = parser.parse_args()

    try:
        records, issues = parseEventCsv(args.csv)
    except EventImportError as e:
        print(f"[错误] {e}")
        return 2

    if issues:
        print("[错误] CSV 存在无法解析的行：")
        for issue in issues:
            print(f"  - {issue}")
        return 2
    if not records:
        print("[错误] CSV 没有可导入的记录")
        return 2

    print(f"CSV：{args.csv}")
    print(f"目标库：{args.db}")
    print(describe(records))

    if not args.apply:
        print("\n预演完成，未写入数据库。确认无误后加 --apply 执行。")
        return 0

    DatabaseConnection.setDbPath(args.db)
    ensureResourceStatisticsSchema(args.db)
    service = EventRecordService()

    existing = service.countAll()
    if existing:
        print(f"\n[跳过] event_record 已有 {existing} 条记录，未重复导入。")
        return 1

    backup_path = backupDatabase(args.db)
    if backup_path:
        print(f"\n已备份数据库：{backup_path}")

    try:
        imported = service.importRecords(records)
        result = verifyImport(args.db, records)
    except EventImportError as e:
        print(f"\n[错误] {e}")
        return 1
    except Exception as e:  # noqa: BLE001 - 一次性脚本，给出明确原因即可
        print(f"\n[错误] 导入失败：{e}")
        return 1

    print(f"\n导入完成：{imported} 条")
    print(f"回读核对：{result['total']} 条｜{result['date_range'][0]} ~ "
          f"{result['date_range'][1]}｜建造次数合计 {result['build_count_total']}"
          f"（{result['build_count_known']} 条已统计）")
    print(f"状态分布：{result['statuses']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
