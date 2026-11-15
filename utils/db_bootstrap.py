"""
首次使用数据库初始化模块。

把「没有数据库文件 / 旧库缺表」的初次使用场景补齐成一份可直接使用的空白模板：

1. 建数据库文件与父目录（``data/`` 不存在时一并创建）；
2. 建全部业务表：资源统计、魔方任务、贸易许可证、活动记录、图鉴 4 表、指挥官快照；
3. 写入可离线生成的种子：类型字典、任务定义、等级经验基准（``data/commander_level.csv``）；
4. 缺失时生成 ``data/user.json``（用户名 + 今日开始日期），让执勤天数有可计算起点。

已有数据一律不覆盖：种子只在目标表为空时写入，``user.json`` 只在文件缺失时创建。
打包运行（PyInstaller）时数据库与 ``user.json`` 落在 exe 同目录的 ``data/``，
等级经验 CSV 从资源目录（``_MEIPASS/data/``）读取，见 :mod:`utils.constants`。
"""

import csv
import json
import os
import sqlite3
from dataclasses import dataclass
from typing import List, Optional, Set, Tuple

from utils import time_source
from utils.constants import BASE_DIR
from utils.db_connection import DatabaseConnection, DatabaseContext
from utils.db_schema import (
    ensureCodexSchema,
    ensureCommanderSchema,
    ensureResourceStatisticsSchema,
)
from utils.exceptions import DatabaseError

# 等级经验基准：源文件在资源目录（随包携带），写入 commander_level_exp
LEVEL_EXP_CSV_NAME = "commander_level.csv"
# 本机用户数据：跟数据库同目录，缺失时自动生成
USER_FILE_NAME = "user.json"
DEFAULT_USER_NAME = "指挥官"


@dataclass(frozen=True)
class DatabaseInitReport:
    """
    一次数据库初始化的结果。

    Attributes:
        db_path: 数据库文件绝对路径。
        database_created: 本次是否新建了数据库文件（真正意义上的首次运行）。
        created_tables: 本次新建的表名（已有表不在其中）。
        level_exp_rows: 本次写入的等级经验基准行数；0 表示未写入（已有数据或源文件缺失）。
        user_file_path: ``user.json`` 路径。
        user_file_created: 本次是否新建了 ``user.json``。
    """

    db_path: str
    database_created: bool
    created_tables: Tuple[str, ...] = ()
    level_exp_rows: int = 0
    user_file_path: str = ""
    user_file_created: bool = False

    @property
    def table_count(self) -> int:
        """本次新建的表数量。"""
        return len(self.created_tables)


def ensureDatabaseReady(
    db_path: Optional[str] = None,
    level_exp_csv: Optional[str] = None,
    user_file: Optional[str] = None,
) -> DatabaseInitReport:
    """
    确保数据库可直接使用：建库、建表、写种子、补 ``user.json``。

    幂等：可重复调用。已有数据库只做结构升级与缺表补齐，种子不覆盖用户数据。

    Args:
        db_path: 可选的数据库路径，默认使用全局配置。
        level_exp_csv: 可选的等级经验 CSV 路径，默认 ``<资源目录>/data/commander_level.csv``。
        user_file: 可选的 ``user.json`` 路径，默认与数据库同目录。

    Returns:
        :class:`DatabaseInitReport`，供启动流程判断是否首次创建、展示提示。

    Raises:
        DatabaseError: 建表、写入种子或创建 ``user.json`` 失败时抛出。
    """
    path = os.path.abspath(db_path or DatabaseConnection.getDbPath())
    _ensureParentDir(path)

    database_created = not os.path.exists(path)
    if database_created:
        _touchDatabase(path)

    tables_before = _tableNames(path)
    ensureResourceStatisticsSchema(path)
    ensureCodexSchema(path)
    ensureCommanderSchema(path)
    created_tables = tuple(sorted(_tableNames(path) - tables_before))

    level_exp_rows = _seedCommanderLevelExpIfEmpty(
        path, level_exp_csv or _defaultLevelExpCsv()
    )
    user_path = os.path.abspath(
        user_file or os.path.join(os.path.dirname(path), USER_FILE_NAME)
    )
    user_created = _ensureUserFile(user_path)

    return DatabaseInitReport(
        db_path=path,
        database_created=database_created,
        created_tables=created_tables,
        level_exp_rows=level_exp_rows,
        user_file_path=user_path,
        user_file_created=user_created,
    )


def _defaultLevelExpCsv() -> str:
    """
    等级经验 CSV 的默认位置。

    Returns:
        资源目录下的 ``data/commander_level.csv`` 绝对路径。
    """
    return os.path.join(BASE_DIR, "data", LEVEL_EXP_CSV_NAME)


