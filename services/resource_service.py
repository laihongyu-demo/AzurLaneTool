"""
资源统计服务模块。

提供魔方 / 红尖尖的结余扫描、看板展示文本与只读查询。

本阶段（需求文档 v0.2）不提供任何写入接口，录入与编辑推迟到 #17。
"""

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Dict, List, Optional, Tuple

from models.resource_model import ResourceDailyModel
from repositories.resource_repository import ResourceRepository
from utils.constants import RESOURCE_DETAIL_MODE_DETAIL, RESOURCE_DISPLAY_NAMES
from utils.db_schema import isMissingColumnError, isMissingTableError
from utils.exceptions import DatabaseError
from utils.unit_formatter import formatExact, formatValue

# 结余扫描结果的字段名，供视图层与卡片复用
BALANCE_DATE = "record_date"
BALANCE_INCOME = "income"
BALANCE_EXPENSE = "expense"
BALANCE_VALUE = "balance"
BALANCE_MODE = "detail_mode"
BALANCE_TRANSACTION_COUNT = "transaction_count"
BALANCE_OVERRIDE = "balance_override"
BALANCE_NOTE = "note"
BALANCE_LAST_TIME = "last_record_time"

# 迁移期历史数据只有日期，统一补成 00:00:00 占位；展示时视为"无时刻"退化为日期
PLACEHOLDER_TIME_SUFFIX = " 00:00:00"

# 日环比角标的方向标识
DELTA_TONE_UP = "up"
DELTA_TONE_DOWN = "down"
DELTA_TONE_FLAT = "flat"

# 角标数值超过该位数改用 K/M 缩写，与卡片的"大概数值"口径保持一致
DELTA_ABBREVIATE_THRESHOLD = 10000


@dataclass
class ResourceDailyDelta:
    """
    卡片结余相较昨日的变化。

    Attributes:
        delta: 变化量（正数上涨、负数下降、0 持平）。
        latest_date: 最新记录日 ``yyyy-MM-dd``。
        previous_date: 前一日 ``yyyy-MM-dd``。
        latest_balance: 最新记录日结余。
        previous_balance: 前一日结余。
        has_anchor: 两天中是否含手填结余锚点（锚点会人为跳变结余）。
    """

    delta: int
    latest_date: str
    previous_date: str
    latest_balance: int
    previous_balance: int
    has_anchor: bool = False

    @property
    def tone(self) -> str:
        """
        变化方向，供视图层选颜色。

        Returns:
            ``up`` / ``down`` / ``flat``。
        """
        if self.delta > 0:
            return DELTA_TONE_UP
        if self.delta < 0:
            return DELTA_TONE_DOWN
        return DELTA_TONE_FLAT

    @property
    def display_text(self) -> str:
        """
        角标文案：``↑111`` / ``↓111`` / ``—``。

        Returns:
            展示文本。
        """
        if self.delta == 0:
            return "—"
        magnitude = abs(self.delta)
        rendered = (
            formatExact(magnitude)
            if magnitude < DELTA_ABBREVIATE_THRESHOLD
            else formatValue(magnitude)
        )
        arrow = "↑" if self.delta > 0 else "↓"
        return f"{arrow}{rendered}"


@dataclass
class ResourceCardView:
    """
    资源卡片的完整展示内容（一次结余扫描产出）。

    Attributes:
        text: 卡片数值文本（大概数值口径）。
        tooltip: 悬停提示（精确值 + 末次记录 + 日环比说明）。
        delta: 日环比结果；不可比时为 None。
    """

    text: str
    tooltip: str
    delta: Optional[ResourceDailyDelta] = None


