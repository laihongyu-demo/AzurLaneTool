"""
贸易许可证购买记录数据访问层模块。

封装 ``trade_license_purchase`` 的查询与写入；500 红尖尖明细仍由
``ResourceRepository`` 负责。
"""

import sqlite3
from typing import List, Optional

from models.trade_license_model import TradeLicensePurchaseModel
from repositories.base_repository import BaseRepository
from utils.db_connection import DatabaseConnection
from utils.exceptions import DatabaseError


class TradeLicenseRepository(BaseRepository[TradeLicensePurchaseModel]):
    """贸易许可证购买记录数据访问类。"""

    TABLE = "trade_license_purchase"

    def findAll(self) -> List[TradeLicensePurchaseModel]:
        """
        查询全部购买记录，按到期日升序。

        Returns:
            记录列表。

        Raises:
            DatabaseError: 查询失败时抛出。
        """
        sql = f"""
            SELECT id, purchase_time, start_date, end_date, days, amount,
                   transaction_id, note, created_at
            FROM {self.TABLE}
            ORDER BY end_date, id
        """
        try:
            rows = DatabaseConnection.executeQuery(sql)
            return [TradeLicensePurchaseModel.fromDict(row) for row in rows]
        except Exception as e:
            raise DatabaseError(f"查询贸易许可证记录失败: {e}")

    def findById(self, record_id: int) -> Optional[TradeLicensePurchaseModel]:
        """
        按 ID 查询购买记录。

        Args:
            record_id: 记录 ID。

        Returns:
            记录模型；不存在时返回 None。

        Raises:
            DatabaseError: 查询失败时抛出。
        """
        sql = f"""
            SELECT id, purchase_time, start_date, end_date, days, amount,
                   transaction_id, note, created_at
            FROM {self.TABLE}
            WHERE id = ?
        """
        try:
            rows = DatabaseConnection.executeQuery(sql, (record_id,))
            return TradeLicensePurchaseModel.fromDict(rows[0]) if rows else None
        except Exception as e:
            raise DatabaseError(f"查询贸易许可证记录失败: {e}")

    def findLatest(self) -> Optional[TradeLicensePurchaseModel]:
        """
        查询最近一条购买记录（按到期日、ID 倒序）。

        Returns:
            记录模型；无记录时返回 None。

        Raises:
            DatabaseError: 查询失败时抛出。
        """
        sql = f"""
            SELECT id, purchase_time, start_date, end_date, days, amount,
                   transaction_id, note, created_at
            FROM {self.TABLE}
            ORDER BY end_date DESC, id DESC
            LIMIT 1
        """
        try:
            rows = DatabaseConnection.executeQuery(sql)
            return TradeLicensePurchaseModel.fromDict(rows[0]) if rows else None
        except Exception as e:
            raise DatabaseError(f"查询贸易许可证记录失败: {e}")

    def insert(
        self,
        record: TradeLicensePurchaseModel,
        conn: Optional[sqlite3.Connection] = None,
    ) -> int:
        """
        写入一条购买记录。

        Args:
            record: 购买记录。
            conn: 可选的调用方连接。

        Returns:
            新记录 ID。

        Raises:
            DatabaseError: 写入失败时抛出。
        """
        sql = f"""
            INSERT INTO {self.TABLE}
                (purchase_time, start_date, end_date, days, amount,
                 transaction_id, note)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """
        params = (
            record.purchase_time, record.start_date, record.end_date, record.days,
            record.amount, record.transaction_id, record.note,
        )
        try:
            if conn is not None:
                return conn.execute(sql, params).lastrowid
            with self._getConnection() as own:
                return own.execute(sql, params).lastrowid
        except sqlite3.Error as e:
            raise DatabaseError(f"写入贸易许可证记录失败: {e}")

    def update(self, record: TradeLicensePurchaseModel) -> bool:
        """
        更新购买记录。

        Args:
            record: 记录模型，必须带 ID。

        Returns:
            是否有行被更新。

        Raises:
            DatabaseError: 更新失败时抛出。
        """
        if record.id is None:
            raise DatabaseError("更新贸易许可证记录需要有效 ID")
        sql = f"""
            UPDATE {self.TABLE}
               SET purchase_time = ?, start_date = ?, end_date = ?, days = ?,
                   amount = ?, transaction_id = ?, note = ?
             WHERE id = ?
        """
        params = (
            record.purchase_time, record.start_date, record.end_date, record.days,
            record.amount, record.transaction_id, record.note, record.id,
        )
        try:
            return DatabaseConnection.executeUpdate(sql, params) > 0
        except sqlite3.Error as e:
            raise DatabaseError(f"更新贸易许可证记录失败: {e}")

    def updateDates(
        self,
        record_id: int,
        start_date: str,
        end_date: str,
        days: int,
        conn: Optional[sqlite3.Connection] = None,
    ) -> bool:
        """
        更新最近一条记录的起止日与天数。

        Args:
            record_id: 记录 ID。
            start_date: 生效日。
            end_date: 到期日。
            days: 天数。
            conn: 可选的调用方连接。

        Returns:
            是否有行被更新。

        Raises:
            DatabaseError: 更新失败时抛出。
        """
        sql = f"""
            UPDATE {self.TABLE}
               SET start_date = ?, end_date = ?, days = ?
             WHERE id = ?
        """
        params = (start_date, end_date, days, record_id)
        try:
            if conn is not None:
                return conn.execute(sql, params).rowcount > 0
            return DatabaseConnection.executeUpdate(sql, params) > 0
        except sqlite3.Error as e:
            raise DatabaseError(f"更新贸易许可证日期失败: {e}")

    def delete(
        self, record_id: int, conn: Optional[sqlite3.Connection] = None
    ) -> bool:
        """
        删除一条购买记录。

        Args:
            record_id: 记录 ID。
            conn: 可选的调用方连接。

        Returns:
            是否有行被删除。

        Raises:
            DatabaseError: 删除失败时抛出。
        """
        sql = f"DELETE FROM {self.TABLE} WHERE id = ?"
        try:
            if conn is not None:
                return conn.execute(sql, (record_id,)).rowcount > 0
            return DatabaseConnection.executeUpdate(sql, (record_id,)) > 0
        except sqlite3.Error as e:
            raise DatabaseError(f"删除贸易许可证记录失败: {e}")
