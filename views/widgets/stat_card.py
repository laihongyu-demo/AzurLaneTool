"""
自定义控件模块。

提供项目中可复用的自定义 UI 控件。
"""

import time
from PyQt5.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget
from PyQt5.QtCore import QSize, Qt, pyqtSignal
from PyQt5.QtGui import QMouseEvent

# 角标宽度上限：角标文案变长（↓30 → 未记录 → 数据异常）时只在自己的格子里
# 省略，不给整行布局施压（#38）。
BADGE_MAX_WIDTH = 96
# 标题角标（「预计 27.7 天后升级」这类胶囊标签）比数值角标长，单独放宽上限
TITLE_BADGE_MAX_WIDTH = 180
# 文本宽度安全余量：字体取整与字距会让 advance 比实际绘制宽度略小，
# 留 4px 避免「刚好放得下」时被省略掉最后一个字
TEXT_SLACK_PX = 4
# QWidget 的默认最大宽度（Qt 的 QWIDGETSIZE_MAX），清除角标时恢复
WIDGET_MAX_WIDTH = 16777215

# 日环比角标的三档配色（红涨绿跌，与需求方约定一致）
BADGE_TONE_STYLES = {
    "up": "font-size: 14px; font-weight: bold; color: #c62828;",
    "down": "font-size: 14px; font-weight: bold; color: #2e7d32;",
    "flat": "font-size: 14px; font-weight: bold; color: #757575;",
}

# 标题角标：预计升级是信息型（蓝），与标题行日环比角标的红涨绿跌方向语义分开；
# 满级是完成态（绿）。浅色底 + 圆角让它像标签而不是标题的一部分。
TITLE_BADGE_TONE_STYLES = {
    "info": (
        "font-size: 12px; font-weight: bold; color: #1565c0;"
        "background-color: #e3f2fd; border-radius: 9px; padding: 1px 7px;"
    ),
    "success": (
        "font-size: 12px; font-weight: bold; color: #2e7d32;"
        "background-color: #e8f5e9; border-radius: 9px; padding: 1px 7px;"
    ),
}


class ElidedLabel(QLabel):
    """
    按可用宽度省略文字的标签。

    原生 ``QLabel`` 把完整文本宽度同时当作首选宽度与最小宽度：布局给不足时文字
    被左右两侧直接裁掉，居中绘制时首位数字会消失（#38）。这里把三件事拆开：

    - ``sizeHint()``：完整文本宽度 —— 空间足够时显示全文，不出现省略号；
    - ``minimumSizeHint()``：只要求放得下省略号 —— 空间不足时允许压缩；
    - 实际绘制文本：按当前宽度用 ``QFontMetrics.elidedText()`` 省略，
      中间省略保证首尾可辨；发生省略时 tooltip 回退为全文。

    样式表内边距会写进 ``contentsMargins()``，所以 ``contentsRect()`` 就是可用文字区，
    这里不再额外扣除 padding。

    Args:
        text: 初始文本。
        parent: 父控件。
        mode: 省略位置，``Qt.ElideMiddle``（数值）/ ``Qt.ElideRight``（标题、角标）。
    """

    def __init__(self, text: str = "", parent: QWidget = None, mode=Qt.ElideMiddle):
        super().__init__(parent)
        self._full_text = ""
        self._display_text = ""
        self._mode = mode
        self.setMinimumWidth(0)
        self.setText(text)

    def setText(self, text: str) -> None:
        """
        设置完整文本；实际显示按当前宽度省略。

        Args:
            text: 完整文本。
        """
        text = text or ""
        changed = text != self._full_text
        self._full_text = text
        self._refreshDisplayedText()
        if changed:
            self.updateGeometry()

    def fullText(self) -> str:
        """获取完整文本（不受省略影响）。"""
        return self._full_text

    def clear(self) -> None:
        """清空文本（走 setText，保持完整文本与显示文本同步）。"""
        self.setText("")

    def displayedText(self) -> str:
        """获取当前实际绘制的文本（可能带省略号）。"""
        return self._display_text

    def isElided(self) -> bool:
        """当前是否因宽度不足而省略。"""
        return bool(self._display_text) and self._display_text != self._full_text

    def sizeHint(self) -> QSize:
        """首选宽度取完整文本宽度，保证空间足够时不省略。"""
        base = super().sizeHint()
        margin = self.contentsMargins()
        width = (
            self.fontMetrics().horizontalAdvance(self._full_text)
            + margin.left() + margin.right()
            + TEXT_SLACK_PX
        )
        return QSize(width, base.height())

    def minimumSizeHint(self) -> QSize:
        """最小宽度只保留省略号，允许窄窗口压缩而不是硬裁掉首字。"""
        base = super().minimumSizeHint()
        margin = self.contentsMargins()
        width = self.fontMetrics().horizontalAdvance("…") + margin.left() + margin.right()
        return QSize(width, base.height())

    def resizeEvent(self, event) -> None:
        """宽度变化后重新计算省略文本。"""
        super().resizeEvent(event)
        self._refreshDisplayedText()

    def changeEvent(self, event) -> None:
        """字体/样式变化后字宽会变，重新计算省略文本。"""
        super().changeEvent(event)
        self._refreshDisplayedText()

    def _availableTextWidth(self) -> int:
        """文字实际可用的宽度（``contentsRect()`` 已扣掉样式表内边距）。"""
        return self.contentsRect().width()

    def _refreshDisplayedText(self) -> None:
        """按当前宽度把完整文本省略后交给 QLabel 绘制。"""
        width = self._availableTextWidth()
        if not self._full_text or width <= 0:
            # 还没有有效宽度（构造期 / 未布局）时先保留全文，等 resizeEvent 再算
            display = self._full_text
        else:
            display = self.fontMetrics().elidedText(self._full_text, self._mode, width)
        if display == self._display_text:
            return
        self._display_text = display
        super().setText(display)
        self._refreshToolTip()

    def _refreshToolTip(self) -> None:
        """被省略时给出全文；未省略时交回父卡片自己的说明性提示。"""
        self.setToolTip(self._full_text if self.isElided() else "")


