"""
数据分析模型模块（#19）。

只承载聚合结果，不含数据库访问与 Qt 类型；字段口径见
``docs/20261114_资源分析看板方案.md``。
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple


@dataclass
class BalancePoint:
    """
    逐日结余点（结余链的一行）。

    Attributes:
        record_date: 日期 ``yyyy-MM-dd``。
        balance: 当日结余。
        income: 当日收入（明细日取明细合计，汇总日取存储值）。
        expense: 当日支出。
        detail_mode: ``detail`` / ``summary_only``。
        is_anchor: 当日是否手填结余（锚点会重设累计值，曲线会跳变）。
    """

    record_date: str
    balance: int
    income: int
    expense: int
    detail_mode: str
    is_anchor: bool


@dataclass
class MonthlyPoint:
    """
    月度收支点。

    Attributes:
        month: 月份 ``yyyy-MM``。
        income: 当月收入合计。
        expense: 当月支出合计。
    """

    month: str
    income: int = 0
    expense: int = 0

    @property
    def net(self) -> int:
        """
        当月净额。

        Returns:
            ``income - expense``。
        """
        return self.income - self.expense


@dataclass
class TrendSeries:
    """
    整体趋势数据（结余 + 月度收支）。

    Attributes:
        resource_type: ``cube`` / ``red_gem``。
        display_name: 资源展示名。
        balance_points: 按日期升序的逐日结余。
        monthly_points: 按月份升序的月度收支（只含有记录的月份）。
        total_income: 累计收入。
        total_expense: 累计支出。
        anchor_count: 手填结余天数。
        summary_days: 汇总日（无明细）天数。
        detail_days: 明细日天数。
        range_label: 区间文案（全部 / 近 12 个月）。
        range_start: 区间起始月 ``yyyy-MM``。
        range_end: 区间结束月 ``yyyy-MM``。
    """

    resource_type: str
    display_name: str
    balance_points: List[BalancePoint] = field(default_factory=list)
    monthly_points: List[MonthlyPoint] = field(default_factory=list)
    total_income: int = 0
    total_expense: int = 0
    anchor_count: int = 0
    summary_days: int = 0
    detail_days: int = 0
    range_label: str = ""
    range_start: str = ""
    range_end: str = ""

    @property
    def latestBalance(self) -> int:
        """
        最新结余。

        Returns:
            最后一个结余点的值；无数据时为 0。
        """
        return self.balance_points[-1].balance if self.balance_points else 0

    @property
    def netGrowth(self) -> int:
        """
        累计净增长（收入 − 支出）。

        Returns:
            净增长值。
        """
        return self.total_income - self.total_expense


@dataclass
class CategoryShare:
    """
    单个类目的总额与占比。

    Attributes:
        name: 类目名（原始 ``category``）。
        amount: 金额合计。
        count: 笔数。
        share: 占比（0~1，分母为明细期内该方向的明细合计）。
    """

    name: str
    amount: int
    count: int
    share: float


@dataclass
class CategoryMonthly:
    """
    月度 × 类目矩阵（用于堆叠柱）。

    Attributes:
        months: 月份升序，只含有明细的月份。
        categories: 展示顺序（Top N + 其他）。
        values: 与 ``categories`` 对齐的二维数组，``values[i][j]`` 是第 j 个月第 i 个类目的金额。
        month_totals: 每月明细合计。
    """

    months: List[str] = field(default_factory=list)
    categories: List[str] = field(default_factory=list)
    values: List[List[int]] = field(default_factory=list)
    month_totals: List[int] = field(default_factory=list)


@dataclass
class CategoryBreakdown:
    """
    来源 / 去向类目占比结果。

    Attributes:
        resource_type: ``cube`` / ``red_gem``。
        direction: ``income`` / ``expense``。
        display_name: 资源展示名。
        direction_name: 方向展示名（来源 / 去向）。
        shares: 类目占比，按金额降序。
        monthly: 月度堆叠矩阵。
        detail_start: 明细期起始日期；无明细时为空串。
        detail_end: 明细期结束日期。
        detail_total: 明细期该方向合计（占比分母）。
        summary_days: 汇总日天数（该类目图无法覆盖的部分）。
        summary_income: 汇总日收入合计。
        summary_expense: 汇总日支出合计。
        unmapped_names: 明细里出现、但类型字典没有的类目名。
        total_count: 明细笔数。
    """

    resource_type: str
    direction: str
    display_name: str
    direction_name: str
    shares: List[CategoryShare] = field(default_factory=list)
    monthly: CategoryMonthly = field(default_factory=CategoryMonthly)
    detail_start: str = ""
    detail_end: str = ""
    detail_total: int = 0
    summary_days: int = 0
    summary_income: int = 0
    summary_expense: int = 0
    unmapped_names: List[str] = field(default_factory=list)
    total_count: int = 0

    @property
    def hasData(self) -> bool:
        """
        是否有可展示的类目数据。

        Returns:
            有明细时返回 True。
        """
        return bool(self.shares)


@dataclass
class CommissionTotals:
    """
    军事委托产出汇总。

    Attributes:
        amount: 数量合计。
        count: 笔数。
        max_amount: 最高单笔。
        active_days: 有记录的天数（日均分母）。
        mean: 单笔均值。
        daily_mean: 有记录日的日均产出。
    """

    amount: int = 0
    count: int = 0
    max_amount: int = 0
    active_days: int = 0
    mean: float = 0.0
    daily_mean: float = 0.0


@dataclass
class CommissionOverview:
    """
    军事委托产出概览。

    Attributes:
        resource_type: ``cube`` / ``red_gem``。
        display_name: 资源展示名。
        months: 区间内连续月份 ``yyyy-MM``。
        amounts: 与 ``months`` 对齐的月度产出；``None`` 表示该月无记录（不是 0）。
        counts: 与 ``months`` 对齐的月度笔数。
        rolling_average: 12 个月移动平均；样本不足时为 None。
        amount_distribution: ``(单笔金额, 笔数)``，按金额升序。
        totals: 区间汇总。
        range_label: 区间展示文案（全部 / 近 12 个月）。
        range_start: 区间起始月。
        range_end: 区间结束月。
    """

    resource_type: str
    display_name: str
    months: List[str] = field(default_factory=list)
    amounts: List[Optional[int]] = field(default_factory=list)
    counts: List[int] = field(default_factory=list)
    rolling_average: List[Optional[float]] = field(default_factory=list)
    amount_distribution: List[Tuple[int, int]] = field(default_factory=list)
    totals: CommissionTotals = field(default_factory=CommissionTotals)
    range_label: str = ""
    range_start: str = ""
    range_end: str = ""

    @property
    def hasData(self) -> bool:
        """
        是否有委托记录。

        Returns:
            笔数大于 0 时返回 True。
        """
        return self.totals.count > 0


@dataclass
class BuildPoolPoint:
    """
    一个毕业池的展示点。

    Attributes:
        event_date: 活动开始日期 ``yyyy-MM-dd``。
        event_type: 活动类型。
        name: 活动名称。
        build_count: 有效建造次数（派生值或手填值）。
        build_cost: 单次消耗魔方数。
        derived: 是否由关联明细自动折算。
    """

    event_date: str
    event_type: str
    name: str
    build_count: int
    build_cost: int
    derived: bool


@dataclass
class BuildPoolGroup:
    """
    分组统计（按年份 / 按类型）。

    Attributes:
        name: 分组名（``2026`` / ``祈愿``）。
        sample_size: 样本量。
        median: 中位数。
        mean: 均值。
    """

    name: str
    sample_size: int
    median: float
    mean: float


@dataclass
class BuildPoolAnalysis:
    """
    大建详情分析结果（只含毕业池）。

    Attributes:
        points: 毕业池展示点，按活动日期升序。
        sample_size: 样本量。
        total: 次数合计。
        mean: 均值。
        median: 中位数。
        quantiles: 分位档位 → 次数（线性插值）。
        by_year: 按年份分组统计。
        by_type: 按类型分组统计（祈愿 / 复刻 / 其它）。
        rolling_median: 与 ``points`` 对齐的滚动中位数（尾随窗口）。
        survival: 经验生存曲线 ``(n, P(T > n))``，以 ``(0, 1.0)`` 开头。
        max_count: 样本最大次数。
        excluded_count: 未计入统计的池数（未毕业 / 无次数）。
        scope: 样本范围标识。
    """

    points: List[BuildPoolPoint] = field(default_factory=list)
    sample_size: int = 0
    total: int = 0
    mean: float = 0.0
    median: float = 0.0
    quantiles: Dict[float, float] = field(default_factory=dict)
    by_year: List[BuildPoolGroup] = field(default_factory=list)
    by_type: List[BuildPoolGroup] = field(default_factory=list)
    rolling_median: List[float] = field(default_factory=list)
    survival: List[Tuple[int, float]] = field(default_factory=list)
    max_count: int = 0
    excluded_count: int = 0
    scope: str = ""

    @property
    def hasData(self) -> bool:
        """
        是否有样本。

        Returns:
            样本量大于 0 时返回 True。
        """
        return self.sample_size > 0


@dataclass
class BudgetLevel:
    """
    新池预算档位。

    Attributes:
        label: 档位文案（中位 / 偏高 / 极端）。
        percentile: 分位（0~1）。
        build_count: 预计毕业次数。
        cube_cost: 折算魔方（次数 × 单耗，四舍五入）。
    """

    label: str
    percentile: float
    build_count: float
    cube_cost: int


@dataclass
class ProgressPrediction:
    """
    当前池进度对照（经验分布，不是概率承诺）。

    Attributes:
        current_count: 已抽次数。
        sample_size: 样本量。
        percentile_rank: 当前次数在样本中的分位排名（0~1）。
        remaining_sample_size: 次数高于当前次数的样本数。
        remaining_median: 剩余次数的中位数；样本为空时为 None。
        remaining_p75: 剩余次数的 P75；样本为空时为 None。
        cube_remaining_median: 剩余中位数折算魔方。
        cube_remaining_p75: 剩余 P75 折算魔方。
        exceeded_max: 当前次数是否已达到或超过样本最大值。
        max_count: 样本最大次数。
    """

    current_count: int = 0
    sample_size: int = 0
    percentile_rank: float = 0.0
    remaining_sample_size: int = 0
    remaining_median: Optional[float] = None
    remaining_p75: Optional[float] = None
    cube_remaining_median: Optional[int] = None
    cube_remaining_p75: Optional[int] = None
    exceeded_max: bool = False
    max_count: int = 0
