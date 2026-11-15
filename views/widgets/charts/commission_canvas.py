"""
军事委托产出图（#19）。

左图：月度产出柱（无记录月份留空，不补 0）+ 12 个月移动平均；
右图：单笔产出分布（按金额聚合的笔数）。两块都支持悬停读数。
"""

from typing import Optional

from matplotlib.figure import Figure

from models.analysis_model import CommissionOverview
from utils.chart_style import (
    CHART_GRID_COLOR,
    CHART_INCOME_COLOR,
    CHART_REFERENCE_COLOR,
)
from utils.unit_formatter import formatExact
from views.widgets.charts.base_canvas import BaseChartCanvas


class CommissionCanvas(BaseChartCanvas):
    """军事委托月度产出与单笔分布。"""

    def __init__(self, parent=None):
        """
        初始化委托产出画布。

        Args:
            parent: 父控件。
        """
        super().__init__(parent, height=260)
        self._overview: Optional[CommissionOverview] = None
        self._monthly_axes = None
        self._distribution_axes = None

    def render(self, overview: CommissionOverview, showAverage: bool = True) -> None:
        """
        绘制委托产出概览。

        Args:
            overview: 委托概览结果。
            showAverage: 是否绘制移动平均线（近一年范围下关闭，避免半截均线误导）。
        """
        if not overview.hasData or not overview.months:
            self.setHoverProvider(None)
            self.showHint(
                f"{overview.display_name}军事委托：{overview.range_label}暂无记录"
            )
            return
        self.renderWith(lambda figure: self._draw(figure, overview, showAverage))
        self.setHoverProvider(self._hover)

    def _draw(
        self, figure: Figure, overview: CommissionOverview, showAverage: bool
    ) -> None:
        """
        实际绘制。

        Args:
            figure: 画布 figure。
            overview: 委托概览结果。
            showAverage: 是否绘制移动平均。
        """
        figure.subplots_adjust(left=0.075, right=0.985, bottom=0.17, top=0.94, wspace=0.3)
        grid = figure.add_gridspec(1, 2, width_ratios=[1.45, 1.0])
        self._monthly_axes = figure.add_subplot(grid[0, 0])
        self._distribution_axes = figure.add_subplot(grid[0, 1])
        self._overview = overview

        self._drawMonthly(self._monthly_axes, overview, showAverage)
        self._drawDistribution(self._distribution_axes, overview)

    @staticmethod
    def _drawMonthly(axes, overview: CommissionOverview, showAverage: bool) -> None:
        """
        绘制月度产出柱与移动平均。

        Args:
            axes: 左侧坐标轴。
            overview: 委托概览结果。
            showAverage: 是否绘制移动平均。
        """
        positions = [
            index for index, amount in enumerate(overview.amounts) if amount is not None
        ]
        values = [overview.amounts[index] for index in positions]
        axes.bar(positions, values, color=CHART_INCOME_COLOR, width=0.72, label="月度产出")

        if showAverage:
            average_positions = [
                index
                for index, value in enumerate(overview.rolling_average)
                if value is not None
            ]
            if average_positions:
                axes.plot(
                    average_positions,
                    [overview.rolling_average[index] for index in average_positions],
                    color=CHART_REFERENCE_COLOR,
                    linewidth=1.2,
                    label="12 个月移动平均",
                )

        step = max(1, len(overview.months) // 8)
        indexes = list(range(len(overview.months)))
        axes.set_xticks(indexes[::step])
        axes.set_xticklabels(overview.months[::step], rotation=30, ha="right")
        axes.set_ylabel(f"产出（{overview.display_name}）")
        axes.grid(axis="y", color=CHART_GRID_COLOR, linewidth=0.6, alpha=0.5)
        axes.margins(x=0.01)
        axes.legend(loc="upper left", frameon=False)

    @staticmethod
    def _drawDistribution(axes, overview: CommissionOverview) -> None:
        """
        绘制单笔金额分布。

        Args:
            axes: 右侧坐标轴。
            overview: 委托概览结果。
        """
        amounts = [item[0] for item in overview.amount_distribution]
        counts = [item[1] for item in overview.amount_distribution]
        if not amounts:
            axes.axis("off")
            axes.text(0.5, 0.5, "暂无单笔分布", ha="center", va="center", color="#999999")
            return

        axes.bar(range(len(amounts)), counts, color=CHART_INCOME_COLOR, width=0.8)
        step = max(1, len(amounts) // 8)
        axes.set_xticks(list(range(len(amounts)))[::step])
        axes.set_xticklabels(
            [formatExact(value) for value in amounts[::step]], rotation=30, ha="right"
        )
        axes.set_xlabel("单笔产出")
        axes.set_ylabel("笔数")
        axes.grid(axis="y", color=CHART_GRID_COLOR, linewidth=0.6, alpha=0.5)
        axes.margins(x=0.01)

    def _hover(self, event) -> Optional[str]:
        """
        悬停读数：月度产出或单笔分布的笔数。

        Args:
            event: motion 事件。

        Returns:
            提示文本；没有命中时返回 None。
        """
        overview = self._overview
        if overview is None:
            return None

        if event.inaxes is self._monthly_axes and event.xdata is not None:
            index = int(round(event.xdata))
            if not 0 <= index < len(overview.months):
                return None
            if abs(event.xdata - index) > 0.6:
                return None
            amount = overview.amounts[index]
            month = overview.months[index]
            if amount is None:
                return f"{month}\n无记录"
            return "\n".join([month, f"产出 {formatExact(amount)}", f"{overview.counts[index]} 笔"])

        if event.inaxes is self._distribution_axes and event.xdata is not None:
            index = int(round(event.xdata))
            distribution = overview.amount_distribution
            if not 0 <= index < len(distribution):
                return None
            if abs(event.xdata - index) > 0.6:
                return None
            amount, count = distribution[index]
            total = overview.totals.count
            share = (count / total) if total else 0.0
            return "\n".join(
                [
                    f"单笔 {formatExact(amount)}",
                    f"{count} 笔（{share:.1%}）",
                ]
            )
        return None
