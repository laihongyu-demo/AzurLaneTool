"""
图表样式模块。

统一 matplotlib 的字体、DPI 与分类色板（#19 数据分析看板）。

matplotlib 默认字体不含中文，中文标签会退化成方框；这里按候选列表探测系统字体并缓存，
避免每次重绘都遍历字体库。样式只在首次绘图前应用一次，重复调用无副作用。
"""

import matplotlib

# 中文字体候选：Windows 自带前两个，其余为跨平台兜底
CHART_FONT_CANDIDATES = (
    "Microsoft YaHei",
    "SimHei",
    "Noto Sans CJK SC",
    "Source Han Sans SC",
    "PingFang SC",
)

# 画布 DPI：与 Qt 逻辑像素 1:1，避免高分屏下文字被放大模糊
CHART_DPI = 100

# 分类色板：类目占比等需要多色的图共用，固定顺序避免每次重绘颜色漂移
CHART_PALETTE = (
    "#5B8FF9",
    "#61DDAA",
    "#65789B",
    "#F6BD16",
    "#7262FD",
    "#78D3F8",
    "#9661BC",
    "#F6903D",
    "#008685",
    "#F08BB4",
    "#E8684A",
    "#6DC8EC",
)

# 语义色：收入 / 支出 / 净额 / 手填结余锚点
CHART_INCOME_COLOR = "#5B8FF9"
CHART_EXPENSE_COLOR = "#F6903D"
CHART_NET_COLOR = "#5AD8A6"
CHART_LINE_COLOR = "#1F6FEB"
CHART_ANCHOR_COLOR = "#E8684A"
CHART_REFERENCE_COLOR = "#8C8C8C"
CHART_TEXT_COLOR = "#595959"
CHART_GRID_COLOR = "#D9D9D9"

_FONT_NAME = None
_STYLE_APPLIED = False


def resolveCjkFont() -> str:
    """
    探测可用的中文字体名。

    结果缓存：字体列表在进程内不会变化，重复遍历 `fontManager` 既慢又无收益。

    Returns:
        字体名；系统没有任何候选中文字体时返回空串（此时 matplotlib 会退回默认字体，
        中文可能显示为方框，但不影响程序运行）。
    """
    global _FONT_NAME
    if _FONT_NAME is not None:
        return _FONT_NAME

    from matplotlib import font_manager

    available = {font.name for font in font_manager.fontManager.ttflist}
    for candidate in CHART_FONT_CANDIDATES:
        if candidate in available:
            _FONT_NAME = candidate
            return _FONT_NAME
    _FONT_NAME = ""
    return _FONT_NAME


def applyChartStyle() -> None:
    """
    应用全局图表样式（幂等）。

    - 中文字体：按 :func:`resolveCjkFont` 的结果设置，探测失败时保留默认；
    - 负号：关闭 unicode minus，避免中文字体下负号显示为方框；
    - 字号：坐标轴与图例统一收紧，适配 1024×768 的默认窗口。
    """
    global _STYLE_APPLIED
    if _STYLE_APPLIED:
        return

    font_name = resolveCjkFont()
    if font_name:
        matplotlib.rcParams["font.sans-serif"] = [font_name, "DejaVu Sans"]
    matplotlib.rcParams["axes.unicode_minus"] = False
    matplotlib.rcParams["font.size"] = 9
    matplotlib.rcParams["axes.titlesize"] = 10
    matplotlib.rcParams["axes.labelsize"] = 9
    matplotlib.rcParams["xtick.labelsize"] = 8
    matplotlib.rcParams["ytick.labelsize"] = 8
    matplotlib.rcParams["legend.fontsize"] = 8
    matplotlib.rcParams["axes.edgecolor"] = CHART_GRID_COLOR
    matplotlib.rcParams["axes.labelcolor"] = CHART_TEXT_COLOR
    matplotlib.rcParams["xtick.color"] = CHART_TEXT_COLOR
    matplotlib.rcParams["ytick.color"] = CHART_TEXT_COLOR
    matplotlib.rcParams["text.color"] = CHART_TEXT_COLOR
    _STYLE_APPLIED = True


def paletteColor(index: int) -> str:
    """
    按序号取分类色。

    Args:
        index: 从 0 开始的序号。

    Returns:
        十六进制颜色；超出色板长度时循环取用。
    """
    return CHART_PALETTE[index % len(CHART_PALETTE)]
