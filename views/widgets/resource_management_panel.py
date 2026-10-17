"""
资源统计面板模块。

页签级结构：
- 「魔方任务看板」：内含任务 / 每月签到 / 世界巡游 / 常规录入四个同级分组；
- 「红尖尖任务看板」：与魔方任务看板同级，暂为占位（红尖尖目前没有固定奖励任务）；
- 指级经验已迁移到「指挥官等级」卡片的独立窗口。

整页放在滚动区里，内容变高时滚动浏览。
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

    与「舰娘管理」页签同一组织方式：一个页签承载多个页签级看板；整体可垂直滚动。
    """

    dataRefreshed = pyqtSignal()
    taskResult = pyqtSignal(object)
    entryResult = pyqtSignal(object)

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
        layout.addWidget(self._buildRedGemBoard())
        layout.addStretch()

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        scroll.setWidget(content)

        outer.addWidget(scroll)

    def _buildRedGemBoard(self) -> QGroupBox:
        """
        构建红尖尖任务看板（与魔方任务看板同级，暂为占位）。

        Returns:
            占位分组控件。
        """
        group = QGroupBox("红尖尖任务看板")
        layout = QVBoxLayout(group)
        layout.setContentsMargins(12, 16, 12, 12)

        hint = QLabel(
            "红尖尖目前没有固定数量的周期性来源，暂无任务卡片。"
            "后续如出现同类固定奖励（或需要手工录入），将在此接入（见 issue #17）。",
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
        self._taskBoardPanel.entryResult.connect(self.entryResult.emit)

    def _onDataRefreshed(self) -> None:
        """子面板数据刷新完成事件处理。"""
        self.dataRefreshed.emit()

    def _onTaskResult(self, result: CubeTaskWriteResult) -> None:
        """任务看板写操作结果事件处理。"""
        self.taskResult.emit(result)

    def refreshData(self) -> None:
        """刷新界面数据。"""
        self._taskBoardPanel.refreshData()
        self._taskBoardPanel._entry_panel.refreshCategories()
