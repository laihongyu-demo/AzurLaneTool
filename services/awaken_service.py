"""
认知觉醒服务模块。

提供舰娘认知觉醒相关的业务逻辑处理。
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
from utils.unit_formatter import formatExact


AWAKEN_LEVELS = [
    "未觉醒",
    "认知觉醒一阶",
    "认知觉醒二阶",
    "认知觉醒三阶",
    "认知觉醒四阶",
    "认知觉醒五阶",
    "认知觉醒II",
]


@dataclass
class AwakenResult:
    """
    认知觉醒结果数据类。

    Attributes:
        success: 是否成功。
        ship_name: 舰娘名称。
        old_level: 原觉醒等级。
        new_level: 新觉醒等级。
        tp_value: 科技点增加值。
        buff_details: Buff详情列表。
        expend_gc: 本次觉醒消耗的物资。
        expend_limit: 本次觉醒消耗的心智单元。
        expend_limit2: 本次觉醒消耗的心智单元Ⅱ。
        message: 结果消息。
    """
    success: bool
    ship_name: str = ""
    old_level: str = ""
    new_level: str = ""
    tp_value: int = 0
    buff_details: List[Dict] = None
    expend_gc: int = 0
    expend_limit: int = 0
    expend_limit2: int = 0
    message: str = ""

    def __post_init__(self):
        if self.buff_details is None:
            self.buff_details = []

    def toStatusBarMessage(self) -> str:
        """生成statusBar显示消息（材料消耗不换算，带千分符）。"""
        if not self.success:
            return self.message

        parts = [f"舰娘\"{self.ship_name}\"觉醒成功"]
        parts.append(f"{self.old_level}→{self.new_level}")

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

        parts.append(self.formatConsume())

        return " | ".join(parts)

    def formatConsume(self) -> str:
        """
        生成本次觉醒的材料消耗文本。

        Returns:
            形如 ``本次消耗：物资 2,000 / 心智单元 200``；
            三项均为 0 时返回 ``本次消耗：无``（如四阶→五阶只需经验）。
        """
        items = []
        if self.expend_gc:
            items.append(f"物资 {formatExact(self.expend_gc)}")
        if self.expend_limit:
            items.append(f"心智单元 {formatExact(self.expend_limit)}")
        if self.expend_limit2:
            items.append(f"心智单元Ⅱ {formatExact(self.expend_limit2)}")

        if not items:
            return "本次消耗：无"
        return "本次消耗：" + " / ".join(items)


class AwakenService:
    """
    认知觉醒服务类。

    封装舰娘认知觉醒相关的业务逻辑，确保事务完整性。
    """

    def __init__(
        self,
        group_repository: Optional[CodexGroupRepository] = None,
        tp_repository: Optional[CodexTpRepository] = None,
        buff_repository: Optional[CodexBuffRepository] = None
    ):
        """
        初始化觉醒服务。

        Args:
            group_repository: 舰娘图鉴组数据访问实例。
            tp_repository: TP数据访问实例。
            buff_repository: Buff数据访问实例。
        """
        self._group_repository = group_repository or CodexGroupRepository()
        self._tp_repository = tp_repository or CodexTpRepository()
        self._buff_repository = buff_repository or CodexBuffRepository()

    def getAwakenableShips(self) -> List[CodexGroupModel]:
        """
        获取可进行认知觉醒的舰娘列表。

        Returns:
            可觉醒舰娘模型列表。
        """
        return self._group_repository.findAwakenable()

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

    def getAvailableLevels(self, current_level: str) -> List[str]:
        """
        获取可升级的觉醒等级列表。

        Args:
            current_level: 当前觉醒等级。

        Returns:
            可升级的等级列表。
        """
        try:
            current_index = AWAKEN_LEVELS.index(current_level)
        except ValueError:
            current_index = 0

        return AWAKEN_LEVELS[current_index + 1:]

    def awakenShip(self, codex_id, new_level: str) -> AwakenResult:
        """
        执行舰娘认知觉醒。

        当new_level为"认知觉醒五阶"时，同步更新Lv.120相关的TP和Buff记录。

        Args:
            codex_id: 图鉴ID。
            new_level: 新的觉醒等级。

        Returns:
            AwakenResult 觉醒结果对象。

        Raises:
            ValidationError: 当参数验证失败时抛出。
            DatabaseError: 当数据库操作失败时抛出。
        """
        if codex_id is None:
            raise ValidationError("无效的图鉴ID")

        codex_id = str(codex_id).strip()
        if not codex_id:
            raise ValidationError("图鉴ID不能为空")

        if new_level not in AWAKEN_LEVELS:
            raise ValidationError(f"无效的觉醒等级: {new_level}")

        ship = self._group_repository.findById(codex_id)
        if ship is None:
            return AwakenResult(
                success=False,
                message=f"未找到图鉴ID为 {codex_id} 的舰娘"
            )

        if ship.codex_unlock != "Y":
            return AwakenResult(
                success=False,
                ship_name=ship.ship_name,
                message=f"舰娘 '{ship.ship_name}' 尚未解锁"
            )

        if ship.ship_level == "认知觉醒II":
            return AwakenResult(
                success=False,
                ship_name=ship.ship_name,
                message=f"舰娘 '{ship.ship_name}' 已达到最高觉醒等级"
            )

        available_levels = self.getAvailableLevels(ship.ship_level)
        if new_level not in available_levels:
            return AwakenResult(
                success=False,
                ship_name=ship.ship_name,
                message=f"无法从 '{ship.ship_level}' 升级到 '{new_level}'"
            )

        update_lv120 = (new_level == "认知觉醒五阶")
        consume = self._getConsumeMaterials(codex_id, ship.ship_level, new_level)

        try:
            with DatabaseContext(self._group_repository.dbPath) as conn:
                self._updateShipLevel(conn, codex_id, new_level)

                if update_lv120:
                    tp_value = self._updateLv120Tp(conn, codex_id)
                    buff_details = self._updateLv120Buff(conn, codex_id)
                else:
                    tp_value = 0
                    buff_details = []

            return AwakenResult(
                success=True,
                ship_name=ship.ship_name,
                old_level=ship.ship_level,
                new_level=new_level,
                tp_value=tp_value,
                buff_details=buff_details,
                expend_gc=consume["expend_gc"],
                expend_limit=consume["expend_limit"],
                expend_limit2=consume["expend_limit2"],
                message=f"舰娘 '{ship.ship_name}' 觉醒成功"
            )
        except sqlite3.Error as e:
            raise DatabaseError(f"觉醒操作失败: {e}")

    def _getConsumeMaterials(self, codex_id, from_level: str, to_level: str) -> Dict[str, int]:
        """
        查询本次觉醒消耗的材料。

        材料基准数据缺失（如旧库没有 awakening_of_mind 表）时返回全 0，
        不影响觉醒主流程。

        Args:
            codex_id: 图鉴ID。
            from_level: 觉醒前等级。
            to_level: 觉醒后等级。

        Returns:
            包含expend_gc、expend_limit、expend_limit2的字典。
        """
        try:
            return self._group_repository.calculateAwakenConsume(codex_id, from_level, to_level)
        except DatabaseError:
            return {"expend_gc": 0, "expend_limit": 0, "expend_limit2": 0}

    def _updateShipLevel(self, conn: sqlite3.Connection, codex_id: str, ship_level: str) -> int:
        """更新舰娘觉醒等级。"""
        sql = "UPDATE codex_group SET ship_level = ? WHERE codex_id = ?"
        cursor = conn.execute(sql, (ship_level, codex_id))
        return cursor.rowcount

    def _updateLv120Tp(self, conn: sqlite3.Connection, codex_id: str) -> int:
        """更新Lv.120相关的TP解锁状态并返回科技点值。"""
        sql = """
            UPDATE codex_tp
            SET tp_unlock = 'Y'
            WHERE codex_id = ? AND unlock_cond = 'Lv.120'
        """
        cursor = conn.execute(sql, (codex_id,))

        sql_value = """
            SELECT COALESCE(SUM(tp_value), 0) as total
            FROM codex_tp
            WHERE codex_id = ? AND unlock_cond = 'Lv.120' AND tp_unlock = 'Y'
        """
        cursor = conn.execute(sql_value, (codex_id,))
        row = cursor.fetchone()
        return row[0] if row else 0

    def _updateLv120Buff(self, conn: sqlite3.Connection, codex_id: str) -> List[Dict]:
        """更新Lv.120相关的Buff解锁状态并返回详情。"""
        sql = """
            UPDATE codex_buff
            SET buff_unlock = 'Y'
            WHERE codex_id = ? AND buff_cond = 'Lv.120'
        """
        conn.execute(sql, (codex_id,))

        sql_details = """
            SELECT boost_typ as ship_typ, buff_typ, buff_value
            FROM codex_buff
            WHERE codex_id = ? AND buff_cond = 'Lv.120' AND buff_unlock = 'Y'
        """
        cursor = conn.execute(sql_details, (codex_id,))
        return [dict(row) for row in cursor.fetchall()]
