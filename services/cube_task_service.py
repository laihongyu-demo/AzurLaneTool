"""
资源任务看板业务逻辑层模块。

负责周期键计算（日 / ISO 周 / 自然月 / 双月巡游期）、看板状态汇总，
以及「单击完成 / 双击取消」背后的记账与回滚。同一套服务按
``resource_type`` 复用于魔方与红尖尖。

日常「建造舰船 1 次」是唯一带联动的任务：完成时除了任务奖励收入，还要按所选
卡池记一笔建造支出；消耗建造券时没有支出，但要把这次建造计入进行中活动的
券抽次数。口径见 ``docs/20261025_日常建造任务两笔明细方案.md``。
"""

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Dict, Iterable, List, Optional, Tuple

from models.cube_task_model import CubeTaskCompletionModel, CubeTaskModel
from models.event_model import EventRecordModel
from models.resource_model import ResourceTransactionModel
from models.task_period import TaskPeriodInfo
from repositories.cube_task_repository import CubeTaskRepository
from repositories.event_repository import EventRepository
from repositories.resource_repository import ResourceRepository
from services.world_cruise_service import WorldCruiseService
from utils import time_source
from utils.constants import (
    EVENT_BUILD_CATEGORY, EVENT_DEFAULT_BUILD_COST, RECORD_DATE_FORMAT,
    RECORD_TIME_FORMAT, RESOURCE_DIRECTION_EXPENSE, RESOURCE_DIRECTION_INCOME,
    RESOURCE_DISPLAY_NAMES, RESOURCE_TYPE_CUBE, TASK_DISPLAY_GROUPS_BY_RESOURCE,
    TASK_GROUP_TITLES, TASK_PERIOD_CRUISE, TASK_PERIODS,
)
from utils.db_connection import DatabaseContext
from utils.db_schema import isMissingColumnError, isMissingTableError
from utils.exceptions import DatabaseError, ValidationError
from utils.task_period import (
    addMonths, buildPeriodInfo, buildPeriodKey, cruisePeriodEnd, cruisePeriodStart,
    formatPeriodLabel, monthRange, periodRange, weekRange,
)

PERIOD_TYPES = TASK_PERIODS

# 兼容旧调用方：周期信息值对象已迁到 models/task_period.py
CubePeriodInfo = TaskPeriodInfo

# 唯一带「建造支出 / 券抽」联动的日常任务
BUILD_TASK_CODE = "daily_build_once"

# 卡池键：轻型 / 重型 / 特型用固定单耗，活动池按进行中活动的单耗
BUILD_POOL_LIGHT = "light"
BUILD_POOL_HEAVY = "heavy"
BUILD_POOL_SPECIAL = "special"
BUILD_POOL_EVENT = "event"


@dataclass(frozen=True)
class BuildPool:
    """
    建造任务可选的卡池。

    Attributes:
        key: 卡池键，仅用于界面选择与调用方识别（不落库）。
        label: 展示名（``轻型建造``）。
        category: 写入支出明细时使用的类型名，需存在于类型字典。
        cost: 单次建造消耗的魔方数；活动池由 :func:`CubeTaskService.getBuildPlan`
            换成进行中活动的实际单耗。
    """

    key: str
    label: str
    category: str
    cost: int


BUILD_POOLS: Tuple[BuildPool, ...] = (
    BuildPool(BUILD_POOL_LIGHT, "轻型建造", "轻型建造", 1),
    BuildPool(BUILD_POOL_HEAVY, "重型建造", "重型建造", 2),
    BuildPool(BUILD_POOL_SPECIAL, "特型建造", "特型建造", 2),
    BuildPool(BUILD_POOL_EVENT, "活动建造", EVENT_BUILD_CATEGORY, EVENT_DEFAULT_BUILD_COST),
)

BUILD_POOL_BY_KEY: Dict[str, BuildPool] = {pool.key: pool for pool in BUILD_POOLS}

DEFAULT_BUILD_POOL_KEY = BUILD_POOL_LIGHT


