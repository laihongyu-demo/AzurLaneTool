"""
界限突破服务模块。

提供舰娘界限突破相关的业务逻辑处理。
"""

import sqlite3
from dataclasses import dataclass
from typing import List, Optional, Dict

from models.codex_model import CodexGroupModel
from repositories.codex_repository import (
    CodexGroupRepository, CodexTpRepository, CodexBuffRepository
)
from utils.db_connection import DatabaseContext
from utils.exceptions import DatabaseError, ValidationError


MAX_STAR_MAP = {
    'UR': 6, 'DR': 6, 'SSR': 6, 'PRY': 6,
    'SR': 5, 'R': 5,
    'N': 6
}

MAX_STAR_DEFAULT = 6


@dataclass
class LimitBreakResult:
    """
    界限突破结果数据类。

    Attributes:
        success: 是否成功。
        ship_name: 舰娘名称。
        old_star: 原星级。
        new_star: 新星级。
        is_full_star: 是否达到满星。
        tp_value: 满星获得的科技点值（非满星时为0）。
        message: 结果消息。
    """
    success: bool
    ship_name: str = ""
    old_star: int = 0
    new_star: int = 0
    is_full_star: bool = False
    tp_value: int = 0
    message: str = ""

    def toStatusBarMessage(self) -> str:
        """生成statusBar显示消息。"""
        if not self.success:
            return self.message

        parts = [f"舰娘\"{self.ship_name}\"界限突破成功"]
        parts.append(f"{self.old_star}星→{self.new_star}星")

        if self.is_full_star and self.tp_value > 0:
            parts.append(f"科技点+{self.tp_value}")

        return " | ".join(parts)


