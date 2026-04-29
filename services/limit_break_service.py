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
from utils.logger import log


@dataclass
class LimitBreakResult:
    """
    界限突破结果数据类。

    Attributes:
        success: 是否成功。
        ship_name: 舰娘名称。
        old_star: 原星级。
        new_star: 新星级。
        is_max_star: 是否达到满星。
        tp_value: 科技点增加值。
        buff_details: Buff详情列表。
        message: 结果消息。
    """
    success: bool
    ship_name: str = ""
    old_star: int = 0
    new_star: int = 0
    is_max_star: bool = False
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

        parts = [f"舰娘\"{self.ship_name}\"界限突破成功"]
        parts.append(f"{self.old_star}星→{self.new_star}星")

        if self.is_max_star:
            parts.append("已达满星")

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


class LimitBreakService:
    """
    界限突破服务类。

    封装舰娘界限突破相关的业务逻辑，确保事务完整性。
    """

    MAX_STAR_MAP = {
        'UR': 6,
        'DR': 6,
        'SSR': 6,
        'PRY': 6,
        'SR': 5,
        'R': 5,
        'N': 4
    }

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

        查询条件：
        - ship_star < CASE WHEN ship_rarity IN ('UR', 'DR', 'SSR', 'PRY') THEN 6
                           WHEN ship_rarity IN ('SR', 'R') THEN 5
                           WHEN ship_rarity = 'N' THEN 4 END
        - ship_group != '改造'
        - codex_unlock = 'Y'

        Returns:
            可突破舰娘模型列表。
        """
        sql = """
            SELECT codex_id, ship_name, ship_level, ship_star, ship_rarity,
                   ship_typ, ship_group, ship_aid, ship_camp, ship_liking,
                   oath_status, codex_unlock, date_edit
            FROM codex_group
            WHERE ship_star < CASE
                WHEN ship_rarity IN ('UR', 'DR', 'SSR', 'PRY') THEN 6
                WHEN ship_rarity IN ('SR', 'R') THEN 5
                WHEN ship_rarity = 'N' THEN 4
                END
              AND ship_group != '改造'
              AND codex_unlock = 'Y'
            ORDER BY ship_aid DESC, codex_id DESC
        """
        try:
            with self._group_repository._getConnection() as conn:
                cursor = conn.execute(sql)
                return [CodexGroupModel.fromDict(dict(row)) for row in cursor.fetchall()]
        except sqlite3.Error as e:
            raise DatabaseError(f"查询可突破舰娘列表失败: {e}")

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

    def getMaxStar(self, ship_rarity: str) -> int:
        """
        根据稀有度获取满星数值。

        Args:
            ship_rarity: 舰娘稀有度。

        Returns:
            满星数值。
        """
        return self.MAX_STAR_MAP.get(ship_rarity, 0)

    def limitBreak(self, codex_id) -> LimitBreakResult:
        """
        执行舰娘界限突破（增加1星）。

        当舰娘达到满星时，同步更新tp表和buff表中"条件满星"相关的记录。

        Args:
            codex_id: 图鉴ID。

        Returns:
            LimitBreakResult 突破结果对象。

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

        max_star = self.getMaxStar(ship.ship_rarity)
        if ship.ship_star >= max_star:
            return LimitBreakResult(
                success=False,
                ship_name=ship.ship_name,
                message=f"舰娘 '{ship.ship_name}' 已达满星"
            )

        new_star = ship.ship_star + 1
        is_max_star = (new_star == max_star)

        try:
            with DatabaseContext(self._group_repository.dbPath) as conn:
                self._updateShipStar(conn, codex_id, new_star)

                if is_max_star:
                    tp_value = self._updateMaxStarTp(conn, codex_id)
                    buff_details = self._updateMaxStarBuff(conn, codex_id)
                else:
                    tp_value = 0
                    buff_details = []

            log.info(f"舰娘 '{ship.ship_name}' 界限突破成功: {ship.ship_star}星→{new_star}星")

            return LimitBreakResult(
                success=True,
                ship_name=ship.ship_name,
                old_star=ship.ship_star,
                new_star=new_star,
                is_max_star=is_max_star,
                tp_value=tp_value,
                buff_details=buff_details,
                message=f"舰娘 '{ship.ship_name}' 界限突破成功"
            )
        except sqlite3.Error as e:
            log.error(f"界限突破操作失败: {e}")
            raise DatabaseError(f"界限突破操作失败: {e}")

    def limitBreakMax(self, codex_id) -> LimitBreakResult:
        """
        执行舰娘界限突破·MAX（直接满星）。

        当舰娘达到满星时，同步更新tp表和buff表中"条件满星"相关的记录。

        Args:
            codex_id: 图鉴ID。

        Returns:
            LimitBreakResult 突破结果对象。

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

        max_star = self.getMaxStar(ship.ship_rarity)
        if ship.ship_star >= max_star:
            return LimitBreakResult(
                success=False,
                ship_name=ship.ship_name,
                message=f"舰娘 '{ship.ship_name}' 已达满星"
            )

        new_star = max_star
        is_max_star = True

        try:
            with DatabaseContext(self._group_repository.dbPath) as conn:
                self._updateShipStar(conn, codex_id, new_star)

                tp_value = self._updateMaxStarTp(conn, codex_id)
                buff_details = self._updateMaxStarBuff(conn, codex_id)

            log.info(f"舰娘 '{ship.ship_name}' 界限突破·MAX成功: {ship.ship_star}星→{new_star}星")

            return LimitBreakResult(
                success=True,
                ship_name=ship.ship_name,
                old_star=ship.ship_star,
                new_star=new_star,
                is_max_star=is_max_star,
                tp_value=tp_value,
                buff_details=buff_details,
                message=f"舰娘 '{ship.ship_name}' 界限突破·MAX成功"
            )
        except sqlite3.Error as e:
            log.error(f"界限突破·MAX操作失败: {e}")
            raise DatabaseError(f"界限突破·MAX操作失败: {e}")

    def _updateShipStar(self, conn: sqlite3.Connection, codex_id: str, ship_star: int) -> int:
        """更新舰娘星级。"""
        sql = "UPDATE codex_group SET ship_star = ? WHERE codex_id = ?"
        cursor = conn.execute(sql, (ship_star, codex_id))
        return cursor.rowcount

    def _updateMaxStarTp(self, conn: sqlite3.Connection, codex_id: str) -> int:
        """更新满星相关的TP解锁状态并返回科技点值。"""
        sql = """
            UPDATE codex_tp
            SET tp_unlock = 'Y'
            WHERE codex_id = ? AND unlock_cond = '条件满星'
        """
        conn.execute(sql, (codex_id,))

        sql_value = """
            SELECT COALESCE(SUM(tp_value), 0) as total
            FROM codex_tp
            WHERE codex_id = ? AND unlock_cond = '条件满星' AND tp_unlock = 'Y'
        """
        cursor = conn.execute(sql_value, (codex_id,))
        row = cursor.fetchone()
        return row[0] if row else 0

    def _updateMaxStarBuff(self, conn: sqlite3.Connection, codex_id: str) -> List[Dict]:
        """更新满星相关的Buff解锁状态并返回详情。"""
        sql = """
            UPDATE codex_buff
            SET buff_unlock = 'Y'
            WHERE codex_id = ? AND buff_cond = '条件满星'
        """
        conn.execute(sql, (codex_id,))

        sql_details = """
            SELECT boost_typ as ship_typ, buff_typ, buff_value
            FROM codex_buff
            WHERE codex_id = ? AND buff_cond = '条件满星' AND buff_unlock = 'Y'
        """
        cursor = conn.execute(sql_details, (codex_id,))
        return [dict(row) for row in cursor.fetchall()]
