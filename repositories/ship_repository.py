"""
船舶数据访问层模块。

封装船舶相关的数据库 CRUD 操作。
"""

import sqlite3
from typing import List, Optional

from models.ship_model import ShipModel
from repositories.base_repository import BaseRepository
from utils.exceptions import DatabaseError


class ShipRepository(BaseRepository[ShipModel]):
    """
    船舶数据访问类。

    提供船舶数据的增删改查操作。
    """

    TABLE_NAME = "ships"

    def findAll(self) -> List[ShipModel]:
        """
        查询所有船舶记录。

        Returns:
            船舶模型列表。

        Raises:
            DatabaseError: 当查询失败时抛出。
        """
        sql = f"""
            SELECT id, name, capacity, launch_date, status
            FROM {self.TABLE_NAME}
            ORDER BY id
        """
        try:
            results = DatabaseConnection.executeQuery(sql)
            return [ShipModel.fromDict(row) for row in results]
        except Exception as e:
            raise DatabaseError(f"查询船舶列表失败: {e}")

    def findById(self, record_id: int) -> Optional[ShipModel]:
        """
        根据 ID 查询单条船舶记录。

        Args:
            record_id: 船舶 ID。

        Returns:
            船舶模型实例，不存在则返回 None。

        Raises:
            DatabaseError: 当查询失败时抛出。
        """
        sql = f"""
            SELECT id, name, capacity, launch_date, status
            FROM {self.TABLE_NAME}
            WHERE id = ?
        """
        try:
            results = DatabaseConnection.executeQuery(sql, (record_id,))
            if results:
                return ShipModel.fromDict(results[0])
            return None
        except Exception as e:
            raise DatabaseError(f"查询船舶详情失败: {e}")

    def insert(self, record: ShipModel) -> int:
        """
        插入新船舶记录。

        Args:
            record: 船舶模型实例。

        Returns:
            新记录的 ID。

        Raises:
            DatabaseError: 当插入失败时抛出。
        """
        sql = f"""
            INSERT INTO {self.TABLE_NAME} (name, capacity, launch_date, status)
            VALUES (?, ?, ?, ?)
        """
        params = (
            record.name,
            record.capacity,
            record.launch_date.isoformat() if record.launch_date else None,
            record.status
        )
        try:
            with self._getConnection() as conn:
                cursor = conn.execute(sql, params)
                return cursor.lastrowid
        except sqlite3.Error as e:
            raise DatabaseError(f"插入船舶记录失败: {e}")

    def update(self, record: ShipModel) -> bool:
        """
        更新船舶记录。

        Args:
            record: 船舶模型实例。

        Returns:
            更新是否成功。

        Raises:
            DatabaseError: 当更新失败时抛出。
        """
        if record.id is None:
            raise DatabaseError("更新操作需要有效的 ID")

        sql = f"""
            UPDATE {self.TABLE_NAME}
            SET name = ?, capacity = ?, launch_date = ?, status = ?
            WHERE id = ?
        """
        params = (
            record.name,
            record.capacity,
            record.launch_date.isoformat() if record.launch_date else None,
            record.status,
            record.id
        )
        try:
            rowcount = DatabaseConnection.executeUpdate(sql, params)
            return rowcount > 0
        except Exception as e:
            raise DatabaseError(f"更新船舶记录失败: {e}")

    def delete(self, record_id: int) -> bool:
        """
        删除船舶记录。

        Args:
            record_id: 船舶 ID。

        Returns:
            删除是否成功。

        Raises:
            DatabaseError: 当删除失败时抛出。
        """
        sql = f"DELETE FROM {self.TABLE_NAME} WHERE id = ?"
        try:
            rowcount = DatabaseConnection.executeUpdate(sql, (record_id,))
            return rowcount > 0
        except Exception as e:
            raise DatabaseError(f"删除船舶记录失败: {e}")

    def findByStatus(self, status: str) -> List[ShipModel]:
        """
        根据状态查询船舶列表。

        Args:
            status: 船舶状态。

        Returns:
            船舶模型列表。
        """
        sql = f"""
            SELECT id, name, capacity, launch_date, status
            FROM {self.TABLE_NAME}
            WHERE status = ?
            ORDER BY id
        """
        try:
            results = DatabaseConnection.executeQuery(sql, (status,))
            return [ShipModel.fromDict(row) for row in results]
        except Exception as e:
            raise DatabaseError(f"查询船舶列表失败: {e}")

    def count(self) -> int:
        """
        统计船舶总数。

        Returns:
            船舶总数。
        """
        sql = f"SELECT COUNT(*) as count FROM {self.TABLE_NAME}"
        try:
            results = DatabaseConnection.executeQuery(sql)
            return results[0]['count'] if results else 0
        except Exception as e:
            raise DatabaseError(f"统计船舶数量失败: {e}")
