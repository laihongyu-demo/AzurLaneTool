"""
数据库表结构引导模块。

负责在应用启动时确保资源统计相关表存在（幂等 DDL），
并提供"表不存在"异常的识别辅助，供业务层做降级处理。
"""

from typing import Optional

from utils.db_connection import DatabaseConnection, DatabaseContext
from utils.sql_loader import loadSqlFile

RESOURCE_SCHEMA_FILE = "CreateResourceStatisticsTables.sql"


def ensureResourceStatisticsSchema(db_path: Optional[str] = None) -> None:
    """
    确保资源统计相关表与索引存在。

    执行 ``sql/CreateResourceStatisticsTables.sql``，脚本内全部为 ``IF NOT EXISTS``，
    可重复调用；不会修改既有表结构。

    Args:
        db_path: 可选的数据库路径，默认使用全局配置。

    Raises:
        DatabaseError: 当 SQL 文件缺失或执行失败时抛出。
    """
    sql = loadSqlFile(RESOURCE_SCHEMA_FILE)
    path = db_path or DatabaseConnection.getDbPath()
    with DatabaseContext(path) as conn:
        conn.executescript(sql)


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
