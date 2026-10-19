"""
资源统计数据模型模块。

定义魔方 / 红尖尖的日汇总、明细与事件字典的数据结构。
"""

from dataclasses import dataclass
from typing import Optional

from models.base_model import BaseModel
from utils.constants import (
    RESOURCE_DETAIL_MODE_DETAIL, RESOURCE_DIRECTION_INCOME, RESOURCE_TYPE_CUBE
)


@dataclass
class ResourceDailyModel(BaseModel):
    """
    资源日汇总模型。

    对应 ``resource_daily`` 表。两种模式互斥：

    - ``detail``：当日存在明细，``income`` / ``expense`` 必须为 None，由明细汇总得出；
    - ``summary_only``：当日无明细，``income`` / ``expense`` 即当日事实值。

    Attributes:
        id: 记录 ID。
        resource_type: 资源类型，``cube`` 或 ``red_gem``。
        record_date: 记录日期，格式 ``yyyy-MM-dd``。
        detail_mode: 明细模式，``detail`` 或 ``summary_only``。
        income: 当日收入（仅 ``summary_only`` 使用）。
        expense: 当日支出（仅 ``summary_only`` 使用）。
        balance_override: 手填结余，作为累加锚点；None 表示自动累加。
        note: 备注。
        last_record_time: 该日最后一笔明细的准确时刻（``yyyy-MM-dd HH:mm:ss``）；
            None 表示该日只有日期信息（历史汇总日）或尚无明细。
        created_at: 创建时间。
        updated_at: 更新时间。
    """

    id: Optional[int] = None
    resource_type: str = RESOURCE_TYPE_CUBE
    record_date: str = ""
    detail_mode: str = RESOURCE_DETAIL_MODE_DETAIL
    income: Optional[int] = None
    expense: Optional[int] = None
    balance_override: Optional[int] = None
    note: str = ""
    last_record_time: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


@dataclass
class ResourceTransactionModel(BaseModel):
    """
    资源明细模型。

    对应 ``resource_transaction`` 表，一笔收入或支出；同一日期同一事件可有多笔。

    Attributes:
        id: 记录 ID。
        resource_type: 资源类型，``cube`` 或 ``red_gem``。
        direction: 方向，``income`` 或 ``expense``。
        record_time: 发生时刻，格式 ``yyyy-MM-dd HH:mm:ss``。录入时可手填以支持补录
            （例如今天补录昨天发生的记录），日期部分决定归属哪一天。
        category: 来源 / 去向名称。
        amount: 数量，必须大于 0。
        note: 备注。
        created_at: 创建时间。
        updated_at: 更新时间。
    """

    id: Optional[int] = None
    resource_type: str = RESOURCE_TYPE_CUBE
    direction: str = RESOURCE_DIRECTION_INCOME
    record_time: str = ""
    category: str = ""
    amount: int = 1
    note: str = ""
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


@dataclass
class ResourceCategoryModel(BaseModel):
    """
    资源事件字典模型。

    对应 ``resource_category`` 表，作为录入时的事件下拉候选。

    Attributes:
        id: 记录 ID。
        resource_type: 资源类型，``cube`` 或 ``red_gem``。
        direction: 方向，``income`` 或 ``expense``。
        name: 事件名称。
        sort_order: 排序序号，越小越靠前。
        is_active: 是否启用（1 启用 / 0 停用）。停用后不出现在录入下拉，
            历史明细仍按原名称保留。
    """

    id: Optional[int] = None
    resource_type: str = RESOURCE_TYPE_CUBE
    direction: str = RESOURCE_DIRECTION_INCOME
    name: str = ""
    sort_order: int = 0
    is_active: int = 1
