"""
活动记录业务逻辑层模块。

负责活动记录的增删改查、筛选、汇总，以及「常规录入 → 活动建造」关联校验。

口径（见 docs/20261022_活动记录方案与导入报告.md）：

- 有明细时 ``build_count`` = 关联魔方 ÷ ``build_cost`` + 建造券次数；
  无明细时使用手工 / 历史的 ``build_count``；
- ``resource_transaction.event_id`` 用于汇总该活动的魔方支出与笔数；
- 删除活动只解除明细关联（``event_id`` 置空），不删除任何明细。
"""

from dataclasses import dataclass, field
from datetime import date
from typing import List, Optional

from models.event_model import EventOption, EventRecordModel
from repositories.event_repository import EventRepository
from utils import time_source
from utils.constants import (
    EVENT_BUILD_COST_OPTIONS,
    EVENT_DEFAULT_BUILD_COST,
    EVENT_STATUS_GRADUATED,
    EVENT_STATUS_MISSING,
    EVENT_STATUS_ONGOING,
    EVENT_STATUS_OPTIONS,
    EVENT_STATUS_UNSET_LABEL,
    MAX_EVENT_BUILD_COUNT,
    MAX_EVENT_NAME_LENGTH,
    MAX_EVENT_NOTE_LENGTH,
    MAX_EVENT_STATUS_LENGTH,
    MAX_EVENT_STATUS_NOTE_LENGTH,
    MAX_EVENT_TYPE_LENGTH,
    RECORD_DATE_FORMAT,
)
from utils.db_connection import DatabaseContext
from utils.exceptions import ValidationError


@dataclass
class EventRecordView:
    """
    活动记录的展示行（记录 + 关联汇总 + 有效建造次数）。

    Attributes:
        record: 活动记录本身。
        transaction_count: 关联的魔方支出明细笔数。
        cube_expense: 关联的魔方支出合计。
        build_count: 有效建造次数：有关联明细时为「魔方折算 + 券抽」，否则为手工 / 历史值。
        cube_build_count: 关联魔方折算出的建造次数。
        ticket_build_count: 计入合计的券抽次数。
        remainder: 关联魔方除以单耗后的余数；非 0 表示数据对不上，需要核对。
        derived: 是否由关联明细自动计算。
    """

    record: EventRecordModel
    transaction_count: int = 0
    cube_expense: int = 0
    build_count: Optional[int] = None
    cube_build_count: int = 0
    ticket_build_count: int = 0
    remainder: int = 0
    derived: bool = False


@dataclass
class EventFilterOptions:
    """
    活动记录筛选下拉的可选值。

    Attributes:
        years: 出现过的年份，倒序。
        types: 出现过的活动类型，按使用次数倒序。
        statuses: 状态建议值（固定三项 + 历史自定义状态）。
    """

    years: List[str] = field(default_factory=list)
    types: List[str] = field(default_factory=list)
    statuses: List[str] = field(default_factory=list)


@dataclass
class EventSummary:
    """
    当前筛选结果的口径汇总。

    Attributes:
        total: 记录总数。
        graduated: 状态为「毕业」的数量。
        missing: 状态为「缺」的数量。
        ongoing: 状态为「进行中」的数量。
        unset: 未标记状态的数量。
        other: 其它自定义状态的数量。
        build_count_known: 有建造次数记录的活动数（建造次数非 None）。
        build_count_total: 有建造次数记录的活动合计。
        linked_count: 有明细关联的活动数。
        cube_expense: 关联魔方支出合计。
    """

    total: int = 0
    graduated: int = 0
    missing: int = 0
    ongoing: int = 0
    unset: int = 0
    other: int = 0
    build_count_known: int = 0
    build_count_total: int = 0
    linked_count: int = 0
    cube_expense: int = 0


@dataclass
class EventWriteResult:
    """
    活动记录写操作结果。

    Attributes:
        success: 是否成功。
        message: 面向用户的提示文案。
        record_id: 新增 / 更新后的记录 ID（删除时为原 ID）。
    """

    success: bool
    message: str
    record_id: int = 0

    def toStatusBarMessage(self) -> str:
        """
        状态栏文案。

        Returns:
            提示文案。
        """
        return self.message


