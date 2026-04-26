"""
数据库连接管理模块。

提供数据库连接的创建、管理和上下文管理器支持。
"""

import os
import sqlite3
from typing import Optional

from utils.constants import DEFAULT_DB_PATH, DATA_DIR
from utils.exceptions import DatabaseError, ConnectionError


class DatabaseConnection:
    """
    数据库连接管理类。

    提供单例模式的数据库连接管理，支持上下文管理器。
    """

    _instance: Optional['DatabaseConnection'] = None
    _db_path: str = DEFAULT_DB_PATH

    def __new__(cls) -> 'DatabaseConnection':
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    @classmethod
    def setDbPath(cls, db_path: str) -> None:
        """
        设置数据库文件路径。

        Args:
            db_path: 数据库文件的完整路径。
        """
        cls._db_path = db_path

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
        获取数据库连接。

        Returns:
            SQLite 数据库连接对象。

        Raises:
            ConnectionError: 当数据库连接失败时抛出。
        """
        try:
            db_dir = os.path.dirname(cls._db_path)
            if db_dir and not os.path.exists(db_dir):
                os.makedirs(db_dir, exist_ok=True)

            conn = sqlite3.connect(cls._db_path)
            conn.row_factory = sqlite3.Row
            return conn
        except sqlite3.Error as e:
            raise ConnectionError(f"数据库连接失败: {e}")

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
            raise DatabaseError(f"查询执行失败: {e}")

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
                return cursor.rowcount
        except sqlite3.Error as e:
            raise DatabaseError(f"更新执行失败: {e}")


class DatabaseContext:
    """
    数据库连接上下文管理器。

    用于简化数据库连接的获取和释放。
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
        self._conn = sqlite3.connect(self._db_path)
        self._conn.row_factory = sqlite3.Row
        return self._conn

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        if self._conn:
            if exc_type is None:
                self._conn.commit()
            else:
                self._conn.rollback()
            self._conn.close()
