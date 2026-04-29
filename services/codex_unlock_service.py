"""
舰娘解锁服务模块。

提供舰娘解锁相关的业务逻辑处理。
"""

import sqlite3
from dataclasses import dataclass
from typing import List, Optional, Tuple, Dict

from models.codex_model import CodexGroupModel
from repositories.codex_repository import (
    CodexGroupRepository, CodexTpRepository, CodexBuffRepository
)
from utils.db_connection import DatabaseContext
from utils.exceptions import DatabaseError, ValidationError


@dataclass
class UnlockResult:
    """
    解锁结果数据类。

    Attributes:
        success: 是否成功。
        ship_name: 舰娘名称。
        ship_group: 舰娘分组。
        tp_value: 科技点增加值。
        buff_details: Buff详情列表，每项包含ship_typ, buff_typ, buff_value。
        message: 结果消息。
    """
    success: bool
    ship_name: str = ""
    ship_group: str = ""
    tp_value: int = 0
    buff_details: List[Dict] = None
    message: str = ""

    def __post_init__(self):
        if self.buff_details is None:
            self.buff_details = []

    def toStatusBarMessage(self) -> str:
        """生成statusBar显示消息。"""
        if not self.success:
            return self.message

        parts = [f"舰娘\"{self.ship_name}\"解锁成功"]

        if self.tp_value > 0:
            parts.append(f"科技点+{self.tp_value}")

        if self.buff_details:
            buff_parts = []
            for buff in self.buff_details:
                ship_typ = buff.get('ship_typ', '')
                buff_typ = buff.get('buff_typ', '')
                buff_value = buff.get('buff_value', 0)
                if ship_typ and buff_typ:
                    buff_parts.append(f"{ship_typ} {buff_typ}+{buff_value}")
            if buff_parts:
                parts.append(" ".join(buff_parts))

        return " | ".join(parts)