class EventRecordService:
    """活动记录服务：CRUD、筛选、汇总与导入。"""

    def __init__(self, event_repository: Optional[EventRepository] = None):
        """
        初始化活动记录服务。

        Args:
            event_repository: 活动记录数据访问实例。
        """
        self._repository = event_repository or EventRepository()

    # ------------------------------------------------------------- 查询

    def listRecords(
        self,
        year: Optional[str] = None,
        event_type: Optional[str] = None,
        status: Optional[str] = None,
        keyword: Optional[str] = None,
    ) -> List[EventRecordView]:
        """
        查询活动记录并附带关联汇总。

        Args:
            year: 可选年份。
            event_type: 可选类型。
            status: 可选状态；空串表示「未标记」。
            keyword: 可选关键词。

        Returns:
            展示行列表，按开始日期、ID 倒序。

        Raises:
            DatabaseError: 当查询失败时抛出。
        """
        records = self._repository.findRecords(year, event_type, status, keyword)
        stats = self._repository.findTransactionStats()
        return [
            self._buildView(record, *stats.get(record.id, (0, 0)))
            for record in records
        ]

    def _buildView(
        self, record: EventRecordModel, transaction_count: int, cube_expense: int
    ) -> EventRecordView:
        """
        构造展示行：有明细时按单耗折算建造次数，无明细时回退手填值。

        Args:
            record: 活动记录。
            transaction_count: 关联明细笔数。
            cube_expense: 关联魔方合计。

        Returns:
            展示行。
        """
        if not transaction_count:
            return EventRecordView(
                record=record,
                transaction_count=0,
                cube_expense=0,
                build_count=record.build_count,
                derived=False,
            )

        cost = record.build_cost or EVENT_DEFAULT_BUILD_COST
        cube_builds, remainder = divmod(cube_expense, cost)
        ticket = (record.ticket_build_count or 0) if record.use_ticket else 0
        return EventRecordView(
            record=record,
            transaction_count=transaction_count,
            cube_expense=cube_expense,
            build_count=cube_builds + ticket,
            cube_build_count=cube_builds,
            ticket_build_count=ticket,
            remainder=remainder,
            derived=True,
        )

    def getRecord(self, record_id: int) -> Optional[EventRecordModel]:
        """
        按 ID 查询活动记录。

        Args:
            record_id: 活动记录 ID。

        Returns:
            活动记录；不存在时返回 None。

        Raises:
            DatabaseError: 当查询失败时抛出。
        """
        return self._repository.findById(record_id)

    def getFilterOptions(self) -> EventFilterOptions:
        """
        查询筛选下拉可选值。

        Returns:
            年份与类型列表。

        Raises:
            DatabaseError: 当查询失败时抛出。
        """
        return EventFilterOptions(
            years=self._repository.findYearOptions(),
            types=self._repository.findTypeOptions(),
            statuses=self._mergedStatusOptions(self._repository.findStatusOptions()),
        )

    def getSelectableEvents(self) -> List[EventOption]:
        """
        查询常规录入可关联的活动选项（按开始日期倒序）。

        Returns:
            活动选项列表。

        Raises:
            DatabaseError: 当查询失败时抛出。
        """
        return [
            EventOption(
                id=record.id,
                event_date=record.event_date,
                name=record.name,
                status=record.status,
                build_cost=record.build_cost,
            )
            for record in self._repository.findAll()
        ]

    def getSummary(self, views: List[EventRecordView]) -> EventSummary:
        """
        汇总当前筛选结果。

        Args:
            views: :meth:`listRecords` 的结果。

        Returns:
            口径汇总。
        """
        summary = EventSummary(total=len(views))
        for view in views:
            record = view.record
            if record.status == EVENT_STATUS_GRADUATED:
                summary.graduated += 1
            elif record.status == EVENT_STATUS_MISSING:
                summary.missing += 1
            elif record.status == EVENT_STATUS_ONGOING:
                summary.ongoing += 1
            elif not record.status:
                summary.unset += 1
            else:
                summary.other += 1
            if view.build_count is not None:
                summary.build_count_known += 1
                summary.build_count_total += view.build_count
            if view.transaction_count:
                summary.linked_count += 1
                summary.cube_expense += view.cube_expense
        return summary

    def countAll(self) -> int:
        """
        统计活动记录总数。

        Returns:
            记录数。

        Raises:
            DatabaseError: 当查询失败时抛出。
        """
        return self._repository.countAll()

    # ------------------------------------------------------------- 校验

    def normalizeRecord(self, record: EventRecordModel) -> EventRecordModel:
        """
        规范化并校验一条活动记录（不写库）。

        Dialog 在保存前调用它做即时校验，``create`` / ``update`` 内部也会再调用一次，
        避免绕过界面直接写入非法值。

        Args:
            record: 原始记录。

        Returns:
            规范化后的新记录模型。

        Raises:
            ValidationError: 日期非法 / 晚于今天、单耗或建造次数非法、文本超长时抛出。
        """
        status = self._normalizeText(record.status, MAX_EVENT_STATUS_LENGTH, "状态")
        # 「未标记」是展示兜底文案，不作为真实状态落库
        if status == EVENT_STATUS_UNSET_LABEL:
            status = ""
        use_ticket = self._normalizeTicketFlag(record.use_ticket)
        return EventRecordModel(
            id=record.id,
            event_date=self._normalizeDate(record.event_date),
            event_type=self._normalizeText(
                record.event_type, MAX_EVENT_TYPE_LENGTH, "活动类型"
            ),
            name=self._normalizeText(record.name, MAX_EVENT_NAME_LENGTH, "活动名称"),
            status=status,
            status_note=self._normalizeText(
                record.status_note, MAX_EVENT_STATUS_NOTE_LENGTH, "状态备注"
            ),
            build_cost=self._normalizeBuildCost(record.build_cost),
            use_ticket=use_ticket,
            ticket_build_count=(
                self._normalizeTicketBuildCount(record.ticket_build_count)
                if use_ticket else None
            ),
            build_count=self._normalizeBuildCount(record.build_count),
            note=self._normalizeText(record.note, MAX_EVENT_NOTE_LENGTH, "备注"),
            created_at=record.created_at,
            updated_at=record.updated_at,
        )

    def _normalizeDate(self, value: str) -> str:
        """
        校验并规范化活动开始日期。

        Args:
            value: 原始日期文本。

        Returns:
            ``yyyy-MM-dd``。

        Raises:
            ValidationError: 为空、格式错误或晚于今天时抛出。
        """
        text = (value or "").strip()
        if not text:
            raise ValidationError("活动日期不能为空")
        try:
            parsed = date.fromisoformat(text)
        except ValueError:
            raise ValidationError(f"活动日期格式应为 yyyy-MM-dd：{text}")
        if parsed > time_source.today():
            raise ValidationError("活动日期不能晚于今天")
        return parsed.strftime(RECORD_DATE_FORMAT)

    def _normalizeText(self, value: Optional[str], max_length: int, label: str) -> str:
        """
        去除首尾空白并校验长度。

        Args:
            value: 原始文本。
            max_length: 最大长度。
            label: 字段名（用于提示）。

        Returns:
            规范化文本。

        Raises:
            ValidationError: 超过最大长度时抛出。
        """
        text = (value or "").strip()
        if len(text) > max_length:
            raise ValidationError(f"{label}不能超过 {max_length} 字")
        return text

    def _normalizeTicketFlag(self, value) -> int:
        """
        校验建造券开关：0 / 1（兼容 bool 与数字字符串）。

        Args:
            value: 原始开关值。

        Returns:
            0 或 1。

        Raises:
            ValidationError: 不是 0 / 1 时抛出。
        """
        if value is None or (isinstance(value, str) and not value.strip()):
            return 0
        try:
            flag = int(value)
        except (TypeError, ValueError):
            raise ValidationError("建造券开关只能为 0 或 1")
        if flag not in (0, 1):
            raise ValidationError("建造券开关只能为 0 或 1")
        return flag

    def _normalizeBuildCost(self, value) -> int:
        """
        校验单次建造消耗：只能是 1 或 2 魔方。

        Args:
            value: 原始单耗；空值按默认 2 处理。

        Returns:
            1 或 2。

        Raises:
            ValidationError: 不是 1 / 2 时抛出。
        """
        if value is None or (isinstance(value, str) and not value.strip()):
            return EVENT_DEFAULT_BUILD_COST
        if isinstance(value, bool):
            raise ValidationError("单次消耗只能是 1 或 2 魔方")
        try:
            cost = int(str(value).strip())
        except (TypeError, ValueError):
            raise ValidationError("单次消耗只能是 1 或 2 魔方")
        if cost not in EVENT_BUILD_COST_OPTIONS:
            raise ValidationError("单次消耗只能是 1 或 2 魔方")
        return cost

    def _normalizeTicketBuildCount(self, value) -> int:
        """
        校验建造券抽次数：空值按 0 处理，必须是非负整数。

        Args:
            value: 原始券抽次数。

        Returns:
            非负整数。

        Raises:
            ValidationError: 不是整数、为负或超过上限时抛出。
        """
        if value is None or (isinstance(value, str) and not value.strip()):
            return 0
        if isinstance(value, bool):
            raise ValidationError("建造券次数需为 0 或正整数")
        try:
            count = int(str(value).strip())
        except (TypeError, ValueError):
            raise ValidationError("建造券次数需为 0 或正整数")
        if count < 0:
            raise ValidationError("建造券次数不能为负数")
        if count > MAX_EVENT_BUILD_COUNT:
            raise ValidationError(f"建造券次数不能超过 {MAX_EVENT_BUILD_COUNT}")
        return count

    def _normalizeBuildCount(self, value) -> Optional[int]:
        """
        校验建造次数：None / 空串表示未统计，0 表示确实 0 次。

        Args:
            value: 原始建造次数。

        Returns:
            非负整数或 None。

        Raises:
            ValidationError: 不是整数、为负或超过上限时抛出。
        """
        if value is None:
            return None
        if isinstance(value, str) and not value.strip():
            return None
        if isinstance(value, bool):
            raise ValidationError("建造次数需为 0 或正整数，留空表示未统计")
        if not isinstance(value, int):
            try:
                value = int(str(value).strip())
            except (TypeError, ValueError):
                raise ValidationError("建造次数需为 0 或正整数，留空表示未统计")
        if value < 0:
            raise ValidationError("建造次数不能为负数")
        if value > MAX_EVENT_BUILD_COUNT:
            raise ValidationError(f"建造次数不能超过 {MAX_EVENT_BUILD_COUNT}")
        return value

    # ------------------------------------------------------------- 写入

    def create(self, record: EventRecordModel) -> EventWriteResult:
        """
        新增一条活动记录。

        Args:
            record: 活动记录（``id`` 会被忽略）。

        Returns:
            写操作结果。

        Raises:
            ValidationError: 字段校验失败时抛出。
            DatabaseError: 数据库写入失败时抛出。
        """
        normalized = self.normalizeRecord(record)
        normalized.id = None
        record_id = self._repository.insert(normalized)
        return EventWriteResult(
            True,
            f"已新增活动：{normalized.event_date} {normalized.displayName}",
            record_id,
        )

    def update(self, record_id: int, record: EventRecordModel) -> EventWriteResult:
        """
        更新一条活动记录。

        Args:
            record_id: 活动记录 ID。
            record: 新的字段值。

        Returns:
            写操作结果。

        Raises:
            ValidationError: 记录不存在或字段校验失败时抛出。
            DatabaseError: 数据库写入失败时抛出。
        """
        if self._repository.findById(record_id) is None:
            raise ValidationError(f"活动记录不存在：{record_id}")

        normalized = self.normalizeRecord(record)
        normalized.id = record_id
        if not self._repository.update(normalized):
            raise ValidationError(f"活动记录不存在：{record_id}")
        return EventWriteResult(
            True,
            f"已更新活动：{normalized.event_date} {normalized.displayName}",
            record_id,
        )

    def delete(self, record_id: int) -> EventWriteResult:
        """
        删除一条活动记录，并解除关联明细（明细本身保留）。

        Args:
            record_id: 活动记录 ID。

        Returns:
            写操作结果。

        Raises:
            ValidationError: 记录不存在时抛出。
            DatabaseError: 数据库写入失败时抛出。
        """
        record = self._repository.findById(record_id)
        if record is None:
            raise ValidationError(f"活动记录不存在：{record_id}")

        with DatabaseContext(self._repository.dbPath) as conn:
            unlinked = self._repository.unlinkTransactions(record_id, conn)
            self._repository.delete(record_id, conn)

        message = f"已删除活动：{record.event_date} {record.displayName}"
        if unlinked:
            message += f"；解除 {unlinked} 笔明细关联（明细保留）"
        return EventWriteResult(True, message, record_id)

    def importRecords(self, records: List[EventRecordModel]) -> int:
        """
        在一个事务里批量导入活动记录（一次性导入脚本用）。

        Args:
            records: 待导入记录列表。

        Returns:
            实际写入条数。

        Raises:
            ValidationError: 任一条记录校验失败时抛出（整批回滚）。
            DatabaseError: 数据库写入失败时抛出。
        """
        normalized = []
        for record in records:
            item = self.normalizeRecord(record)
            item.id = None
            normalized.append(item)

        with DatabaseContext(self._repository.dbPath) as conn:
            for record in normalized:
                self._repository.insert(record, conn)
        return len(normalized)

    def getStatusOptions(self) -> List[str]:
        """
        状态建议值：固定三项在前，历史自定义状态按使用次数追加。

        Returns:
            状态列表。

        Raises:
            DatabaseError: 当查询失败时抛出。
        """
        return self._mergedStatusOptions(self._repository.findStatusOptions())

    def _mergedStatusOptions(self, distinct: List[str]) -> List[str]:
        """
        合并固定状态建议值与历史出现过的自定义状态。

        Args:
            distinct: 库中出现过的非空状态。

        Returns:
            合并后的状态列表（去重、固定项保持顺序）。
        """
        merged = list(EVENT_STATUS_OPTIONS)
        for status in distinct:
            if status and status != EVENT_STATUS_UNSET_LABEL and status not in merged:
                merged.append(status)
        return merged

    def getTypeOptions(self) -> List[str]:
        """
        活动类型建议值（来自已有记录，按使用次数倒序）。

        Returns:
            类型列表。

        Raises:
            DatabaseError: 当查询失败时抛出。
        """
        return self._repository.findTypeOptions()
