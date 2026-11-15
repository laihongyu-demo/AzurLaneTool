"""
资源分析服务模块（#19）。

提供三块只读聚合：整体趋势（结余 + 月度收支）、来源 / 去向类目占比、
军事委托产出概览。口径见 ``docs/20261114_资源分析看板方案.md``。

与 :mod:`services.resource_service` 的分工：结余链仍由 ``ResourceService`` 计算，
本服务只在结果之上做月度与类目维度的聚合，避免两套结余逻辑。
"""

from typing import Dict, List, Optional, Tuple

from models.analysis_model import (
    BalancePoint,
    CategoryBreakdown,
    CategoryMonthly,
    CategoryShare,
    CommissionOverview,
    CommissionTotals,
    MonthlyPoint,
    TrendSeries,
)
from repositories.resource_repository import ResourceRepository
from services.resource_service import (
    BALANCE_DATE,
    BALANCE_EXPENSE,
    BALANCE_INCOME,
    BALANCE_MODE,
    BALANCE_OVERRIDE,
    BALANCE_VALUE,
    ResourceService,
)
from utils import time_source
from utils.constants import (
    ANALYSIS_TOP_CATEGORY_COUNT,
    MILITARY_COMMISSION_CATEGORY,
    RESOURCE_DETAIL_MODE_DETAIL,
    RESOURCE_DETAIL_MODE_SUMMARY_ONLY,
    RESOURCE_DIRECTION_INCOME,
    RESOURCE_DIRECTION_NAMES,
    RESOURCE_DISPLAY_NAMES,
)
from utils.db_schema import isMissingColumnError, isMissingTableError
from utils.exceptions import DatabaseError

# 堆叠柱里合并尾部类目的展示名
CATEGORY_OTHER_LABEL = "其他"

# 移动平均窗口与最少样本：样本过少时不画均线，避免半截线被当成趋势
ROLLING_AVERAGE_WINDOW = 12
ROLLING_AVERAGE_MIN_SAMPLES = 3