@dataclass
class BuildTaskPlan:
    """
    建造任务的确认信息（供对话框渲染）。

    Attributes:
        pools: 可选卡池；活动池的 ``cost`` 已按进行中活动替换。
        ongoing_event: 进行中活动；None 表示当前没有（活动池按默认单耗、不关联）。
    """

    pools: Tuple[BuildPool, ...] = BUILD_POOLS
    ongoing_event: Optional[EventRecordModel] = None


# ------------------------------------------------------------------ 视图对象


@dataclass
class CubeTaskState:
    """
    单个任务在某周期的状态。

    Attributes:
        task: 任务定义。
        completed: 是否已完成。
        completed_at: 完成时刻。
        transaction_id: 关联的收入明细 ID。
        orphan: 完成记录存在但关联收入明细已不存在。
        marked_only: 仅标记完成、无对应明细（期初对齐时的兜底）。
        expense_transaction_id: 建造任务的支出明细 ID；None 表示没有支出（建造券）。
        expense_category: 支出类型名（轻型建造等），用于展示与取消提示。
        expense_amount: 支出魔方数。
    """

    task: CubeTaskModel
    completed: bool = False
    completed_at: Optional[str] = None
    transaction_id: Optional[int] = None
    orphan: bool = False
    marked_only: bool = False
    expense_transaction_id: Optional[int] = None
    expense_category: str = ""
    expense_amount: int = 0