def _applyBadgeWidth(label: ElidedLabel, text: str, max_width: int) -> None:
    """
    按文案宽度给角标设置宽度上限（超长封顶，空间不足时由标签内部省略）。

    角标宽度受上限约束后，文案变长（↓30 → 未记录 → 数据异常）不会抬高卡片首选
    宽度，也就不会挤占同排其他卡片（#38）；封顶则保证长文案不会把卡片撑得过宽。
    用上限而不是固定宽度，是为了让极窄卡片里角标先退化为省略号，把宽度留给主数值。

    Args:
        label: 角标标签。
        text: 角标文案。
        max_width: 角标宽度上限。
    """
    # 样式表里的字号要等 polish 之后才写回控件字体，先强制应用再测量
    label.ensurePolished()
    margin = label.contentsMargins()
    text_width = (
        label.fontMetrics().horizontalAdvance(text)
        + margin.left() + margin.right()
        + TEXT_SLACK_PX
    )
    label.setMaximumWidth(max(0, min(text_width, max_width)))


class StatCard(QWidget):
    """
    统计卡片控件。

    用于展示单个统计指标，包含标题和数值。
    支持点击交互。
    """

    clicked = pyqtSignal()

    def __init__(self, title: str = "", value: str = "", parent: QWidget = None, clickable: bool = False):
        """
        初始化统计卡片。

        Args:
            title: 卡片标题。
            value: 卡片数值。
            parent: 父控件。
            clickable: 是否可点击。
        """
        super().__init__(parent)
        self._title = title
        self._value = value
        self._clickable = clickable
        self._last_click_time = 0
        self._click_threshold = 500
        self._initUi()

    def _initUi(self) -> None:
        """初始化用户界面。"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(15, 15, 15, 15)
        layout.setSpacing(10)

        self._titleLabel = ElidedLabel(self._title, mode=Qt.ElideRight)
        self._titleLabel.setStyleSheet("font-size: 14px; color: #666;")
        self._titleLabel.setAlignment(Qt.AlignCenter)

        # 标题 + 角标同一行：角标只占用标题行的空白，不参与数值行宽度竞争（#38）
        header_row = QHBoxLayout()
        header_row.setSpacing(6)
        header_row.addStretch()
        header_row.addWidget(self._titleLabel, 0, Qt.AlignVCenter)
        # 日环比状态角标（↓30 / 未记录 / 数据异常）：贴着标题，语义是「这张卡今天的状态」
        self._badgeLabel = ElidedLabel("", mode=Qt.ElideRight)
        self._badgeLabel.setVisible(False)
        header_row.addWidget(self._badgeLabel, 0, Qt.AlignVCenter)
        # 标题角标（预计升级 / 已满级）：带底色的胶囊，与日环比角标配色语义分开
        self._titleBadgeLabel = ElidedLabel("", mode=Qt.ElideRight)
        self._titleBadgeLabel.setAlignment(Qt.AlignCenter)
        self._titleBadgeLabel.setVisible(False)
        header_row.addWidget(self._titleBadgeLabel, 0, Qt.AlignVCenter)
        header_row.addStretch()
        layout.addLayout(header_row)

        self._valueLabel = ElidedLabel(self._value, mode=Qt.ElideMiddle)
        self._valueLabel.setStyleSheet("font-size: 28px; font-weight: bold; color: #333;")
        self._valueLabel.setAlignment(Qt.AlignCenter)

        # 数值行只放数值：宽度完全由数值本身决定，角标变化不会挤压数值与同排卡片
        value_row = QHBoxLayout()
        value_row.setSpacing(6)
        value_row.addStretch()
        value_row.addWidget(self._valueLabel, 0, Qt.AlignVCenter)
        value_row.addStretch()
        layout.addLayout(value_row)

        self._badge_text = ""
        self._badge_tone = ""
        self._title_badge_text = ""
        self._title_badge_tone = ""

        self._updateStyle()

    def _updateStyle(self) -> None:
        """更新样式。"""
        if self._clickable:
            self.setStyleSheet("""
                StatCard {
                    background-color: #fff;
                    border: 1px solid #e0e0e0;
                    border-radius: 8px;
                }
                StatCard:hover {
                    background-color: #f5f5f5;
                    border: 1px solid #bdbdbd;
                }
            """)
            self.setCursor(Qt.PointingHandCursor)
        else:
            self.setStyleSheet("""
                StatCard {
                    background-color: #fff;
                    border: 1px solid #e0e0e0;
                    border-radius: 8px;
                }
            """)
            self.setCursor(Qt.ArrowCursor)

    def setClickable(self, clickable: bool) -> None:
        """
        设置是否可点击。

        Args:
            clickable: 是否可点击。
        """
        self._clickable = clickable
        self._updateStyle()

    def clickable(self) -> bool:
        """
        当前是否可点击。

        Returns:
            True 表示卡片可点击并会发出 ``clicked`` 信号。
        """
        return self._clickable

    def mousePressEvent(self, event: QMouseEvent) -> None:
        """鼠标按下事件处理。"""
        if event.button() == Qt.LeftButton and self._clickable:
            current_time = int(time.time() * 1000)
            if current_time - self._last_click_time >= self._click_threshold:
                self._last_click_time = current_time
                self.clicked.emit()
        super().mousePressEvent(event)

    def setTitle(self, title: str) -> None:
        """
        设置卡片标题。

        Args:
            title: 新标题。
        """
        self._title = title
        self._titleLabel.setText(title)

    def setValue(self, value: str) -> None:
        """
        设置卡片数值。

        Args:
            value: 新数值。
        """
        self._value = value
        self._valueLabel.setText(value)

    def title(self) -> str:
        """获取当前标题。"""
        return self._title

    def value(self) -> str:
        """获取当前数值。"""
        return self._value

    def setBadge(self, text: str, tone: str = "flat") -> None:
        """
        设置标题行右侧的状态角标（日环比 / 未记录 / 数据异常）。

        角标贴在标题行，不占数值行，因此文案变长也不会挤压数值或同排卡片（#38）。

        Args:
            text: 角标文案，如 ``↑111`` / ``↓111`` / ``—``。
            tone: 配色档位，``up`` / ``down`` / ``flat``。
        """
        self._badge_text = text
        self._badge_tone = tone
        # 先定字号再量宽度：宽度上限依赖当前字体度量
        self._badgeLabel.setStyleSheet(BADGE_TONE_STYLES.get(tone, BADGE_TONE_STYLES["flat"]))
        self._badgeLabel.setText(text)
        _applyBadgeWidth(self._badgeLabel, text, BADGE_MAX_WIDTH)
        self._badgeLabel.setVisible(bool(text))

    def clearBadge(self) -> None:
        """移除角标（数据不可比或卡片降级时调用）。"""
        self._badge_text = ""
        self._badge_tone = ""
        self._badgeLabel.clear()
        self._badgeLabel.setMaximumWidth(WIDGET_MAX_WIDTH)
        self._badgeLabel.setVisible(False)

    def badgeText(self) -> str:
        """获取当前状态角标文案；无角标时为空串。"""
        return self._badge_text

    def badgeTone(self) -> str:
        """获取当前状态角标配色档位；无角标时为空串。"""
        return self._badge_tone

    def setTitleBadge(self, text: str, tone: str = "info") -> None:
        """
        设置标题右侧的角标。

        角标与标题同处标题行，只占用标题行的空白，不会把数值行撑宽；
        适合“预计升级”这类不属于主数值本身的附加信息。

        Args:
            text: 角标文案，如 ``预计 22.0 天后升级`` / ``已满级``。
            tone: 配色档位，``info``（信息）/ ``success``（完成）。
        """
        self._title_badge_text = text
        self._title_badge_tone = tone
        # 先定字号再量宽度：宽度上限依赖当前字体度量
        self._titleBadgeLabel.setStyleSheet(
            TITLE_BADGE_TONE_STYLES.get(tone, TITLE_BADGE_TONE_STYLES["info"])
        )
        self._titleBadgeLabel.setText(text)
        _applyBadgeWidth(self._titleBadgeLabel, text, TITLE_BADGE_MAX_WIDTH)
        self._titleBadgeLabel.setVisible(bool(text))

    def clearTitleBadge(self) -> None:
        """移除标题角标（无快照 / 无法估算 / 错误降级时调用）。"""
        self._title_badge_text = ""
        self._title_badge_tone = ""
        self._titleBadgeLabel.clear()
        self._titleBadgeLabel.setMaximumWidth(WIDGET_MAX_WIDTH)
        self._titleBadgeLabel.setVisible(False)

    def titleBadgeText(self) -> str:
        """获取当前标题角标文案；无角标时为空串。"""
        return self._title_badge_text

    def titleBadgeTone(self) -> str:
        """获取当前标题角标配色档位；无角标时为空串。"""
        return self._title_badge_tone
