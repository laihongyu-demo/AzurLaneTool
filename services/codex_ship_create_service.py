"""
舰娘新增服务模块。

提供新增舰娘的业务逻辑处理，在单一事务中写入 codex_group、codex_tp、
codex_buff 三张表，并负责图鉴ID生成、字段校验、科技属性文本解析与SQL预览。
"""

import sqlite3
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from models.codex_model import CodexGroupModel, CodexTpModel, CodexBuffModel
from repositories.codex_repository import (
    CodexGroupRepository, CodexTpRepository, CodexBuffRepository
)
from utils import codex_options as options
from utils.codex_text_parser import parseBuffTextBlock
from utils.db_connection import DatabaseContext
from utils.exceptions import DatabaseError, ValidationError


@dataclass
class ShipCreateDraft:
    """
    新增舰娘草稿数据类。

    Attributes:
        codex_id: 图鉴ID。
        ship_name: 舰娘名称。
        ship_group: 舰娘分组。
        ship_typ: 舰船类型。
        ship_rarity: 稀有度。
        ship_star: 星级。
        ship_camp: 阵营。
        ship_aid: 实装日期（yyyy/MM/dd）。
        ship_level: 舰娘等级。
        ship_liking: 好感度。
        oath_status: 誓约状态。
        date_edit: 编辑日期（yyyy-MM-dd HH:mm:ss）。
        tp_values: 科技点数值，形如 {'解锁': '26', '满星': '52', 'Lv.120': '39'}，
            三项需同时填写或全部留空。
        buff_text: 科技属性原始数据文本，形如 {'解锁': '战巡/战列/航战 耐久+1',
            'Lv.120': '战巡/战列/航战 炮击+1'}。
    """

    codex_id: str = ""
    ship_name: str = ""
    ship_group: str = options.SHIP_GROUPS[0]
    ship_typ: str = ""
    ship_rarity: str = ""
    ship_star: int = 0
    ship_camp: str = ""
    ship_aid: str = ""
    ship_level: str = "未觉醒"
    ship_liking: str = "陌生"
    oath_status: str = "N"
    date_edit: str = ""
    tp_values: Dict[str, Any] = field(default_factory=dict)
    buff_text: Dict[str, str] = field(default_factory=dict)


@dataclass
class ShipCreateResult:
    """
    新增舰娘结果数据类。

    Attributes:
        success: 是否成功。
        codex_id: 图鉴ID。
        ship_name: 舰娘名称。
        ship_group: 舰娘分组。
        tp_count: 写入的科技点行数。
        buff_count: 写入的科技属性行数。
        message: 结果消息。
    """

    success: bool
    codex_id: str = ""
    ship_name: str = ""
    ship_group: str = ""
    tp_count: int = 0
    buff_count: int = 0
    message: str = ""

    def toStatusBarMessage(self) -> str:
        """生成statusBar显示消息。"""
        if not self.success:
            return self.message

        parts = [f"舰娘\"{self.ship_name}\"新增成功", f"图鉴ID:{self.codex_id}"]

        if self.tp_count or self.buff_count:
            parts.append(f"科技点{self.tp_count}条 科技属性{self.buff_count}条")
        else:
            parts.append(f"{self.ship_group}类型，无科技点/科技属性记录")

        return " | ".join(parts)


