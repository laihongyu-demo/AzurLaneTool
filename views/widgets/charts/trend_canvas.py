"""
整体趋势图（#19）。

- :class:`TrendBalanceCanvas`：日结余折线，手填结余日画 ▲（锚点会让结余跳变）；
  折线只标「最高 / 最低 / 最新 / 手填结余」这些突出点，避免 1200 个标签互相压住；
- :class:`TrendMonthlyCanvas`：月度收入 / 支出分组柱 + 净额线，数值走悬停读数。
"""

from datetime import date
from typing import List, Optional

from matplotlib import dates as mdates
from matplotlib.dates import AutoDateLocator, DateFormatter
from matplotlib.figure import Figure

from models.analysis_model import BalancePoint, TrendSeries
from utils.chart_style import (
    CHART_ANCHOR_COLOR,
    CHART_EXPENSE_COLOR,
    CHART_GRID_COLOR,
    CHART_INCOME_COLOR,
    CHART_LINE_COLOR,
    CHART_NET_COLOR,
)
from utils.unit_formatter import formatExact
from views.widgets.charts.base_canvas import (
    HOVER_X_TOLERANCE,
    BaseChartCanvas,
    annotateLanes,
)

# 局部极值窗口（天）：14 天内的最高 / 最低点才算「阶段峰谷」，避免把日内小波动都标出来
LOCAL_EXTREME_WINDOW = 14

# 峰谷的最小起伏（占全区间跨度的比例）：太平的段不标
LOCAL_EXTREME_PROMINENCE = 0.06

# 各类标签的数量上限：峰谷各 5 个，峰在上、谷在下，互不挤占
PEAK_LABEL_LIMIT = 5
TROUGH_LABEL_LIMIT = 5
ANCHOR_LABEL_LIMIT = 2

# 单日涨跌的标注门槛：至少跨度的 4%，太小的日波动不标
DELTA_LABEL_RATIO = 0.04
DELTA_LABEL_MIN = 50


