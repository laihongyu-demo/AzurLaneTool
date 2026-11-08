"""
活动记录数据访问层模块。

封装 ``event_record`` 的增删改查、筛选选项，以及活动与魔方明细的关联统计。

关联关系存放在 ``resource_transaction.event_id``：本仓储只负责读取统计与解除关联，
明细本身的写入仍由 :class:`ResourceRepository` 负责。
"""

import sqlite3
from typing import Dict, List, Optional, Tuple

from models.event_model import EventRecordModel
from repositories.base_repository import BaseRepository
from utils.constants import EVENT_STATUS_ONGOING
from utils.db_connection import DatabaseConnection
from utils.exceptions import DatabaseError

EVENT_COLUMNS = (
    "id, event_date, event_type, name, status, status_note, build_cost, use_ticket,"
    " ticket_build_count, build_count, note, created_at, updated_at"
)


def _likePattern(keyword: str) -> str:
    """
    把用户输入转成 LIKE 模式，并转义 ``%`` / ``_`` / ``\\``。

    Args:
        keyword: 原始关键词。

    Returns:
        形如 ``%关键词%`` 的模式串。
    """
    escaped = (
        keyword.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    )
    return f"%{escaped}%"


class EventRepository(BaseRepository[EventRecordModel]):
    """
    活动记录数据访问类。

    对应 ``event_record`` 表；``findTransactionStats`` 读取明细里按活动聚合的
    魔方支出（只统计 ``cube`` + ``expense``，与写入侧校验保持一致）。
    """

    TABLE = "event_record"
    TRANSACTION_TABLE = "resource_transaction"

    def findAll(self) -> List[EventRecordModel]:
        """
        查询全部活动记录（按开始日期倒序）。

        Returns:
            活动记录模型列表。

        Raises:
            DatabaseError: 当查询失败时抛出。
        """
        return self.findRecords()

    def findRecords(
        self,
        year: Optional[str] = None,
        event_type: Optional[str] = None,
        status: Optional[str] = None,
        keyword: Optional[str] = None,
    ) -> List[EventRecordModel]:
        """
        按条件查询活动记录。

        Args:
            year: 可选年份（``yyyy``），按开始日期匹配。
            event_type: 可选活动类型，精确匹配。
            status: 可选状态，精确匹配；空串表示筛选「未标记」。
            keyword: 可选关键词，模糊匹配名称 / 备注 / 状态备注。

        Returns:
            活动记录模型列表，按开始日期、ID 倒序。

        Raises:
            DatabaseError: 当查询失败时抛出。
        """
        conditions: List[str] = []
        params: List[str] = []
        if year:
            conditions.append("substr(event_date, 1, 4) = ?")
            params.append(year)
        if event_type is not None:
            conditions.append("event_type = ?")
            params.append(event_type)
        if status is not None:
            conditions.append("status = ?")
            params.append(status)
        if keyword:
            pattern = _likePattern(keyword.strip())
            conditions.append(
                "(name LIKE ? ESCAPE '\\' OR note LIKE ? ESCAPE '\\'"
                " OR status_note LIKE ? ESCAPE '\\')"
            )
            params.extend([pattern, pattern, pattern])

        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        sql = f"""
            SELECT {EVENT_COLUMNS}
            FROM {self.TABLE}
            {where}
            ORDER BY event_date DESC, id DESC
        """
        try:
            results = DatabaseConnection.executeQuery(sql, tuple(params))
            return [EventRecordModel.fromDict(row) for row in results]
        except Exception as e:
            raise DatabaseError(f"查询活动记录失败: {e}")

    def findById(self, record_id: int) -> Optional[EventRecordModel]:
        """
        根据 ID 查询单条活动记录。

        Args:
            record_id: 活动记录 ID。

        Returns:
            活动记录模型；不存在时返回 None。

        Raises:
            DatabaseError: 当查询失败时抛出。
        """
        sql = f"SELECT {EVENT_COLUMNS} FROM {self.TABLE} WHERE id = ?"
        try:
            results = DatabaseConnection.executeQuery(sql, (record_id,))
            return EventRecordModel.fromDict(results[0]) if results else None
        except Exception as e:
            raise DatabaseError(f"查询活动记录详情失败: {e}")

    def findLatestOngoing(self) -> Optional[EventRecordModel]:
        """
        查询最近一条「进行中」的活动记录。

        任务看板的建造任务用它自动关联活动：状态为 ``进行中`` 时按开始日期、
        ID 倒序取第一条，与常规录入下拉的默认选择保持一致。

        Returns:
            活动记录模型；没有进行中活动时返回 None。

        Raises:
            DatabaseError: 当查询失败时抛出。
        """
        sql = f"""
            SELECT {EVENT_COLUMNS}
            FROM {self.TABLE}
            WHERE status = ?
            ORDER BY event_date DESC, id DESC
            LIMIT 1
        """
        try:
            results = DatabaseConnection.executeQuery(sql, (EVENT_STATUS_ONGOING,))
            return EventRecordModel.fromDict(results[0]) if results else None
        except Exception as e:
            raise DatabaseError(f"查询进行中活动失败: {e}")

    def findYearOptions(self) -> List[str]:
        """
        查询出现过的年份（倒序），供筛选下拉使用。

        Returns:
            年份字符串列表。

        Raises:
            DatabaseError: 当查询失败时抛出。
        """
        sql = f"""
            SELECT DISTINCT substr(event_date, 1, 4) AS year
            FROM {self.TABLE}
            WHERE length(event_date) >= 4
            ORDER BY year DESC
        """
        try:
            results = DatabaseConnection.executeQuery(sql)
            return [row["year"] for row in results if row["year"]]
        except Exception as e:
            raise DatabaseError(f"查询活动年份失败: {e}")

    def findTypeOptions(self) -> List[str]:
        """
        查询出现过的活动类型，按使用次数倒序。

        Returns:
            类型名称列表（不含空串）。

        Raises:
            DatabaseError: 当查询失败时抛出。
        """
        sql = f"""
            SELECT event_type, COUNT(*) AS total
            FROM {self.TABLE}
            WHERE event_type <> ''
            GROUP BY event_type
            ORDER BY total DESC, event_type
        """
        try:
            results = DatabaseConnection.executeQuery(sql)
            return [row["event_type"] for row in results]
        except Exception as e:
            raise DatabaseError(f"查询活动类型失败: {e}")

    def findStatusOptions(self) -> List[str]:
        """
        查询出现过的活动状态，按使用次数倒序。

        状态是自由文本：用户可能输入「放弃」等建议值之外的状态，这里一并返回，
        供筛选下拉与编辑对话框使用。

        Returns:
            状态名称列表（不含空串）。

        Raises:
            DatabaseError: 当查询失败时抛出。
        """
        sql = f"""
            SELECT status, COUNT(*) AS total
            FROM {self.TABLE}
            WHERE status <> ''
            GROUP BY status
            ORDER BY total DESC, status
        """
        try:
            results = DatabaseConnection.executeQuery(sql)
            return [row["status"] for row in results]
        except Exception as e:
            raise DatabaseError(f"查询活动状态失败: {e}")

    def findTransactionStats(self) -> Dict[int, Tuple[int, int]]:
        """
        按活动聚合关联的魔方支出。

        只统计 ``cube`` + ``expense``：写入侧只允许「支出 · 活动建造」关联活动，
        这里再做一层口径保护，避免脏数据影响展示。

        Returns:
            以 ``event_id`` 为键、``(笔数, 魔方合计)`` 为值的字典；无关联时为空字典。

        Raises:
            DatabaseError: 当查询失败时抛出。
        """
        sql = f"""
            SELECT event_id, COUNT(*) AS total, SUM(amount) AS amount
            FROM {self.TRANSACTION_TABLE}
            WHERE event_id IS NOT NULL
              AND resource_type = 'cube'
              AND direction = 'expense'
            GROUP BY event_id
        """
        try:
            results = DatabaseConnection.executeQuery(sql)
        except Exception as e:
            raise DatabaseError(f"汇总活动关联魔方失败: {e}")

        return {
            int(row["event_id"]): (int(row["total"] or 0), int(row["amount"] or 0))
            for row in results
        }

    def countAll(self) -> int:
        """
        统计活动记录总数（导入脚本用于判断是否已导入）。

        Returns:
            记录数。

        Raises:
            DatabaseError: 当查询失败时抛出。
        """
        sql = f"SELECT COUNT(*) AS total FROM {self.TABLE}"
        try:
            results = DatabaseConnection.executeQuery(sql)
            return int(results[0]["total"]) if results else 0
        except Exception as e:
            raise DatabaseError(f"统计活动记录数量失败: {e}")

    def insert(
        self, record: EventRecordModel, conn: Optional[sqlite3.Connection] = None
    ) -> int:
        """
        插入一条活动记录。

        Args:
            record: 活动记录模型。
            conn: 可选的调用方连接（导入脚本用同一事务批量写入）。

        Returns:
            新记录 ID。

        Raises:
            DatabaseError: 当插入失败时抛出。
        """
        sql = f"""
            INSERT INTO {self.TABLE}
                (event_date, event_type, name, status, status_note, build_cost,
                 use_ticket, ticket_build_count, build_count, note)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        params = (
            record.event_date, record.event_type, record.name, record.status,
            record.status_note, record.build_cost, int(record.use_ticket),
            record.ticket_build_count, record.build_count, record.note,
        )
        try:
            if conn is not None:
                return conn.execute(sql, params).lastrowid
            with self._getConnection() as own:
                return own.execute(sql, params).lastrowid
        except sqlite3.Error as e:
            raise DatabaseError(f"插入活动记录失败: {e}")

    def update(
        self, record: EventRecordModel, conn: Optional[sqlite3.Connection] = None
    ) -> bool:
        """
        更新一条活动记录。

        Args:
            record: 活动记录模型，必须带有效 ID。
            conn: 可选的调用方连接。

        Returns:
            是否有行被更新。

        Raises:
            DatabaseError: 当更新失败或缺少 ID 时抛出。
        """
        if record.id is None:
            raise DatabaseError("更新活动记录需要有效的 ID")

        sql = f"""
            UPDATE {self.TABLE}
               SET event_date = ?, event_type = ?, name = ?, status = ?,
                   status_note = ?, build_cost = ?, use_ticket = ?,
                   ticket_build_count = ?, build_count = ?, note = ?,
                   updated_at = datetime('now', 'localtime')
             WHERE id = ?
        """
        params = (
            record.event_date, record.event_type, record.name, record.status,
            record.status_note, record.build_cost, int(record.use_ticket),
            record.ticket_build_count, record.build_count, record.note, record.id,
        )
        try:
            if conn is not None:
                return conn.execute(sql, params).rowcount > 0
            return DatabaseConnection.executeUpdate(sql, params) > 0
        except sqlite3.Error as e:
            raise DatabaseError(f"更新活动记录失败: {e}")

    def delete(
        self, record_id: int, conn: Optional[sqlite3.Connection] = None
    ) -> bool:
        """
        删除一条活动记录。

        关联明细的 ``event_id`` 由调用方在同一个事务里先解除（见
        :meth:`unlinkTransactions`），本方法不级联删除明细。

        Args:
            record_id: 活动记录 ID。
            conn: 可选的调用方连接。

        Returns:
            是否有行被删除。

        Raises:
            DatabaseError: 当删除失败时抛出。
        """
        sql = f"DELETE FROM {self.TABLE} WHERE id = ?"
        try:
            if conn is not None:
                return conn.execute(sql, (record_id,)).rowcount > 0
            return DatabaseConnection.executeUpdate(sql, (record_id,)) > 0
        except sqlite3.Error as e:
            raise DatabaseError(f"删除活动记录失败: {e}")

    def adjustTicketBuildCount(
        self, record_id: int, delta: int, conn: Optional[sqlite3.Connection] = None
    ) -> bool:
        """
        增减活动的建造券抽次数（任务看板「建造」任务联动）。

        口径：

        - ``delta=+1``：券抽 +1，并把 ``use_ticket`` 置 1（券抽只有开启时才计入建造次数）；
        - ``delta=-1``：券抽 -1 且不低于 0，减到 0 时把 ``use_ticket`` 清 0。

        只改这两列，不覆盖用户手工维护的单耗、建造次数与备注。

        Args:
            record_id: 活动记录 ID。
            delta: ``+1`` 或 ``-1``。
            conn: 可选的调用方连接（与明细写入合并进同一事务）。

        Returns:
            是否有行被更新。

        Raises:
            ValueError: ``delta`` 不是 ±1 时抛出。
            DatabaseError: 当更新失败时抛出。
        """
        if delta not in (-1, 1):
            raise ValueError(f"券抽次数只允许 +1 / -1：{delta}")

        sql = f"""
            UPDATE {self.TABLE}
               SET ticket_build_count = MAX(COALESCE(ticket_build_count, 0) + ?, 0),
                   use_ticket = CASE
                       WHEN MAX(COALESCE(ticket_build_count, 0) + ?, 0) > 0 THEN 1
                       ELSE 0
                   END,
                   updated_at = datetime('now', 'localtime')
             WHERE id = ?
        """
        params = (delta, delta, record_id)
        try:
            if conn is not None:
                return conn.execute(sql, params).rowcount > 0
            return DatabaseConnection.executeUpdate(sql, params) > 0
        except sqlite3.Error as e:
            raise DatabaseError(f"调整活动建造券次数失败: {e}")

    def unlinkTransactions(
        self, event_id: int, conn: Optional[sqlite3.Connection] = None
    ) -> int:
        """
        解除该活动下所有明细的关联（明细保留，只把 ``event_id`` 置空）。

        Args:
            event_id: 活动记录 ID。
            conn: 可选的调用方连接。

        Returns:
            被解除关联的明细行数。

        Raises:
            DatabaseError: 当更新失败时抛出。
        """
        sql = f"""
            UPDATE {self.TRANSACTION_TABLE}
               SET event_id = NULL, updated_at = datetime('now', 'localtime')
             WHERE event_id = ?
        """
        try:
            if conn is not None:
                return conn.execute(sql, (event_id,)).rowcount
            return DatabaseConnection.executeUpdate(sql, (event_id,))
        except sqlite3.Error as e:
            raise DatabaseError(f"解除活动关联失败: {e}")
