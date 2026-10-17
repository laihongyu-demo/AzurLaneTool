"""
数据库表结构引导模块。

负责在应用启动时确保资源统计相关表存在（幂等 DDL），并把早期版本的表结构
就地升级到当前口径（明细精确到秒），同时提供"表 / 列不存在"异常的识别辅助。
"""

import sqlite3
from typing import Optional, Set

from utils.db_connection import DatabaseConnection, DatabaseContext
from utils.sql_loader import loadSqlFile

RESOURCE_SCHEMA_FILE = "CreateResourceStatisticsTables.sql"

# 仅日期（yyyy-MM-dd）的写法长度；用于识别需要补时分秒的旧值
LEGACY_DATE_LENGTH = 10


def ensureResourceStatisticsSchema(db_path: Optional[str] = None) -> None:
    """
    确保资源统计相关表与索引存在，并把旧结构升级到当前口径。

    执行 ``sql/CreateResourceStatisticsTables.sql``（全部 ``IF NOT EXISTS``），
    随后运行幂等升级步骤：

    - 明细的 ``record_date``（仅日期）→ ``record_time``（``yyyy-MM-dd HH:mm:ss``）
    - 日汇总补齐 ``last_record_time``（该日最后一笔的准确时刻）
    - 重建明细上的时间索引

    可重复调用；不会破坏既有数据。

    Args:
        db_path: 可选的数据库路径，默认使用全局配置。

    Raises:
        DatabaseError: 当 SQL 文件缺失或执行失败时抛出。
    """
    sql = loadSqlFile(RESOURCE_SCHEMA_FILE)
    path = db_path or DatabaseConnection.getDbPath()
    with DatabaseContext(path) as conn:
        # 先升级旧结构：表不存在时各步骤自动跳过，不会误建/误改
        _upgradeLegacySchema(conn)
        conn.executescript(sql)
        _backfillLastRecordTime(conn)


def _tableColumns(conn: sqlite3.Connection, table: str) -> Set[str]:
    """
    读取表的列名集合。

    Args:
        conn: 数据库连接。
        table: 表名。

    Returns:
        列名集合；表不存在时返回空集合（PRAGMA 不抛错）。
    """
    try:
        return {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
    except sqlite3.Error:
        return set()


def _upgradeLegacySchema(conn: sqlite3.Connection) -> None:
    """
    把 v0.2 的表结构就地升级为「明细精确到秒」的当前口径。

    只做列级调整，不创建索引与表（那些交给 SQL 脚本，保证全新库与旧库走同一份定义）。
    全部步骤都以列是否存在为前提，因此可重复执行。

    Args:
        conn: 数据库连接。
    """
    transaction_columns = _tableColumns(conn, "resource_transaction")
    if "record_date" in transaction_columns and "record_time" not in transaction_columns:
        conn.execute("ALTER TABLE resource_transaction RENAME COLUMN record_date TO record_time")
        conn.execute(
            "UPDATE resource_transaction SET record_time = record_time || ' 00:00:00'"
            " WHERE length(record_time) = ?",
            (LEGACY_DATE_LENGTH,),
        )

    # 旧索引名与新口径不符，统一由 SQL 脚本重建为 idx_resource_transaction_time
    conn.execute("DROP INDEX IF EXISTS idx_resource_transaction_date")

    daily_columns = _tableColumns(conn, "resource_daily")
    if daily_columns and "last_record_time" not in daily_columns:
        conn.execute("ALTER TABLE resource_daily ADD COLUMN last_record_time TEXT")


def _backfillLastRecordTime(conn: sqlite3.Connection) -> None:
    """
    为明细日回填「最后一笔时刻」。

    历史数据的时刻统一为 00:00:00，展示层会退化为仅日期；
    后续正常录入（#17）会在写入时维护该列。

    Args:
        conn: 数据库连接。
    """
    daily_columns = _tableColumns(conn, "resource_daily")
    if "last_record_time" not in daily_columns:
        return

    conn.execute(
        """
        UPDATE resource_daily
           SET last_record_time = (
               SELECT MAX(t.record_time) FROM resource_transaction t
                WHERE t.resource_type = resource_daily.resource_type
                  AND substr(t.record_time, 1, 10) = resource_daily.record_date
           )
         WHERE detail_mode = 'detail' AND last_record_time IS NULL
        """
    )


def isMissingTableError(exc: Exception) -> bool:
    """
    判断异常是否由"表不存在"引起。

    迁移尚未执行、或用户使用旧库时，新表可能缺失。业务层据此降级为空结果，
    而不是把数据库异常抛到界面上。

    Args:
        exc: 捕获到的异常。

    Returns:
        是"no such table"类错误返回 True。
    """
    return "no such table" in str(exc).lower()


def isMissingColumnError(exc: Exception) -> bool:
    """
    判断异常是否由"列不存在"引起。

    结构升级未执行时可能出现，业务层同样按降级处理。

    Args:
        exc: 捕获到的异常。

    Returns:
        是"no such column"类错误返回 True。
    """
    return "no such column" in str(exc).lower()
