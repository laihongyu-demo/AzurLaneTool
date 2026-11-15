"""
图表画布基类（#19）。

统一画布高度、空状态、重绘入口与悬停读数；所有图表都只接收 dataclass，不查库、不写 SQL。

布局用显式边距（``subplots_adjust``）而不是 ``constrained``：实测 6 个画布首绘时
constrained 布局求解约占三成时间，且首帧在布局未稳定时容易出现裁切伪影。
"""

from typing import Callable, Optional

from PyQt5.QtGui import QCursor
from PyQt5.QtWidgets import QSizePolicy, QToolTip, QWidget
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg
from matplotlib.figure import Figure

from utils.chart_style import CHART_DPI

EMPTY_HINT_COLOR = "#999999"

# 画布默认宽度（像素）：只在控件还没拿到真实宽度时兜底；resize 后由 Qt 同步
DEFAULT_CANVAS_WIDTH = 960

# 悬停读数的命中容差（相对坐标轴宽度）
HOVER_X_TOLERANCE = 0.02

# 标签去重阈值（相对坐标轴宽 / 高）：太挤就不标，宁可少标也不重叠
LABEL_MIN_DX = 0.075
LABEL_MIN_DY = 0.09


def _normalized(axes, x: float, y: float) -> tuple:
    """
    把数据坐标换算到坐标轴的 0~1 归一化坐标。

    Args:
        axes: 坐标轴。
        x: 数据 X。
        y: 数据 Y。

    Returns:
        ``(nx, ny)``。
    """
    x0, x1 = axes.get_xlim()
    y0, y1 = axes.get_ylim()
    nx = (x - x0) / (x1 - x0) if x1 != x0 else 0.0
    ny = (y - y0) / (y1 - y0) if y1 != y0 else 0.0
    return nx, ny


def annotateSpaced(axes, entries, max_labels: int = 9) -> None:
    """
    依次标注数据点，跳过与已标点过近的项。

    折线 / 散点有上千个点时不可能全部标数字：这里只标调用方挑出的突出点，
    并按归一化距离去重，保证标签不重叠。

    Args:
        axes: 坐标轴。
        entries: ``(x, y, text)`` 列表；按优先级排序，先标重要的。
        max_labels: 最多标注数量。
    """
    placed = []
    for x, y, text in entries:
        if len(placed) >= max_labels:
            break
        nx, ny = _normalized(axes, x, y)
        if any(
            abs(nx - px) < LABEL_MIN_DX and abs(ny - py) < LABEL_MIN_DY
            for px, py in placed
        ):
            continue
        placed.append((nx, ny))
        # 贴边的点把标签往内侧收，避免被坐标系裁剪
        if nx > 0.92:
            horizontal, offset_x = "right", -5
        elif nx < 0.08:
            horizontal, offset_x = "left", 5
        else:
            horizontal, offset_x = "center", 0
        axes.annotate(
            text,
            xy=(x, y),
            xytext=(offset_x, 7),
            textcoords="offset points",
            ha=horizontal,
            va="bottom",
            fontsize=6.5,
            color="#333333",
            bbox={"facecolor": "white", "edgecolor": "none", "alpha": 0.7, "pad": 0.6},
        )


def annotateLanes(
    axes,
    above,
    below,
    max_above: int = 7,
    max_below: int = 6,
    min_gap: float = 0.065,
    offset: int = 12,
) -> None:
    """
    分上下两道标注峰谷，带引导线。

    峰与谷在时间轴上是交替出现的，同一道里按水平距离避让即可：峰标注放在点上方、
    谷放在点下方，两个方向互不挤占，能比单道标注多显示一倍的点。

    Args:
        axes: 坐标轴。
        above: 放在点上方的条目 ``(x, y, text)``，按优先级排序。
        below: 放在点下方的条目。
        max_above: 上方最多标注数量。
        max_below: 下方最多标注数量。
        min_gap: 同侧标签之间的最小水平间隔（归一化 0~1）。
        offset: 标签与数据点的垂直距离（点）。
    """
    x_low, x_high = axes.get_xlim()
    span = (x_high - x_low) or 1.0

    for entries, limit, lane in ((above, max_above, "above"), (below, max_below, "below")):
        placed = []
        for x, y, text in entries:
            if len(placed) >= limit:
                break
            nx = (x - x_low) / span
            if any(abs(nx - px) < min_gap for px in placed):
                continue
            placed.append(nx)

            if nx > 0.94:
                horizontal, offset_x = "right", -4
            elif nx < 0.06:
                horizontal, offset_x = "left", 4
            else:
                horizontal, offset_x = "center", 0

            if lane == "above":
                xytext = (offset_x, offset)
                vertical = "bottom"
            else:
                xytext = (offset_x, -offset)
                vertical = "top"

            axes.annotate(
                text,
                xy=(x, y),
                xytext=xytext,
                textcoords="offset points",
                ha=horizontal,
                va=vertical,
                fontsize=6.5,
                color="#333333",
                bbox={"facecolor": "white", "edgecolor": "none", "alpha": 0.75, "pad": 0.6},
                arrowprops={
                    "arrowstyle": "-",
                    "color": "#999999",
                    "linewidth": 0.7,
                    "shrinkA": 1,
                    "shrinkB": 2,
                },
                annotation_clip=True,
            )