class CodexShipCreateService:
    """
    舰娘新增服务类。

    封装新增舰娘相关的业务逻辑，确保三张表的事务完整性。
    """

    def __init__(
        self,
        group_repository: Optional[CodexGroupRepository] = None,
        tp_repository: Optional[CodexTpRepository] = None,
        buff_repository: Optional[CodexBuffRepository] = None
    ):
        """
        初始化新增服务。

        Args:
            group_repository: 舰娘图鉴组数据访问实例。
            tp_repository: TP数据访问实例。
            buff_repository: Buff数据访问实例。
        """
        self._group_repository = group_repository or CodexGroupRepository()
        self._tp_repository = tp_repository or CodexTpRepository()
        self._buff_repository = buff_repository or CodexBuffRepository()

    def getNextCodexId(self, ship_group: str) -> str:
        """
        生成指定分组的下一个图鉴ID。

        Args:
            ship_group: 舰娘分组。

        Returns:
            下一个可用的图鉴ID字符串。
        """
        return self._group_repository.getNextCodexId(ship_group)

    def getGroupFieldDefaults(self, ship_group: str) -> Dict[str, str]:
        """
        获取分组默认字段形态（等级、好感度、誓约状态）。

        Args:
            ship_group: 舰娘分组。

        Returns:
            默认字段字典。
        """
        return options.getGroupFieldDefaults(ship_group)

    def getDefaultStar(self, ship_group: str, ship_rarity: str) -> int:
        """
        获取默认星级。

        Args:
            ship_group: 舰娘分组。
            ship_rarity: 稀有度。

        Returns:
            默认星级数值。
        """
        return options.getDefaultStar(ship_group, ship_rarity)

    def isNoTpBuffGroup(self, ship_group: str) -> bool:
        """
        判断分组是否不写入科技点与科技属性记录。

        Args:
            ship_group: 舰娘分组。

        Returns:
            无需写入时返回 True。
        """
        return options.isNoTpBuffGroup(ship_group)

    def findDuplicateShips(self, ship_name: str, ship_group: str) -> List[CodexGroupModel]:
        """
        查询同分组内的同名舰娘。

        Args:
            ship_name: 舰娘名称。
            ship_group: 舰娘分组。

        Returns:
            同名舰娘模型列表。
        """
        ship_name = str(ship_name).strip()
        if not ship_name:
            return []
        return self._group_repository.findByShipName(ship_name, ship_group)

    def parseBuffRows(self, buff_text: Optional[Dict[str, str]]) -> List[Dict]:
        """
        解析科技属性文本为明细行。

        供界面实时预览行数与错误定位使用。

        Args:
            buff_text: 解锁条件 -> 原始数据文本的映射。

        Returns:
            科技属性明细行列表。

        Raises:
            ValidationError: 当文本不合法时抛出。
        """
        return [row.toDict() for row in parseBuffTextBlock(buff_text)]

    def validateDraft(self, draft: ShipCreateDraft) -> None:
        """
        校验新增草稿。

        Args:
            draft: 新增舰娘草稿。

        Raises:
            ValidationError: 当草稿数据不合法时抛出。
        """
        self.normalizeDraft(draft)

    def normalizeDraft(self, draft: ShipCreateDraft) -> Dict:
        """
        规范化并校验草稿数据。

        Args:
            draft: 新增舰娘草稿。

        Returns:
            规范化后的数据字典，包含 tp_rows 与 buff_rows。

        Raises:
            ValidationError: 当草稿数据不合法时抛出。
        """
        if draft is None:
            raise ValidationError("新增数据不能为空")

        codex_id = str(draft.codex_id or "").strip()
        if not codex_id:
            raise ValidationError("图鉴ID不能为空")

        ship_name = str(draft.ship_name or "").strip()
        if not ship_name:
            raise ValidationError("舰娘名称不能为空")

        ship_group = str(draft.ship_group or "").strip()
        if ship_group not in options.SHIP_GROUPS:
            raise ValidationError(f"未知的舰娘分组: {ship_group or '空'}")

        ship_typ = str(draft.ship_typ or "").strip()
        if not ship_typ:
            raise ValidationError("舰船类型不能为空")

        ship_rarity = str(draft.ship_rarity or "").strip()
        if ship_rarity not in options.SHIP_RARITIES:
            raise ValidationError(f"未知的稀有度: {ship_rarity or '空'}")

        ship_camp = str(draft.ship_camp or "").strip()
        if not ship_camp:
            raise ValidationError("阵营不能为空")

        ship_aid = str(draft.ship_aid or "").strip()
        if not ship_aid:
            raise ValidationError("实装日期不能为空")
        if not _isValidShipAid(ship_aid):
            raise ValidationError("实装日期格式应为 yyyy/MM/dd")

        ship_star = _toInt(draft.ship_star, "星级")
        if ship_star < 0 or ship_star > 6:
            raise ValidationError("星级应在 0 ~ 6 之间")

        if self._group_repository.findById(codex_id) is not None:
            raise ValidationError(f"图鉴ID {codex_id} 已存在")

        no_tp_buff = options.isNoTpBuffGroup(ship_group)
        tp_rows = self._normalizeTpValues(draft.tp_values or {}, no_tp_buff, ship_group)
        buff_rows = self._normalizeBuffText(draft.buff_text or {}, no_tp_buff, ship_group)

        return {
            "codex_id": codex_id,
            "ship_name": ship_name,
            "ship_group": ship_group,
            "ship_typ": ship_typ,
            "ship_rarity": ship_rarity,
            "ship_star": ship_star,
            "ship_camp": ship_camp,
            "ship_aid": ship_aid,
            "ship_level": str(draft.ship_level if draft.ship_level is not None else ""),
            "ship_liking": str(draft.ship_liking if draft.ship_liking is not None else ""),
            "oath_status": str(draft.oath_status if draft.oath_status is not None else ""),
            "date_edit": str(draft.date_edit or "").strip() or None,
            "tp_rows": tp_rows,
            "buff_rows": buff_rows
        }

    def createShip(self, draft: ShipCreateDraft) -> ShipCreateResult:
        """
        新增舰娘。

        在同一事务中写入三张表：
        1. codex_group 图鉴记录（codex_unlock 固定为 'N'）
        2. codex_tp 科技点记录（联动、μ兵装、小船、改造类型跳过）
        3. codex_buff 科技属性记录（联动、μ兵装、小船、改造类型跳过）

        任一步写入失败则整体回滚。

        Args:
            draft: 新增舰娘草稿。

        Returns:
            ShipCreateResult 新增结果对象。

        Raises:
            ValidationError: 当草稿数据不合法时抛出。
            DatabaseError: 当数据库操作失败时抛出。
        """
        normalized = self.normalizeDraft(draft)

        group_record = CodexGroupModel(
            codex_id=normalized["codex_id"],
            ship_name=normalized["ship_name"],
            ship_level=normalized["ship_level"],
            ship_star=normalized["ship_star"],
            ship_rarity=normalized["ship_rarity"],
            ship_typ=normalized["ship_typ"],
            ship_group=normalized["ship_group"],
            ship_aid=normalized["ship_aid"],
            ship_camp=normalized["ship_camp"],
            ship_liking=normalized["ship_liking"],
            oath_status=normalized["oath_status"],
            codex_unlock="N",
            date_edit=normalized["date_edit"]
        )

        try:
            with DatabaseContext(self._group_repository.dbPath) as conn:
                self._group_repository.insert(group_record, conn=conn)

                for row in normalized["tp_rows"]:
                    self._tp_repository.insert(
                        CodexTpModel(
                            codex_id=normalized["codex_id"],
                            ship_name=normalized["ship_name"],
                            ship_camp=normalized["ship_camp"],
                            ship_typ=normalized["ship_typ"],
                            tp_value=row["tp_value"],
                            unlock_cond=row["unlock_cond"],
                            tp_unlock="N",
                            date_edit=None
                        ),
                        conn=conn
                    )

                for row in normalized["buff_rows"]:
                    self._buff_repository.insert(
                        CodexBuffModel(
                            codex_id=normalized["codex_id"],
                            ship_name=normalized["ship_name"],
                            ship_camp=normalized["ship_camp"],
                            ship_typ=normalized["ship_typ"],
                            boost_typ=row["boost_typ"],
                            buff_typ=row["buff_typ"],
                            buff_value=row["buff_value"],
                            buff_cond=row["buff_cond"],
                            buff_unlock="N"
                        ),
                        conn=conn
                    )
        except sqlite3.Error as e:
            raise DatabaseError(f"新增舰娘失败: {e}")

        return ShipCreateResult(
            success=True,
            codex_id=normalized["codex_id"],
            ship_name=normalized["ship_name"],
            ship_group=normalized["ship_group"],
            tp_count=len(normalized["tp_rows"]),
            buff_count=len(normalized["buff_rows"]),
            message=f"舰娘 '{normalized['ship_name']}' 新增成功"
        )

    def buildPreviewSql(self, draft: ShipCreateDraft) -> str:
        """
        生成新增操作的等价SQL预览。

        Args:
            draft: 新增舰娘草稿。

        Returns:
            可直接复制的SQL语句文本。

        Raises:
            ValidationError: 当草稿数据不合法时抛出。
        """
        normalized = self.normalizeDraft(draft)
        lines: List[str] = []

        lines.append(f"-- 新增图鉴_{normalized['ship_group']}")
        lines.append(
            "INSERT INTO codex_group (codex_id, ship_name, ship_level, ship_star, ship_rarity, "
            "ship_typ, ship_group, ship_aid, ship_camp, ship_liking, oath_status, codex_unlock, date_edit)"
        )
        lines.append("VALUES")
        lines.append("(" + ", ".join([
            _sqlQuote(normalized["codex_id"]),
            _sqlQuote(normalized["ship_name"]),
            _sqlQuote(normalized["ship_level"]),
            _sqlQuote(normalized["ship_star"]),
            _sqlQuote(normalized["ship_rarity"]),
            _sqlQuote(normalized["ship_typ"]),
            _sqlQuote(normalized["ship_group"]),
            _sqlQuote(normalized["ship_aid"]),
            _sqlQuote(normalized["ship_camp"]),
            _sqlQuote(normalized["ship_liking"]),
            _sqlQuote(normalized["oath_status"]),
            _sqlQuote("N"),
            _sqlQuote(normalized["date_edit"])
        ]) + ");")

        if normalized["tp_rows"]:
            lines.append("")
            lines.append("-- 新增科技点")
            lines.append(
                "INSERT INTO codex_tp (codex_id, ship_name, ship_camp, ship_typ, tp_value, unlock_cond, tp_unlock)"
            )
            lines.append("VALUES")
            value_lines = []
            for row in normalized["tp_rows"]:
                value_lines.append("(" + ", ".join([
                    _sqlQuote(normalized["codex_id"]),
                    _sqlQuote(normalized["ship_name"]),
                    _sqlQuote(normalized["ship_camp"]),
                    _sqlQuote(normalized["ship_typ"]),
                    _sqlQuote(row["tp_value"]),
                    _sqlQuote(row["unlock_cond"]),
                    _sqlQuote("N")
                ]) + ")")
            lines.append(",\n".join(value_lines) + ";")

        if normalized["buff_rows"]:
            lines.append("")
            lines.append("-- 新增科技属性")
            lines.append(
                "INSERT INTO codex_buff (codex_id, ship_name, ship_camp, ship_typ, boost_typ, "
                "buff_typ, buff_value, buff_cond, buff_unlock)"
            )
            lines.append("VALUES")
            value_lines = []
            for row in normalized["buff_rows"]:
                value_lines.append("(" + ", ".join([
                    _sqlQuote(normalized["codex_id"]),
                    _sqlQuote(normalized["ship_name"]),
                    _sqlQuote(normalized["ship_camp"]),
                    _sqlQuote(normalized["ship_typ"]),
                    _sqlQuote(row["boost_typ"]),
                    _sqlQuote(row["buff_typ"]),
                    _sqlQuote(row["buff_value"]),
                    _sqlQuote(row["buff_cond"]),
                    _sqlQuote("N")
                ]) + ")")
            lines.append(",\n".join(value_lines) + ";")

        return "\n".join(lines)

    def _normalizeTpValues(self, tp_values: Dict[str, Any], no_tp_buff: bool,
                           ship_group: str) -> List[Dict]:
        """
        规范化科技点数值。

        三个条件需同时填写或全部留空。

        Args:
            tp_values: 解锁条件 -> 数值的映射。
            no_tp_buff: 该分组是否不写入科技点。
            ship_group: 舰娘分组。

        Returns:
            科技点明细行列表。

        Raises:
            ValidationError: 当数值不合法时抛出。
        """
        filled: Dict[str, int] = {}

        unknown = [
            key for key, value in (tp_values or {}).items()
            if key not in options.TP_CONDS and str(value or "").strip()
        ]
        if unknown:
            raise ValidationError(
                f"未知的科技点解锁条件: {'/'.join(str(key) for key in unknown)}；"
                f"可用条件：{'/'.join(options.TP_CONDS)}"
            )

        for unlock_cond in options.TP_CONDS:
            raw_value = (tp_values or {}).get(unlock_cond)
            if raw_value is None or str(raw_value).strip() == "":
                continue

            tp_value = _toInt(raw_value, f"科技点（{unlock_cond}）")
            if tp_value < 0:
                raise ValidationError(f"科技点（{unlock_cond}）不能为负数")
            filled[unlock_cond] = tp_value

        if no_tp_buff:
            if filled:
                raise ValidationError(f"{ship_group}类型不支持录入科技点，请清空科技点输入")
            return []

        if not filled:
            return []

        missing = [cond for cond in options.TP_CONDS if cond not in filled]
        if missing:
            raise ValidationError(
                f"科技点需同时填写 {'/'.join(options.TP_CONDS)}（或全部留空），"
                f"当前缺少：{'/'.join(missing)}"
            )

        return [{"unlock_cond": cond, "tp_value": filled[cond]} for cond in options.TP_CONDS]

    def _normalizeBuffText(self, buff_text: Dict[str, str], no_tp_buff: bool,
                           ship_group: str) -> List[Dict]:
        """
        规范化科技属性文本。

        Args:
            buff_text: 解锁条件 -> 原始数据文本的映射。
            no_tp_buff: 该分组是否不写入科技属性。
            ship_group: 舰娘分组。

        Returns:
            科技属性明细行列表。

        Raises:
            ValidationError: 当文本不合法时抛出。
        """
        unknown = [
            key for key, value in (buff_text or {}).items()
            if key not in options.BUFF_CONDS and str(value or "").strip()
        ]
        if unknown:
            raise ValidationError(
                f"未知的科技属性解锁条件: {'/'.join(str(key) for key in unknown)}；"
                f"可用条件：{'/'.join(options.BUFF_CONDS)}"
            )

        if no_tp_buff:
            if any(str(text or "").strip() for text in (buff_text or {}).values()):
                raise ValidationError(f"{ship_group}类型不支持录入科技属性，请清空科技属性输入")
            return []

        return self.parseBuffRows(buff_text)


def _toInt(value, label: str) -> int:
    """
    将输入转换为整数。

    Args:
        value: 原始值。
        label: 用于错误提示的字段名称。

    Returns:
        转换后的整数。

    Raises:
        ValidationError: 当数值无法转换为整数时抛出。
    """
    if value is None or (isinstance(value, str) and not value.strip()):
        raise ValidationError(f"{label}不能为空")

    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        raise ValidationError(f"{label}应为整数: {value}")


def _isValidShipAid(ship_aid: str) -> bool:
    """校验实装日期格式（yyyy/MM/dd，允许一位月日）。"""
    parts = ship_aid.split("/")
    if len(parts) != 3:
        return False

    year, month, day = parts
    if not (year.isdigit() and len(year) == 4):
        return False
    if not (month.isdigit() and day.isdigit()):
        return False

    return 1 <= int(month) <= 12 and 1 <= int(day) <= 31


def _sqlQuote(value) -> str:
    """将值转换为SQL字面量。"""
    if value is None:
        return "NULL"
    if isinstance(value, int):
        return str(value)

    text = str(value)
    if text == "":
        return "''"
    return "'" + text.replace("'", "''") + "'"
