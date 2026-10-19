"""
魔方任务看板业务逻辑层模块。

负责周期键计算（日 / ISO 周 / 自然月 / 双月巡游期）、看板状态汇总，
以及「单击完成 / 双击取消」背后的记账与回滚。
"""

import calendar
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional, Tuple

from models.cube_task_model import CubeTaskCompletionModel, CubeTaskModel
from models.resource_model import ResourceTransactionModel
from repositories.cube_task_repository import CubeTaskRepository
from repositories.resource_repository import ResourceRepository
from utils import time_source
from utils.constants import (
    CRUISE_PERIOD_MONTHS, RECORD_DATE_FORMAT, RECORD_TIME_FORMAT, RESOURCE_DIRECTION_INCOME,
    RESOURCE_TYPE_CUBE, TASK_DISPLAY_GROUPS, TASK_PERIOD_CRUISE, TASK_PERIOD_DAY,
    TASK_PERIOD_MONTH, TASK_PERIOD_WEEK, TASK_GROUP_TITLES,
)
from utils.db_connection import DatabaseContext
from utils.db_schema import isMissingColumnError, isMissingTableError
from utils.exceptions import DatabaseError, ValidationError

PERIOD_TYPES = (TASK_PERIOD_DAY, TASK_PERIOD_WEEK, TASK_PERIOD_MONTH, TASK_PERIOD_CRUISE)


# --------------------------------------------------------------- 周期计算


