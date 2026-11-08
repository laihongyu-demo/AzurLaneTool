"""
活动记录数据模型模块。

定义活动记录实体，以及常规录入下拉使用的活动选项视图对象。
"""

from dataclasses import dataclass
from typing import Optional

from models.base_model import BaseModel
from utils.constants import (
    EVENT_DEFAULT_BUILD_COST, EVENT_STATUS_UNSET_LABEL, EVENT_UNNAMED_LABEL
)


@dataclass
class EventRecordModel(BaseModel):
    """
    活动记录模型。

    对应 ``event_record`` 表，一行代表一次活动（同一活动拆成多个卡池时按行独立记录）。

    Attributes:
        id: 记录 ID。
        event_date: 活动开始日期，格式 ``yyyy-MM-dd``。
        event_type: 活动类型，自由文本（如 ``大型海域·周年``）。
        name: 活动名称，允许为空（历史数据存在未命名记录）。
        status: 状态，自由文本；空串表示未标记。
        status_note: 状态备注（如 ``缺吉尚``）。
        build_cost: 单次建造消耗的魔方数（1 或 2）。
        use_ticket: 是否使用过建造券（1 是 / 0 否）；券抽不消耗魔方。
        ticket_build_count: 建造券抽次数；仅在 ``use_ticket=1`` 且有关联明细时计入合计。
        build_count: 手工 / 历史建造次数；None 表示未统计，0 表示确实 0 次。
            有明细关联时展示值改为「关联魔方 ÷ build_cost + 券抽次数」，本字段作为回退值。
        note: 备注。
        created_at: 创建时间。
        updated_at: 更新时间。
    """

    id: Optional[int] = None
    event_date: str = ""
    event_type: str = ""
    name: str = ""
    status: str = ""
    status_note: str = ""
    build_cost: int = EVENT_DEFAULT_BUILD_COST
    use_ticket: int = 0
    ticket_build_count: Optional[int] = None
    build_count: Optional[int] = None
    note: str = ""
    created_at: Optional[str] = None
    updated_at: Optional[str] = None

    @property
    def displayName(self) -> str:
        """
        活动展示名（空名称退化为占位文案）。

        Returns:
            活动名称或 ``（未命名活动）``。
        """
        return self.name.strip() or EVENT_UNNAMED_LABEL

    @property
    def displayStatus(self) -> str:
        """
        状态展示文案（空状态退化为「未标记」）。

        Returns:
            状态或 ``未标记``。
        """
        return self.status.strip() or EVENT_STATUS_UNSET_LABEL


@dataclass
class EventOption:
    """
    常规录入「所属活动」下拉选项。

    Attributes:
        id: 活动记录 ID。
        event_date: 活动开始日期 ``yyyy-MM-dd``。
        name: 活动名称。
        status: 状态；空串表示未标记。
        build_cost: 单次建造消耗的魔方数（1 或 2）。
    """

    id: int
    event_date: str
    name: str
    status: str = ""
    build_cost: int = EVENT_DEFAULT_BUILD_COST

    @property
    def label(self) -> str:
        """
        下拉项文案：``2026-10-22 飓风与雾霭回廊（进行中｜2魔方/次）``。

        Returns:
            展示文本。
        """
        display = self.name.strip() or EVENT_UNNAMED_LABEL
        parts = [part for part in (self.status.strip(), f"{self.build_cost}魔方/次") if part]
        return f"{self.event_date} {display}（{'｜'.join(parts)}）"
