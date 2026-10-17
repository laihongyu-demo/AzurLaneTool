"""
资源统计数据访问层模块。

封装魔方 / 红尖尖的日汇总、明细与事件字典的读写操作。

写入能力目前只由「魔方任务看板」使用（完成 / 取消任务时增删明细并维护日汇总）；
#17 的通用手工录入上线后可直接复用同一套方法。
"""

import sqlite3
from typing import Any, Dict, List, Optional, Set

from models.resource_model import (
    ResourceCategoryModel, ResourceDailyModel, ResourceTransactionModel
)
from repositories.base_repository import BaseRepository
from utils.db_connection import DatabaseConnection
from utils.exceptions import DatabaseError


class ResourceRepository(BaseRepository[ResourceDailyModel]):
    """
    资源统计数据访问类。

    日汇总与明细分别对应 ``resource_daily`` / ``resource_transaction``，
    事件字典对应 ``resource_category``。
    """

    DAILY_TABLE = "resource_daily"
    TRANSACTION_TABLE = "resource_transaction"
    CATEGORY_TABLE = "resource_category"

    def findAll(self) -> List[ResourceDailyModel]:
        """
        查询全部日汇总行。

        Returns:
            日汇总模型列表，按资源类型、日期升序。

        Raises:
            DatabaseError: 当查询失败时抛出。
        """
        sql = f"""
            SELECT id, resource_type, record_date, detail_mode, income, expense,
                   balance_override, note, last_record_time, created_at, updated_at
            FROM {self.DAILY_TABLE}
            ORDER BY resource_type, record_date
        """
        try:
            results = DatabaseConnection.executeQuery(sql)
            return [ResourceDailyModel.fromDict(row) for row in results]
        except Exception as e:
            raise DatabaseError(f"查询资源日汇总失败: {e}")

    def findById(self, record_id: int) -> Optional[ResourceDailyModel]:
        """
        根据 ID 查询单条日汇总行。

        Args:
            record_id: 记录 ID。

        Returns:
            日汇总模型实例，不存在则返回 None。

        Raises:
            DatabaseError: 当查询失败时抛出。
        """
        sql = f"""
            SELECT id, resource_type, record_date, detail_mode, income, expense,
                   balance_override, note, last_record_time, created_at, updated_at
            FROM {self.DAILY_TABLE}
            WHERE id = ?
        """
        try:
            results = DatabaseConnection.executeQuery(sql, (record_id,))
            if results:
                return ResourceDailyModel.fromDict(results[0])
            return None
        except Exception as e:
            raise DatabaseError(f"查询资源日汇总详情失败: {e}")

    def findAllDaily(self, resource_type: str) -> List[ResourceDailyModel]:
        """
        按资源类型查询全部日汇总行，按日期升序（供结余扫描）。

        Args:
            resource_type: 资源类型，``cube`` 或 ``red_gem``。

        Returns:
            日汇总模型列表。

        Raises:
            DatabaseError: 当查询失败时抛出。
        """
        sql = f"""
            SELECT id, resource_type, record_date, detail_mode, income, expense,
                   balance_override, note, last_record_time, created_at, updated_at
            FROM {self.DAILY_TABLE}
            WHERE resource_type = ?
            ORDER BY record_date
        """
        try:
            results = DatabaseConnection.executeQuery(sql, (resource_type,))
            return [ResourceDailyModel.fromDict(row) for row in results]
        except Exception as e:
            raise DatabaseError(f"查询资源日汇总失败: {e}")

    def findDaily(self, resource_type: str, record_date: str) -> Optional[ResourceDailyModel]:
        """
        查询某一天的日汇总行。

        Args:
            resource_type: 资源类型，``cube`` 或 ``red_gem``。
            record_date: 日期 ``yyyy-MM-dd``。

        Returns:
            日汇总模型；该日无记录时返回 None。

        Raises:
            DatabaseError: 当查询失败时抛出。
        """
        sql = f"""
            SELECT id, resource_type, record_date, detail_mode, income, expense,
                   balance_override, note, last_record_time, created_at, updated_at
            FROM {self.DAILY_TABLE}
            WHERE resource_type = ? AND record_date = ?
        """
        try:
            results = DatabaseConnection.executeQuery(sql, (resource_type, record_date))
            return ResourceDailyModel.fromDict(results[0]) if results else None
        except Exception as e:
            raise DatabaseError(f"查询资源日汇总失败: {e}")

    def findLatestDaily(self, resource_type: str) -> Optional[ResourceDailyModel]:
        """
        查询指定资源最后一个有记录的日期。

        Args:
            resource_type: 资源类型。

        Returns:
            日汇总模型实例；无记录时返回 None。

        Raises:
            DatabaseError: 当查询失败时抛出。
        """
        sql = f"""
            SELECT id, resource_type, record_date, detail_mode, income, expense,
                   balance_override, note, last_record_time, created_at, updated_at
            FROM {self.DAILY_TABLE}
            WHERE resource_type = ?
            ORDER BY record_date DESC
            LIMIT 1
        """
        try:
            results = DatabaseConnection.executeQuery(sql, (resource_type,))
            if results:
                return ResourceDailyModel.fromDict(results[0])
            return None
        except Exception as e:
            raise DatabaseError(f"查询最新资源日汇总失败: {e}")

    def findTransactionTotals(self, resource_type: str) -> Dict[str, Dict[str, Any]]:
        """
        按日期汇总明细的收入、支出与笔数。

        用于把明细日折算成日收支，避免逐日多次查询。明细存的是时刻（到秒），
        这里按日期部分（``substr(record_time, 1, 10)``）归并到「天」。

        Args:
            resource_type: 资源类型。

        Returns:
            以日期（``yyyy-MM-dd``）为键的字典，值为
            ``{"income": int, "expense": int, "count": int, "last_time": str}``，
            其中 ``last_time`` 为该日最后一笔的时刻。

        Raises:
            DatabaseError: 当查询失败时抛出。
        """
        sql = f"""
            SELECT substr(record_time, 1, 10) AS record_day,
                   direction,
                   SUM(amount)    AS total,
                   COUNT(*)       AS cnt,
                   MAX(record_time) AS last_time
            FROM {self.TRANSACTION_TABLE}
            WHERE resource_type = ?
            GROUP BY record_day, direction
        """
        try:
            results = DatabaseConnection.executeQuery(sql, (resource_type,))
        except Exception as e:
            raise DatabaseError(f"汇总资源明细失败: {e}")

        totals: Dict[str, Dict[str, object]] = {}
        for row in results:
            bucket = totals.setdefault(
                row["record_day"], {"income": 0, "expense": 0, "count": 0, "last_time": ""}
            )
            bucket[row["direction"]] = int(bucket.get(row["direction"], 0)) + int(row["total"] or 0)
            bucket["count"] = int(bucket["count"]) + int(row["cnt"] or 0)
            last_time = row["last_time"] or ""
            if last_time > str(bucket["last_time"]):
                bucket["last_time"] = last_time
        return totals

    def findLatestRecordTime(self, resource_type: str) -> Optional[str]:
        """
        查询指定资源最后一笔明细的时刻。

        Args:
            resource_type: 资源类型。

        Returns:
            形如 ``2026-10-17 21:35:12`` 的时刻；无明细时返回 None。

        Raises:
            DatabaseError: 当查询失败时抛出。
        """
        sql = f"""
            SELECT MAX(record_time) AS latest
            FROM {self.TRANSACTION_TABLE}
            WHERE resource_type = ?
        """
        try:
            results = DatabaseConnection.executeQuery(sql, (resource_type,))
            if results and results[0]["latest"]:
                return results[0]["latest"]
            return None
        except Exception as e:
            raise DatabaseError(f"查询资源最新明细时刻失败: {e}")

    def findTransactions(
        self, resource_type: str, start_date: Optional[str] = None, end_date: Optional[str] = None
    ) -> List[ResourceTransactionModel]:
        """
        查询资源明细。

        Args:
            resource_type: 资源类型。
            start_date: 可选起始日期，格式 ``yyyy-MM-dd``（含当天）。
            end_date: 可选结束日期，格式 ``yyyy-MM-dd``（含当天）。

        Returns:
            明细模型列表，按发生时刻升序。

        Raises:
            DatabaseError: 当查询失败时抛出。
        """
        conditions = ["resource_type = ?"]
        params: List[str] = [resource_type]
        if start_date:
            conditions.append("record_time >= ?")
            params.append(f"{start_date} 00:00:00")
        if end_date:
            conditions.append("record_time <= ?")
            params.append(f"{end_date} 23:59:59")

        sql = f"""
            SELECT id, resource_type, direction, record_time, category, amount,
                   note, created_at, updated_at
            FROM {self.TRANSACTION_TABLE}
            WHERE {' AND '.join(conditions)}
            ORDER BY record_time, id
        """
        try:
            results = DatabaseConnection.executeQuery(sql, tuple(params))
            return [ResourceTransactionModel.fromDict(row) for row in results]
        except Exception as e:
            raise DatabaseError(f"查询资源明细失败: {e}")

    def findLatestManualTransaction(self, resource_type: str) -> Optional[ResourceTransactionModel]:
        """
        查询最近一笔「非任务来源」的明细（供常规录入撤销使用）。

        任务看板写入的明细会在 ``cube_task_completion.transaction_id`` 留下引用，
        这里用反连接把它们排除，避免撤销误伤任务卡片。

        Args:
            resource_type: 资源类型。

        Returns:
            明细模型；没有可撤销记录时返回 None。

        Raises:
            DatabaseError: 当查询失败时抛出。
        """
        sql = f"""
            SELECT t.id, t.resource_type, t.direction, t.record_time, t.category,
                   t.amount, t.note, t.created_at, t.updated_at
            FROM {self.TRANSACTION_TABLE} t
            LEFT JOIN cube_task_completion c ON c.transaction_id = t.id
            WHERE t.resource_type = ? AND c.id IS NULL
            ORDER BY t.record_time DESC, t.id DESC
            LIMIT 1
        """
        try:
            results = DatabaseConnection.executeQuery(sql, (resource_type,))
            return ResourceTransactionModel.fromDict(results[0]) if results else None
        except Exception as e:
            raise DatabaseError(f"查询最近一笔常规录入失败: {e}")

    def countTransactionsByDate(
        self, resource_type: str, record_date: str, conn: Optional[sqlite3.Connection] = None
    ) -> int:
        """
        统计某日的明细笔数（撤销后判断是否要清掉空日汇总行）。

        Args:
            resource_type: 资源类型。
            record_date: 日期 ``yyyy-MM-dd``。
            conn: 可选的调用方连接。

        Returns:
            该日剩余明细笔数。

        Raises:
            DatabaseError: 当查询失败时抛出。
        """
        sql = f"""
            SELECT COUNT(*) AS total
            FROM {self.TRANSACTION_TABLE}
            WHERE resource_type = ? AND substr(record_time, 1, 10) = ?
        """
        params = (resource_type, record_date)
        try:
            if conn is not None:
                row = conn.execute(sql, params).fetchone()
                return int(row[0]) if row else 0
            results = DatabaseConnection.executeQuery(sql, params)
            return int(results[0]["total"]) if results else 0
        except sqlite3.Error as e:
            raise DatabaseError(f"统计资源明细笔数失败: {e}")

    def deleteDaily(
        self, resource_type: str, record_date: str, conn: Optional[sqlite3.Connection] = None
    ) -> None:
        """
        删除某日的日汇总行（仅用于撤销后该日已无任何明细的场景）。

        Args:
            resource_type: 资源类型。
            record_date: 日期 ``yyyy-MM-dd``。
            conn: 可选的调用方连接。

        Raises:
            DatabaseError: 当删除失败时抛出。
        """
        sql = f"DELETE FROM {self.DAILY_TABLE} WHERE resource_type = ? AND record_date = ?"
        params = (resource_type, record_date)
        try:
            if conn is not None:
                conn.execute(sql, params)
                return
            with self._getConnection() as own:
                own.execute(sql, params)
        except sqlite3.Error as e:
            raise DatabaseError(f"删除资源日汇总失败: {e}")

    def findCategories(self, resource_type: str, direction: str) -> List[ResourceCategoryModel]:
        """
        查询事件字典。

        Args:
            resource_type: 资源类型。
            direction: 方向，``income`` 或 ``expense``。

        Returns:
            字典模型列表，按排序序号与名称升序。

        Raises:
            DatabaseError: 当查询失败时抛出。
        """
        sql = f"""
            SELECT id, resource_type, direction, name, sort_order
            FROM {self.CATEGORY_TABLE}
            WHERE resource_type = ? AND direction = ?
            ORDER BY sort_order, name
        """
        try:
            results = DatabaseConnection.executeQuery(sql, (resource_type, direction))
            return [ResourceCategoryModel.fromDict(row) for row in results]
        except Exception as e:
            raise DatabaseError(f"查询资源事件字典失败: {e}")

    def countDaily(self, resource_type: str) -> int:
        """
        统计日汇总行数。

        Args:
            resource_type: 资源类型。

        Returns:
            记录数。

        Raises:
            DatabaseError: 当查询失败时抛出。
        """
        sql = f"SELECT COUNT(*) AS count FROM {self.DAILY_TABLE} WHERE resource_type = ?"
        try:
            results = DatabaseConnection.executeQuery(sql, (resource_type,))
            return results[0]["count"] if results else 0
        except Exception as e:
            raise DatabaseError(f"统计资源日汇总数量失败: {e}")

    def insert(self, record: ResourceDailyModel) -> int:
        """
        插入一条日汇总行。

        Args:
            record: 日汇总模型实例。

        Returns:
            新记录的 ID。

        Raises:
            DatabaseError: 当插入失败时抛出。
        """
        sql = f"""
            INSERT INTO {self.DAILY_TABLE}
                (resource_type, record_date, detail_mode, income, expense,
                 balance_override, note, last_record_time)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """
        params = (
            record.resource_type, record.record_date, record.detail_mode,
            record.income, record.expense, record.balance_override,
            record.note, record.last_record_time,
        )
        try:
            with self._getConnection() as conn:
                cursor = conn.execute(sql, params)
                return cursor.lastrowid
        except sqlite3.Error as e:
            raise DatabaseError(f"插入资源日汇总失败: {e}")

    def update(self, record: ResourceDailyModel) -> bool:
        """
        更新一条日汇总行。

        Args:
            record: 日汇总模型实例，必须带有效 ID。

        Returns:
            更新是否成功。

        Raises:
            DatabaseError: 当更新失败或缺少 ID 时抛出。
        """
        if record.id is None:
            raise DatabaseError("更新资源日汇总需要有效的 ID")

        sql = f"""
            UPDATE {self.DAILY_TABLE}
               SET detail_mode = ?, income = ?, expense = ?, balance_override = ?,
                   note = ?, last_record_time = ?, updated_at = datetime('now', 'localtime')
             WHERE id = ?
        """
        params = (
            record.detail_mode, record.income, record.expense, record.balance_override,
            record.note, record.last_record_time, record.id,
        )
        try:
            rowcount = DatabaseConnection.executeUpdate(sql, params)
            return rowcount > 0
        except Exception as e:
            raise DatabaseError(f"更新资源日汇总失败: {e}")

    def delete(self, record_id: int) -> bool:
        """
        删除一条日汇总行。

        Args:
            record_id: 记录 ID。

        Returns:
            删除是否成功。

        Raises:
            DatabaseError: 当删除失败时抛出。
        """
        sql = f"DELETE FROM {self.DAILY_TABLE} WHERE id = ?"
        try:
            rowcount = DatabaseConnection.executeUpdate(sql, (record_id,))
            return rowcount > 0
        except Exception as e:
            raise DatabaseError(f"删除资源日汇总失败: {e}")

    # ---------------------------------------------------------------- 明细写入

    def insertTransaction(
        self, record: ResourceTransactionModel, conn: Optional[sqlite3.Connection] = None
    ) -> int:
        """
        插入一条明细。

        Args:
            record: 明细模型实例。
            conn: 可选的调用方连接（用于把多条写入合并进同一事务）；
                为空时自行开连接并提交。

        Returns:
            新记录的 ID。

        Raises:
            DatabaseError: 当插入失败时抛出。
        """
        sql = f"""
            INSERT INTO {self.TRANSACTION_TABLE}
                (resource_type, direction, record_time, category, amount, note)
            VALUES (?, ?, ?, ?, ?, ?)
        """
        params = (
            record.resource_type, record.direction, record.record_time,
            record.category, record.amount, record.note,
        )
        try:
            if conn is not None:
                return conn.execute(sql, params).lastrowid
            with self._getConnection() as own:
                return own.execute(sql, params).lastrowid
        except sqlite3.Error as e:
            raise DatabaseError(f"插入资源明细失败: {e}")

    def deleteTransaction(
        self, record_id: int, conn: Optional[sqlite3.Connection] = None
    ) -> bool:
        """
        删除一条明细。

        Args:
            record_id: 明细 ID。
            conn: 可选的调用方连接。

        Returns:
            删除是否成功。

        Raises:
            DatabaseError: 当删除失败时抛出。
        """
        sql = f"DELETE FROM {self.TRANSACTION_TABLE} WHERE id = ?"
        try:
            if conn is not None:
                return conn.execute(sql, (record_id,)).rowcount > 0
            return DatabaseConnection.executeUpdate(sql, (record_id,)) > 0
        except sqlite3.Error as e:
            raise DatabaseError(f"删除资源明细失败: {e}")

    def findTransactionById(self, record_id: int) -> Optional[ResourceTransactionModel]:
        """
        根据 ID 查询明细。

        Args:
            record_id: 明细 ID。

        Returns:
            明细模型实例；不存在则返回 None。

        Raises:
            DatabaseError: 当查询失败时抛出。
        """
        sql = f"""
            SELECT id, resource_type, direction, record_time, category, amount,
                   note, created_at, updated_at
            FROM {self.TRANSACTION_TABLE}
            WHERE id = ?
        """
        try:
            results = DatabaseConnection.executeQuery(sql, (record_id,))
            if results:
                return ResourceTransactionModel.fromDict(results[0])
            return None
        except Exception as e:
            raise DatabaseError(f"查询资源明细失败: {e}")

    def findExistingTransactionIds(self, record_ids: List[int]) -> Set[int]:
        """
        批量校验明细 ID 是否仍然存在（用于识别孤儿完成记录）。

        Args:
            record_ids: 待检查的明细 ID 列表。

        Returns:
            仍然存在的 ID 集合。
        """
        ids = [int(value) for value in record_ids if value is not None]
        if not ids:
            return set()

        placeholders = ", ".join("?" for _ in ids)
        sql = f"SELECT id FROM {self.TRANSACTION_TABLE} WHERE id IN ({placeholders})"
        try:
            results = DatabaseConnection.executeQuery(sql, tuple(ids))
            return {row["id"] for row in results}
        except Exception as e:
            raise DatabaseError(f"校验资源明细是否存在失败: {e}")

    def upsertDetailDaily(
        self,
        resource_type: str,
        record_date: str,
        record_time: Optional[str] = None,
        conn: Optional[sqlite3.Connection] = None,
    ) -> None:
        """
        确保某日是「明细日」，并把 `last_record_time` 更新为较晚者。

        若该日原本是汇总日（历史段），会被切换为明细日并清空 stored 收支 —— 该场景
        只会在把任务记到很早的历史日期时发生，调用方需自行确认。

        Args:
            resource_type: 资源类型。
            record_date: 日期 ``yyyy-MM-dd``。
            record_time: 可选的最新时刻 ``yyyy-MM-dd HH:mm:ss``。
            conn: 可选的调用方连接。

        Raises:
            DatabaseError: 当写入失败时抛出。
        """
        sql = f"""
            INSERT INTO {self.DAILY_TABLE}
                (resource_type, record_date, detail_mode, income, expense, note, last_record_time)
            VALUES (?, ?, 'detail', NULL, NULL, '', ?)
            ON CONFLICT(resource_type, record_date) DO UPDATE SET
                detail_mode = 'detail',
                income = NULL,
                expense = NULL,
                last_record_time = CASE
                    WHEN excluded.last_record_time IS NULL
                        THEN {self.DAILY_TABLE}.last_record_time
                    WHEN {self.DAILY_TABLE}.last_record_time IS NULL
                        THEN excluded.last_record_time
                    WHEN excluded.last_record_time > {self.DAILY_TABLE}.last_record_time
                        THEN excluded.last_record_time
                    ELSE {self.DAILY_TABLE}.last_record_time
                END,
                updated_at = datetime('now', 'localtime')
        """
        params = (resource_type, record_date, record_time)
        try:
            if conn is not None:
                conn.execute(sql, params)
                return
            with self._getConnection() as own:
                own.execute(sql, params)
        except sqlite3.Error as e:
            raise DatabaseError(f"维护资源日汇总失败: {e}")

    def recomputeLastRecordTime(
        self,
        resource_type: str,
        record_date: str,
        conn: Optional[sqlite3.Connection] = None,
    ) -> None:
        """
        按该日剩余明细重算 `last_record_time`（无明细则置 NULL）。

        Args:
            resource_type: 资源类型。
            record_date: 日期 ``yyyy-MM-dd``。
            conn: 可选的调用方连接。

        Raises:
            DatabaseError: 当写入失败时抛出。
        """
        sql = f"""
            UPDATE {self.DAILY_TABLE}
               SET last_record_time = (
                       SELECT MAX(t.record_time) FROM {self.TRANSACTION_TABLE} t
                        WHERE t.resource_type = ? AND substr(t.record_time, 1, 10) = ?
                   ),
                   updated_at = datetime('now', 'localtime')
             WHERE resource_type = ? AND record_date = ?
        """
        params = (resource_type, record_date, resource_type, record_date)
        try:
            if conn is not None:
                conn.execute(sql, params)
                return
            with self._getConnection() as own:
                own.execute(sql, params)
        except sqlite3.Error as e:
            raise DatabaseError(f"重算资源末次记录时刻失败: {e}")
