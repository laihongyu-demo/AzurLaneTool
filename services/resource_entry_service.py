"""
常规录入服务模块。

承接「资源统计 → 魔方任务看板 → 常规录入」的手工记账：选择类型（收入 / 支出由类型
字典决定）、数量与时刻，写入一笔明细并维护当日汇总。

与任务看板的写入路径共用 `ResourceRepository`，但这类记录不产生完成记录，
因此单独成服务，避免把「任务语义」混进通用记账里。
"""

from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional

from models.resource_model import ResourceTransactionModel
from repositories.cube_task_repository import CubeTaskRepository
from repositories.resource_repository import ResourceRepository
from utils.constants import (
    RECORD_TIME_FORMAT,
    RESOURCE_DETAIL_MODE_SUMMARY_ONLY,
    RESOURCE_DIRECTION_EXPENSE,
    RESOURCE_DIRECTION_INCOME,
    RESOURCE_DIRECTION_NAMES,
    RESOURCE_DISPLAY_NAMES,
    RESOURCE_TYPE_CUBE,
)
from utils.db_connection import DatabaseContext
from utils.exceptions import ValidationError

# 单笔数量上限：仅用于拦住误触输入，不限制真实玩法
MAX_ENTRY_AMOUNT = 100000


@dataclass
class ResourceCategoryOption:
    """
    常规录入可选的类型。

    Attributes:
        name: 类型名称（写入 ``resource_transaction.category``）。
        direction: 该类型决定的方向，``income`` 或 ``expense``。
    """

    name: str
    direction: str


@dataclass
class ResourceEntryResult:
    """
    常规录入结果。

    Attributes:
        success: 是否成功。
        message: 面向用户的提示文案。
        transaction_id: 新明细 ID（失败时为 0）。
    """

    success: bool
    message: str
    transaction_id: int = 0

    def toStatusBarMessage(self) -> str:
        """
        状态栏文案。

        Returns:
            提示文案。
        """
        return self.message


