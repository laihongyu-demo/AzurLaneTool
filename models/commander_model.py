"""
指挥官数据模型模块。

定义指挥官等级快照与等级经验基准的数据结构。
"""

from dataclasses import dataclass
from typing import Optional

from models.base_model import BaseModel
from utils.constants import COMMANDER_LEVEL_MIN


@dataclass
class CommanderSnapshotModel(BaseModel):
    """
    指挥官等级快照模型。

    对应 ``commander_info`` 表，属历史快照语义：每次记录追加一行，不覆盖旧记录。

    Attributes:
        id: 记录 ID。
        statistics_date: 记录时间，格式 ``yyyy-MM-dd HH:mm``（本地时间，精度到分）。
        commander_level: 指挥官等级，1～200。
        commander_exp: 当前等级内已累积的经验（不含此前等级）。
    """

    id: Optional[int] = None
    statistics_date: str = ""
    commander_level: int = COMMANDER_LEVEL_MIN
    commander_exp: int = 0

    def __post_init__(self):
        """初始化后处理：只做类型归一，取值范围由业务层校验（避免静默钳制掩盖非法输入）。"""
        if self.commander_level is None:
            self.commander_level = COMMANDER_LEVEL_MIN
        if self.commander_exp is None:
            self.commander_exp = 0
        self.commander_level = int(self.commander_level)
        self.commander_exp = int(self.commander_exp)
        if self.statistics_date is None:
            self.statistics_date = ""


@dataclass
class CommanderLevelExpModel(BaseModel):
    """
    指挥官等级经验基准模型。

    对应 ``commander_level_exp`` 表，由 ``data/commander_level.csv`` 导入。

    Attributes:
        level: 等级，1～200。
        level_up_exp: 本级升到下一级所需经验；最高等级为 None。
        cumulative_exp: 从 1 级起累计到本级所需经验；最高等级为 None。
        note: 备注，如"当前版本最高等级"。
    """

    level: int = COMMANDER_LEVEL_MIN
    level_up_exp: Optional[int] = None
    cumulative_exp: Optional[int] = None
    note: str = ""