class LimitBreakService:
    """
    界限突破服务类。

    封装舰娘界限突破相关的业务逻辑，确保事务完整性。
    """

    def __init__(
        self,
        group_repository: Optional[CodexGroupRepository] = None,
        tp_repository: Optional[CodexTpRepository] = None,
        buff_repository: Optional[CodexBuffRepository] = None
    ):
        """
        初始化界限突破服务。

        Args:
            group_repository: 舰娘图鉴组数据访问实例。
            tp_repository: TP数据访问实例。
            buff_repository: Buff数据访问实例。
        """
        self._group_repository = group_repository or CodexGroupRepository()
        self._tp_repository = tp_repository or CodexTpRepository()
        self._buff_repository = buff_repository or CodexBuffRepository()

    def getLimitBreakableShips(self) -> List[CodexGroupModel]:
        """
        获取可进行界限突破的舰娘列表。

        Returns:
            可界限突破的舰娘模型列表。
        """
        return self._group_repository.findLimitBreakable()

    def getShipById(self, codex_id) -> Optional[CodexGroupModel]:
        """
        根据ID获取舰娘详情。

        Args:
            codex_id: 图鉴ID。

        Returns:
            舰娘模型实例。
        """
        codex_id = str(codex_id) if codex_id is not None else ""
        return self._group_repository.findById(codex_id)

    def _getMaxStar(self, ship_rarity: str) -> int:
        """
        根据稀有度获取满星阈值。

        Args:
            ship_rarity: 舰娘稀有度。

        Returns:
            满星数值。
        """
        return MAX_STAR_MAP.get(ship_rarity, MAX_STAR_DEFAULT)

    def _updateFullStarConditions(self, conn: sqlite3.Connection, codex_id: str) -> None:
        """
        更新满星相关的条件解锁状态。

        在同一连接中更新tp表和buff表的满星条件记录。

        Args:
            conn: 数据库连接。
            codex_id: 图鉴ID。
        """
        tp_sql = "UPDATE codex_tp SET tp_unlock = 'Y' WHERE codex_id = ? AND unlock_cond = '满星'"
        conn.execute(tp_sql, (codex_id,))

        buff_sql = "UPDATE codex_buff SET buff_unlock = 'Y' WHERE codex_id = ? AND buff_cond = '满星'"
        conn.execute(buff_sql, (codex_id,))

    def limitBreak(self, codex_id) -> LimitBreakResult:
        """
        执行舰娘界限突破（星级+1）。

        将舰娘星级提升1级，若达到满星则同步更新tp表和buff表的满星条件。

        Args:
            codex_id: 图鉴ID。

        Returns:
            LimitBreakResult 界限突破结果对象。

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
            return LimitBreakResult(
                success=False,
                message=f"未找到图鉴ID为 {codex_id} 的舰娘"
            )

        if ship.codex_unlock != "Y":
            return LimitBreakResult(
                success=False,
                ship_name=ship.ship_name,
                message=f"舰娘 '{ship.ship_name}' 尚未解锁"
            )

        if ship.ship_group == "改造":
            return LimitBreakResult(
                success=False,
                ship_name=ship.ship_name,
                message=f"舰娘 '{ship.ship_name}' 为改造类型，不支持界限突破"
            )

        max_star = self._getMaxStar(ship.ship_rarity)
        old_star = ship.ship_star
        new_star = old_star + 1

        if new_star > max_star:
            return LimitBreakResult(
                success=False,
                ship_name=ship.ship_name,
                old_star=old_star,
                message=f"舰娘 '{ship.ship_name}' 已达到满星（{max_star}星）"
            )

        is_full_star = (new_star == max_star)
        tp_value = 0
        if is_full_star:
            tp_value = self._tp_repository.getTpValueByCondition(codex_id, "满星")

        try:
            with DatabaseContext(self._group_repository.dbPath) as conn:
                update_sql = "UPDATE codex_group SET ship_star = ? WHERE codex_id = ?"
                conn.execute(update_sql, (new_star, codex_id))

                if is_full_star:
                    self._updateFullStarConditions(conn, codex_id)

            return LimitBreakResult(
                success=True,
                ship_name=ship.ship_name,
                old_star=old_star,
                new_star=new_star,
                is_full_star=is_full_star,
                tp_value=tp_value,
                message=f"舰娘 '{ship.ship_name}' 界限突破成功"
            )
        except sqlite3.Error as e:
            raise DatabaseError(f"界限突破操作失败: {e}")

    def limitBreakMax(self, codex_id) -> LimitBreakResult:
        """
        执行舰娘界限突破·MAX（直接提升至满星）。

        将舰娘星级直接设置为满星，若原星级未满则同步更新tp表和buff表的满星条件。

        Args:
            codex_id: 图鉴ID。

        Returns:
            LimitBreakResult 界限突破结果对象。

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
            return LimitBreakResult(
                success=False,
                message=f"未找到图鉴ID为 {codex_id} 的舰娘"
            )

        if ship.codex_unlock != "Y":
            return LimitBreakResult(
                success=False,
                ship_name=ship.ship_name,
                message=f"舰娘 '{ship.ship_name}' 尚未解锁"
            )

        if ship.ship_group == "改造":
            return LimitBreakResult(
                success=False,
                ship_name=ship.ship_name,
                message=f"舰娘 '{ship.ship_name}' 为改造类型，不支持界限突破"
            )

        max_star = self._getMaxStar(ship.ship_rarity)
        old_star = ship.ship_star

        if old_star >= max_star:
            return LimitBreakResult(
                success=False,
                ship_name=ship.ship_name,
                old_star=old_star,
                message=f"舰娘 '{ship.ship_name}' 已达到满星（{max_star}星）"
            )

        new_star = max_star
        is_full_star = True
        tp_value = self._tp_repository.getTpValueByCondition(codex_id, "满星")

        try:
            with DatabaseContext(self._group_repository.dbPath) as conn:
                update_sql = "UPDATE codex_group SET ship_star = ? WHERE codex_id = ?"
                conn.execute(update_sql, (new_star, codex_id))

                self._updateFullStarConditions(conn, codex_id)

            return LimitBreakResult(
                success=True,
                ship_name=ship.ship_name,
                old_star=old_star,
                new_star=new_star,
                is_full_star=is_full_star,
                tp_value=tp_value,
                message=f"舰娘 '{ship.ship_name}' 界限突破·MAX成功"
            )
        except sqlite3.Error as e:
            raise DatabaseError(f"界限突破·MAX操作失败: {e}")