class BaseChartCanvas(FigureCanvasQTAgg):
    """
    固定高度的 Matplotlib 画布。

    高度固定、宽度随容器伸缩：图表放进滚动区后不会因为内容变化把整页抖来抖去。
    画布本身不画任何业务图形，只负责空状态、绘制回调与悬停提示的管线。
    """

    def __init__(self, parent: QWidget = None, height: int = 240, dpi: int = CHART_DPI):
        """
        初始化画布。

        Args:
            parent: 父控件。
            height: 画布高度（逻辑像素）。
            dpi: 绘图 DPI。
        """
        figure = Figure(
            figsize=(DEFAULT_CANVAS_WIDTH / dpi, height / dpi), dpi=dpi, layout=None
        )
        super().__init__(figure)
        self._canvas_height = height
        self._hover_provider: Optional[Callable] = None
        self.setParent(parent)
        self.setMinimumHeight(height)
        self.setMaximumHeight(height)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setMouseTracking(True)
        self.mpl_connect("motion_notify_event", self._onMotion)
        self.showHint("暂无数据")

    # ------------------------------------------------------------- 绘制

    def showHint(self, text: str) -> None:
        """
        用居中提示替换图表内容（空数据 / 降级场景）。

        Args:
            text: 提示文案。
        """
        figure = self.figure
        figure.clear()
        figure.subplots_adjust(left=0.02, right=0.98, bottom=0.02, top=0.98)
        axes = figure.add_subplot(111)
        axes.axis("off")
        axes.text(
            0.5,
            0.5,
            text,
            ha="center",
            va="center",
            color=EMPTY_HINT_COLOR,
            fontsize=10,
        )
        self.draw()

    def renderWith(self, draw: Callable[[Figure], None]) -> None:
        """
        清空画布并执行绘制回调。

        同步 ``draw()``：首帧若用 ``draw_idle()``，绘制会排到事件循环，用户看到的是
        半成品或裁切画面，滚动区也会因为布局未稳定而抖一下。

        Args:
            draw: 接收 ``Figure`` 的绘制函数。
        """
        figure = self.figure
        figure.clear()
        draw(figure)
        self.draw()

    # ------------------------------------------------------------- 悬停

    def setHoverProvider(self, provider: Optional[Callable]) -> None:
        """
        设置悬停读数回调。

        Args:
            provider: 接收 matplotlib ``motion_notify_event`` 并返回文本（无命中返回 None）
                的函数；传 None 表示关闭悬停。
        """
        self._hover_provider = provider

    def _onMotion(self, event) -> None:
        """
        motion 事件：把命中文本交给 QToolTip 展示。

        Args:
            event: matplotlib 的 motion 事件。
        """
        provider = self._hover_provider
        if provider is None or event.x is None or event.y is None:
            QToolTip.hideText()
            return
        try:
            text = provider(event)
        except Exception:
            text = None
        if text:
            # 用 Qt 的全局光标位置，而不是 matplotlib 的 event.x/y：
            # 后者的原点在左下角，直接换算到 Qt 会让提示框上下反向跟随鼠标。
            QToolTip.showText(QCursor.pos(), text, self)
        else:
            QToolTip.hideText()

    def leaveEvent(self, event) -> None:
        """
        鼠标离开画布时收起悬停提示。

        Args:
            event: Qt 事件。
        """
        QToolTip.hideText()
        super().leaveEvent(event)

    # ------------------------------------------------------------- 工具

    @staticmethod
    def nearestIndex(values, target: float) -> Optional[int]:
        """
        返回距离目标最近的序号（线性扫描，数据量只有千级，无需二分）。

        Args:
            values: 升序数值序列。
            target: 目标值。

        Returns:
            最近序号；序列为空时返回 None。
        """
        if not len(values):
            return None
        best_index = 0
        best_distance = abs(values[0] - target)
        for index, value in enumerate(values):
            distance = abs(value - target)
            if distance < best_distance:
                best_index = index
                best_distance = distance
        return best_index
