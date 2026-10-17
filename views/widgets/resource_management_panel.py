"""
资源统计面板模块。

「资源统计」页签的容器控件：本期承载「魔方任务看板」与「指级经验」两个面板；
魔方 / 红尖尖的手工录入与列表仍推迟到 #17（见 docs/资源统计迁移需求文档_20261017.md 附录 D）。
"""

from typing import Optional

from PyQt5.QtCore import pyqtSignal
from PyQt5.QtWidgets import QGridLayout, QWidget

from services.commander_service import CommanderService, CommanderWriteResult
from services.cube_task_service import CubeTaskService, CubeTaskWriteResult
from views.widgets.commander_exp_panel import CommanderExpPanel
from views.widgets.cube_task_board_panel import CubeTaskBoardPanel


class ResourceManagementPanel(QWidget):
    """
    资源统计面板控件。

    与「舰娘管理」页签保持同一组织方式：一个页签内以网格承载多个面板。
    """

    dataRefreshed = pyqtSignal()
    snapshotResult = pyqtSignal(object)
    taskResult = pyqtSignal(object)

    def __init__(
        self,
        commander_service: Optional[CommanderService] = None,
        cube_task_service: Optional[CubeTaskService] = None,
        parent: QWidget = None
    ):
        """
        初始化资源统计面板。

        Args:
            commander_service: 指挥官服务实例。
            cube_task_service: 魔方任务看板服务实例。
            parent: 父控件。
        """
        super().__init__(parent)
        self._commander_service = commander_service or CommanderService()
        self._cube_task_service = cube_task_service or CubeTaskService()
        self._initUi()
        self._connectSignals()

    def _initUi(self) -> None:
        """初始化用户界面。"""
        layout = QGridLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(15)

        self._taskBoardPanel = CubeTaskBoardPanel(self._cube_task_service)
        self._commanderPanel = CommanderExpPanel(self._commander_service)

        layout.addWidget(self._taskBoardPanel, 0, 0)
        layout.addWidget(self._commanderPanel, 1, 0)

    def _connectSignals(self) -> None:
        """连接信号与槽。"""
        self._taskBoardPanel.dataRefreshed.connect(self._onDataRefreshed)
        self._taskBoardPanel.resultReady.connect(self._onTaskResult)
        self._commanderPanel.dataRefreshed.connect(self._onDataRefreshed)
        self._commanderPanel.snapshotResult.connect(self._onSnapshotResult)

    def _onDataRefreshed(self) -> None:
        """子面板数据刷新完成事件处理。"""
        self.dataRefreshed.emit()

    def _onTaskResult(self, result: CubeTaskWriteResult) -> None:
        """任务看板写操作结果事件处理。"""
        self.taskResult.emit(result)

    def _onSnapshotResult(self, result: CommanderWriteResult) -> None:
        """快照写操作结果事件处理。"""
        self.snapshotResult.emit(result)

    def refreshData(self) -> None:
        """刷新界面数据。"""
        self._taskBoardPanel.refreshData()
        self._commanderPanel.refreshData()
