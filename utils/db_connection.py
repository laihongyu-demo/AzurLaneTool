"""
数据库连接管理模块。

提供数据库连接的创建、管理和上下文管理器支持。
支持线程安全的单例模式和连接复用。
"""

import os
import sqlite3
import threading
from typing import Optional, Set

from utils.constants import DEFAULT_DB_PATH, DATA_DIR
from utils.exceptions import DatabaseError, ConnectionError, SecurityError
from utils.logger import log


ALLOWED_TABLES: Set[str] = frozenset({
    "ships",
    "codex_group",
    "codex_tp",
    "codex_buff",
    "user",
    "awakening_of_mind"
})


def validateTableName(table_name: str) -> str:
    """
    验证表名是否在白名单中。

    Args:
        table_name: 要验证的表名。

    Returns:
        验证通过的表名。

    Raises:
        SecurityError: 当表名不在白名单中时抛出。
    """
    if table_name not in ALLOWED_TABLES:
        log.warning(
            f"检测到非法表名访问尝试",
            extra={"operation": "validateTableName", "table_name": table_name}
        )
        raise SecurityError(
            message="非法的表名访问",
            operation="validateTableName",
            details={"table_name": table_name}
        )
    return table_name


class DatabaseConnection:
    """
    数据库连接管理类。

    提供线程安全的单例模式和连接管理，支持上下文管理器。
    使用线程局部存储实现连接复用。
    """

    _instance: Optional['DatabaseConnection'] = None
    _lock: threading.Lock = threading.Lock()
    _db_path: str = DEFAULT_DB_PATH
    _thread_local: threading.local = threading.local()

    def __new__(cls) -> 'DatabaseConnection':
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    log.debug("DatabaseConnection 单例实例已创建")
        return cls._instance

    @classmethod
    def setDbPath(cls, db_path: str) -> None:
        """
        设置数据库文件路径。

        Args:
            db_path: 数据库文件的完整路径。
        """
        cls._db_path = db_path
        log.info(f"数据库路径已设置: {db_path}")

    @classmethod
    def getDbPath(cls) -> str:
        """
        获取当前数据库文件路径。

        Returns:
            当前数据库文件路径。
        """
        return cls._db_path

    @classmethod
    def getConnection(cls) -> sqlite3.Connection:
        """
        获取数据库连接（线程局部存储）。

        使用线程局部存储实现连接复用，避免频繁创建和销毁连接。

        Returns:
            SQLite 数据库连接对象。

        Raises:
            ConnectionError: 当数据库连接失败时抛出。
        """
        try:
            if hasattr(cls._thread_local, 'conn') and cls._thread_local.conn is not None:
                try:
                    cls._thread_local.conn.execute("SELECT 1")
                    return cls._thread_local.conn
                except sqlite3.Error:
                    cls._thread_local.conn = None

            db_dir = os.path.dirname(cls._db_path)
            if db_dir and not os.path.exists(db_dir):
                os.makedirs(db_dir, exist_ok=True)

            conn = sqlite3.connect(cls._db_path, check_same_thread=False)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA foreign_keys=ON")

            cls._thread_local.conn = conn
            log.debug(f"数据库连接已创建: {cls._db_path}")
            return conn

        except sqlite3.Error as e:
            log.error(f"数据库连接失败: {e}")
            raise ConnectionError(
                message="数据库连接失败",
                db_path=cls._db_path,
                original_error=e
            )

    @classmethod
    def closeConnection(cls) -> None:
        """关闭当前线程的数据库连接。"""
        if hasattr(cls._thread_local, 'conn') and cls._thread_local.conn is not None:
            try:
                cls._thread_local.conn.close()
                log.debug("数据库连接已关闭")
            except sqlite3.Error as e:
                log.warning(f"关闭数据库连接时出错: {e}")
            finally:
                cls._thread_local.conn = None

    @classmethod
    def executeQuery(cls, sql: str, params: tuple = ()) -> list:
        """
        执行查询语句并返回结果。

        Args:
            sql: SQL 查询语句。
            params: 查询参数元组。

        Returns:
            查询结果列表，每项为字典形式。

        Raises:
            DatabaseError: 当查询执行失败时抛出。
        """
        try:
            with cls.getConnection() as conn:
                cursor = conn.execute(sql, params)
                return [dict(row) for row in cursor.fetchall()]
        except sqlite3.Error as e:
            log.error(f"查询执行失败: {e}", extra={"sql": sql, "params": params})
            raise DatabaseError(
                message="查询执行失败",
                sql=sql,
                params=params,
                original_error=e
            )

    @classmethod
    def executeUpdate(cls, sql: str, params: tuple = ()) -> int:
        """
        执行更新语句并返回影响的行数。

        Args:
            sql: SQL 更新语句。
            params: 更新参数元组。

        Returns:
            影响的行数。

        Raises:
            DatabaseError: 当更新执行失败时抛出。
        """
        try:
            with cls.getConnection() as conn:
                cursor = conn.execute(sql, params)
                conn.commit()
                log.debug(f"更新执行成功，影响行数: {cursor.rowcount}")
                return cursor.rowcount
        except sqlite3.Error as e:
            log.error(f"更新执行失败: {e}", extra={"sql": sql, "params": params})
            raise DatabaseError(
                message="更新执行失败",
                sql=sql,
                params=params,
                original_error=e
            )


class DatabaseContext:
    """
    数据库连接上下文管理器。

    用于简化数据库连接的获取和释放，支持事务管理。
    """

    def __init__(self, db_path: Optional[str] = None):
        """
        初始化上下文管理器。

        Args:
            db_path: 可选的数据库路径，默认使用全局配置。
        """
        self._db_path = db_path or DatabaseConnection.getDbPath()
        self._conn: Optional[sqlite3.Connection] = None

    def __enter__(self) -> sqlite3.Connection:
        try:
            self._conn = sqlite3.connect(self._db_path)
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA journal_mode=WAL")
            return self._conn
        except sqlite3.Error as e:
            log.error(f"创建数据库上下文连接失败: {e}")
            raise ConnectionError(
                message="创建数据库连接失败",
                db_path=self._db_path,
                original_error=e
            )

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        if self._conn:
            if exc_type is None:
                try:
                    self._conn.commit()
                    log.debug("事务已提交")
                except sqlite3.Error as e:
                    log.error(f"事务提交失败: {e}")
                    self._conn.rollback()
                    raise DatabaseError(
                        message="事务提交失败",
                        original_error=e
                    )
            else:
                log.warning(
                    f"事务回滚: {exc_type.__name__ if exc_type else 'Unknown'}: {exc_val}"
                )
                self._conn.rollback()

            self._conn.close()
            self._conn = None