class CodexUnlockService:
    """
    舰娘解锁服务类。

    封装舰娘解锁相关的业务逻辑，确保事务完整性。
    """

    def __init__(
        self,
        group_repository: Optional[CodexGroupRepository] = None,
        tp_repository: Optional[CodexTpRepository] = None,
        buff_repository: Optional[CodexBuffRepository] = None
    ):
        """
        初始化解锁服务。

        Args:
            group_repository: 舰娘图鉴组数据访问实例。
            tp_repository: TP数据访问实例。
            buff_repository: Buff数据访问实例。
        """
        self._group_repository = group_repository or CodexGroupRepository()
        self._tp_repository = tp_repository or CodexTpRepository()
        self._buff_repository = buff_repository or CodexBuffRepository()

    def getLockedShips(self) -> List[CodexGroupModel]:
        """
        获取所有未解锁的舰娘列表。

        Returns:
            未解锁舰娘模型列表。
        """
        return self._group_repository.findLocked()

    def getUnlockedShips(self) -> List[CodexGroupModel]:
        """
        获取所有已解锁的舰娘列表。

        Returns:
            已解锁舰娘模型列表。
        """
        return self._group_repository.findUnlocked()

    def getShipById(self, codex_id) -> Optional[CodexGroupModel]:
        """
        根据ID获取舰娘详情。

        Args:
            codex_id: 图鉴ID（支持纯数字或字母+数字组合格式）。

        Returns:
            舰娘模型实例。
        """
        codex_id = str(codex_id) if codex_id is not None else ""
        return self._group_repository.findById(codex_id)

    def unlockShip(self, codex_id) -> UnlockResult:
        """
        解锁舰娘。

        在同一事务中更新三个表的解锁状态：
        1. codex_group 表的 codex_unlock 字段
        2. codex_tp 表中 unlock_cond='解锁' 的 tp_unlock 字段（特殊舰娘跳过）
        3. codex_buff 表中 buff_cond='解锁' 的 buff_unlock 字段（特殊舰娘跳过）

        特殊舰娘类型（联动、μ兵装、小船、改造）不更新 tp 和 buff 表。

        Args:
            codex_id: 图鉴ID（支持纯数字或字母+数字组合格式）。

        Returns:
            UnlockResult 解锁结果对象。

        Raises:
            ValidationError: 当参数验证失败时抛出。
            DatabaseError: 当数据库操作失败时抛出。
        """
        if codex_id is None:
            raise ValidationError("无效的图鉴ID")

        codex_id = str(codex_id).strip()
        if not codex_id:
            raise ValidationError("图鉴ID不能为空")

        ship = self._group_repository.findById(codex_id)
        if ship is None:
            return UnlockResult(
                success=False,
                message=f"未找到图鉴ID为 {codex_id} 的舰娘"
            )

        if ship.codex_unlock == "Y":
            return UnlockResult(
                success=False,
                ship_name=ship.ship_name,
                message=f"舰娘 '{ship.ship_name}' 已经解锁"
            )

        skip_tp_buff = ship.ship_group in ("联动", "μ兵装", "小船", "改造")

        try:
            with DatabaseContext(self._group_repository.dbPath) as conn:
                group_updated = self._updateGroupUnlock(conn, codex_id)

                if skip_tp_buff:
                    tp_updated = 0
                    buff_updated = 0
                    tp_value = 0
                    buff_details = []
                else:
                    tp_updated = self._updateTpUnlock(conn, codex_id)
                    buff_updated = self._updateBuffUnlock(conn, codex_id)
                    tp_value = self._getTpValue(conn, codex_id)
                    buff_details = self._getBuffDetails(conn, codex_id)

            if skip_tp_buff:
                return UnlockResult(
                    success=True,
                    ship_name=ship.ship_name,
                    ship_group=ship.ship_group,
                    tp_value=0,
                    buff_details=[],
                    message=f"舰娘 '{ship.ship_name}' 解锁成功（{ship.ship_group}类型，跳过TP/Buff更新）"
                )

            return UnlockResult(
                success=True,
                ship_name=ship.ship_name,
                ship_group=ship.ship_group,
                tp_value=tp_value,
                buff_details=buff_details,
                message=f"舰娘 '{ship.ship_name}' 解锁成功"
            )
        except sqlite3.Error as e:
            raise DatabaseError(f"解锁操作失败: {e}")

    def _updateGroupUnlock(self, conn: sqlite3.Connection, codex_id: str) -> int:
        """更新图鉴组解锁状态。"""
        sql = "UPDATE codex_group SET codex_unlock = 'Y' WHERE codex_id = ?"
        cursor = conn.execute(sql, (codex_id,))
        return cursor.rowcount

    def _updateTpUnlock(self, conn: sqlite3.Connection, codex_id: str) -> int:
        """更新TP解锁状态。"""
        sql = """
            UPDATE codex_tp
            SET tp_unlock = 'Y'
            WHERE codex_id = ? AND unlock_cond = '解锁'
        """
        cursor = conn.execute(sql, (codex_id,))
        return cursor.rowcount

    def _updateBuffUnlock(self, conn: sqlite3.Connection, codex_id: str) -> int:
        """更新Buff解锁状态。"""
        sql = """
            UPDATE codex_buff
            SET buff_unlock = 'Y'
            WHERE codex_id = ? AND buff_cond = '解锁'
        """
        cursor = conn.execute(sql, (codex_id,))
        return cursor.rowcount

    def _getTpValue(self, conn: sqlite3.Connection, codex_id: str) -> int:
        """获取解锁的科技点值。"""
        sql = """
            SELECT COALESCE(SUM(tp_value), 0) as total
            FROM codex_tp
            WHERE codex_id = ? AND unlock_cond = '解锁' AND tp_unlock = 'Y'
        """
        cursor = conn.execute(sql, (codex_id,))
        row = cursor.fetchone()
        return row[0] if row else 0

    def _getBuffDetails(self, conn: sqlite3.Connection, codex_id: str) -> List[Dict]:
        """获取解锁的Buff详情。"""
        sql = """
            SELECT boost_typ as ship_typ, buff_typ, buff_value
            FROM codex_buff
            WHERE codex_id = ? AND buff_cond = '解锁' AND buff_unlock = 'Y'
        """
        cursor = conn.execute(sql, (codex_id,))
        return [dict(row) for row in cursor.fetchall()]

    def getUnlockStatistics(self) -> dict:
        """
        获取解锁统计信息。

        收藏率计算排除联动舰娘（ship_group='联动'）。
        数量显示格式为"不含联动总数（含联动总数）"。

        Returns:
            包含解锁统计的字典，包含以下字段：
            - total: 含联动舰娘总数
            - total_excluding_collab: 不含联动舰娘总数
            - locked: 含联动未解锁数
            - locked_excluding_collab: 不含联动未解锁数
            - unlocked: 含联动已解锁数
            - unlocked_excluding_collab: 不含联动已解锁数
            - unlock_rate: 收藏率（排除联动舰娘计算）
        """
        all_ships = self._group_repository.findAll()
        all_ships_excluding_collab = self._group_repository.findAllExcludingCollab()

        locked_ships = [s for s in all_ships if s.codex_unlock == "N"]
        unlocked_ships = [s for s in all_ships if s.codex_unlock == "Y"]

        locked_excluding_collab = [s for s in all_ships_excluding_collab if s.codex_unlock == "N"]
        unlocked_excluding_collab = [s for s in all_ships_excluding_collab if s.codex_unlock == "Y"]

        total_excluding_collab = len(all_ships_excluding_collab)
        unlock_rate = (
            len(unlocked_excluding_collab) / total_excluding_collab * 100
            if total_excluding_collab > 0 else 0
        )

        return {
            "total": len(all_ships),
            "total_excluding_collab": total_excluding_collab,
            "locked": len(locked_ships),
            "locked_excluding_collab": len(locked_excluding_collab),
            "unlocked": len(unlocked_ships),
            "unlocked_excluding_collab": len(unlocked_excluding_collab),
            "unlock_rate": unlock_rate
        }