def localExtremes(values: List[int], window: int, min_prominence: float) -> tuple:
    """
    找阶段峰 / 谷，并按「起伏幅度」排序。

    结余是长期上涨的，按绝对值排序会让标签全挤在末期；这里用「相对前后窗口的起伏」
    衡量突出程度，活动前后的尖峰更容易被选中。

    Args:
        values: 结余序列（按日期升序）。
        window: 前后比较窗口（天）。
        min_prominence: 最小起伏（绝对值）。

    Returns:
        ``(peaks, troughs)``：``(索引, 起伏)`` 列表，按起伏降序。
    """
    count = len(values)
    peaks: List[tuple] = []
    troughs: List[tuple] = []
    for index, value in enumerate(values):
        low = max(0, index - window)
        high = min(count, index + window + 1)
        segment = values[low:high]
        if value == max(segment):
            prominence = value - min(segment)
            if prominence >= min_prominence:
                peaks.append((index, prominence))
        if value == min(segment):
            prominence = max(segment) - value
            if prominence >= min_prominence:
                troughs.append((index, prominence))

    gap = max(1, window // 2)
    peaks = _thinPeaks(peaks, gap)
    troughs = _thinPeaks(troughs, gap)
    peaks.sort(key=lambda item: item[1], reverse=True)
    troughs.sort(key=lambda item: item[1], reverse=True)
    return peaks, troughs


def _thinPeaks(peaks: List[tuple], min_gap: int) -> List[tuple]:
    """
    平台期去重：同一段横盘会连续产生多个极值点，只保留间隔足够的那个。

    Args:
        peaks: ``(索引, 起伏)`` 列表。
        min_gap: 两个保留点之间的最小索引间隔。

    Returns:
        去重后的 ``(索引, 起伏)`` 列表。
    """
    ordered = sorted(peaks)
    kept: List[tuple] = []
    for index, prominence in ordered:
        if kept and index - kept[-1][0] < min_gap:
            continue
        kept.append((index, prominence))
    return kept


class TrendBalanceCanvas(BaseChartCanvas):
    """日结余折线。"""

    def __init__(self, parent=None):
        """
        初始化结余画布。

        Args:
            parent: 父控件。
        """
        super().__init__(parent, height=240)
        self._points: List[BalancePoint] = []
        self._dates_num: List[float] = []
        self._axes = None

    def render(self, series: TrendSeries) -> None:
        """
        绘制结余曲线。

        Args:
            series: 趋势数据。
        """
        if not series.balance_points:
            self.setHoverProvider(None)
            self.showHint(f"{series.display_name}：暂无记录")
            return
        self.renderWith(lambda figure: self._draw(figure, series))
        self.setHoverProvider(self._hover)

    def _draw(self, figure: Figure, series: TrendSeries) -> None:
        """
        实际绘制。

        Args:
            figure: 画布 figure。
            series: 趋势数据。
        """
        figure.subplots_adjust(left=0.085, right=0.985, bottom=0.14, top=0.97)
        axes = figure.add_subplot(111)
        self._axes = axes
        self._points = series.balance_points
        self._dates_num = [
            mdates.date2num(date.fromisoformat(point.record_date))
            for point in series.balance_points
        ]

        axes.plot(
            self._dates_num,
            [point.balance for point in series.balance_points],
            color=CHART_LINE_COLOR,
            linewidth=1.3,
            label="结余",
        )

        anchors = [point for point in series.balance_points if point.is_anchor]
        if anchors:
            axes.scatter(
                [mdates.date2num(date.fromisoformat(point.record_date)) for point in anchors],
                [point.balance for point in anchors],
                marker="^",
                s=26,
                color=CHART_ANCHOR_COLOR,
                zorder=3,
                label="手填结余",
            )
            axes.legend(loc="upper left", frameon=False)

        axes.set_ylabel(f"结余（{series.display_name}）")
        axes.grid(axis="y", color=CHART_GRID_COLOR, linewidth=0.6, alpha=0.5)
        axes.xaxis.set_major_locator(AutoDateLocator(minticks=4, maxticks=8))
        axes.xaxis.set_major_formatter(DateFormatter("%Y-%m"))
        # 上方留白要能容纳「峰 + 引导线 + 标签」，否则顶部的峰标签会被图边界裁掉
        axes.margins(x=0.01, y=0.15)

        self._annotate(axes, series)

    @staticmethod
    def _annotate(axes, series: TrendSeries) -> None:
        """
        标注突出点：峰在上方、谷在下方，带引导线；另有最新、单日涨跌与手填结余。

        峰谷按「相对前后窗口的起伏」排序，各取前 4 个；同一侧按水平距离避让，
        两侧互不挤占，因此比单道标注能多显示一倍的点。

        Args:
            axes: 坐标轴。
            series: 趋势数据。
        """
        points = series.balance_points
        if len(points) < 3:
            return

        values = [point.balance for point in points]
        numbers = [
            mdates.date2num(date.fromisoformat(point.record_date)) for point in points
        ]
        span = max(values) - min(values)

        above = [(numbers[-1], values[-1], f"最新 {formatExact(values[-1])}")]
        below = []

        peaks, troughs = localExtremes(
            values, LOCAL_EXTREME_WINDOW, max(1.0, span * LOCAL_EXTREME_PROMINENCE)
        )

        # 单日大幅变化放在峰 / 谷之前：它往往就是用户最关心的「某天突然涨了一截」
        if len(values) >= 2:
            deltas = [
                (values[index] - values[index - 1], index)
                for index in range(1, len(values))
            ]
            best_up = max(deltas, key=lambda item: item[0])
            best_down = min(deltas, key=lambda item: item[0])
            delta_threshold = max(DELTA_LABEL_MIN, span * DELTA_LABEL_RATIO)
            if best_up[0] >= delta_threshold:
                above.append(
                    (
                        numbers[best_up[1]],
                        values[best_up[1]],
                        f"单日 +{formatExact(best_up[0])}",
                    )
                )
            if -best_down[0] >= delta_threshold:
                below.append(
                    (
                        numbers[best_down[1]],
                        values[best_down[1]],
                        f"单日 −{formatExact(abs(best_down[0]))}",
                    )
                )

        for index, _ in peaks[:PEAK_LABEL_LIMIT]:
            above.append((numbers[index], values[index], f"峰 {formatExact(values[index])}"))
        for index, _ in troughs[:TROUGH_LABEL_LIMIT]:
            below.append((numbers[index], values[index], f"谷 {formatExact(values[index])}"))

        for point in [point for point in points if point.is_anchor][:ANCHOR_LABEL_LIMIT]:
            above.append(
                (
                    mdates.date2num(date.fromisoformat(point.record_date)),
                    point.balance,
                    f"手填 {formatExact(point.balance)}",
                )
            )

        annotateLanes(axes, above, below)

    def _hover(self, event) -> Optional[str]:
        """
        悬停读数：最近日期的结余与当日收支。

        Args:
            event: motion 事件。

        Returns:
            提示文本；没有命中时返回 None。
        """
        axes = self._axes
        if axes is None or event.inaxes is not axes or event.xdata is None:
            return None
        if not self._dates_num:
            return None
        index = self.nearestIndex(self._dates_num, event.xdata)
        if index is None:
            return None
        span = self._dates_num[-1] - self._dates_num[0]
        if span and abs(event.xdata - self._dates_num[index]) > span * HOVER_X_TOLERANCE:
            return None
        point = self._points[index]
        lines = [
            point.record_date,
            f"结余 {formatExact(point.balance)}",
            f"收 {formatExact(point.income)} / 支 {formatExact(point.expense)}",
        ]
        if point.is_anchor:
            lines.append("当天为手填结余")
        return "\n".join(lines)


class TrendMonthlyCanvas(BaseChartCanvas):
    """月度收入 / 支出柱与净额线。"""

    def __init__(self, parent=None):
        """
        初始化月度收支画布。

        Args:
            parent: 父控件。
        """
        super().__init__(parent, height=210)
        self._series: Optional[TrendSeries] = None
        self._axes = None

    def render(self, series: TrendSeries) -> None:
        """
        绘制月度收支。

        Args:
            series: 趋势数据。
        """
        if not series.monthly_points:
            self.setHoverProvider(None)
            self.showHint("暂无月度记录")
            return
        self.renderWith(lambda figure: self._draw(figure, series))
        self.setHoverProvider(self._hover)

    def _draw(self, figure: Figure, series: TrendSeries) -> None:
        """
        实际绘制。

        Args:
            figure: 画布 figure。
            series: 趋势数据。
        """
        figure.subplots_adjust(left=0.075, right=0.99, bottom=0.16, top=0.97)
        axes = figure.add_subplot(111)
        self._axes = axes
        self._series = series

        labels = [point.month for point in series.monthly_points]
        indexes = list(range(len(labels)))
        width = 0.4

        axes.bar(
            [index - width / 2 for index in indexes],
            [point.income for point in series.monthly_points],
            width=width,
            color=CHART_INCOME_COLOR,
            label="收入",
        )
        axes.bar(
            [index + width / 2 for index in indexes],
            [point.expense for point in series.monthly_points],
            width=width,
            color=CHART_EXPENSE_COLOR,
            label="支出",
        )
        axes.plot(
            indexes,
            [point.net for point in series.monthly_points],
            color=CHART_NET_COLOR,
            linewidth=1.2,
            marker="o",
            markersize=2.5,
            label="净额",
        )

        step = max(1, len(labels) // 8)
        axes.set_xticks(indexes[::step])
        axes.set_xticklabels(labels[::step])
        axes.set_ylabel("数量")
        axes.grid(axis="y", color=CHART_GRID_COLOR, linewidth=0.6, alpha=0.5)
        axes.legend(ncol=3, frameon=False, loc="upper left")
        axes.margins(x=0.01)

    def _hover(self, event) -> Optional[str]:
        """
        悬停读数：当月的收入、支出与净额。

        Args:
            event: motion 事件。

        Returns:
            提示文本；没有命中时返回 None。
        """
        axes = self._axes
        series = self._series
        if axes is None or series is None or event.inaxes is not axes or event.xdata is None:
            return None
        index = int(round(event.xdata))
        if index < 0 or index >= len(series.monthly_points):
            return None
        if abs(event.xdata - index) > 0.6:
            return None
        point = series.monthly_points[index]
        return "\n".join(
            [
                point.month,
                f"收入 {formatExact(point.income)}",
                f"支出 {formatExact(point.expense)}",
                f"净额 {point.net:+d}",
            ]
        )