class ResourceEntryService:
    """常规录入服务：可选类型查询与单笔记账。"""

    def __init__(
        self,
        resource_repository: Optional[ResourceRepository] = None,
        task_repository: Optional[CubeTaskRepository] = None,
    ):
        """
        初始化常规录入服务。

        Args:
            resource_repository: 资源仓储实例。
            task_repository: 任务仓储实例（用于排除任务看板已覆盖的类型）。
        """
        self._repository = resource_repository or ResourceRepository()
        self._task_repository = task_repository or CubeTaskRepository()

    def getCategories(self, resource_type: str = RESOURCE_TYPE_CUBE) -> List[ResourceCategoryOption]:
        """
        查询可选类型：支出在前、收入在后，并排除任务看板已覆盖的类型。

        任务看板会写 ``日常任务`` / ``周常任务`` / ``每月签到`` / ``世界巡游``，
        若在常规录入里再选这些类型，容易与任务卡片重复记账，因此不列出。

        Args:
            resource_type: 资源类型。

        Returns:
            类型选项列表。
        """
        owned = {task.category for task in self._task_repository.findAll()}

        options: List[ResourceCategoryOption] = []
        for direction in (RESOURCE_DIRECTION_EXPENSE, RESOURCE_DIRECTION_INCOME):
            for record in self._repository.findCategories(resource_type, direction):
                if record.name in owned:
                    continue
                options.append(ResourceCategoryOption(record.name, direction))
        return options

    def record(
        self,
        category: str,
        direction: str,
        amount: int,
        moment: datetime,
        resource_type: str = RESOURCE_TYPE_CUBE,
        note: str = "",
    ) -> ResourceEntryResult:
        """
        记录一笔常规收支。

        Args:
            category: 类型名称，需存在于类型字典中。
            direction: 方向，``income`` 或 ``expense``。同一类型名可能同时存在于两个方向
                （如红尖尖的「礼包」），因此不能只靠名字推断。
            amount: 数量（正整数）。
            moment: 发生时刻，不能晚于当前时间。
            resource_type: 资源类型。
            note: 备注，可为空。

        Returns:
            录入结果。

        Raises:
            ValidationError: 当类型不存在、数量非法、时刻越界或目标日期属于历史汇总段时抛出。
        """
        self._validatePair(category, direction, resource_type)
        self._validateAmount(amount)
        self._validateMoment(moment)
        self._validateTargetDay(resource_type, moment)

        record_time_text = moment.strftime(RECORD_TIME_FORMAT)
        record_date_text = record_time_text[:10]
        record = ResourceTransactionModel(
            resource_type=resource_type,
            direction=direction,
            record_time=record_time_text,
            category=category,
            amount=amount,
            note=note,
        )

        with DatabaseContext(self._repository.dbPath) as conn:
            transaction_id = self._repository.insertTransaction(record, conn)
            self._repository.upsertDetailDaily(
                resource_type, record_date_text, record_time_text, conn
            )
            self._repository.recomputeLastRecordTime(resource_type, record_date_text, conn)

        direction_name = RESOURCE_DIRECTION_NAMES.get(direction, direction)
        resource_name = RESOURCE_DISPLAY_NAMES.get(resource_type, resource_type)
        message = (
            f"已记录：{resource_name} {direction_name} {amount}（{category}，{record_time_text}）"
        )
        return ResourceEntryResult(True, message, transaction_id)

    # ------------------------------------------------------------- 撤销

    def getUndoableEntry(
        self, resource_type: str = RESOURCE_TYPE_CUBE
    ) -> Optional[ResourceTransactionModel]:
        """
        查询可撤销的最近一笔常规录入。

        只针对「非任务来源」的明细：任务卡片的完成/取消由看板自己负责，
        撤销按钮不应该把任务记账删掉。

        Args:
            resource_type: 资源类型。

        Returns:
            明细模型；没有可撤销记录时返回 None。
        """
        return self._repository.findLatestManualTransaction(resource_type)

    def undoLast(self, resource_type: str = RESOURCE_TYPE_CUBE) -> ResourceEntryResult:
        """
        撤销最近一笔常规录入。

        删除明细；若该日已无任何明细，连当日汇总行一起清掉（撤销后不该留下空行），
        否则按剩余明细重算末次时刻。

        Args:
            resource_type: 资源类型。

        Returns:
            撤销结果。

        Raises:
            ValidationError: 没有可撤销的常规录入时抛出。
        """
        target = self.getUndoableEntry(resource_type)
        if target is None:
            raise ValidationError("没有可撤销的常规录入")

        record_date_text = target.record_time[:10]
        with DatabaseContext(self._repository.dbPath) as conn:
            self._repository.deleteTransaction(target.id, conn)
            remaining = self._repository.countTransactionsByDate(
                resource_type, record_date_text, conn
            )
            if remaining == 0:
                self._repository.deleteDaily(resource_type, record_date_text, conn)
            else:
                self._repository.recomputeLastRecordTime(resource_type, record_date_text, conn)

        direction_name = RESOURCE_DIRECTION_NAMES.get(target.direction, target.direction)
        resource_name = RESOURCE_DISPLAY_NAMES.get(resource_type, resource_type)
        message = (
            f"已撤销：{resource_name} {direction_name} {target.amount}"
            f"（{target.category}，{target.record_time}）"
        )
        return ResourceEntryResult(True, message, 0)

    # ------------------------------------------------------------- 校验

    def _validatePair(self, category: str, direction: str, resource_type: str) -> None:
        """
        校验「类型 + 方向」是否存在于类型字典。

        Args:
            category: 类型名称。
            direction: 方向。
            resource_type: 资源类型。

        Raises:
            ValidationError: 类型或方向不存在时抛出。
        """
        if direction not in RESOURCE_DIRECTION_NAMES:
            raise ValidationError(f"未知的收支方向：{direction}")
        names = {record.name for record in self._repository.findCategories(resource_type, direction)}
        if category not in names:
            direction_name = RESOURCE_DIRECTION_NAMES.get(direction, direction)
            raise ValidationError(f"未知的收支类型：{category}（{direction_name}）")

    def _validateAmount(self, amount: int) -> None:
        """
        校验数量。

        Args:
            amount: 数量。

        Raises:
            ValidationError: 数量非正整数或超过上限时抛出。
        """
        if not isinstance(amount, int) or amount <= 0:
            raise ValidationError("数量需为大于 0 的整数")
        if amount > MAX_ENTRY_AMOUNT:
            raise ValidationError(f"单笔数量不能超过 {MAX_ENTRY_AMOUNT}")

    def _validateMoment(self, moment: datetime) -> None:
        """
        校验发生时刻。

        Args:
            moment: 时刻。

        Raises:
            ValidationError: 时刻晚于当前时间时抛出。
        """
        if moment > datetime.now():
            raise ValidationError("记录时刻不能晚于当前时间")

    def _validateTargetDay(self, resource_type: str, moment: datetime) -> None:
        """
        校验目标日期是否为可写明细日。

        历史汇总段（``summary_only``）只有日收支合计、没有明细，写入会被汇总覆盖，
        因此直接拦下并提示改用明细日。

        Args:
            resource_type: 资源类型。
            moment: 时刻。

        Raises:
            ValidationError: 目标日期属于历史汇总段时抛出。
        """
        record_date_text = moment.strftime(RECORD_TIME_FORMAT)[:10]
        daily = self._repository.findDaily(resource_type, record_date_text)
        if daily is not None and daily.detail_mode == RESOURCE_DETAIL_MODE_SUMMARY_ONLY:
            raise ValidationError(
                f"{record_date_text} 属于历史汇总段（只有日合计、没有逐笔明细），"
                "不能补录明细；请选择其它日期"
            )