@dataclass
class CubeTaskGroupView:
    """
    展示分组（任务 / 每月签到 / 世界巡游）。

    Attributes:
        key: 分组键。
        title: 分组标题。
        tasks: 分组内的任务状态列表。
        earned: 本周期已获得的资源数量。
        total: 本周期应得的资源总数。
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
        resource_repository: Optional[ResourceRepository] = None,
        resource_type: str = RESOURCE_TYPE_CUBE,
        display_groups=None,
        world_cruise_service: Optional[WorldCruiseService] = None,
        event_repository: Optional[EventRepository] = None,
    ):
        """
        初始化任务看板服务。

        Args:
            task_repository: 任务定义 / 完成记录数据访问实例。
            resource_repository: 资源明细数据访问实例。
            resource_type: 资源类型，``cube`` 或 ``red_gem``。
            display_groups: 展示分组；为空时按资源类型取默认值。
            world_cruise_service: 世界巡游档期服务。
            event_repository: 活动记录数据访问实例（建造任务关联进行中活动）。
        """
        self._task_repository = task_repository or CubeTaskRepository()
        self._resource_repository = resource_repository or ResourceRepository()
        self._resource_type = resource_type
        self._display_groups = tuple(
            display_groups or TASK_DISPLAY_GROUPS_BY_RESOURCE.get(resource_type, ())
        )
        self._world_cruise_service = world_cruise_service or WorldCruiseService()
        self._event_repository = event_repository or EventRepository()

    @property
    def resourceType(self) -> str:
        """
        当前服务对应的资源类型。

        Returns:
            ``cube`` 或 ``red_gem``。
        """
        return self._resource_type

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
            period_type: self._periodKey(period_type, record_date)
            for period_type in PERIOD_TYPES
        }

    def _periodKey(self, period_type: str, when: date) -> str:
        """
        生成单个周期键；巡游期统一走 `WorldCruiseService`。

        Args:
            period_type: 周期类型。
            when: 归属日期。

        Returns:
            周期键。
        """
        if period_type == TASK_PERIOD_CRUISE:
            return self._world_cruise_service.getPeriod(when).key
        return buildPeriodKey(period_type, when)

    def getPeriodInfo(self, record_date: date) -> Dict[str, TaskPeriodInfo]:
        """
        生成 4 个周期的展示信息。

        Args:
            record_date: 归属日期。

        Returns:
            周期类型 → 周期信息。
        """
        info: Dict[str, TaskPeriodInfo] = {}
        for period_type in PERIOD_TYPES:
            if period_type == TASK_PERIOD_CRUISE:
                period = self._world_cruise_service.getPeriod(record_date)
                info[period_type] = TaskPeriodInfo(
                    period_type=period_type,
                    period_key=period.key,
                    label=period.label,
                    start=period.start.strftime(RECORD_DATE_FORMAT),
                    end=period.end.strftime(RECORD_DATE_FORMAT),
                )
            else:
                info[period_type] = buildPeriodInfo(period_type, record_date)
        return info

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
            tasks = self._task_repository.findAll(self._resource_type)
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

        expense_by_id = self._findExpenseTransactions(active.values())

        groups: List[CubeTaskGroupView] = []
        for group_key, title, group_codes in self._display_groups:
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
                    state.expense_transaction_id = completion.expense_transaction_id
                    expense = expense_by_id.get(completion.expense_transaction_id)
                    if expense is not None:
                        state.expense_category = expense.category
                        state.expense_amount = expense.amount
                view.tasks.append(state)
                view.total += task.reward
                if state.completed:
                    view.earned += task.reward
            groups.append(view)
        return groups

    def _findExpenseTransactions(
        self, completions: Iterable[CubeTaskCompletionModel]
    ) -> Dict[int, ResourceTransactionModel]:
        """
        批量取完成记录关联的建造支出明细（一次查询，避免 N+1）。

        Args:
            completions: 完成记录集合。

        Returns:
            明细 ID → 明细模型；没有支出或表缺失时返回空字典。

        Raises:
            DatabaseError: 非结构缺失类的查询失败时抛出。
        """
        expense_ids = [
            completion.expense_transaction_id
            for completion in completions if completion.expense_transaction_id
        ]
        if not expense_ids:
            return {}
        try:
            records = self._resource_repository.findTransactionsByIds(expense_ids)
        except DatabaseError as e:
            if isMissingTableError(e) or isMissingColumnError(e):
                return {}
            raise
        return {record.id: record for record in records}

    def _emptyGroups(self) -> List[CubeTaskGroupView]:
        """
        构造空分组（表缺失时的降级结果）。

        Returns:
            分组视图列表。
        """
        return [
            CubeTaskGroupView(key=key, title=title)
            for key, title, _codes in self._display_groups
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
        if task.resource_type != self._resource_type:
            raise ValidationError(f"任务「{task.name}」不属于当前资源")
        if task.code == BUILD_TASK_CODE:
            # 建造任务要同时决定建造支出与活动联动，必须走确认框，避免写出只有收入的不一致数据
            raise ValidationError("建造任务需要先选择卡池，请通过建造确认框完成")

        period_key = self.getPeriodKeys(moment.date())[task.period_type]
        existing = self._task_repository.findCompletion(task_code, period_key)
        if existing is not None:
            raise ValidationError(f"本期已完成「{task.name}」，双击可取消")

        record_date_text = moment.strftime(RECORD_DATE_FORMAT)
        record_time_text = moment.strftime(RECORD_TIME_FORMAT)
        transaction = ResourceTransactionModel(
            resource_type=self._resource_type,
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
                self._resource_type, record_date_text, record_time_text, conn
            )
            completion.transaction_id = transaction_id
            completion_id = self._task_repository.insertCompletion(completion, conn)
            if completion_id is None:
                # 并发下的兜底：唯一约束拒绝了重复完成，回滚整笔写入
                raise ValidationError(f"本期已完成「{task.name}」，双击可取消")

        resource_name = RESOURCE_DISPLAY_NAMES.get(self._resource_type, self._resource_type)
        return CubeTaskWriteResult(
            success=True,
            task_code=task_code,
            message=(
                f"已完成「{task.name}」，{resource_name} +{task.reward}（{record_time_text}）"
            ),
        )

    # ----------------------------------------------------------- 建造任务

    def getBuildPlan(self) -> BuildTaskPlan:
        """
        生成建造任务的确认信息（进行中活动 + 各卡池实际单耗）。

        活动池的单耗跟随进行中活动的 ``build_cost``；没有进行中活动时按默认单耗、
        不关联活动。

        Returns:
            确认信息。

        Raises:
            DatabaseError: 查询活动记录失败（非结构缺失）时抛出。
        """
        ongoing = self._findOngoingEvent()
        event_cost = (
            ongoing.build_cost if ongoing is not None else EVENT_DEFAULT_BUILD_COST
        )
        pools = tuple(
            BuildPool(
                key=pool.key,
                label=pool.label,
                category=pool.category,
                cost=event_cost if pool.key == BUILD_POOL_EVENT else pool.cost,
            )
            for pool in BUILD_POOLS
        )
        return BuildTaskPlan(pools=pools, ongoing_event=ongoing)

    def _findOngoingEvent(self) -> Optional[EventRecordModel]:
        """
        查询最近一条进行中活动；活动表缺失时降级为「没有进行中活动」。

        Returns:
            活动记录；没有进行中活动（或旧库缺表）时返回 None。

        Raises:
            DatabaseError: 非结构缺失类的查询失败时抛出。
        """
        try:
            return self._event_repository.findLatestOngoing()
        except DatabaseError as e:
            if isMissingTableError(e) or isMissingColumnError(e):
                return None
            raise

    def completeBuildTask(
        self,
        task_code: str,
        at: Optional[datetime] = None,
        pool_key: str = DEFAULT_BUILD_POOL_KEY,
        use_ticket: bool = False,
    ) -> CubeTaskWriteResult:
        """
        完成建造任务：写入任务奖励收入，并按选择写入建造支出（同一事务）。

        口径：

        - 不使用建造券：写「支出 · 卡池类型 · 单耗」＋「收入 · 日常任务 · 奖励」两笔；
          活动池按进行中活动的单耗扣减，并把明细关联到该活动；
        - 使用建造券：只写收入，不扣魔方；若当前有进行中活动，把该活动的券抽次数 +1
          （``use_ticket`` 同步置 1），使这次建造计入活动建造次数。

        Args:
            task_code: 任务编码，仅接受 :data:`BUILD_TASK_CODE`。
            at: 完成时刻，默认当前时间；补录时传历史时刻。
            pool_key: 卡池键，见 :data:`BUILD_POOLS`。
            use_ticket: 是否使用建造券。

        Returns:
            写操作结果。

        Raises:
            ValidationError: 任务不符、卡池非法、时刻在未来或本期已完成时抛出。
            DatabaseError: 数据库写入失败时抛出。
        """
        moment = at or time_source.now()
        if moment > time_source.now():
            raise ValidationError("不能录入未来的完成时刻")

        task = self._task_repository.findByCode(task_code)
        if task is None:
            raise ValidationError(f"任务不存在或已停用: {task_code}")
        if task.resource_type != self._resource_type:
            raise ValidationError(f"任务「{task.name}」不属于当前资源")
        if task.code != BUILD_TASK_CODE:
            raise ValidationError(f"「{task.name}」不是建造任务，不需要选择卡池")
        if self._resource_type != RESOURCE_TYPE_CUBE:
            raise ValidationError("只有魔方看板支持建造任务")

        pool = BUILD_POOL_BY_KEY.get(pool_key)
        if pool is None:
            raise ValidationError(f"未知的建造卡池: {pool_key}")

        period_key = self.getPeriodKeys(moment.date())[task.period_type]
        existing = self._task_repository.findCompletion(task_code, period_key)
        if existing is not None:
            raise ValidationError(f"本期已完成「{task.name}」，双击可取消")

        ongoing = self._findOngoingEvent()
        record_date_text = moment.strftime(RECORD_DATE_FORMAT)
        record_time_text = moment.strftime(RECORD_TIME_FORMAT)

        expense = None
        event_id = None
        cost = 0
        if use_ticket:
            event_id = ongoing.id if ongoing is not None else None
        else:
            if pool.key == BUILD_POOL_EVENT:
                cost = (
                    ongoing.build_cost if ongoing is not None else EVENT_DEFAULT_BUILD_COST
                )
                event_id = ongoing.id if ongoing is not None else None
            else:
                cost = pool.cost
            expense = ResourceTransactionModel(
                resource_type=self._resource_type,
                direction=RESOURCE_DIRECTION_EXPENSE,
                record_time=record_time_text,
                category=pool.category,
                amount=cost,
                note=f"{task.name}（{pool.label}）",
                event_id=event_id,
            )

        income = ResourceTransactionModel(
            resource_type=self._resource_type,
            direction=RESOURCE_DIRECTION_INCOME,
            record_time=record_time_text,
            category=task.category,
            amount=task.reward,
            note=f"{task.name}（建造券）" if use_ticket else task.name,
        )
        completion = CubeTaskCompletionModel(
            task_code=task_code,
            period_key=period_key,
            completed_at=record_time_text,
            event_id=event_id,
        )

        with DatabaseContext(self._task_repository.dbPath) as conn:
            expense_id = None
            if expense is not None:
                expense_id = self._resource_repository.insertTransaction(expense, conn)
            transaction_id = self._resource_repository.insertTransaction(income, conn)
            self._resource_repository.upsertDetailDaily(
                self._resource_type, record_date_text, record_time_text, conn
            )
            if use_ticket and ongoing is not None:
                self._event_repository.adjustTicketBuildCount(ongoing.id, 1, conn)
            completion.transaction_id = transaction_id
            completion.expense_transaction_id = expense_id
            completion_id = self._task_repository.insertCompletion(completion, conn)
            if completion_id is None:
                # 并发下的兜底：唯一约束拒绝了重复完成，回滚整笔写入
                raise ValidationError(f"本期已完成「{task.name}」，双击可取消")

        resource_name = RESOURCE_DISPLAY_NAMES.get(self._resource_type, self._resource_type)
        if use_ticket:
            message = (
                f"已完成「{task.name}」（建造券），{resource_name} +{task.reward}，不扣魔方"
            )
            if ongoing is not None:
                message += f"；已计入活动「{ongoing.displayName}」券抽 1 次"
        else:
            message = (
                f"已完成「{task.name}」：支出 · {pool.category} {cost}，"
                f"收入 · {task.category} +{task.reward}"
            )
            if ongoing is not None and event_id is not None:
                message += f"（关联活动「{ongoing.displayName}」）"
        return CubeTaskWriteResult(
            success=True, task_code=task_code, message=f"{message}（{record_time_text}）"
        )

    def cancelTask(self, task_code: str, record_date: date) -> CubeTaskWriteResult:
        """
        取消某个任务在本周期的完成状态（删除明细 + 完成记录）。

        建造任务会连带删除建造支出，并把当初计入的进行中活动券抽次数 -1。

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
        if task.resource_type != self._resource_type:
            raise ValidationError(f"任务「{task.name}」不属于当前资源")

        period_key = self.getPeriodKeys(record_date)[task.period_type]
        completion = self._task_repository.findCompletion(task_code, period_key)
        if completion is None:
            raise ValidationError(f"「{task.name}」本期尚未完成")

        transaction = None
        if completion.transaction_id is not None:
            transaction = self._resource_repository.findTransactionById(completion.transaction_id)

        expense = None
        if completion.expense_transaction_id is not None:
            expense = self._resource_repository.findTransactionById(
                completion.expense_transaction_id
            )

        # 没有支出但记了活动，说明当初走的是建造券：取消要把券抽次数还回去
        ticket_event_id = (
            completion.event_id
            if completion.expense_transaction_id is None and completion.event_id is not None
            else None
        )

        target_date = (completion.completed_at or "")[:10] or record_date.strftime(RECORD_DATE_FORMAT)

        with DatabaseContext(self._task_repository.dbPath) as conn:
            if transaction is not None:
                self._resource_repository.deleteTransaction(transaction.id, conn)
            if expense is not None:
                self._resource_repository.deleteTransaction(expense.id, conn)
            if ticket_event_id is not None:
                self._event_repository.adjustTicketBuildCount(ticket_event_id, -1, conn)
            self._task_repository.deleteCompletion(completion.id, conn)
            self._resource_repository.recomputeLastRecordTime(
                self._resource_type, target_date, conn
            )

        resource_name = RESOURCE_DISPLAY_NAMES.get(self._resource_type, self._resource_type)
        deleted = []
        if transaction is not None:
            deleted.append(f"收入 {transaction.amount}")
        if expense is not None:
            deleted.append(f"支出 {expense.amount}")
        if not deleted:
            return CubeTaskWriteResult(
                success=True,
                task_code=task_code,
                message=f"已取消「{task.name}」（关联明细已不存在，仅清理完成记录）",
            )

        message = (
            f"已取消「{task.name}」，并删除 {completion.completed_at or target_date} 的 "
            + "、".join(deleted)
            + f" 个{resource_name}记录"
        )
        if ticket_event_id is not None:
            message += "；已回滚活动券抽 1 次"
        return CubeTaskWriteResult(success=True, task_code=task_code, message=message)

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
