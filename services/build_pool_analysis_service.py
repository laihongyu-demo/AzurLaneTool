"""
大建详情与毕业预测服务（#19）。

口径（见 ``docs/20261114_资源分析看板方案.md``）：

- 样本只含**状态为「毕业」且建造次数非空**的活动池；「缺 / 进行中 / 未标记」不进统计；
- 建造次数复用 :class:`services.event_record_service.EventRecordView.build_count`
  （有明细时 = 关联魔方 ÷ 单耗 + 券抽；无明细时用手填值），不另立口径；
- 分位数用线性插值（与 numpy 默认一致），毕业预测是**经验参考**，不是概率承诺。
"""

from typing import Dict, List, Optional, Sequence, Tuple

from models.analysis_model import (
    BudgetLevel,
    BuildPoolAnalysis,
    BuildPoolGroup,
    BuildPoolPoint,
    ProgressPrediction,
)
from services.event_record_service import EventRecordService, EventRecordView
from utils.constants import (
    ANALYSIS_BUDGET_LABELS,
    ANALYSIS_BUDGET_PERCENTILES,
    ANALYSIS_QUANTILES,
    ANALYSIS_ROLLING_WINDOW,
    BUILD_SCOPE_ALL,
    BUILD_SCOPE_COPY,
    BUILD_SCOPE_EXCLUDE_WISH,
    BUILD_SCOPE_WISH,
    EVENT_DEFAULT_BUILD_COST,
    EVENT_STATUS_GRADUATED,
    EVENT_TYPE_GROUP_OTHER,
    EVENT_TYPE_KEYWORD_COPY,
    EVENT_TYPE_KEYWORD_WISH,
)
from utils.db_schema import isMissingColumnError, isMissingTableError
from utils.exceptions import DatabaseError

# 类型分组展示顺序：复刻 → 祈愿 → 首次活动（判定时先复刻，避免「复刻祈愿」重复归类）
TYPE_GROUP_ORDER = (EVENT_TYPE_KEYWORD_COPY, EVENT_TYPE_KEYWORD_WISH, EVENT_TYPE_GROUP_OTHER)


def percentile(values: Sequence[float], fraction: float) -> float:
    """
    线性插值分位数。

    用线性插值而不是「取第 k 个」：样本量 61 时取整数位会让 P90 在相邻两个值之间跳变，
    而预测预算需要稳定、可复现的数字。

    Args:
        values: 已升序排列的数值序列；空序列返回 0.0。
        fraction: 分位（0~1，超出范围自动截断）。

    Returns:
        分位数值。
    """
    if not values:
        return 0.0
    if len(values) == 1:
        return float(values[0])

    clamped = min(max(fraction, 0.0), 1.0)
    position = (len(values) - 1) * clamped
    low = int(position)
    high = min(low + 1, len(values) - 1)
    weight = position - low
    return float(values[low] + (values[high] - values[low]) * weight)


