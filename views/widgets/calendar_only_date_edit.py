"""
仅允许日历下拉选择的日期控件模块。

提供禁止手动输入、只能通过日历下拉选择日期的日期控件，
用于避免录入时手写出非法日期格式。

实现要点：不使用 QDateEdit.setReadOnly()，因为 Qt 的只读状态会同时禁用
日历下拉按钮；改为把内部行编辑设为只读，从而在保留日历下拉的同时
屏蔽键盘输入、粘贴、拖放、滚轮与上下箭头步进。
"""

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QDateEdit

# 允许透传给基类的按键（焦点切换），其余按键不会导致手动输入
ALLOWED_KEYS = (Qt.Key_Tab, Qt.Key_Backtab)

# 会触发步进或整段跳转的按键，直接忽略
BLOCKED_KEYS = (
    Qt.Key_Up, Qt.Key_Down,
    Qt.Key_PageUp, Qt.Key_PageDown,
    Qt.Key_Home, Qt.Key_End,
)


class CalendarOnlyDateEdit(QDateEdit):
    """
    仅允许日历下拉选择的日期控件。

    日期只能点击下拉箭头在日历中选择；键盘输入、粘贴、拖放、滚轮调节
    与上下箭头步进均被屏蔽，Tab 焦点切换保持可用。
    """

    def __init__(self, parent=None):
        """
        初始化控件。

        Args:
            parent: 父控件。
        """
        super().__init__(parent)
        self.setCalendarPopup(True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setToolTip("禁止手动输入，请点击下拉箭头在日历中选择日期")

        line_edit = self.lineEdit()
        if line_edit is not None:
            line_edit.setReadOnly(True)
            line_edit.setAcceptDrops(False)
            line_edit.setContextMenuPolicy(Qt.NoContextMenu)

    def keyPressEvent(self, event) -> None:
        """屏蔽会修改日期或移动插入点的按键，仅保留焦点切换等按键。"""
        if event.key() in BLOCKED_KEYS:
            event.ignore()
            return

        super().keyPressEvent(event)

    def stepBy(self, steps: int) -> None:
        """忽略步进操作，避免通过上下箭头或滚动按钮修改日期。"""
        return

    def wheelEvent(self, event) -> None:
        """忽略滚轮操作，避免误改日期。"""
        event.ignore()
