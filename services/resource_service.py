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
from utils import time_source
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

# 角标的计算口径：连续两天用结余差；昨日断档 / 仅一天记录改用今日净额（#37）
DELTA_BASIS_DAILY = "daily"
DELTA_BASIS_TODAY_NET = "today_net"

# 角标数值超过该位数改用 K/M 缩写，与卡片的"大概数值"口径保持一致
DELTA_ABBREVIATE_THRESHOLD = 10000


@dataclass
class ResourceDailyDelta:
    """
    卡片最新的变化量（今日 vs 昨日，断档时退化为今日净额）。

    ``delta`` 的含义随 ``basis`` 变化，调用方不要假定它等于两个结余之差（#37）：

    - ``basis == DELTA_BASIS_DAILY``：``delta = latest_balance - previous_balance``；
    - ``basis == DELTA_BASIS_TODAY_NET``：``delta = 今日收入 - 今日支出``，
      此时 ``previous_date`` 是**上次记录日**而非昨日，``gap_days`` 为与今天相隔的天数。

    Attributes:
        delta: 变化量（正数上涨、负数下降、0 持平）。
        latest_date: 最新记录日 ``yyyy-MM-dd``。
        previous_date: ``daily`` 口径为前一日；``today_net`` 口径为上次记录日，
            仅有今天一条记录时为空串。
        latest_balance: 最新记录日结余。
        previous_balance: 前一日 / 上次记录日结余；没有更早记录时为 0。
        has_anchor: 参与比较的日期中是否含手填结余锚点（锚点会人为跳变结余）。
        basis: 计算口径，``daily`` / ``today_net``。
        gap_days: ``today_net`` 口径下上次记录距今的天数（无更早记录时为 0）；
            ``daily`` 口径为 1。
    """

    delta: int
    latest_date: str
    previous_date: str
    latest_balance: int
    previous_balance: int
    has_anchor: bool = False
    basis: str = DELTA_BASIS_DAILY
    gap_days: int = 0

    @property
    def isTodayNet(self) -> bool:
        """
        是否按「今日净额」口径计算。

        Returns:
            ``True`` 表示 ``delta`` 是今日收支净额，不是结余差。
        """
        return self.basis == DELTA_BASIS_TODAY_NET

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
        delta: 日环比结果；「未记录」「数据异常」「无数据」时为 None。
        badge_text: 角标文案；无角标时为空串。除数字角标外，也用于
            「未记录」「数据异常」这类灰色状态。
        badge_tone: 角标配色档位，``up`` / ``down`` / ``flat``。
    """

    text: str
    tooltip: str
    delta: Optional[ResourceDailyDelta] = None
    badge_text: str = ""
    badge_tone: str = ""


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

        delta, note, badge_text, badge_tone = self._buildDailyDelta(series, time_source.today())
        return ResourceCardView(
            text, f"{tooltip}｜{note}", delta, badge_text, badge_tone
        )

    def _buildDailyDelta(
        self, series: List[Dict], today: date
    ) -> Tuple[Optional[ResourceDailyDelta], str, str, str]:
        """
        按「今天 vs 昨天」计算日环比角标。

        今天有记录时给出数字角标：
        - 昨天也有记录（连续）：``delta = 今日结余 - 昨日结余``（``daily`` 口径）；
        - 昨天断档 / 仅有今天一天：``delta = 今日收入 - 今日支出``（``today_net`` 口径， #37）。

        今天没有记录或最新记录晚于今天时不猜数字：
        - 今天还没有记录：灰色「未记录」，tooltip 保留最近一次日环比；
        - 最新记录晚于今天（脏数据）：灰色「数据异常」。

        Args:
            series: :meth:`getBalanceSeries` 的结果。
            today: 今天（由调用方传入，便于测试跨天）。

        Returns:
            ``(环比结果或 None, 追加到 tooltip 的说明文案, 角标文案, 角标配色)``。
        """
        latest = series[-1]
        latest_date = date.fromisoformat(latest[BALANCE_DATE])

        if latest_date > today:
            return (
                None,
                f"最新记录日期 {latest_date:%Y-%m-%d} 晚于今天，请检查数据",
                "数据异常",
                DELTA_TONE_FLAT,
            )

        if len(series) < 2:
            if latest_date == today:
                return self._buildTodayNetDelta(latest, None, today)
            return (
                None,
                f"今日未记录｜仅一天记录（{latest_date:%Y-%m-%d}）",
                "未记录",
                DELTA_TONE_FLAT,
            )

        previous = series[-2]
        previous_date = date.fromisoformat(previous[BALANCE_DATE])
        latest_balance = int(latest[BALANCE_VALUE])
        previous_balance = int(previous[BALANCE_VALUE])
        has_anchor = (
            latest.get(BALANCE_OVERRIDE) is not None
            or previous.get(BALANCE_OVERRIDE) is not None
        )
        anchor_note = "（含手填结余）" if has_anchor else ""
        consecutive = latest_date - previous_date == timedelta(days=1)

        if latest_date != today:
            if consecutive:
                last_delta = latest_balance - previous_balance
                if last_delta == 0:
                    last_text = (
                        f"持平（{latest_date:%Y-%m-%d}、{previous_date:%Y-%m-%d} "
                        f"均为 {formatExact(latest_balance)}）"
                    )
                else:
                    last_text = (
                        f"{last_delta:+d}（{previous_date:%Y-%m-%d} "
                        f"{formatExact(previous_balance)} → "
                        f"{latest_date:%Y-%m-%d} {formatExact(latest_balance)}）"
                    )
                note = (
                    f"今日未记录｜最近一次日环比 {latest_date:%Y-%m-%d} "
                    f"{last_text}{anchor_note}"
                )
            else:
                note = (
                    f"今日未记录｜最近记录 {latest_date:%Y-%m-%d}，"
                    f"与上一记录日 {previous_date:%Y-%m-%d} 不连续"
                )
            return None, note, "未记录", DELTA_TONE_FLAT

        if not consecutive:
            return self._buildTodayNetDelta(latest, previous, today)

        delta = ResourceDailyDelta(
            delta=latest_balance - previous_balance,
            latest_date=latest[BALANCE_DATE],
            previous_date=previous[BALANCE_DATE],
            latest_balance=latest_balance,
            previous_balance=previous_balance,
            has_anchor=has_anchor,
            basis=DELTA_BASIS_DAILY,
            gap_days=1,
        )

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
        return delta, note, delta.display_text, delta.tone

    def _buildTodayNetDelta(
        self, latest: Dict, previous: Optional[Dict], today: date
    ) -> Tuple[ResourceDailyDelta, str, str, str]:
        """
        昨日断档 / 仅有今天一天时，用「今日收入 − 今日支出」给出角标（#37 口径 A）。

        为什么不用「今日结余 − 上次记录结余」：断档多日时那个差额是多日累计，
        写进角标会被读成「一天的变化」（#25 的顾虑）；今日净额只描述今天进出的钱，
        金额可逐笔核对，缺口日的收支则明确排除。

        手填结余日（``balance_override`` 非空）不给出数字：锚点会让结余跳变，
        与当日净额不是同一回事，强行相减会误导。

        Args:
            latest: 结余链最后一行（今天）。
            previous: 上一次有记录的日期；仅有今天一天记录时为 None。
            today: 今天。

        Returns:
            ``(环比结果, tooltip 补充文案, 角标文案, 角标配色)``。
        """
        income = int(latest.get(BALANCE_INCOME) or 0)
        expense = int(latest.get(BALANCE_EXPENSE) or 0)
        latest_balance = int(latest[BALANCE_VALUE])
        today_is_anchor = latest.get(BALANCE_OVERRIDE) is not None

        if previous is None:
            previous_date = ""
            previous_balance = 0
            gap_days = 0
            head = "仅一天记录"
        else:
            previous_date = str(previous[BALANCE_DATE])
            previous_balance = int(previous[BALANCE_VALUE])
            gap_days = (today - date.fromisoformat(previous_date)).days
            head = f"今日有记录，昨日（{today - timedelta(days=1):%Y-%m-%d}）无记录"

        previous_is_anchor = previous is not None and previous.get(BALANCE_OVERRIDE) is not None
        net = 0 if today_is_anchor else income - expense

        delta = ResourceDailyDelta(
            delta=net,
            latest_date=latest[BALANCE_DATE],
            previous_date=previous_date,
            latest_balance=latest_balance,
            previous_balance=previous_balance,
            has_anchor=today_is_anchor or previous_is_anchor,
            basis=DELTA_BASIS_TODAY_NET,
            gap_days=gap_days,
        )

        amount = f"收入 {formatExact(income)} − 支出 {formatExact(expense)}"
        gap_span = self._formatGapSpan(previous_date, today)
        if gap_span:
            amount = f"{amount}，不含 {gap_span} 收支"

        if today_is_anchor:
            basis_text = f"今日为手填结余，不按净额比较（{amount}）"
        elif income == 0 and expense == 0:
            basis_text = "今日无收支"
        elif net == 0:
            # 有进有出但相抵时不能说「无收支」，否则与后面的收/支数字自相矛盾
            basis_text = f"今日净额 0（{amount}）"
        else:
            basis_text = f"按今日净额 {net:+d} 计算（{amount}）"

        parts = [head, basis_text]
        if previous is not None:
            parts.append(
                f"上次记录 {previous_date} 结余 {formatExact(previous_balance)} → "
                f"今日 {formatExact(latest_balance)}，跨 {gap_days} 天"
                f"{'（含手填结余）' if previous_is_anchor else ''}"
            )
        return delta, "；".join(parts), delta.display_text, delta.tone

    @staticmethod
    def _formatGapSpan(previous_date: str, today: date) -> str:
        """
        格式化断档区间（上次记录日的次日到今天前一天）。

        Args:
            previous_date: 上次记录日 ``yyyy-MM-dd``；空串表示没有更早记录。
            today: 今天。

        Returns:
            缺口的日期文案，如 ``2026-10-27～2026-10-29``；没有缺口时返回空串。
        """
        if not previous_date:
            return ""
        gap_start = date.fromisoformat(previous_date) + timedelta(days=1)
        gap_end = today - timedelta(days=1)
        if gap_start > gap_end:
            return ""
        if gap_start == gap_end:
            return f"{gap_start:%Y-%m-%d}"
        return f"{gap_start:%Y-%m-%d}～{gap_end:%Y-%m-%d}"

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
