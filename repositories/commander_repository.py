"""
指挥官数据访问层模块。

封装指挥官等级快照与等级经验基准的数据库读写操作。
"""

import sqlite3
from typing import List, Optional

from models.commander_model import CommanderLevelExpModel, CommanderSnapshotModel
from repositories.base_repository import BaseRepository
from utils.db_connection import DatabaseConnection
from utils.exceptions import DatabaseError


class CommanderRepository(BaseRepository[CommanderSnapshotModel]):
    """
    指挥官数据访问类。

    快照表 ``commander_info`` 为历史快照语义，取"当前状态"必须按时间倒序取首行；
    排序键固定为 ``statistics_date DESC, id DESC``（时间已规范为可比较的定长格式）。
    """

    TABLE_NAME = "commander_info"
    LEVEL_EXP_TABLE = "commander_level_exp"

    ORDER_BY_LATEST = "ORDER BY statistics_date DESC, id DESC"

    def findAll(self) -> List[CommanderSnapshotModel]:
        """
        查询全部指挥官快照。

        Returns:
            快照模型列表，按时间倒序。

        Raises:
            DatabaseError: 当查询失败时抛出。
        """
        sql = f"""
            SELECT id, statistics_date, commander_level, commander_exp
            FROM {self.TABLE_NAME}
            {self.ORDER_BY_LATEST}
        """
        try:
            results = DatabaseConnection.executeQuery(sql)
            return [CommanderSnapshotModel.fromDict(row) for row in results]
        except Exception as e:
            raise DatabaseError(f"查询指挥官快照失败: {e}")

    def findById(self, record_id: int) -> Optional[CommanderSnapshotModel]:
        """
        根据 ID 查询单条快照。

        Args:
            record_id: 快照 ID。

        Returns:
            快照模型实例，不存在则返回 None。

        Raises:
            DatabaseError: 当查询失败时抛出。
        """
        sql = f"""
            SELECT id, statistics_date, commander_level, commander_exp
            FROM {self.TABLE_NAME}
            WHERE id = ?
        """
        try:
            results = DatabaseConnection.executeQuery(sql, (record_id,))
            if results:
                return CommanderSnapshotModel.fromDict(results[0])
            return None
        except Exception as e:
            raise DatabaseError(f"查询指挥官快照详情失败: {e}")

    def findLatest(self) -> Optional[CommanderSnapshotModel]:
        """
        查询最新一条指挥官快照。

        Returns:
            快照模型实例；表为空时返回 None。

        Raises:
            DatabaseError: 当查询失败时抛出。
        """
        sql = f"""
            SELECT id, statistics_date, commander_level, commander_exp
            FROM {self.TABLE_NAME}
            {self.ORDER_BY_LATEST}
            LIMIT 1
        """
        try:
            results = DatabaseConnection.executeQuery(sql)
            if results:
                return CommanderSnapshotModel.fromDict(results[0])
            return None
        except Exception as e:
            raise DatabaseError(f"查询最新指挥官快照失败: {e}")

    def findRecent(self, limit: int = 30) -> List[CommanderSnapshotModel]:
        """
        查询最近若干条快照。

        Args:
            limit: 返回条数上限。

        Returns:
            快照模型列表，按时间倒序。

        Raises:
            DatabaseError: 当查询失败时抛出。
        """
        sql = f"""
            SELECT id, statistics_date, commander_level, commander_exp
            FROM {self.TABLE_NAME}
            {self.ORDER_BY_LATEST}
            LIMIT ?
        """
        try:
            results = DatabaseConnection.executeQuery(sql, (int(limit),))
            return [CommanderSnapshotModel.fromDict(row) for row in results]
        except Exception as e:
            raise DatabaseError(f"查询最近指挥官快照失败: {e}")

    def findByDateRange(self, start_date: str, end_date: str) -> List[CommanderSnapshotModel]:
        """
        按日期范围查询快照。

        Args:
            start_date: 起始日期，格式 ``yyyy-MM-dd``（含当天）。
            end_date: 结束日期，格式 ``yyyy-MM-dd``（含当天）。

        Returns:
            快照模型列表，按时间倒序。

        Raises:
            DatabaseError: 当查询失败时抛出。
        """
        sql = f"""
            SELECT id, statistics_date, commander_level, commander_exp
            FROM {self.TABLE_NAME}
            WHERE date(statistics_date) BETWEEN ? AND ?
            {self.ORDER_BY_LATEST}
        """
        try:
            results = DatabaseConnection.executeQuery(sql, (start_date, end_date))
            return [CommanderSnapshotModel.fromDict(row) for row in results]
        except Exception as e:
            raise DatabaseError(f"按日期范围查询指挥官快照失败: {e}")

    def existsAt(self, statistics_date: str) -> bool:
        """
        判断指定时间点是否已存在快照。

        Args:
            statistics_date: 记录时间，格式 ``yyyy-MM-dd HH:mm``。

        Returns:
            存在返回 True。

        Raises:
            DatabaseError: 当查询失败时抛出。
        """
        sql = f"SELECT 1 FROM {self.TABLE_NAME} WHERE statistics_date = ? LIMIT 1"
        try:
            return bool(DatabaseConnection.executeQuery(sql, (statistics_date,)))
        except Exception as e:
            raise DatabaseError(f"检查指挥官快照时间失败: {e}")

    def insert(self, record: CommanderSnapshotModel) -> int:
        """
        插入一条快照。

        Args:
            record: 快照模型实例。

        Returns:
            新记录的 ID。

        Raises:
            DatabaseError: 当插入失败时抛出。
        """
        sql = f"""
            INSERT INTO {self.TABLE_NAME} (statistics_date, commander_level, commander_exp)
            VALUES (?, ?, ?)
        """
        params = (record.statistics_date, record.commander_level, record.commander_exp)
        try:
            with self._getConnection() as conn:
                cursor = conn.execute(sql, params)
                return cursor.lastrowid
        except sqlite3.Error as e:
            raise DatabaseError(f"插入指挥官快照失败: {e}")

    def update(self, record: CommanderSnapshotModel) -> bool:
        """
        更新一条快照。

        Args:
            record: 快照模型实例，必须带有效 ID。

        Returns:
            更新是否成功。

        Raises:
            DatabaseError: 当更新失败或缺少 ID 时抛出。
        """
        if record.id is None:
            raise DatabaseError("更新指挥官快照需要有效的 ID")

        sql = f"""
            UPDATE {self.TABLE_NAME}
            SET statistics_date = ?, commander_level = ?, commander_exp = ?
            WHERE id = ?
        """
        params = (record.statistics_date, record.commander_level, record.commander_exp, record.id)
        try:
            rowcount = DatabaseConnection.executeUpdate(sql, params)
            return rowcount > 0
        except Exception as e:
            raise DatabaseError(f"更新指挥官快照失败: {e}")

    def delete(self, record_id: int) -> bool:
        """
        删除一条快照。

        Args:
            record_id: 快照 ID。

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
            raise DatabaseError(f"删除指挥官快照失败: {e}")

    def count(self) -> int:
        """
        统计快照总数。

        Returns:
            快照总数。

        Raises:
            DatabaseError: 当查询失败时抛出。
        """
        sql = f"SELECT COUNT(*) AS count FROM {self.TABLE_NAME}"
        try:
            results = DatabaseConnection.executeQuery(sql)
            return results[0]["count"] if results else 0
        except Exception as e:
            raise DatabaseError(f"统计指挥官快照数量失败: {e}")

    def findLevelExp(self, level: int) -> Optional[CommanderLevelExpModel]:
        """
        查询指定等级的升级经验基准。

        Args:
            level: 等级，1～200。

        Returns:
            基准模型实例，不存在则返回 None。

        Raises:
            DatabaseError: 当查询失败时抛出。
        """
        sql = f"""
            SELECT level, level_up_exp, cumulative_exp, note
            FROM {self.LEVEL_EXP_TABLE}
            WHERE level = ?
        """
        try:
            results = DatabaseConnection.executeQuery(sql, (level,))
            if results:
                return CommanderLevelExpModel.fromDict(results[0])
            return None
        except Exception as e:
            raise DatabaseError(f"查询等级经验基准失败: {e}")

    def findAllLevelExp(self) -> List[CommanderLevelExpModel]:
        """
        查询全部等级经验基准。

        Returns:
            基准模型列表，按等级升序。

        Raises:
            DatabaseError: 当查询失败时抛出。
        """
        sql = f"""
            SELECT level, level_up_exp, cumulative_exp, note
            FROM {self.LEVEL_EXP_TABLE}
            ORDER BY level
        """
        try:
            results = DatabaseConnection.executeQuery(sql)
            return [CommanderLevelExpModel.fromDict(row) for row in results]
        except Exception as e:
            raise DatabaseError(f"查询等级经验基准列表失败: {e}")
