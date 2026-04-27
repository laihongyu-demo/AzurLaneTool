"""
统计卡片组件模块。

定义可点击的统计卡片控件。
"""

from typing import Optional

from PyQt5.QtWidgets import QWidget, QVBoxLayout, QLabel, QPushButton
from PyQt5.QtCore import pyqtSignal, Qt


class StatCard(QPushButton):
    """
    统计卡片控件。

    显示标题和数值，支持点击事件。

    Signals:
        clicked: 点击信号。
    """

    def __init__(
        self,
        title: str,
        value: str = "-",
        clickable: bool = False,
        parent: Optional[QWidget] = None
    ):
        """
        初始化统计卡片。

        Args:
            title: 卡片标题。
            value: 卡片数值。
            clickable: 是否可点击。
            parent: 父控件。
        """
        super().__init__(parent)
        self._title = title
        self._value = value
        self._clickable = clickable

        self._initUi()

    def _initUi(self) -> None:
        """初始化用户界面。"""
        self.setFixedSize(150, 80)
        self.setStyleSheet("""
            QPushButton {
                background-color: transparent;
                border: none;
                text-align: center;
                padding: 5px;
            }
            QPushButton:hover {
                background-color: transparent;
            }
            QPushButton:pressed {
                background-color: transparent;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 5, 10, 5)
        layout.setSpacing(5)

        self._titleLabel = QLabel(self._title)
        self._titleLabel.setAlignment(Qt.AlignCenter)
        self._titleLabel.setStyleSheet("font-size: 19px; color: #000000; border: none; background: transparent;")

        self._valueLabel = QLabel(self._value)
        self._valueLabel.setAlignment(Qt.AlignCenter)
        self._valueLabel.setStyleSheet("font-size: 18px; color: #333; border: none; background: transparent;")

        layout.addWidget(self._titleLabel)
        layout.addWidget(self._valueLabel)

        if not self._clickable:
            self.setEnabled(False)
            self.setStyleSheet("""
                QPushButton {
                    background-color: transparent;
                    border: none;
                    text-align: center;
                    padding: 5px;
                }
            """)

    def setValue(self, value: str) -> None:
        """
        设置卡片数值。

        Args:
            value: 新的数值字符串。
        """
        self._value = value
        self._valueLabel.setText(value)

    def value(self) -> str:
        """
        获取当前数值。

        Returns:
            当前数值字符串。
        """
        return self._value

    def title(self) -> str:
        """
        获取卡片标题。

        Returns:
            卡片标题。
        """
        return self._title