def addMonths(value: date, months: int) -> date:
    """
    在日期上增减自然月（月末自动取该月最后一天）。

    Args:
        value: 基准日期。
        months: 增减的月数（可为负）。

    Returns:
        计算后的日期。
    """
    month_index = value.month - 1 + months
    year = value.year + month_index // 12
    month = month_index % 12 + 1
    day = min(value.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def cruisePeriodStart(when: date) -> date:
    """
    计算世界巡游「本期」的起始日。

    规则：每 2 个自然月为一期，起点为偶数月 1 日 00:00。
    例如 10 月 → 当年 10-01；12 月 → 当年 12-01（跨年到次年 1 月）；
    1 月 → 上一年 12-01。

    Args:
        when: 任意日期。

    Returns:
        本期起始日。
    """
    month = when.month - (when.month % CRUISE_PERIOD_MONTHS)
    if month <= 0:
        return date(when.year - 1, 12, 1)
    return date(when.year, month, 1)


def cruisePeriodEnd(when: date) -> date:
    """
    计算世界巡游「本期」的结束日（含）。

    Args:
        when: 任意日期。

    Returns:
        本期结束日。
    """
    return addMonths(cruisePeriodStart(when), CRUISE_PERIOD_MONTHS) - timedelta(days=1)


def weekRange(when: date) -> Tuple[date, date]:
    """
    计算 ISO 周（周一 ~ 周日）的起止日期。

    Args:
        when: 任意日期。

    Returns:
        ``(周一, 周日)``。
    """
    monday = when - timedelta(days=when.weekday())
    return monday, monday + timedelta(days=6)


def monthRange(when: date) -> Tuple[date, date]:
    """
    计算自然月的起止日期。

    Args:
        when: 任意日期。

    Returns:
        ``(1 日, 月末)``。
    """
    last_day = calendar.monthrange(when.year, when.month)[1]
    return date(when.year, when.month, 1), date(when.year, when.month, last_day)


def buildPeriodKey(period_type: str, when: date) -> str:
    """
    按周期类型生成周期键。

    Args:
        period_type: ``day`` / ``week`` / ``month`` / ``cruise``。
        when: 归属日期。

    Returns:
        周期键：``2026-10-17`` / ``2026-W42`` / ``2026-10``（月与期为 ``yyyy-MM``）。

    Raises:
        ValidationError: 周期类型未知时抛出。
    """
    if period_type == TASK_PERIOD_DAY:
        return when.strftime(RECORD_DATE_FORMAT)
    if period_type == TASK_PERIOD_WEEK:
        iso_year, iso_week, _ = when.isocalendar()
        return f"{iso_year:04d}-W{iso_week:02d}"
    if period_type == TASK_PERIOD_MONTH:
        return when.strftime("%Y-%m")
    if period_type == TASK_PERIOD_CRUISE:
        return cruisePeriodStart(when).strftime("%Y-%m")
    raise ValidationError(f"未知的周期类型: {period_type}")


def periodRange(period_type: str, when: date) -> Tuple[date, date]:
    """
    计算某周期的起止日期（用于期初对齐脚本扫描区间）。

    Args:
        period_type: 周期类型。
        when: 归属日期。

    Returns:
        ``(起始日, 结束日)``，均含当天。

    Raises:
        ValidationError: 周期类型未知时抛出。
    """
    if period_type == TASK_PERIOD_DAY:
        return when, when
    if period_type == TASK_PERIOD_WEEK:
        return weekRange(when)
    if period_type == TASK_PERIOD_MONTH:
        return monthRange(when)
    if period_type == TASK_PERIOD_CRUISE:
        return cruisePeriodStart(when), cruisePeriodEnd(when)
    raise ValidationError(f"未知的周期类型: {period_type}")


# ------------------------------------------------------------------ 视图对象


@dataclass
class CubePeriodInfo:
    """
    周期展示信息。

    Attributes:
        period_type: 周期类型。
        period_key: 周期键。
        label: 展示文案（如 ``2026 第 42 周（10-12 ~ 10-18）``）。
        start: 起始日期 ``yyyy-MM-dd``。
        end: 结束日期 ``yyyy-MM-dd``。
    """

    period_type: str
    period_key: str
    label: str
    start: str
    end: str


@dataclass
class CubeTaskState:
    """
    单个任务在某周期的状态。

    Attributes:
        task: 任务定义。
        completed: 是否已完成。
        completed_at: 完成时刻。
        transaction_id: 关联的明细 ID。
        orphan: 完成记录存在但关联明细已不存在。
        marked_only: 仅标记完成、无对应明细（期初对齐时的兜底）。
    """

    task: CubeTaskModel
    completed: bool = False
    completed_at: Optional[str] = None
    transaction_id: Optional[int] = None
    orphan: bool = False
    marked_only: bool = False


@dataclass
class CubeTaskGroupView:
    """
    展示分组（任务 / 每月签到 / 世界巡游）。

    Attributes:
        key: 分组键。
        title: 分组标题。
        tasks: 分组内的任务状态列表。
        earned: 本周期已获得的魔方数。
        total: 本周期应得的魔方总数。
    """

    key: str
    title: str
    tasks: List[CubeTaskState] = field(default_factory=list)
    earned: int = 0
    total: int = 0


@dataclass
class CubeTaskWriteResult:
    """
    任务写操作结果。

    Attributes:
        success: 是否成功。
        task_code: 任务编码。
        message: 结果消息（可直接用于状态栏）。
    """

    success: bool
    task_code: str = ""
    message: str = ""

    def toStatusBarMessage(self) -> str:
        """
        生成状态栏显示消息。

        Returns:
            中文提示文本。
        """
        return self.message


class CubeTaskService:
    """
    魔方任务看板服务类。

    完成即写入一笔魔方收入明细并登记完成记录；取消则反向删除。
    周期键由完成时刻推导，因此补录时只要传过去的时刻即可归属正确周期。
    """

    def __init__(
        self,
        task_repository: Optional[CubeTaskRepository] = None,
        resource_repository: Optional[ResourceRepository] = None
    ):
        """
        初始化任务看板服务。

        Args:
            task_repository: 任务定义 / 完成记录数据访问实例。
            resource_repository: 资源明细数据访问实例。
        """
        self._task_repository = task_repository or CubeTaskRepository()
        self._resource_repository = resource_repository or ResourceRepository()

    # ------------------------------------------------------------- 周期信息

    def getPeriodKeys(self, record_date: date) -> Dict[str, str]:
        """
        生成 4 个周期键。

        Args:
            record_date: 归属日期。

        Returns:
            周期类型 → 周期键。

        Raises:
            ValidationError: 周期类型异常时抛出（理论上不会发生）。
        """
        return {
            period_type: buildPeriodKey(period_type, record_date)
            for period_type in PERIOD_TYPES
        }

    def getPeriodInfo(self, record_date: date) -> Dict[str, CubePeriodInfo]:
        """
        生成 4 个周期的展示信息。

        Args:
            record_date: 归属日期。

        Returns:
            周期类型 → 周期信息。
        """
        info: Dict[str, CubePeriodInfo] = {}
        for period_type in PERIOD_TYPES:
            start, end = periodRange(period_type, record_date)
            info[period_type] = CubePeriodInfo(
                period_type=period_type,
                period_key=buildPeriodKey(period_type, record_date),
                label=self._formatPeriodLabel(period_type, start, end),
                start=start.strftime(RECORD_DATE_FORMAT),
                end=end.strftime(RECORD_DATE_FORMAT),
            )
        return info

    def _formatPeriodLabel(self, period_type: str, start: date, end: date) -> str:
        """
        生成周期展示文案。

        Args:
            period_type: 周期类型。
            start: 起始日。
            end: 结束日。

        Returns:
            展示文案。
        """
        if period_type == TASK_PERIOD_DAY:
            return start.strftime(RECORD_DATE_FORMAT)
        if period_type == TASK_PERIOD_WEEK:
            iso_year, iso_week, _ = start.isocalendar()
            return f"{iso_year} 第 {iso_week} 周（{start:%m-%d} ~ {end:%m-%d}）"
        if period_type == TASK_PERIOD_MONTH:
            return start.strftime("%Y-%m")
        return f"{start:%Y-%m-%d} ~ {end:%Y-%m-%d}"

    # --------------------------------------------------------------- 看板

    def getBoard(self, record_date: date) -> List[CubeTaskGroupView]:
        """
        汇总指定日期的看板数据（3 个展示分组）。

        Args:
            record_date: 归属日期。

        Returns:
            分组视图列表；表缺失时返回空分组。
        """
        try:
            tasks = self._task_repository.findAll()
            periods = self.getPeriodKeys(record_date)
            completions = self._task_repository.findCompletionsByPeriodKeys(
                list(set(periods.values()))
            )
        except DatabaseError as e:
            if isMissingTableError(e) or isMissingColumnError(e):
                return self._emptyGroups()
            raise

        task_by_code = {task.code: task for task in tasks}
        active: Dict[str, CubeTaskCompletionModel] = {}
        for completion in completions:
            task = task_by_code.get(completion.task_code)
            if task is None:
                continue
            if periods.get(task.period_type) != completion.period_key:
                continue
            active[completion.task_code] = completion

        existing_ids = set()
        try:
            existing_ids = self._resource_repository.findExistingTransactionIds(
                [completion.transaction_id for completion in active.values()
                 if completion.transaction_id]
            )
        except DatabaseError as e:
            if not (isMissingTableError(e) or isMissingColumnError(e)):
                raise

        groups: List[CubeTaskGroupView] = []
        for group_key, title, group_codes in TASK_DISPLAY_GROUPS:
            view = CubeTaskGroupView(key=group_key, title=title)
            for task in tasks:
                if task.grp not in group_codes:
                    continue
                completion = active.get(task.code)
                state = CubeTaskState(task=task, completed=completion is not None)
                if completion is not None:
                    state.completed_at = completion.completed_at
                    state.transaction_id = completion.transaction_id
                    state.marked_only = completion.transaction_id is None
                    state.orphan = (
                        completion.transaction_id is not None
                        and completion.transaction_id not in existing_ids
                    )
                view.tasks.append(state)
                view.total += task.reward
                if state.completed:
                    view.earned += task.reward
            groups.append(view)
        return groups

    def _emptyGroups(self) -> List[CubeTaskGroupView]:
        """
        构造空分组（表缺失时的降级结果）。

        Returns:
            分组视图列表。
        """
        return [
            CubeTaskGroupView(key=key, title=title)
            for key, title, _codes in TASK_DISPLAY_GROUPS
        ]

    # ------------------------------------------------------------- 写操作

    def completeTask(
        self, task_code: str, at: Optional[datetime] = None
    ) -> CubeTaskWriteResult:
        """
        完成一个任务：写入收入明细 + 登记完成记录（同一事务）。

        Args:
            task_code: 任务编码。
            at: 完成时刻，默认当前时间；补录时传历史时刻。

        Returns:
            写操作结果。

        Raises:
            ValidationError: 任务不存在、时刻在未来或本期已完成时抛出。
            DatabaseError: 数据库写入失败时抛出。
        """
        moment = at or time_source.now()
        if moment > time_source.now():
            raise ValidationError("不能录入未来的完成时刻")

        task = self._task_repository.findByCode(task_code)
        if task is None:
            raise ValidationError(f"任务不存在或已停用: {task_code}")

        period_key = buildPeriodKey(task.period_type, moment.date())
        existing = self._task_repository.findCompletion(task_code, period_key)
        if existing is not None:
            raise ValidationError(f"本期已完成「{task.name}」，双击可取消")

        record_date_text = moment.strftime(RECORD_DATE_FORMAT)
        record_time_text = moment.strftime(RECORD_TIME_FORMAT)
        transaction = ResourceTransactionModel(
            resource_type=RESOURCE_TYPE_CUBE,
            direction=RESOURCE_DIRECTION_INCOME,
            record_time=record_time_text,
            category=task.category,
            amount=task.reward,
            note=task.name,
        )
        completion = CubeTaskCompletionModel(
            task_code=task_code,
            period_key=period_key,
            completed_at=record_time_text,
        )

        with DatabaseContext(self._task_repository.dbPath) as conn:
            transaction_id = self._resource_repository.insertTransaction(transaction, conn)
            self._resource_repository.upsertDetailDaily(
                RESOURCE_TYPE_CUBE, record_date_text, record_time_text, conn
            )
            completion.transaction_id = transaction_id
            completion_id = self._task_repository.insertCompletion(completion, conn)
            if completion_id is None:
                # 并发下的兜底：唯一约束拒绝了重复完成，回滚整笔写入
                raise ValidationError(f"本期已完成「{task.name}」，双击可取消")

        return CubeTaskWriteResult(
            success=True,
            task_code=task_code,
            message=f"已完成「{task.name}」，魔方 +{task.reward}（{record_time_text}）",
        )

    def cancelTask(self, task_code: str, record_date: date) -> CubeTaskWriteResult:
        """
        取消某个任务在本周期的完成状态（删除明细 + 完成记录）。

        Args:
            task_code: 任务编码。
            record_date: 归属日期，用于定位周期。

        Returns:
            写操作结果。

        Raises:
            ValidationError: 任务不存在或本期未完成时抛出。
            DatabaseError: 数据库写入失败时抛出。
        """
        task = self._task_repository.findByCode(task_code)
        if task is None:
            raise ValidationError(f"任务不存在或已停用: {task_code}")

        period_key = buildPeriodKey(task.period_type, record_date)
        completion = self._task_repository.findCompletion(task_code, period_key)
        if completion is None:
            raise ValidationError(f"「{task.name}」本期尚未完成")

        transaction = None
        if completion.transaction_id is not None:
            transaction = self._resource_repository.findTransactionById(completion.transaction_id)

        target_date = (completion.completed_at or "")[:10] or record_date.strftime(RECORD_DATE_FORMAT)

        with DatabaseContext(self._task_repository.dbPath) as conn:
            if transaction is not None:
                self._resource_repository.deleteTransaction(transaction.id, conn)
            self._task_repository.deleteCompletion(completion.id, conn)
            self._resource_repository.recomputeLastRecordTime(
                RESOURCE_TYPE_CUBE, target_date, conn
            )

        if transaction is None:
            return CubeTaskWriteResult(
                success=True,
                task_code=task_code,
                message=f"已取消「{task.name}」（关联明细已不存在，仅清理完成记录）",
            )
        return CubeTaskWriteResult(
            success=True,
            task_code=task_code,
            message=(
                f"已取消「{task.name}」，并删除 {transaction.record_time} 的 "
                f"{transaction.amount} 个魔方记录"
            ),
        )

    # ------------------------------------------------------------- 辅助

    def getGroupTitle(self, group_code: str) -> str:
        """
        获取任务分组的展示标题。

        Args:
            group_code: 分组编码（daily / weekly / signin / cruise）。

        Returns:
            中文标题；未知分组返回原编码。
        """
        return TASK_GROUP_TITLES.get(group_code, group_code)
