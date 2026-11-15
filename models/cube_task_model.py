"""
魔方任务看板数据模型模块。

定义固定奖励任务（日常 / 周常 / 签到 / 世界巡游）的任务定义与完成记录。
"""

from dataclasses import dataclass
from typing import Optional

from models.base_model import BaseModel


@dataclass
class CubeTaskModel(BaseModel):
    """
    任务定义模型。

    对应 ``cube_task`` 表，由 ``sql/CreateCubeTaskTables.sql`` 初始化；
    该表为历史表名，现在同时承载魔方与红尖尖的固定奖励任务。

    Attributes:
        code: 任务编码，主键（如 ``daily_build_once``）。
        resource_type: 资源类型，``cube`` 或 ``red_gem``。
        grp: 分组，``daily`` / ``weekly`` / ``signin`` / ``cruise``。
        name: 任务完整名称（用于 tooltip 与明细备注）。
        short_name: 看板卡片用的短标签（单行显示）。
        reward: 完成奖励数量。
        period_type: 周期类型，``day`` / ``week`` / ``month`` / ``cruise``。
        category: 写入明细时使用的来源名。
        sort_order: 排序序号。
        active: 是否启用（1 启用）。
    """

    code: str = ""
    resource_type: str = "cube"
    grp: str = ""
    name: str = ""
    short_name: str = ""
    reward: int = 0
    period_type: str = ""
    category: str = ""
    sort_order: int = 0
    active: int = 1


@dataclass
class CubeTaskCompletionModel(BaseModel):
    """
    任务完成记录模型。

    对应 ``cube_task_completion`` 表；一条记录对应一笔收入明细。
    建造任务（``daily_build_once``）还会挂第二笔支出明细与关联活动：

    - ``expense_transaction_id`` 指向建造支出；使用建造券时为空（不扣魔方）；
    - ``event_id`` 记录本次建造关联 / 计入券抽次数的活动，取消时据此回滚。

    Attributes:
        id: 记录 ID。
        task_code: 任务编码。
        period_key: 周期键（``2026-10-17`` / ``2026-W42`` / ``2026-10``）。
        completed_at: 完成时刻，格式 ``yyyy-MM-dd HH:mm:ss``。
        transaction_id: 关联的收入 ``resource_transaction.id``；``None`` 表示仅标记、无对应明细。
        expense_transaction_id: 关联的支出明细 ID；``None`` 表示本次没有支出（如使用建造券）。
        event_id: 关联 / 计入券抽次数的活动记录 ID；``None`` 表示没有进行中活动。
        created_at: 记录创建时间。
    """

    id: Optional[int] = None
    task_code: str = ""
    period_key: str = ""
    completed_at: str = ""
    transaction_id: Optional[int] = None
    expense_transaction_id: Optional[int] = None
    event_id: Optional[int] = None
    created_at: Optional[str] = None
