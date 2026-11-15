"""
大建详情图（#19）。

- :class:`BuildPoolTrendCanvas`：左=每次活动的毕业次数与近 N 池滚动中位数，
  右=次数分布直方图与 P25 / P50 / P90 标线；
- :class:`BuildPoolCompareCanvas`：左=按类型的中位数（标样本量），
  右=经验生存曲线（可叠加当前池的已抽次数）。

两块都支持悬停读数；散点只标最高 / 最新两个突出点。
"""

from datetime import date
from typing import List, Optional

from matplotlib import dates as mdates
from matplotlib.dates import AutoDateLocator, DateFormatter
from matplotlib.figure import Figure

from models.analysis_model import BuildPoolAnalysis
from utils.chart_style import (
    CHART_ANCHOR_COLOR,
    CHART_EXPENSE_COLOR,
    CHART_GRID_COLOR,
    CHART_INCOME_COLOR,
    CHART_LINE_COLOR,
    CHART_REFERENCE_COLOR,
    paletteColor,
)
from utils.constants import ANALYSIS_HISTOGRAM_BIN, ANALYSIS_ROLLING_WINDOW
from utils.unit_formatter import formatExact
from views.widgets.charts.base_canvas import (
    HOVER_X_TOLERANCE,
    BaseChartCanvas,
    annotateSpaced,
)

# 分布标线要展示的分位（与预算档位一致：P25 / P50 / P90）
_MARKER_QUANTILES = ((0.25, "P25"), (0.50, "P50"), (0.90, "P90"))


