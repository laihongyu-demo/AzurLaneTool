"""
舰娘图鉴模型模块。

定义舰娘图鉴相关的数据结构。
"""

from dataclasses import dataclass
from typing import Optional

from models.base_model import BaseModel


@dataclass
class CodexGroupModel(BaseModel):
    """
    舰娘图鉴组模型。

    Attributes:
        codex_id: 图鉴ID（主键）。
        ship_name: 舰娘名称。
        ship_level: 舰娘等级。
        ship_star: 舰娘星级。
        ship_rarity: 舰娘稀有度。
        ship_typ: 舰娘类型。
        ship_group: 舰娘分组。
        ship_aid: 舰娘实装日期。
        ship_camp: 舰娘阵营。
        ship_liking: 舰娘好感度。
        oath_status: 誓约状态。
        codex_unlock: 图鉴解锁状态。
        date_edit: 编辑日期。
    """

    codex_id: str = ""
    ship_name: str = ""
    ship_level: str = ""
    ship_star: int = 0
    ship_rarity: str = ""
    ship_typ: str = ""
    ship_group: str = ""
    ship_aid: Optional[str] = None
    ship_camp: str = ""
    ship_liking: str = ""
    oath_status: str = "N"
    codex_unlock: str = "N"
    date_edit: Optional[str] = None

    def __post_init__(self):
        """初始化后处理，确保字段类型正确。"""
        if self.codex_id is not None and not isinstance(self.codex_id, str):
            self.codex_id = str(self.codex_id)
        if self.ship_name is not None and not isinstance(self.ship_name, str):
            self.ship_name = str(self.ship_name)
        if self.ship_typ is not None and not isinstance(self.ship_typ, str):
            self.ship_typ = str(self.ship_typ)
        if self.ship_rarity is not None and not isinstance(self.ship_rarity, str):
            self.ship_rarity = str(self.ship_rarity)
        if self.ship_camp is not None and not isinstance(self.ship_camp, str):
            self.ship_camp = str(self.ship_camp)
        if self.ship_group is not None and not isinstance(self.ship_group, str):
            self.ship_group = str(self.ship_group)


@dataclass
class CodexTpModel(BaseModel):
    """
    舰娘图鉴TP模型。

    Attributes:
        id: 记录ID。
        codex_id: 图鉴ID（外键）。
        ship_name: 舰娘名称。
        ship_camp: 舰娘阵营。
        ship_typ: 舰娘类型。
        tp_value: TP值。
        unlock_cond: 解锁条件。
        tp_unlock: TP解锁状态。
        date_edit: 编辑日期。
    """

    id: int = 0
    codex_id: str = ""
    ship_name: str = ""
    ship_camp: str = ""
    ship_typ: str = ""
    tp_value: int = 0
    unlock_cond: str = ""
    tp_unlock: str = "N"
    date_edit: Optional[str] = None


@dataclass
class CodexBuffModel(BaseModel):
    """
    舰娘图鉴Buff模型。

    Attributes:
        id: 记录ID。
        codex_id: 图鉴ID（外键）。
        ship_name: 舰娘名称。
        ship_camp: 舰娘阵营。
        ship_typ: 舰娘类型。
        boost_typ: 增益类型。
        buff_typ: Buff类型。
        buff_value: Buff值。
        buff_cond: Buff条件。
        buff_unlock: Buff解锁状态。
    """

    id: int = 0
    codex_id: str = ""
    ship_name: str = ""
    ship_camp: str = ""
    ship_typ: str = ""
    boost_typ: str = ""
    buff_typ: str = ""
    buff_value: int = 0
    buff_cond: str = ""
    buff_unlock: str = "N"