class BuildPoolAnalysisService:
    """
    大建详情分析服务（只读）。

    只依赖 :class:`EventRecordService`，不写 SQL、不碰资源明细表。
    """

    def __init__(self, event_service: Optional[EventRecordService] = None):
        """
        初始化大建分析服务。

        Args:
            event_service: 活动记录服务，默认新建实例。
        """
        self._event_service = event_service or EventRecordService()

    def getAnalysis(self, scope: str = BUILD_SCOPE_ALL) -> BuildPoolAnalysis:
        """
        汇总毕业池的建造次数分布。

        Args:
            scope: 样本范围，取值为 ``BUILD_SCOPES`` 之一。

        Returns:
            分析结果；无样本时 ``sample_size`` 为 0、各列表为空。
        """
        try:
            views = self._event_service.listRecords()
        except DatabaseError as e:
            if isMissingTableError(e) or isMissingColumnError(e):
                return BuildPoolAnalysis(scope=scope)
            raise

        graduated = [
            view
            for view in views
            if self._isGraduated(view) and view.build_count is not None
        ]
        excluded_count = len(views) - len(graduated)

        points = self._filterByScope([self._toPoint(view) for view in graduated], scope)
        if not points:
            return BuildPoolAnalysis(scope=scope, excluded_count=excluded_count)

        # 活动记录服务按日期倒序返回，图表与滚动中位数都要求时间升序
        points.sort(key=lambda point: (point.event_date, point.build_count))
        counts = [point.build_count for point in points]
        sorted_counts = sorted(counts)
        sample_size = len(counts)

        return BuildPoolAnalysis(
            points=points,
            sample_size=sample_size,
            total=sum(counts),
            mean=sum(counts) / sample_size,
            median=percentile(sorted_counts, 0.5),
            quantiles={step: percentile(sorted_counts, step) for step in ANALYSIS_QUANTILES},
            by_year=self._groupByYear(points),
            by_type=self._groupByType(points),
            rolling_median=self._rollingMedian(counts, ANALYSIS_ROLLING_WINDOW),
            survival=self._survival(sorted_counts),
            max_count=max(counts),
            excluded_count=excluded_count,
            scope=scope,
        )

    def buildBudget(
        self, analysis: BuildPoolAnalysis, build_cost: int = EVENT_DEFAULT_BUILD_COST
    ) -> List[BudgetLevel]:
        """
        按历史分位给出新池的预算档位。

        Args:
            analysis: :meth:`getAnalysis` 的结果。
            build_cost: 单次消耗魔方数（1 或 2）。

        Returns:
            中位 / 偏高 / 极端三档；样本为空时返回空列表。
        """
        if not analysis.hasData:
            return []
        levels: List[BudgetLevel] = []
        for step in ANALYSIS_BUDGET_PERCENTILES:
            count = analysis.quantiles.get(step)
            if count is None:
                continue
            levels.append(
                BudgetLevel(
                    label=ANALYSIS_BUDGET_LABELS.get(step, f"P{int(step * 100)}"),
                    percentile=step,
                    build_count=count,
                    cube_cost=int(round(count * build_cost)),
                )
            )
        return levels

    def predictProgress(
        self,
        analysis: BuildPoolAnalysis,
        current_count: int,
        build_cost: int = EVENT_DEFAULT_BUILD_COST,
    ) -> ProgressPrediction:
        """
        按经验分布对照当前池的进度。

        分位排名用「小于当前次数的样本 + 0.5×相等样本」除以样本量，相等时取中位位置，
        避免并列值让排名在 0/1 之间跳。

        Args:
            analysis: :meth:`getAnalysis` 的结果。
            current_count: 当前已抽次数（负数按 0 处理）。
            build_cost: 单次消耗魔方数。

        Returns:
            对照结果；无样本时只回填 ``current_count``。
        """
        counts = [point.build_count for point in analysis.points]
        current = max(0, int(current_count))
        sample_size = len(counts)
        if not sample_size:
            return ProgressPrediction(current_count=current)

        below = sum(1 for value in counts if value < current)
        equal = sum(1 for value in counts if value == current)
        rank = (below + 0.5 * equal) / sample_size

        remaining = sorted(value - current for value in counts if value > current)
        remaining_median = percentile(remaining, 0.5) if remaining else None
        remaining_p75 = percentile(remaining, 0.75) if remaining else None

        return ProgressPrediction(
            current_count=current,
            sample_size=sample_size,
            percentile_rank=rank,
            remaining_sample_size=len(remaining),
            remaining_median=remaining_median,
            remaining_p75=remaining_p75,
            cube_remaining_median=(
                int(round(remaining_median * build_cost))
                if remaining_median is not None
                else None
            ),
            cube_remaining_p75=(
                int(round(remaining_p75 * build_cost)) if remaining_p75 is not None else None
            ),
            exceeded_max=current >= analysis.max_count,
            max_count=analysis.max_count,
        )

    # ------------------------------------------------------------- 内部

    @staticmethod
    def _isGraduated(view: EventRecordView) -> bool:
        """
        判定是否毕业池。

        状态是自由文本，只认精确的「毕业」；写成「已毕业」等自定义状态不会被计入，
        这是页面「仅统计状态=毕业」提示存在的原因。

        Args:
            view: 活动记录展示行。

        Returns:
            状态（去空格后）等于「毕业」时返回 True。
        """
        return (view.record.status or "").strip() == EVENT_STATUS_GRADUATED

    @staticmethod
    def _toPoint(view: EventRecordView) -> BuildPoolPoint:
        """
        把活动记录展示行转成图表点。

        Args:
            view: 活动记录展示行。

        Returns:
            毕业池展示点。
        """
        record = view.record
        return BuildPoolPoint(
            event_date=record.event_date,
            event_type=record.event_type,
            name=record.displayName,
            build_count=int(view.build_count or 0),
            build_cost=int(record.build_cost or EVENT_DEFAULT_BUILD_COST),
            derived=bool(view.derived),
        )

    @staticmethod
    def _filterByScope(points: List[BuildPoolPoint], scope: str) -> List[BuildPoolPoint]:
        """
        按样本范围过滤。

        Args:
            points: 全部毕业池。
            scope: ``BUILD_SCOPES`` 之一；未知值按「全部」处理。

        Returns:
            过滤后的点，保持原顺序（按活动日期升序）。
        """
        if scope == BUILD_SCOPE_COPY:
            return [point for point in points if EVENT_TYPE_KEYWORD_COPY in point.event_type]
        if scope == BUILD_SCOPE_WISH:
            return [point for point in points if EVENT_TYPE_KEYWORD_WISH in point.event_type]
        if scope == BUILD_SCOPE_EXCLUDE_WISH:
            return [
                point for point in points if EVENT_TYPE_KEYWORD_WISH not in point.event_type
            ]
        return list(points)

    @staticmethod
    def _typeGroup(event_type: str) -> str:
        """
        类型分组：复刻 → 祈愿 → 首次活动。

        Args:
            event_type: 活动类型文本。

        Returns:
            分组名。
        """
        if EVENT_TYPE_KEYWORD_COPY in event_type:
            return EVENT_TYPE_KEYWORD_COPY
        if EVENT_TYPE_KEYWORD_WISH in event_type:
            return EVENT_TYPE_KEYWORD_WISH
        return EVENT_TYPE_GROUP_OTHER

    def _groupByYear(self, points: List[BuildPoolPoint]) -> List[BuildPoolGroup]:
        """
        按年份分组统计。

        Args:
            points: 毕业池。

        Returns:
            年份升序的分组统计；无样本时为空列表。
        """
        buckets: Dict[str, List[int]] = {}
        for point in points:
            buckets.setdefault(point.event_date[:4], []).append(point.build_count)
        return [self._buildGroup(name, buckets[name]) for name in sorted(buckets)]

    def _groupByType(self, points: List[BuildPoolPoint]) -> List[BuildPoolGroup]:
        """
        按类型分组统计（只输出存在的分组）。

        Args:
            points: 毕业池。

        Returns:
            按 :data:`TYPE_GROUP_ORDER` 排列的分组统计。
        """
        buckets: Dict[str, List[int]] = {}
        for point in points:
            buckets.setdefault(self._typeGroup(point.event_type), []).append(point.build_count)
        return [
            self._buildGroup(name, buckets[name])
            for name in TYPE_GROUP_ORDER
            if name in buckets
        ]

    @staticmethod
    def _buildGroup(name: str, counts: List[int]) -> BuildPoolGroup:
        """
        构造分组统计。

        Args:
            name: 分组名。
            counts: 该组次数。

        Returns:
            分组统计。
        """
        ordered = sorted(counts)
        return BuildPoolGroup(
            name=name,
            sample_size=len(ordered),
            median=percentile(ordered, 0.5),
            mean=sum(ordered) / len(ordered),
        )

    @staticmethod
    def _rollingMedian(counts: List[int], window: int) -> List[float]:
        """
        尾随滚动中位数（含当前池）。

        开头几个池的窗口不足 ``window``，按已有样本计算，并在图上说明「近 N 池」。

        Args:
            counts: 按日期升序的次数。
            window: 窗口长度。

        Returns:
            与 ``counts`` 等长的中位数序列。
        """
        result: List[float] = []
        for index in range(len(counts)):
            start = max(0, index - window + 1)
            result.append(percentile(sorted(counts[start : index + 1]), 0.5))
        return result

    @staticmethod
    def _survival(sorted_counts: List[int]) -> List[Tuple[int, float]]:
        """
        经验生存曲线 ``P(T > n)``。

        以 ``(0, 1.0)`` 开头，便于用阶梯线从 0 次开始画；``n`` 取样本中的不同次数。

        Args:
            sorted_counts: 升序次数。

        Returns:
            ``(n, 生存概率)`` 列表。
        """
        sample_size = len(sorted_counts)
        if not sample_size:
            return []
        points = [(0, 1.0)]
        for value in sorted(set(sorted_counts)):
            surviving = sum(1 for item in sorted_counts if item > value)
            points.append((int(value), surviving / sample_size))
        return points
