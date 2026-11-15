"""
来源 / 去向类目占比图（#19）。

左图：总计横向条形（全部类目，按金额降序，标出金额与占比）；
右图：月度堆叠柱，可切「绝对值 / 占比」；两块图都支持悬停读数。
"""

from typing import Optional

from matplotlib.figure import Figure

from models.analysis_model import CategoryBreakdown
from utils.chart_style import CHART_GRID_COLOR, paletteColor
from utils.unit_formatter import formatExact
from views.widgets.charts.base_canvas import BaseChartCanvas

# 左图右侧留白：条形末端的「金额（占比）」文字需要空间，否则会被裁掉
_TOTAL_LABEL_MARGIN = 0.5

# 图例放在整幅图右侧、纵向排布；右边界要给图例让出空间
_LEGEND_BBOX = (0.805, 0.5)


def drawTotals(axes, breakdown: CategoryBreakdown) -> None:
    """
    绘制总计横向条形（金额降序，最大在最上）。

    Args:
        axes: 左侧坐标轴。
        breakdown: 类目占比结果。
    """
    ordered = list(reversed(breakdown.shares))
    names = [item.name for item in ordered]
    amounts = [item.amount for item in ordered]
    colors = [paletteColor(index) for index in range(len(ordered))]

    axes.barh(range(len(names)), amounts, color=colors, height=0.55)
    axes.set_yticks(range(len(names)))
    axes.set_yticklabels(names)
    axes.tick_params(axis="y", labelsize=8)
    axes.set_xlabel(f"{breakdown.direction_name}数量")
    axes.grid(axis="x", color=CHART_GRID_COLOR, linewidth=0.6, alpha=0.5)
    axes.margins(x=_TOTAL_LABEL_MARGIN)

    maximum = max(amounts) if amounts else 0
    for index, item in enumerate(ordered):
        axes.text(
            item.amount + maximum * 0.02,
            index,
            f"{formatExact(item.amount)}（{item.share:.1%}）",
            va="center",
            fontsize=7,
        )


def drawMonthly(axes, breakdown: CategoryBreakdown, ratio_mode: bool) -> None:
    """
    绘制月度堆叠柱。

    Args:
        axes: 右侧坐标轴。
        breakdown: 类目占比结果。
        ratio_mode: True 时按月归一化为占比（%）。
    """
    monthly = breakdown.monthly
    indexes = list(range(len(monthly.months)))
    bottom = [0.0] * len(indexes)

    for row_index, category in enumerate(monthly.categories):
        values = monthly.values[row_index]
        if ratio_mode:
            values = [
                (value / total * 100.0) if total else 0.0
                for value, total in zip(values, monthly.month_totals)
            ]
        axes.bar(
            indexes,
            values,
            bottom=bottom,
            color=paletteColor(row_index),
            width=0.85,
            label=category,
        )
        bottom = [base + value for base, value in zip(bottom, values)]

    step = max(1, len(indexes) // 8)
    axes.set_xticks(indexes[::step])
    axes.set_xticklabels(monthly.months[::step], rotation=30, ha="right")
    axes.set_ylabel("占比（%）" if ratio_mode else "数量")
    axes.grid(axis="y", color=CHART_GRID_COLOR, linewidth=0.6, alpha=0.5)
    axes.margins(x=0.01)
    if ratio_mode:
        axes.set_ylim(0, 100)


class CategoryCanvas(BaseChartCanvas):
    """总计 + 月度类目图（1×2）。"""

    def __init__(self, parent=None):
        """
        初始化类目占比画布。

        Args:
            parent: 父控件。
        """
        super().__init__(parent, height=380)
        self._breakdown: Optional[CategoryBreakdown] = None
        self._ratio_mode = False
        self._totals_axes = None
        self._monthly_axes = None

    def render(self, breakdown: CategoryBreakdown, ratio_mode: bool = False) -> None:
        """
        绘制类目占比。

        Args:
            breakdown: 类目占比结果。
            ratio_mode: True 时月度图按月归一化为占比（%）。
        """
        if not breakdown.hasData:
            self.setHoverProvider(None)
            self.showHint(f"{breakdown.display_name}{breakdown.direction_name}：暂无明细")
            return
        self.renderWith(lambda figure: self._draw(figure, breakdown, ratio_mode))
        self.setHoverProvider(self._hover)

    def _draw(self, figure: Figure, breakdown: CategoryBreakdown, ratio_mode: bool) -> None:
        """
        实际绘制。

        Args:
            figure: 画布 figure。
            breakdown: 类目占比结果。
            ratio_mode: 是否按月归一化。
        """
        figure.subplots_adjust(
            left=0.15, right=0.80, bottom=0.13, top=0.94, wspace=0.42
        )
        grid = figure.add_gridspec(1, 2, width_ratios=[1.0, 1.3])
        self._totals_axes = figure.add_subplot(grid[0, 0])
        self._monthly_axes = figure.add_subplot(grid[0, 1])
        self._breakdown = breakdown
        self._ratio_mode = ratio_mode

        drawTotals(self._totals_axes, breakdown)
        drawMonthly(self._monthly_axes, breakdown, ratio_mode)

        handles, labels = self._monthly_axes.get_legend_handles_labels()
        if handles:
            figure.legend(
                handles,
                labels,
                loc="center left",
                bbox_to_anchor=_LEGEND_BBOX,
                ncol=1,
                fontsize=7.5,
                frameon=False,
                title="类目",
                title_fontsize=7.5,
            )

    def _hover(self, event) -> Optional[str]:
        """
        悬停读数：左图给类目总计，右图给「月份 × 类目」金额。

        Args:
            event: motion 事件。

        Returns:
            提示文本；没有命中时返回 None。
        """
        breakdown = self._breakdown
        if breakdown is None:
            return None

        if event.inaxes is self._totals_axes and event.ydata is not None:
            ordered = list(reversed(breakdown.shares))
            index = int(round(event.ydata))
            if 0 <= index < len(ordered):
                item = ordered[index]
                return "\n".join(
                    [
                        item.name,
                        f"{formatExact(item.amount)}（{item.share:.1%}）",
                        f"{item.count} 笔",
                    ]
                )
            return None

        if event.inaxes is self._monthly_axes and event.xdata is not None:
            month_index = int(round(event.xdata))
            monthly = breakdown.monthly
            if not 0 <= month_index < len(monthly.months):
                return None
            if event.ydata is None:
                return None
            total = monthly.month_totals[month_index]
            cursor = 0.0
            for row_index, category in enumerate(monthly.categories):
                value = monthly.values[row_index][month_index]
                height = (value / total * 100.0) if (self._ratio_mode and total) else value
                if cursor <= event.ydata <= cursor + height:
                    share = (value / total) if total else 0.0
                    return "\n".join(
                        [
                            monthly.months[month_index],
                            category,
                            f"{formatExact(value)}（{share:.1%}）",
                        ]
                    )
                cursor += height
            if total:
                return f"{monthly.months[month_index]}\n合计 {formatExact(total)}"
        return None
