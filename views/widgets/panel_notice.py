"""
面板内提示条模块。

页签面板在 ``__init__`` 里就要读库；此阶段弹模态框会把主窗口构建卡住
（空库 / 缺表时表现为「启动即弹框」，无头环境直接崩溃，#28）。因此
「场景类」问题改为在面板内就地提示：没有错误时控件隐藏，布局与原先一致。
"""

from typing import Optional

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QLabel, QWidget

# 提示条配色沿用项目既有的警示橙，避免与错误红（写操作失败）混淆
NOTICE_STYLE = (
    "QLabel {"
    " background: #fff4e5; border: 1px solid #f0b357; border-radius: 4px;"
    " color: #8a4b00; padding: 6px 10px; font-size: 12px;"
    "}"
)


class PanelNoticeLabel(QLabel):
    """
    面板顶部的就地提示条。

    用于替代「面板构造期 / 刷新期」的模态错误框：只在有错误时显示，
    恢复成功后立即隐藏，不改变正常数据下的界面布局。
    """

    def __init__(self, parent: Optional[QWidget] = None):
        """
        初始化提示条。

        Args:
            parent: 父控件。
        """
        super().__init__(parent)
        self.setWordWrap(True)
        self.setStyleSheet(NOTICE_STYLE)
        # 允许用户复制提示文案，便于把库缺失信息贴给他人排查
        self.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.hide()

    def showError(self, message: str) -> None:
        """
        显示一条错误提示。

        Args:
            message: 面向用户的中文提示（由 ``utils.error_messages`` 生成）。
        """
        self.setText(message)
        self.show()

    def clearError(self) -> None:
        """清空并隐藏提示条（数据读取恢复正常时调用）。"""
        self.setText("")
        self.hide()

    def hasError(self) -> bool:
        """
        当前是否处于错误提示状态。

        Returns:
            提示条可见且文案非空时返回 True。
        """
        return not self.isHidden() and bool(self.text())
