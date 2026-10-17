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

    对应 ``cube_task`` 表，由 ``sql/CreateCubeTaskTables.sql`` 初始化，共 18 项。

    Attributes:
        code: 任务编码，主键（如 ``daily_build_once``）。
        grp: 分组，``daily`` / ``weekly`` / ``signin`` / ``cruise``。
        name: 任务名称。
        reward: 完成奖励（魔方数量）。
        period_type: 周期类型，``day`` / ``week`` / ``month`` / ``cruise``。
        category: 写入明细时使用的来源名。
        sort_order: 排序序号。
        active: 是否启用（1 启用）。
    """

    code: str = ""
    grp: str = ""
    name: str = ""
    reward: int = 0
    period_type: str = ""
    category: str = ""
    sort_order: int = 0
    active: int = 1


@dataclass
class CubeTaskCompletionModel(BaseModel):
    """
    任务完成记录模型。

    对应 ``cube_task_completion`` 表；一条记录对应一笔魔方收入明细。

    Attributes:
        id: 记录 ID。
        task_code: 任务编码。
        period_key: 周期键（``2026-10-17`` / ``2026-W42`` / ``2026-10``）。
        completed_at: 完成时刻，格式 ``yyyy-MM-dd HH:mm:ss``。
        transaction_id: 关联的 ``resource_transaction.id``；``None`` 表示仅标记、无对应明细。
        created_at: 记录创建时间。
    """

    id: Optional[int] = None
    task_code: str = ""
    period_key: str = ""
    completed_at: str = ""
    transaction_id: Optional[int] = None
    created_at: Optional[str] = None