class BuildPoolTrendCanvas(BaseChartCanvas):
    """毕业次数时间序列与分布。"""

    def __init__(self, parent=None):
        """
        初始化大建趋势画布。

        Args:
            parent: 父控件。
        """
        super().__init__(parent, height=300)
        self._analysis: Optional[BuildPoolAnalysis] = None
        self._dates_num: List[float] = []
        self._trend_axes = None
        self._hist_axes = None
        self._bins: List[int] = []

    def render(self, analysis: BuildPoolAnalysis) -> None:
        """
        绘制时间序列与分布。

        Args:
            analysis: 大建分析结果。
        """
        if not analysis.hasData:
            self.setHoverProvider(None)
            self.showHint("暂无毕业池样本（仅统计状态=毕业的池）")
            return
        self.renderWith(lambda figure: self._draw(figure, analysis))
        self.setHoverProvider(self._hover)

    def _draw(self, figure: Figure, analysis: BuildPoolAnalysis) -> None:
        """
        实际绘制。

        Args:
            figure: 画布 figure。
            analysis: 大建分析结果。
        """
        figure.subplots_adjust(left=0.08, right=0.985, bottom=0.16, top=0.94, wspace=0.3)
        grid = figure.add_gridspec(1, 2, width_ratios=[1.45, 1.0])
        self._trend_axes = figure.add_subplot(grid[0, 0])
        self._hist_axes = figure.add_subplot(grid[0, 1])
        self._analysis = analysis
        self._dates_num = [
            mdates.date2num(date.fromisoformat(point.event_date))
            for point in analysis.points
        ]

        self._drawTrend(self._trend_axes, analysis)
        self._drawHistogram(self._hist_axes, analysis)

    def _drawTrend(self, axes, analysis: BuildPoolAnalysis) -> None:
        """
        绘制毕业次数时间序列。

        Args:
            axes: 左侧坐标轴。
            analysis: 大建分析结果。
        """
        counts = [point.build_count for point in analysis.points]
        axes.scatter(self._dates_num, counts, s=18, color=CHART_INCOME_COLOR, label="毕业次数")
        axes.plot(
            self._dates_num,
            analysis.rolling_median,
            color=CHART_REFERENCE_COLOR,
            linewidth=1.2,
            label=f"近 {ANALYSIS_ROLLING_WINDOW} 池中位数",
        )
        axes.set_ylabel("毕业次数")
        axes.grid(axis="y", color=CHART_GRID_COLOR, linewidth=0.6, alpha=0.5)
        axes.xaxis.set_major_locator(AutoDateLocator(minticks=3, maxticks=7))
        axes.xaxis.set_major_formatter(DateFormatter("%Y-%m"))
        axes.legend(loc="upper left", frameon=False)
        axes.margins(x=0.02, y=0.08)

        max_index = max(range(len(counts)), key=lambda index: counts[index])
        annotateSpaced(
            axes,
            [
                (self._dates_num[max_index], counts[max_index], f"最高 {counts[max_index]} 次"),
                (self._dates_num[-1], counts[-1], f"最新 {counts[-1]} 次"),
            ],
        )

    def _drawHistogram(self, axes, analysis: BuildPoolAnalysis) -> None:
        """
        绘制次数分布与分位标线。

        Args:
            axes: 右侧坐标轴。
            analysis: 大建分析结果。
        """
        counts = [point.build_count for point in analysis.points]
        upper = ((max(counts) // ANALYSIS_HISTOGRAM_BIN) + 1) * ANALYSIS_HISTOGRAM_BIN
        self._bins = list(
            range(0, upper + ANALYSIS_HISTOGRAM_BIN, ANALYSIS_HISTOGRAM_BIN)
        )
        axes.hist(counts, bins=self._bins, color=CHART_INCOME_COLOR, edgecolor="white")

        for index, (step, label) in enumerate(_MARKER_QUANTILES):
            value = analysis.quantiles.get(step)
            if value is None:
                continue
            axes.axvline(value, color=CHART_ANCHOR_COLOR, linewidth=1.0, linestyle="--")
            axes.text(
                value,
                axes.get_ylim()[1] * (0.98 - index * 0.09),
                f"{label} {value:g}",
                color=CHART_ANCHOR_COLOR,
                fontsize=7,
                ha="center",
                va="top",
                bbox={"facecolor": "white", "edgecolor": "none", "alpha": 0.75, "pad": 0.6},
            )

        axes.set_xlabel("毕业次数")
        axes.set_ylabel("池数")
        axes.grid(axis="y", color=CHART_GRID_COLOR, linewidth=0.6, alpha=0.5)

    def _hover(self, event) -> Optional[str]:
        """
        悬停读数：时间序列给活动详情，分布图给区间池数。

        Args:
            event: motion 事件。

        Returns:
            提示文本；没有命中时返回 None。
        """
        analysis = self._analysis
        if analysis is None:
            return None

        if event.inaxes is self._trend_axes and event.xdata is not None:
            index = self.nearestIndex(self._dates_num, event.xdata)
            if index is None:
                return None
            span = self._dates_num[-1] - self._dates_num[0]
            if span and abs(event.xdata - self._dates_num[index]) > span * HOVER_X_TOLERANCE:
                return None
            point = analysis.points[index]
            lines = [
                point.event_date,
                point.name,
                f"{point.event_type}",
                f"毕业 {point.build_count} 次（单耗 {point.build_cost}）",
            ]
            if point.derived:
                lines.append("次数由关联魔方折算")
            return "\n".join(lines)

        if event.inaxes is self._hist_axes and event.xdata is not None:
            if len(self._bins) < 2:
                return None
            index = min(
                range(len(self._bins) - 1),
                max(0, int((event.xdata - self._bins[0]) // ANALYSIS_HISTOGRAM_BIN)),
            )
            low, high = self._bins[index], self._bins[index + 1]
            count = sum(
                1
                for point in analysis.points
                if low <= point.build_count < high
            )
            return f"{formatExact(low)}–{formatExact(high)} 次\n{count} 个池"
        return None


class BuildPoolCompareCanvas(BaseChartCanvas):
    """类型对照与经验生存曲线。"""

    def __init__(self, parent=None):
        """
        初始化对照画布。

        Args:
            parent: 父控件。
        """
        super().__init__(parent, height=260)
        self._analysis: Optional[BuildPoolAnalysis] = None
        self._group_axes = None
        self._survival_axes = None
        self._survival_x: List[int] = []

    def render(
        self, analysis: BuildPoolAnalysis, current_count: Optional[int] = None
    ) -> None:
        """
        绘制类型对照与生存曲线。

        Args:
            analysis: 大建分析结果。
            current_count: 当前已抽次数；None 表示不画当前池标线。
        """
        if not analysis.hasData:
            self.setHoverProvider(None)
            self.showHint("暂无毕业池样本（仅统计状态=毕业的池）")
            return
        self.renderWith(lambda figure: self._draw(figure, analysis, current_count))
        self.setHoverProvider(self._hover)

    def _draw(
        self,
        figure: Figure,
        analysis: BuildPoolAnalysis,
        current_count: Optional[int],
    ) -> None:
        """
        实际绘制。

        Args:
            figure: 画布 figure。
            analysis: 大建分析结果。
            current_count: 当前已抽次数。
        """
        figure.subplots_adjust(left=0.13, right=0.985, bottom=0.16, top=0.94, wspace=0.3)
        grid = figure.add_gridspec(1, 2, width_ratios=[1.0, 1.35])
        self._group_axes = figure.add_subplot(grid[0, 0])
        self._survival_axes = figure.add_subplot(grid[0, 1])
        self._analysis = analysis
        self._survival_x = [point[0] for point in analysis.survival]

        self._drawGroups(self._group_axes, analysis)
        self._drawSurvival(self._survival_axes, analysis, current_count)

    @staticmethod
    def _drawGroups(axes, analysis: BuildPoolAnalysis) -> None:
        """
        绘制按类型的中位数条形。

        Args:
            axes: 左侧坐标轴。
            analysis: 大建分析结果。
        """
        groups = list(reversed(analysis.by_type))
        names = [group.name for group in groups]
        medians = [group.median for group in groups]
        colors = [paletteColor(index) for index in range(len(groups))]

        axes.barh(range(len(names)), medians, color=colors, height=0.62)
        axes.set_yticks(range(len(names)))
        axes.set_yticklabels(names)
        axes.set_xlabel("中位毕业次数")
        axes.grid(axis="x", color=CHART_GRID_COLOR, linewidth=0.6, alpha=0.5)
        axes.margins(x=0.35)

        maximum = max(medians) if medians else 0
        for index, group in enumerate(groups):
            axes.text(
                group.median + maximum * 0.03,
                index,
                f"{group.median:g} 次（N={group.sample_size}）",
                va="center",
                fontsize=7,
            )

    @staticmethod
    def _drawSurvival(
        axes, analysis: BuildPoolAnalysis, current_count: Optional[int]
    ) -> None:
        """
        绘制经验生存曲线 ``P(T > n)``。

        Args:
            axes: 右侧坐标轴。
            analysis: 大建分析结果。
            current_count: 当前已抽次数。
        """
        xs = [point[0] for point in analysis.survival]
        ys = [point[1] for point in analysis.survival]
        axes.step(xs, ys, where="post", color=CHART_LINE_COLOR, linewidth=1.4)
        axes.fill_between(xs, ys, step="post", color=CHART_LINE_COLOR, alpha=0.08)

        if current_count is not None and current_count > 0:
            axes.axvline(
                current_count,
                color=CHART_EXPENSE_COLOR,
                linewidth=1.1,
                linestyle="--",
                label=f"当前 {current_count} 次",
            )
            axes.legend(loc="upper right", frameon=False)

        axes.set_xlabel("已抽次数 n")
        axes.set_ylabel("历史池中仍需 > n 次的比例")
        axes.set_ylim(0, 1.05)
        axes.grid(color=CHART_GRID_COLOR, linewidth=0.6, alpha=0.5)
        axes.margins(x=0.01)

    def _hover(self, event) -> Optional[str]:
        """
        悬停读数：类型分组统计与生存概率。

        Args:
            event: motion 事件。

        Returns:
            提示文本；没有命中时返回 None。
        """
        analysis = self._analysis
        if analysis is None:
            return None

        if event.inaxes is self._group_axes and event.ydata is not None:
            groups = list(reversed(analysis.by_type))
            index = int(round(event.ydata))
            if 0 <= index < len(groups):
                group = groups[index]
                return "\n".join(
                    [
                        f"{group.name}池",
                        f"样本 {group.sample_size} 个",
                        f"中位 {group.median:g} 次",
                        f"均值 {group.mean:.1f} 次",
                    ]
                )
            return None

        if event.inaxes is self._survival_axes and event.xdata is not None:
            index = self.nearestIndex(self._survival_x, event.xdata)
            if index is None:
                return None
            span = self._survival_x[-1] - self._survival_x[0]
            if span and abs(event.xdata - self._survival_x[index]) > span * HOVER_X_TOLERANCE:
                return None
            value, ratio = analysis.survival[index]
            return "\n".join(
                [
                    f"已抽 {value} 次",
                    f"历史池中仍需更多次数的比例 {ratio:.1%}",
                    f"样本 {analysis.sample_size} 个",
                ]
            )
        return None
