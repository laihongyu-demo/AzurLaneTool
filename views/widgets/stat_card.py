"""
自定义控件模块。

提供项目中可复用的自定义 UI 控件。
"""

import time
from PyQt5.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QMouseEvent

# 日环比角标的三档配色（红涨绿跌，与需求方约定一致）
BADGE_TONE_STYLES = {
    "up": "font-size: 14px; font-weight: bold; color: #c62828;",
    "down": "font-size: 14px; font-weight: bold; color: #2e7d32;",
    "flat": "font-size: 14px; font-weight: bold; color: #757575;",
}

# 标题角标：预计升级是信息型（蓝），与数值右侧的红涨绿跌方向语义分开；
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

        self._titleLabel = QLabel(self._title)
        self._titleLabel.setStyleSheet("font-size: 14px; color: #666;")
        self._titleLabel.setAlignment(Qt.AlignCenter)

        # 标题 + 标题角标同一行：角标只占用标题行的空白，不会撑宽数值行
        header_row = QHBoxLayout()
        header_row.setSpacing(6)
        header_row.addStretch()
        header_row.addWidget(self._titleLabel, 0, Qt.AlignVCenter)
        self._titleBadgeLabel = QLabel("")
        self._titleBadgeLabel.setAlignment(Qt.AlignCenter)
        self._titleBadgeLabel.setVisible(False)
        header_row.addWidget(self._titleBadgeLabel, 0, Qt.AlignVCenter)
        header_row.addStretch()
        layout.addLayout(header_row)

        self._valueLabel = QLabel(self._value)
        self._valueLabel.setStyleSheet("font-size: 28px; font-weight: bold; color: #333;")
        self._valueLabel.setAlignment(Qt.AlignCenter)

        # 数值 + 角标同一行：角标贴数值右侧，居中后整体仍居中，卡片高度不变
        value_row = QHBoxLayout()
        value_row.setSpacing(6)
        value_row.addStretch()
        value_row.addWidget(self._valueLabel, 0, Qt.AlignVCenter)
        self._badgeLabel = QLabel("")
        self._badgeLabel.setVisible(False)
        value_row.addWidget(self._badgeLabel, 0, Qt.AlignVCenter)
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
        设置数值右侧的角标。

        Args:
            text: 角标文案，如 ``↑111`` / ``↓111`` / ``—``。
            tone: 配色档位，``up`` / ``down`` / ``flat``。
        """
        self._badge_text = text
        self._badge_tone = tone
        self._badgeLabel.setText(text)
        self._badgeLabel.setStyleSheet(BADGE_TONE_STYLES.get(tone, BADGE_TONE_STYLES["flat"]))
        self._badgeLabel.setVisible(bool(text))

    def clearBadge(self) -> None:
        """移除角标（数据不可比或卡片降级时调用）。"""
        self._badge_text = ""
        self._badge_tone = ""
        self._badgeLabel.clear()
        self._badgeLabel.setVisible(False)

    def badgeText(self) -> str:
        """获取当前数值右侧角标文案；无角标时为空串。"""
        return self._badge_text

    def badgeTone(self) -> str:
        """获取当前数值右侧角标配色档位；无角标时为空串。"""
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
        self._titleBadgeLabel.setText(text)
        self._titleBadgeLabel.setStyleSheet(
            TITLE_BADGE_TONE_STYLES.get(tone, TITLE_BADGE_TONE_STYLES["info"])
        )
        self._titleBadgeLabel.setVisible(bool(text))

    def clearTitleBadge(self) -> None:
        """移除标题角标（无快照 / 无法估算 / 错误降级时调用）。"""
        self._title_badge_text = ""
        self._title_badge_tone = ""
        self._titleBadgeLabel.clear()
        self._titleBadgeLabel.setVisible(False)

    def titleBadgeText(self) -> str:
        """获取当前标题角标文案；无角标时为空串。"""
        return self._title_badge_text

    def titleBadgeTone(self) -> str:
        """获取当前标题角标配色档位；无角标时为空串。"""
        return self._title_badge_tone
