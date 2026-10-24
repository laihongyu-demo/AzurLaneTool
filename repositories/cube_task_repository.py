"""
魔方任务看板数据访问层模块。

封装任务定义（``cube_task``）与完成记录（``cube_task_completion``）的读写。
"""

import sqlite3
from typing import List, Optional, Sequence

from models.cube_task_model import CubeTaskCompletionModel, CubeTaskModel
from repositories.base_repository import BaseRepository
from utils.constants import RESOURCE_TYPE_CUBE
from utils.db_connection import DatabaseConnection
from utils.exceptions import DatabaseError


class CubeTaskRepository(BaseRepository[CubeTaskModel]):
    """
    魔方任务看板数据访问类。

    任务定义由 ``sql/CreateCubeTaskTables.sql`` 初始化；完成记录一条对应一笔收入明细，
    以 ``(task_code, period_key)`` 唯一约束作为重复完成的最终防线。
    """

    TASK_TABLE = "cube_task"
    COMPLETION_TABLE = "cube_task_completion"

    def findAll(self, resource_type: str = RESOURCE_TYPE_CUBE) -> List[CubeTaskModel]:
        """
        查询指定资源的全部启用的任务定义。

        Args:
            resource_type: 资源类型，``cube`` 或 ``red_gem``。

        Returns:
            任务模型列表，按排序序号升序。

        Raises:
            DatabaseError: 当查询失败时抛出。
        """
        sql = f"""
            SELECT code, resource_type, grp, name, short_name, reward, period_type,
                   category, sort_order, active
            FROM {self.TASK_TABLE}
            WHERE active = 1 AND resource_type = ?
            ORDER BY sort_order
        """
        try:
            results = DatabaseConnection.executeQuery(sql, (resource_type,))
            return [CubeTaskModel.fromDict(row) for row in results]
        except Exception as e:
            raise DatabaseError(f"查询任务定义失败: {e}")

    def findById(self, record_id: str) -> Optional[CubeTaskModel]:
        """
        按任务编码查询任务定义。

        Args:
            record_id: 任务编码（如 ``daily_build_once``）。

        Returns:
            任务模型实例；不存在则返回 None。

        Raises:
            DatabaseError: 当查询失败时抛出。
        """
        return self.findByCode(record_id)

    def findByCode(self, code: str) -> Optional[CubeTaskModel]:
        """
        按任务编码查询任务定义。

        Args:
            code: 任务编码。

        Returns:
            任务模型实例；不存在则返回 None。

        Raises:
            DatabaseError: 当查询失败时抛出。
        """
        sql = f"""
            SELECT code, resource_type, grp, name, short_name, reward, period_type,
                   category, sort_order, active
            FROM {self.TASK_TABLE}
            WHERE code = ? AND active = 1
        """
        try:
            results = DatabaseConnection.executeQuery(sql, (code,))
            if results:
                return CubeTaskModel.fromDict(results[0])
            return None
        except Exception as e:
            raise DatabaseError(f"查询任务定义失败: {e}")

    def findCompletion(self, task_code: str, period_key: str) -> Optional[CubeTaskCompletionModel]:
        """
        查询某个任务在某个周期的完成记录。

        Args:
            task_code: 任务编码。
            period_key: 周期键。

        Returns:
            完成记录模型；不存在则返回 None。

        Raises:
            DatabaseError: 当查询失败时抛出。
        """
        sql = f"""
            SELECT id, task_code, period_key, completed_at, transaction_id, created_at
            FROM {self.COMPLETION_TABLE}
            WHERE task_code = ? AND period_key = ?
        """
        try:
            results = DatabaseConnection.executeQuery(sql, (task_code, period_key))
            if results:
                return CubeTaskCompletionModel.fromDict(results[0])
            return None
        except Exception as e:
            raise DatabaseError(f"查询任务完成记录失败: {e}")

    def findCompletionsByPeriodKeys(
        self, period_keys: Sequence[str]
    ) -> List[CubeTaskCompletionModel]:
        """
        按周期键批量查询完成记录（看板一次取齐当日/当周/当月/当期）。

        Args:
            period_keys: 周期键列表。

        Returns:
            完成记录模型列表；入参为空时返回空列表。

        Raises:
            DatabaseError: 当查询失败时抛出。
        """
        keys = [key for key in period_keys if key]
        if not keys:
            return []

        placeholders = ", ".join("?" for _ in keys)
        sql = f"""
            SELECT id, task_code, period_key, completed_at, transaction_id, created_at
            FROM {self.COMPLETION_TABLE}
            WHERE period_key IN ({placeholders})
        """
        try:
            results = DatabaseConnection.executeQuery(sql, tuple(keys))
            return [CubeTaskCompletionModel.fromDict(row) for row in results]
        except Exception as e:
            raise DatabaseError(f"批量查询任务完成记录失败: {e}")

    def findCompletionsByTaskCodes(
        self, task_codes: Sequence[str]
    ) -> List[CubeTaskCompletionModel]:
        """
        按任务编码查询全部完成记录（供迁移/核对脚本使用）。

        Args:
            task_codes: 任务编码列表。

        Returns:
            完成记录模型列表。

        Raises:
            DatabaseError: 当查询失败时抛出。
        """
        codes = [code for code in task_codes if code]
        if not codes:
            return []

        placeholders = ", ".join("?" for _ in codes)
        sql = f"""
            SELECT id, task_code, period_key, completed_at, transaction_id, created_at
            FROM {self.COMPLETION_TABLE}
            WHERE task_code IN ({placeholders})
            ORDER BY completed_at
        """
        try:
            results = DatabaseConnection.executeQuery(sql, tuple(codes))
            return [CubeTaskCompletionModel.fromDict(row) for row in results]
        except Exception as e:
            raise DatabaseError(f"按任务查询完成记录失败: {e}")

    def insertCompletion(
        self,
        completion: CubeTaskCompletionModel,
        conn: Optional[sqlite3.Connection] = None
    ) -> Optional[int]:
        """
        写入完成记录。

        使用 ``ON CONFLICT DO NOTHING``，同周期重复完成时返回 None（由调用方转为友好提示）。

        Args:
            completion: 完成记录模型。
            conn: 可选的调用方连接（与明细写入合并进同一事务）。

        Returns:
            新记录 ID；已存在同周期记录时返回 None。

        Raises:
            DatabaseError: 当写入失败时抛出。
        """
        sql = f"""
            INSERT INTO {self.COMPLETION_TABLE}
                (task_code, period_key, completed_at, transaction_id)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(task_code, period_key) DO NOTHING
        """
        params = (
            completion.task_code, completion.period_key,
            completion.completed_at, completion.transaction_id,
        )
        try:
            if conn is not None:
                cursor = conn.execute(sql, params)
                return cursor.lastrowid if cursor.rowcount > 0 else None
            with self._getConnection() as own:
                cursor = own.execute(sql, params)
                return cursor.lastrowid if cursor.rowcount > 0 else None
        except sqlite3.Error as e:
            raise DatabaseError(f"写入任务完成记录失败: {e}")

    def deleteCompletion(
        self, completion_id: int, conn: Optional[sqlite3.Connection] = None
    ) -> bool:
        """
        删除完成记录。

        Args:
            completion_id: 完成记录 ID。
            conn: 可选的调用方连接。

        Returns:
            删除是否成功。

        Raises:
            DatabaseError: 当删除失败时抛出。
        """
        sql = f"DELETE FROM {self.COMPLETION_TABLE} WHERE id = ?"
        try:
            if conn is not None:
                return conn.execute(sql, (completion_id,)).rowcount > 0
            return DatabaseConnection.executeUpdate(sql, (completion_id,)) > 0
        except sqlite3.Error as e:
            raise DatabaseError(f"删除任务完成记录失败: {e}")

    def deleteCompletionByTaskPeriod(self, task_code: str, period_key: str) -> bool:
        """
        按任务 + 周期删除完成记录（迁移/修复脚本使用）。

        Args:
            task_code: 任务编码。
            period_key: 周期键。

        Returns:
            删除是否成功。

        Raises:
            DatabaseError: 当删除失败时抛出。
        """
        sql = f"DELETE FROM {self.COMPLETION_TABLE} WHERE task_code = ? AND period_key = ?"
        try:
            return DatabaseConnection.executeUpdate(sql, (task_code, period_key)) > 0
        except Exception as e:
            raise DatabaseError(f"删除任务完成记录失败: {e}")

    def insert(self, record: CubeTaskModel) -> int:
        """
        新增任务定义（一般只由 SQL 脚本初始化，此方法供测试/扩展使用）。

        Args:
            record: 任务模型。

        Returns:
            受影响行数（1）。

        Raises:
            DatabaseError: 当写入失败时抛出。
        """
        sql = f"""
            INSERT INTO {self.TASK_TABLE}
                (code, resource_type, grp, name, reward, period_type, category,
                 sort_order, active)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        params = (
            record.code, record.resource_type, record.grp, record.name, record.reward,
            record.period_type, record.category, record.sort_order, record.active,
        )
        try:
            return DatabaseConnection.executeUpdate(sql, params)
        except Exception as e:
            raise DatabaseError(f"新增任务定义失败: {e}")

    def update(self, record: CubeTaskModel) -> bool:
        """
        更新任务定义。

        Args:
            record: 任务模型，``code`` 必填。

        Returns:
            更新是否成功。

        Raises:
            DatabaseError: 当更新失败时抛出。
        """
        sql = f"""
            UPDATE {self.TASK_TABLE}
               SET resource_type = ?, grp = ?, name = ?, reward = ?, period_type = ?,
                   category = ?, sort_order = ?, active = ?
             WHERE code = ?
        """
        params = (
            record.resource_type, record.grp, record.name, record.reward,
            record.period_type, record.category, record.sort_order, record.active,
            record.code,
        )
        try:
            return DatabaseConnection.executeUpdate(sql, params) > 0
        except Exception as e:
            raise DatabaseError(f"更新任务定义失败: {e}")

    def delete(self, record_id: str) -> bool:
        """
        删除任务定义。

        Args:
            record_id: 任务编码。

        Returns:
            删除是否成功。

        Raises:
            DatabaseError: 当删除失败时抛出。
        """
        sql = f"DELETE FROM {self.TASK_TABLE} WHERE code = ?"
        try:
            return DatabaseConnection.executeUpdate(sql, (record_id,)) > 0
        except Exception as e:
            raise DatabaseError(f"删除任务定义失败: {e}")
