"""
资源统计数据访问层模块。

封装魔方 / 红尖尖的日汇总、明细与事件字典的读取操作。

本阶段（需求文档 v0.2）只提供读接口：魔方 / 红尖尖的录入与编辑推迟到 #17，
写入路径不存在，避免出现绕过一致性维护的入口。数据由迁移脚本一次性写入。
"""

from typing import Any, Dict, List, Optional

from models.resource_model import (
    ResourceCategoryModel, ResourceDailyModel, ResourceTransactionModel
)
from repositories.base_repository import BaseRepository
from utils.db_connection import DatabaseConnection
from utils.exceptions import DatabaseError


class ResourceRepository(BaseRepository[ResourceDailyModel]):
    """
    资源统计数据访问类（只读）。

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
        写入接口在本阶段不提供。

        Raises:
            NotImplementedError: 始终抛出；写入需与明细、日汇总一致性维护一起实现（#17）。
        """
        raise NotImplementedError("资源统计写入接口尚未开放，见 issue #17")

    def update(self, record: ResourceDailyModel) -> bool:
        """
        写入接口在本阶段不提供。

        Raises:
            NotImplementedError: 始终抛出；写入需与明细、日汇总一致性维护一起实现（#17）。
        """
        raise NotImplementedError("资源统计写入接口尚未开放，见 issue #17")

    def delete(self, record_id: int) -> bool:
        """
        写入接口在本阶段不提供。

        Raises:
            NotImplementedError: 始终抛出；写入需与明细、日汇总一致性维护一起实现（#17）。
        """
        raise NotImplementedError("资源统计写入接口尚未开放，见 issue #17")