class ResourceAnalysisService:
    """
    资源分析服务（只读）。

    所有方法都返回 dataclass；缺表 / 缺列时降级为空结果，不把数据库异常抛到界面。
    """

    def __init__(
        self,
        resource_service: Optional[ResourceService] = None,
        resource_repository: Optional[ResourceRepository] = None,
    ):
        """
        初始化资源分析服务。

        Args:
            resource_service: 结余链服务，默认新建实例。
            resource_repository: 资源数据访问实例，默认新建实例。
        """
        self._resource_service = resource_service or ResourceService()
        self._repository = resource_repository or ResourceRepository()

    # ------------------------------------------------------------- 趋势

    def getTrend(self, resource_type: str, months: Optional[int] = None) -> TrendSeries:
        """
        计算结余曲线与月度收支。

        月度收支直接对结余链的日值求和：明细日取明细合计、汇总日取存储值，因此
        2024-10 之前的汇总期同样计入（与看板卡片同源）。

        Args:
            resource_type: ``cube`` 或 ``red_gem``。
            months: ``None`` 表示全部；否则为截至当月的自然月数（含当月）。
                指定区间时只保留区间内的结余点与月度收支，累计值按区间重算；
                结余本身仍是历史累计值，不做重设。

        Returns:
            趋势结果；表缺失或无数据时返回空结果（``balance_points`` 为空）。

        Raises:
            DatabaseError: 非缺表 / 缺列原因的查询失败。
        """
        display_name = RESOURCE_DISPLAY_NAMES.get(resource_type, resource_type)
        range_label = self._rangeLabel(months)
        try:
            series = self._resource_service.getBalanceSeries(resource_type)
        except DatabaseError as e:
            if isMissingTableError(e) or isMissingColumnError(e):
                return TrendSeries(
                    resource_type, display_name, range_label=range_label
                )
            raise

        points: List[BalancePoint] = []
        monthly: Dict[str, MonthlyPoint] = {}

        for row in series:
            income = int(row.get(BALANCE_INCOME) or 0)
            expense = int(row.get(BALANCE_EXPENSE) or 0)
            record_date = str(row[BALANCE_DATE])
            mode = str(row.get(BALANCE_MODE) or "")
            is_anchor = row.get(BALANCE_OVERRIDE) is not None

            points.append(
                BalancePoint(
                    record_date=record_date,
                    balance=int(row.get(BALANCE_VALUE) or 0),
                    income=income,
                    expense=expense,
                    detail_mode=mode,
                    is_anchor=is_anchor,
                )
            )

            month = record_date[:7]
            bucket = monthly.setdefault(month, MonthlyPoint(month))
            bucket.income += income
            bucket.expense += expense

        if not points:
            return TrendSeries(resource_type, display_name, range_label=range_label)

        all_months = sorted(monthly)
        start_month, end_month, range_label = self._resolveMonthRange(all_months, months)
        if months is not None and start_month:
            points = [point for point in points if point.record_date[:7] >= start_month]
            monthly = {month: value for month, value in monthly.items() if month >= start_month}

        summary_days = sum(
            1 for point in points if point.detail_mode == RESOURCE_DETAIL_MODE_SUMMARY_ONLY
        )
        return TrendSeries(
            resource_type=resource_type,
            display_name=display_name,
            balance_points=points,
            monthly_points=sorted(monthly.values(), key=lambda item: item.month),
            total_income=sum(point.income for point in points),
            total_expense=sum(point.expense for point in points),
            anchor_count=sum(1 for point in points if point.is_anchor),
            summary_days=summary_days,
            detail_days=len(points) - summary_days,
            range_label=range_label,
            range_start=start_month,
            range_end=end_month,
        )

    # ------------------------------------------------------------- 类目占比

    def getCategoryBreakdown(self, resource_type: str, direction: str) -> CategoryBreakdown:
        """
        计算来源 / 去向的类目占比与月度堆叠矩阵。

        占比分母只取**明细期**：汇总日只有日合计、无法拆分到类目，这部分金额
        通过 ``summary_income`` / ``summary_expense`` 单列，由界面显式标注。

        Args:
            resource_type: ``cube`` 或 ``red_gem``。
            direction: ``income``（来源）或 ``expense``（去向）。

        Returns:
            类目占比结果；无明细或表缺失时 ``shares`` 为空。
        """
        display_name = RESOURCE_DISPLAY_NAMES.get(resource_type, resource_type)
        direction_name = RESOURCE_DIRECTION_NAMES.get(direction, direction)
        empty = CategoryBreakdown(resource_type, direction, display_name, direction_name)

        try:
            series = self._resource_service.getBalanceSeries(resource_type)
            rows = self._repository.findMonthlyCategoryTotals(resource_type, direction)
            known_names = {
                category.name
                for category in self._repository.findCategories(
                    resource_type, direction, include_inactive=True
                )
            }
        except DatabaseError as e:
            if isMissingTableError(e) or isMissingColumnError(e):
                return empty
            raise

        detail_rows = [row for row in series if row.get(BALANCE_MODE) == RESOURCE_DETAIL_MODE_DETAIL]
        summary_rows = [
            row for row in series if row.get(BALANCE_MODE) == RESOURCE_DETAIL_MODE_SUMMARY_ONLY
        ]

        detail_start = str(detail_rows[0][BALANCE_DATE]) if detail_rows else ""
        detail_end = str(detail_rows[-1][BALANCE_DATE]) if detail_rows else ""
        summary_income = sum(int(row.get(BALANCE_INCOME) or 0) for row in summary_rows)
        summary_expense = sum(int(row.get(BALANCE_EXPENSE) or 0) for row in summary_rows)

        by_category: Dict[str, List[int]] = {}
        by_month: Dict[str, Dict[str, int]] = {}
        months: List[str] = []

        for row in rows:
            name = str(row["category"])
            amount = int(row["amount"])
            count = int(row["count"])
            month = str(row["month"])

            bucket = by_category.setdefault(name, [0, 0])
            bucket[0] += amount
            bucket[1] += count

            month_bucket = by_month.setdefault(month, {})
            month_bucket[name] = month_bucket.get(name, 0) + amount
            if month not in months:
                months.append(month)

        total_amount = sum(value[0] for value in by_category.values())
        total_count = sum(value[1] for value in by_category.values())

        shares = [
            CategoryShare(
                name=name,
                amount=amount,
                count=count,
                share=(amount / total_amount) if total_amount else 0.0,
            )
            for name, (amount, count) in by_category.items()
        ]
        shares.sort(key=lambda item: (-item.amount, item.name))

        return CategoryBreakdown(
            resource_type=resource_type,
            direction=direction,
            display_name=display_name,
            direction_name=direction_name,
            shares=shares,
            monthly=self._buildCategoryMonthly(shares, by_month, sorted(months)),
            detail_start=detail_start,
            detail_end=detail_end,
            # 分母取类目合计而不是日汇总链：占比图必须自洽（各扇区之和 = 分母）
            detail_total=total_amount,
            summary_days=len(summary_rows),
            summary_income=summary_income,
            summary_expense=summary_expense,
            unmapped_names=sorted(name for name in by_category if name not in known_names),
            total_count=total_count,
        )

    @staticmethod
    def _buildCategoryMonthly(
        shares: List[CategoryShare],
        by_month: Dict[str, Dict[str, int]],
        months: List[str],
    ) -> CategoryMonthly:
        """
        构造月度 × 类目矩阵：金额前 N 的类目单独成行，其余合并为「其他」。

        Args:
            shares: 已按金额降序排列的类目占比。
            by_month: 月份 → 类目 → 金额。
            months: 月份升序列表。

        Returns:
            月度矩阵；无数据时为空矩阵。
        """
        if not months:
            return CategoryMonthly()

        top_names = [item.name for item in shares[:ANALYSIS_TOP_CATEGORY_COUNT]]
        other_names = [item.name for item in shares[ANALYSIS_TOP_CATEGORY_COUNT:]]

        values: List[List[int]] = []
        for name in top_names:
            values.append([by_month.get(month, {}).get(name, 0) for month in months])
        if other_names:
            values.append(
                [
                    sum(by_month.get(month, {}).get(name, 0) for name in other_names)
                    for month in months
                ]
            )

        categories = list(top_names)
        if other_names:
            categories.append(CATEGORY_OTHER_LABEL)

        month_totals = [sum(by_month.get(month, {}).values()) for month in months]
        return CategoryMonthly(
            months=months,
            categories=categories,
            values=values,
            month_totals=month_totals,
        )

    # ------------------------------------------------------------- 军事委托

    def getCommissionOverview(
        self, resource_type: str, months: Optional[int] = None
    ) -> CommissionOverview:
        """
        计算军事委托产出概览。

        Args:
            resource_type: ``cube`` 或 ``red_gem``。
            months: ``None`` 表示全部；否则为截至当月的自然月数（含当月）。

        Returns:
            概览结果；无记录时 ``totals.count`` 为 0、``months`` 为空。
        """
        display_name = RESOURCE_DISPLAY_NAMES.get(resource_type, resource_type)
        empty = CommissionOverview(
            resource_type=resource_type,
            display_name=display_name,
            range_label=self._rangeLabel(months),
        )

        try:
            rows = self._repository.findMonthlyCategoryTotals(
                resource_type, RESOURCE_DIRECTION_INCOME, MILITARY_COMMISSION_CATEGORY
            )
        except DatabaseError as e:
            if isMissingTableError(e) or isMissingColumnError(e):
                return empty
            raise

        if not rows:
            return empty

        data_months = sorted({str(row["month"]) for row in rows})
        start_month, end_month, range_label = self._resolveMonthRange(data_months, months)
        month_list = self._monthRange(start_month, end_month)

        amount_by_month = {str(row["month"]): int(row["amount"]) for row in rows}
        count_by_month = {str(row["month"]): int(row["count"]) for row in rows}
        amounts: List[Optional[int]] = [amount_by_month.get(month) for month in month_list]
        counts: List[int] = [count_by_month.get(month, 0) for month in month_list]

        try:
            distribution = self._repository.findCategoryAmountCounts(
                resource_type,
                RESOURCE_DIRECTION_INCOME,
                MILITARY_COMMISSION_CATEGORY,
                start_month,
                end_month,
            )
            active_days = self._repository.countCategoryActiveDays(
                resource_type,
                RESOURCE_DIRECTION_INCOME,
                MILITARY_COMMISSION_CATEGORY,
                start_month,
                end_month,
            )
        except DatabaseError as e:
            if isMissingTableError(e) or isMissingColumnError(e):
                distribution, active_days = [], 0
            else:
                raise

        total_amount = sum(amount for amount in amounts if amount is not None)
        total_count = sum(counts)
        max_amount = max((amount for amount, _ in distribution), default=0)
        totals = CommissionTotals(
            amount=total_amount,
            count=total_count,
            max_amount=max_amount,
            active_days=active_days,
            mean=(total_amount / total_count) if total_count else 0.0,
            daily_mean=(total_amount / active_days) if active_days else 0.0,
        )

        return CommissionOverview(
            resource_type=resource_type,
            display_name=display_name,
            months=month_list,
            amounts=amounts,
            counts=counts,
            rolling_average=self._rollingAverage(amounts),
            amount_distribution=list(distribution),
            totals=totals,
            range_label=range_label,
            range_start=start_month,
            range_end=end_month,
        )

    @staticmethod
    def _rollingAverage(
        values: List[Optional[int]],
        window: int = ROLLING_AVERAGE_WINDOW,
        min_samples: int = ROLLING_AVERAGE_MIN_SAMPLES,
    ) -> List[Optional[float]]:
        """
        计算月度值的尾随移动平均。

        当前月无记录时输出 None（不拿前几个月的均值冒充本月）；窗口内有效值少于
        ``min_samples`` 时同样输出 None，避免开头几个月的均线误导。

        Args:
            values: 月度值；None 表示无记录。
            window: 窗口长度（月）。
            min_samples: 窗口内最少有效值。

        Returns:
            与 ``values`` 等长的均值列表。
        """
        result: List[Optional[float]] = []
        for index, value in enumerate(values):
            if value is None:
                result.append(None)
                continue
            start = max(0, index - window + 1)
            window_values = [item for item in values[start : index + 1] if item is not None]
            if len(window_values) < min_samples:
                result.append(None)
                continue
            result.append(sum(window_values) / len(window_values))
        return result

    @staticmethod
    def _shiftMonth(month: str, delta: int) -> str:
        """
        月份加减。

        Args:
            month: ``yyyy-MM``。
            delta: 偏移月数（可为负）。

        Returns:
            偏移后的月份 ``yyyy-MM``。
        """
        year, mon = int(month[:4]), int(month[5:7])
        index = year * 12 + (mon - 1) + delta
        return f"{index // 12:04d}-{index % 12 + 1:02d}"

    @classmethod
    def _monthRange(cls, start_month: str, end_month: str) -> List[str]:
        """
        生成连续月份列表（含端点）。

        Args:
            start_month: 起始月 ``yyyy-MM``。
            end_month: 结束月 ``yyyy-MM``。

        Returns:
            月份升序列表；区间非法时返回空列表。
        """
        if not start_month or not end_month or start_month > end_month:
            return []
        months: List[str] = []
        cursor = start_month
        while cursor <= end_month:
            months.append(cursor)
            cursor = cls._shiftMonth(cursor, 1)
        return months

    def _resolveMonthRange(
        self, data_months: List[str], months: Optional[int]
    ) -> Tuple[str, str, str]:
        """
        解析「全部 / 近 N 个月」的起止月。

        近一年以**今天所在月**为末月，起点不早于数据起点；数据整体早于窗口时
        退回数据区间，不展示一片空白的月份。

        Args:
            data_months: 有数据的月份（升序）。
            months: 窗口月数；None 表示全部。

        Returns:
            ``(起始月, 结束月, 区间文案)``。
        """
        data_start, data_end = data_months[0], data_months[-1]
        if months is None or months <= 0:
            return data_start, data_end, "全部"

        end_month = time_source.today().strftime("%Y-%m")
        start_month = max(self._shiftMonth(end_month, -(months - 1)), data_start)
        if start_month > end_month:
            return data_start, data_end, f"近 {months} 个月"
        return start_month, end_month, f"近 {months} 个月"

    @staticmethod
    def _rangeLabel(months: Optional[int]) -> str:
        """
        区间文案（无数据时也要显示，便于界面说明）。

        Args:
            months: 窗口月数；None 表示全部。

        Returns:
            ``全部`` 或 ``近 N 个月``。
        """
        if months is None or months <= 0:
            return "全部"
        return f"近 {months} 个月"
