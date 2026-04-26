"""
基础数据访问层模块。

提供所有 Repository 的基类，封装通用的数据库操作。
"""

from abc import ABC, abstractmethod
from typing import List, Optional, TypeVar, Generic

from utils.db_connection import DatabaseConnection, DatabaseContext

T = TypeVar('T')


class BaseRepository(ABC, Generic[T]):
    """
    数据访问层基类。

    所有 Repository 类应继承此类，实现具体的 CRUD 操作。
    """

    def __init__(self, db_path: Optional[str] = None):
        """
        初始化 Repository。

        Args:
            db_path: 可选的数据库路径。
        """
        self._db_path = db_path

    @property
    def dbPath(self) -> str:
        return self._db_path or DatabaseConnection.getDbPath()

    def _getConnection(self):
        """
        获取数据库连接上下文管理器。

        Returns:
            DatabaseContext 实例。
        """
        return DatabaseContext(self.dbPath)

    @abstractmethod
    def findAll(self) -> List[T]:
        """
        查询所有记录。

        Returns:
            记录列表。
        """
        pass

    @abstractmethod
    def findById(self, record_id: int) -> Optional[T]:
        """
        根据 ID 查询单条记录。

        Args:
            record_id: 记录 ID。

        Returns:
            记录实例，不存在则返回 None。
        """
        pass

    @abstractmethod
    def insert(self, record: T) -> int:
        """
        插入新记录。

        Args:
            record: 要插入的记录实例。

        Returns:
            新记录的 ID。
        """
        pass

    @abstractmethod
    def update(self, record: T) -> bool:
        """
        更新记录。

        Args:
            record: 要更新的记录实例。

        Returns:
            更新是否成功。
        """
        pass

    @abstractmethod
    def delete(self, record_id: int) -> bool:
        """
        删除记录。

        Args:
            record_id: 要删除的记录 ID。

        Returns:
            删除是否成功。
        """
        pass
