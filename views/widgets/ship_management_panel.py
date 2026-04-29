"""
舰娘管理面板模块。

整合舰娘解锁、认知觉醒和界限突破功能的界面组件。
"""

from typing import Optional

from PyQt5.QtWidgets import (
    QWidget, QGridLayout
)
from PyQt5.QtCore import pyqtSignal

from services.codex_unlock_service import CodexUnlockService, UnlockResult
from services.awaken_service import AwakenService, AwakenResult
from services.limit_break_service import LimitBreakService, LimitBreakResult
from views.widgets.codex_unlock_panel import CodexUnlockPanel
from views.widgets.awaken_panel import AwakenPanel
from views.widgets.limit_break_panel import LimitBreakPanel


class ShipManagementPanel(QWidget):
    """
    舰娘管理面板控件。

    整合舰娘解锁、认知觉醒和界限突破功能。
    """

    dataRefreshed = pyqtSignal()
    unlockResult = pyqtSignal(object)
    awakenResult = pyqtSignal(object)
    limitBreakResult = pyqtSignal(object)

    def __init__(
        self,
        unlock_service: Optional[CodexUnlockService] = None,
        awaken_service: Optional[AwakenService] = None,
        limit_break_service: Optional[LimitBreakService] = None,
        parent: QWidget = None
    ):
        """
        初始化舰娘管理面板。

        Args:
            unlock_service: 解锁服务实例。
            awaken_service: 觉醒服务实例。
            limit_break_service: 界限突破服务实例。
            parent: 父控件。
        """
        super().__init__(parent)
        self._unlock_service = unlock_service or CodexUnlockService()
        self._awaken_service = awaken_service or AwakenService()
        self._limit_break_service = limit_break_service or LimitBreakService()
        self._initUi()
        self._connectSignals()

    def _initUi(self) -> None:
        """初始化用户界面。"""
        layout = QGridLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(15)

        self._unlockPanel = CodexUnlockPanel(self._unlock_service)
        self._awakenPanel = AwakenPanel(self._awaken_service)
        self._limitBreakPanel = LimitBreakPanel(self._limit_break_service)

        layout.addWidget(self._unlockPanel, 0, 0)
        layout.addWidget(self._awakenPanel, 0, 1)
        layout.addWidget(self._limitBreakPanel, 1, 0)

        layout.setRowStretch(0, 1)
        layout.setRowStretch(1, 1)
        layout.setColumnStretch(0, 1)
        layout.setColumnStretch(1, 1)

    def _connectSignals(self) -> None:
        """连接信号与槽。"""
        self._unlockPanel.dataRefreshed.connect(self._onUnlockDataRefreshed)
        self._unlockPanel.unlockResult.connect(self._onUnlockResult)
        self._awakenPanel.dataRefreshed.connect(self._onAwakenDataRefreshed)
        self._awakenPanel.awakenResult.connect(self._onAwakenResult)
        self._limitBreakPanel.dataRefreshed.connect(self._onLimitBreakDataRefreshed)
        self._limitBreakPanel.limitBreakResult.connect(self._onLimitBreakResult)

    def _onUnlockDataRefreshed(self) -> None:
        """舰娘解锁数据刷新完成事件处理。"""
        self.dataRefreshed.emit()

    def _onUnlockResult(self, result: UnlockResult) -> None:
        """解锁结果事件处理。"""
        self.unlockResult.emit(result)

    def _onAwakenDataRefreshed(self) -> None:
        """认知觉醒数据刷新完成事件处理。"""
        self.dataRefreshed.emit()

    def _onAwakenResult(self, result: AwakenResult) -> None:
        """觉醒结果事件处理。"""
        self.awakenResult.emit(result)

    def _onLimitBreakDataRefreshed(self) -> None:
        """界限突破数据刷新完成事件处理。"""
        self.dataRefreshed.emit()

    def _onLimitBreakResult(self, result: LimitBreakResult) -> None:
        """界限突破结果事件处理。"""
        self.limitBreakResult.emit(result)

    def refreshData(self) -> None:
        """刷新界面数据。"""
        self._unlockPanel.refreshData()
        self._awakenPanel.refreshData()
        self._limitBreakPanel.refreshData()