def _ensureParentDir(path: str) -> None:
    """
    确保文件所在目录存在。

    Args:
        path: 文件路径。

    Raises:
        DatabaseError: 目录创建失败时抛出。
    """
    parent = os.path.dirname(path)
    if parent and not os.path.isdir(parent):
        try:
            os.makedirs(parent, exist_ok=True)
        except OSError as e:
            raise DatabaseError(f"创建数据目录失败: {e}")


def _touchDatabase(path: str) -> None:
    """
    创建空的 SQLite 数据库文件。

    Args:
        path: 数据库路径。

    Raises:
        DatabaseError: 文件无法创建时抛出。
    """
    try:
        sqlite3.connect(path).close()
    except sqlite3.Error as e:
        raise DatabaseError(f"创建数据库文件失败: {e}")


def _tableNames(path: str) -> Set[str]:
    """
    读取数据库中的业务表名（排除 ``sqlite_*`` 内部表）。

    Args:
        path: 数据库路径。

    Returns:
        表名集合。

    Raises:
        DatabaseError: 读取失败（如文件损坏）时抛出。
    """
    try:
        with DatabaseContext(path) as conn:
            rows = conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
                " AND name NOT LIKE 'sqlite_%'"
            ).fetchall()
            return {row[0] for row in rows}
    except sqlite3.Error as e:
        raise DatabaseError(f"读取数据库表结构失败: {e}")


def _seedCommanderLevelExpIfEmpty(path: str, csv_path: str) -> int:
    """
    等级经验表为空时，从 CSV 写入基准数据。

    只在表为空时写入：已有数据（含后续人工修正）不会被启动流程覆盖。
    CSV 缺失时跳过并返回 0，不影响其它表初始化。

    Args:
        path: 数据库路径。
        csv_path: ``commander_level.csv`` 路径。

    Returns:
        本次写入的行数。

    Raises:
        DatabaseError: CSV 解析失败或写库失败时抛出。
    """
    try:
        with DatabaseContext(path) as conn:
            existing = conn.execute(
                "SELECT COUNT(*) FROM commander_level_exp"
            ).fetchone()[0]
            if existing:
                return 0
            rows = _readCommanderLevelExp(csv_path)
            if not rows:
                return 0
            conn.executemany(
                "INSERT OR REPLACE INTO commander_level_exp"
                " (level, level_up_exp, cumulative_exp, note) VALUES (?, ?, ?, ?)",
                rows,
            )
            return len(rows)
    except sqlite3.Error as e:
        raise DatabaseError(f"写入等级经验基准失败: {e}")


def _readCommanderLevelExp(csv_path: str) -> List[Tuple[int, Optional[int], Optional[int], str]]:
    """
    解析等级经验 CSV。

    表头为「等级 / 本次升级所需经验 / 与上一级所需经验差值 / 升级累计所需经验」。
    满级行（如 200 级）的经验列是「当前版本最高等级」这类非数字文本：
    经验写 NULL，文本写入 ``note``，与迁移脚本口径一致。

    Args:
        csv_path: CSV 路径。

    Returns:
        ``(level, level_up_exp, cumulative_exp, note)`` 元组列表；文件不存在时为空列表。

    Raises:
        DatabaseError: 文件读取或解析失败时抛出。
    """
    if not os.path.exists(csv_path):
        return []

    parsed: List[Tuple[int, Optional[int], Optional[int], str]] = []
    try:
        with open(csv_path, "r", encoding="utf-8-sig", newline="") as fp:
            reader = csv.DictReader(fp)
            for row in reader:
                level_text = (row.get("等级") or "").strip()
                if not level_text.isdigit():
                    continue
                level_up_text = (row.get("本次升级所需经验") or "").strip()
                cumulative_text = (row.get("升级累计所需经验") or "").strip()
                level_up = int(level_up_text) if level_up_text.isdigit() else None
                cumulative = int(cumulative_text) if cumulative_text.isdigit() else None
                note = "" if level_up_text.isdigit() else level_up_text
                parsed.append((int(level_text), level_up, cumulative, note))
    except (OSError, csv.Error) as e:
        raise DatabaseError(f"读取等级经验基准失败: {e}")
    except (KeyError, ValueError) as e:
        raise DatabaseError(f"解析等级经验基准失败: {e}")
    return parsed


def _ensureUserFile(path: str) -> bool:
    """
    ``user.json`` 缺失时生成默认内容（用户名 + 今日开始日期）。

    已有文件一律不动，避免覆盖用户自己维护的执勤开始日期。

    Args:
        path: ``user.json`` 路径。

    Returns:
        本次是否新建。

    Raises:
        DatabaseError: 写入失败时抛出。
    """
    if os.path.exists(path):
        return False

    _ensureParentDir(path)
    content = {
        "username": DEFAULT_USER_NAME,
        "start_date": time_source.today().isoformat(),
    }
    try:
        with open(path, "w", encoding="utf-8") as fp:
            json.dump(content, fp, ensure_ascii=False, indent=4)
            fp.write("\n")
    except OSError as e:
        raise DatabaseError(f"创建用户数据文件失败: {e}")
    return True
