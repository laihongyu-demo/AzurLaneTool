"""
资源统计面板模块。

「资源统计」页签承载「魔方任务看板」，并为后续常规录入（活动建造、礼包等）预留位置；
指级经验已迁移到「指挥官等级」卡片的独立窗口（见 ``views/dialogs/commander_exp_dialog.py``）。
"""

from typing import Optional

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QFrame, QGroupBox, QLabel, QScrollArea, QVBoxLayout, QWidget,
)

from services.cube_task_service import CubeTaskService, CubeTaskWriteResult
from views.widgets.cube_task_board_panel import CubeTaskBoardPanel


class ResourceManagementPanel(QWidget):
    """
    资源统计面板控件。

    内容整体可垂直滚动：看板之外还给后续常规录入表单留了空间，内容变高时滚动浏览，
    而不是把控件压扁。
    """

    dataRefreshed = pyqtSignal()
    taskResult = pyqtSignal(object)

    def __init__(
        self,
        cube_task_service: Optional[CubeTaskService] = None,
        parent: QWidget = None
    ):
        """
        初始化资源统计面板。

        Args:
            cube_task_service: 魔方任务看板服务实例。
            parent: 父控件。
        """
        super().__init__(parent)
        self._cube_task_service = cube_task_service or CubeTaskService()
        self._initUi()
        self._connectSignals()

    def _initUi(self) -> None:
        """初始化用户界面。"""
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(15)

        self._taskBoardPanel = CubeTaskBoardPanel(self._cube_task_service)
        layout.addWidget(self._taskBoardPanel)
        layout.addWidget(self._buildReservedGroup())
        layout.addStretch()

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        scroll.setWidget(content)

        outer.addWidget(scroll)

    def _buildReservedGroup(self) -> QGroupBox:
        """
        构建后续常规录入的占位分组。

        Returns:
            占位分组控件。
        """
        group = QGroupBox("常规录入")
        layout = QVBoxLayout(group)
        layout.setContentsMargins(12, 16, 12, 12)

        hint = QLabel(
            "活动建造、特型建造、礼包等非固定收支的手工录入表单将加入本区域"
            "（规划见 issue #17）。固定奖励请使用上方的任务看板。",
            self,
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #888;")
        layout.addWidget(hint)
        return group

    def _connectSignals(self) -> None:
        """连接信号与槽。"""
        self._taskBoardPanel.dataRefreshed.connect(self._onDataRefreshed)
        self._taskBoardPanel.resultReady.connect(self._onTaskResult)

    def _onDataRefreshed(self) -> None:
        """子面板数据刷新完成事件处理。"""
        self.dataRefreshed.emit()

    def _onTaskResult(self, result: CubeTaskWriteResult) -> None:
        """任务看板写操作结果事件处理。"""
        self.taskResult.emit(result)

    def refreshData(self) -> None:
        """刷新界面数据。"""
        self._taskBoardPanel.refreshData()