class ResourceService:
    """
    资源统计服务类。

    结余是派生值：按日期顺序扫描日汇总行，明细日取 Σ明细，汇总日取存储值；
    遇到手填结余（锚点）则重设累计值。因此该服务只读，不存在缓存失效问题。
    """

    def __init__(self, resource_repository: Optional[ResourceRepository] = None):
        """
        初始化资源统计服务。

        Args:
            resource_repository: 资源数据访问实例。
        """
        self._resource_repository = resource_repository or ResourceRepository()

    def getBalanceSeries(self, resource_type: str) -> List[Dict]:
        """
        计算指定资源的逐日收支与结余。

        Args:
            resource_type: 资源类型，``cube`` 或 ``red_gem``。

        Returns:
            按日期升序的列表，每项包含 ``record_date``、``income``、``expense``、
            ``balance``、``detail_mode``、``transaction_count``、``balance_override``、
            ``note``、``last_record_time``（该日最后一笔的准确时刻，可能为 None）。
            表缺失或无数据时返回空列表。
        """
        try:
            daily_rows = self._resource_repository.findAllDaily(resource_type)
            totals = self._resource_repository.findTransactionTotals(resource_type)
        except DatabaseError as e:
            if isMissingTableError(e) or isMissingColumnError(e):
                return []
            raise

        series: List[Dict] = []
        balance = 0
        for row in daily_rows:
            income, expense, count = self._resolveDailyAmount(row, totals)
            if row.balance_override is not None:
                balance = int(row.balance_override)
            else:
                balance += income - expense

            series.append({
                BALANCE_DATE: row.record_date,
                BALANCE_INCOME: income,
                BALANCE_EXPENSE: expense,
                BALANCE_VALUE: balance,
                BALANCE_MODE: row.detail_mode,
                BALANCE_TRANSACTION_COUNT: count,
                BALANCE_OVERRIDE: row.balance_override,
                BALANCE_NOTE: row.note,
                BALANCE_LAST_TIME: self._resolveLastRecordTime(row, totals),
            })
        return series

    def _resolveDailyAmount(self, row: ResourceDailyModel, totals: Dict[str, Dict[str, Any]]):
        """
        解析单日的收入、支出与明细笔数。

        Args:
            row: 日汇总行。
            totals: 按日期汇总的明细，来自 :meth:`getBalanceSeries` 的一次性查询。

        Returns:
            ``(income, expense, transaction_count)`` 三元组。
        """
        if row.detail_mode == RESOURCE_DETAIL_MODE_DETAIL:
            bucket = totals.get(row.record_date, {})
            return (
                int(bucket.get("income", 0)),
                int(bucket.get("expense", 0)),
                int(bucket.get("count", 0)),
            )
        return int(row.income or 0), int(row.expense or 0), 0

    def _resolveLastRecordTime(
        self, row: ResourceDailyModel, totals: Dict[str, Dict[str, Any]]
    ) -> Optional[str]:
        """
        解析该日最后一笔记录的准确时刻。

        以「日汇总行冗余值」与「明细实际最大值」中较晚者为准，避免冗余列未及时更新
        时展示过期时间。

        Args:
            row: 日汇总行。
            totals: 按日期汇总的明细。

        Returns:
            ``yyyy-MM-dd HH:mm:ss``；该日没有时刻信息时返回 None。
        """
        candidates = [value for value in (
            row.last_record_time,
            totals.get(row.record_date, {}).get("last_time"),
        ) if value]
        if not candidates:
            return None
        return max(candidates)

    def getBalance(self, resource_type: str) -> Optional[int]:
        """
        获取指定资源的当前结余（最后一个有记录日期的累计值）。

        Args:
            resource_type: 资源类型。

        Returns:
            结余数值；无数据时返回 None。
        """
        series = self.getBalanceSeries(resource_type)
        if not series:
            return None
        return series[-1][BALANCE_VALUE]

    def getLatestRecordDate(self, resource_type: str) -> Optional[str]:
        """
        获取指定资源最后一个有记录的日期。

        Args:
            resource_type: 资源类型。

        Returns:
            日期字符串 ``yyyy-MM-dd``；无数据时返回 None。
        """
        series = self.getBalanceSeries(resource_type)
        if not series:
            return None
        return series[-1][BALANCE_DATE]

    def getCardView(self, resource_type: str) -> ResourceCardView:
        """
        一次结余扫描生成卡片数值、悬停提示与日环比角标。

        结余链要扫 1800+ 天日汇总与全部明细，分两次调用（文本 / 提示）会把同样的
        扫描做两遍；看板刷新时直接用本方法可省一半开销，角标也不额外查询。

        Args:
            resource_type: 资源类型。

        Returns:
            卡片展示数据；无数据时文本为 ``-``、提示说明暂无记录。
        """
        display_name = RESOURCE_DISPLAY_NAMES.get(resource_type, resource_type)
        series = self.getBalanceSeries(resource_type)
        if not series:
            return ResourceCardView("-", f"{display_name}：暂无记录")

        latest = series[-1]
        text = formatValue(latest[BALANCE_VALUE])
        tooltip = (
            f"{display_name}：{formatExact(latest[BALANCE_VALUE])}"
            f"（末次记录 {self._formatRecordStamp(latest)}）"
        )

        delta, note = self._buildDailyDelta(series)
        return ResourceCardView(text, f"{tooltip}｜{note}", delta)

    def _buildDailyDelta(
        self, series: List[Dict]
    ) -> Tuple[Optional[ResourceDailyDelta], str]:
        """
        按结余链最后两行计算日环比。

        只有最新日的**自然日前一天**也有记录时才算"较昨日"；断档时不拿更早的
        记录冒充昨天，直接标注无法比较。

        Args:
            series: :meth:`getBalanceSeries` 的结果。

        Returns:
            ``(环比结果或 None, 追加到 tooltip 的说明文案)``。
        """
        if len(series) < 2:
            return None, "仅一天记录，无法比较"

        latest = series[-1]
        previous = series[-2]
        latest_date = date.fromisoformat(latest[BALANCE_DATE])
        previous_date = date.fromisoformat(previous[BALANCE_DATE])
        if latest_date - previous_date != timedelta(days=1):
            return None, f"昨日（{latest_date - timedelta(days=1):%Y-%m-%d}）无记录，无法比较"

        has_anchor = (
            latest.get(BALANCE_OVERRIDE) is not None
            or previous.get(BALANCE_OVERRIDE) is not None
        )
        delta = ResourceDailyDelta(
            delta=int(latest[BALANCE_VALUE]) - int(previous[BALANCE_VALUE]),
            latest_date=latest[BALANCE_DATE],
            previous_date=previous[BALANCE_DATE],
            latest_balance=int(latest[BALANCE_VALUE]),
            previous_balance=int(previous[BALANCE_VALUE]),
            has_anchor=has_anchor,
        )

        anchor_note = "（含手填结余）" if has_anchor else ""
        if delta.delta == 0:
            note = (
                f"与昨日持平（{delta.previous_date}、{delta.latest_date} "
                f"均为 {formatExact(delta.latest_balance)}）{anchor_note}"
            )
        else:
            note = (
                f"较昨日 {delta.delta:+d}"
                f"（{delta.previous_date} {formatExact(delta.previous_balance)} → "
                f"{delta.latest_date} {formatExact(delta.latest_balance)}）{anchor_note}"
            )
        return delta, note

    def getCardText(self, resource_type: str) -> str:
        """
        获取看板卡片显示文本。

        魔方 / 红尖尖属于"大概数值"口径：用 K/M/B/T 缩写并保留一位小数。

        Args:
            resource_type: 资源类型。

        Returns:
            卡片文本；无数据时为 ``-``。
        """
        return self.getCardView(resource_type).text

    def getCardTooltip(self, resource_type: str) -> str:
        """
        获取看板卡片悬停提示（精确数值 + 末次记录的准确时刻）。

        时刻已知时精确到秒；仅有日期（迁移期历史数据统一为 ``00:00:00``）时退化为日期。

        Args:
            resource_type: 资源类型。

        Returns:
            提示文本；无数据时说明暂无记录。
        """
        return self.getCardView(resource_type).tooltip

    def _formatRecordStamp(self, item: Dict) -> str:
        """
        把末次记录时刻格式化为展示文本。

        历史数据的时间部分统一为 ``00:00:00`` 占位，此时只展示日期，避免误导。

        Args:
            item: 结余扫描结果中的一行。

        Returns:
            ``yyyy-MM-dd HH:mm:ss`` 或 ``yyyy-MM-dd``。
        """
        stamp = str(item.get(BALANCE_LAST_TIME) or "")
        if stamp.endswith(PLACEHOLDER_TIME_SUFFIX):
            stamp = stamp[: -len(PLACEHOLDER_TIME_SUFFIX)]
        return stamp or str(item[BALANCE_DATE])

    def listDaily(
        self, resource_type: str, start_date: Optional[str] = None, end_date: Optional[str] = None
    ) -> List[Dict]:
        """
        按日期范围查询逐日收支与结余。

        Args:
            resource_type: 资源类型。
            start_date: 可选起始日期 ``yyyy-MM-dd``。
            end_date: 可选结束日期 ``yyyy-MM-dd``。

        Returns:
            列表，字段同 :meth:`getBalanceSeries`，按日期升序。
        """
        series = self.getBalanceSeries(resource_type)
        if start_date:
            series = [item for item in series if item[BALANCE_DATE] >= start_date]
        if end_date:
            series = [item for item in series if item[BALANCE_DATE] <= end_date]
        return series

    def getCategories(self, resource_type: str, direction: str) -> List[str]:
        """
        获取事件字典中的候选名称。

        Args:
            resource_type: 资源类型。
            direction: 方向，``income`` 或 ``expense``。

        Returns:
            事件名称列表；表缺失时返回空列表。
        """
        try:
            return [
                category.name
                for category in self._resource_repository.findCategories(resource_type, direction)
            ]
        except DatabaseError as e:
            if isMissingTableError(e) or isMissingColumnError(e):
                return []
            raise
