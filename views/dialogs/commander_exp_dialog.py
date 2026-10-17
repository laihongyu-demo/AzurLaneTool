"""
指级经验对话框模块。

点击「数据看板 → 指挥官等级」卡片时弹出，承载原本放在「资源统计」页签里的
指级经验面板。做成独立窗口后，面板不再与魔方任务看板争抢同一页签的高度，
也避免了窄宽度下的横向挤压。
"""

from typing import Optional

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import QDialog, QDialogButtonBox, QVBoxLayout, QWidget

from services.commander_service import CommanderService
from views.widgets.commander_exp_panel import CommanderExpPanel


class CommanderExpDialog(QDialog):
    """
    指级经验对话框。

    非模态窗口：打开期间仍可操作主界面；面板内的写操作会通过 ``dataRefreshed``
    通知外部刷新看板卡片。
    """

    dataRefreshed = pyqtSignal()
    snapshotResult = pyqtSignal(object)

    def __init__(
        self,
        commander_service: Optional[CommanderService] = None,
        parent: QWidget = None
    ):
        """
        初始化指级经验对话框。

        Args:
            commander_service: 指挥官服务实例。
            parent: 父控件。
        """
        super().__init__(parent)
        self._commander_service = commander_service or CommanderService()
        self.setWindowTitle("指级经验")
        self.setModal(False)
        self.setMinimumSize(780, 620)
        self.resize(820, 680)
        self._initUi()
        self._connectSignals()

    def _initUi(self) -> None:
        """初始化用户界面。"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        self._panel = CommanderExpPanel(self._commander_service)
        layout.addWidget(self._panel, 1)

        buttons = QDialogButtonBox(QDialogButtonBox.Close, self)
        buttons.button(QDialogButtonBox.Close).setText("关闭")
        buttons.rejected.connect(self.close)
        layout.addWidget(buttons, 0, Qt.AlignRight)

    def _connectSignals(self) -> None:
        """连接信号与槽。"""
        self._panel.dataRefreshed.connect(self._onPanelDataRefreshed)
        self._panel.snapshotResult.connect(self._onPanelSnapshotResult)

    def _onPanelDataRefreshed(self) -> None:
        """面板数据刷新完成事件处理（转发给主窗口刷新卡片）。"""
        self.dataRefreshed.emit()

    def _onPanelSnapshotResult(self, result) -> None:
        """
        面板写操作结果事件处理（转发给状态栏）。

        Args:
            result: ``CommanderWriteResult`` 实例。
        """
        self.snapshotResult.emit(result)

    def refreshData(self) -> None:
        """刷新面板数据。"""
        self._panel.refreshData()

    def closeEvent(self, event) -> None:
        """关闭前再刷新一次，确保看板卡片与最新记录一致。"""
        self.dataRefreshed.emit()
        super().closeEvent(event)
