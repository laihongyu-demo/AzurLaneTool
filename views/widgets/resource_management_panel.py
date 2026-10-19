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
from utils.constants import RESOURCE_TYPE_RED_GEM
from views.widgets.cube_task_board_panel import CubeTaskBoardPanel
from views.widgets.regular_entry_panel import RegularEntryPanel


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
        # 顶部留出与两个看板间距一致的空隙，避免第一个分组贴着页签边缘
        layout.setContentsMargins(0, 15, 0, 0)
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
        构建红尖尖任务看板（与魔方任务看板同级）。

        红尖尖目前没有固定数量的周期性来源，因此这里只放与魔方常规录入同规格的
        录入组件，后续出现固定奖励再补任务卡片。

        Returns:
            红尖尖看板分组控件。
        """
        group = QGroupBox("红尖尖任务看板")
        layout = QVBoxLayout(group)
        layout.setContentsMargins(12, 16, 12, 12)
        layout.setSpacing(8)

        hint = QLabel("红尖尖暂无固定奖励任务，可直接补记收支；方向由类型决定。", self)
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #888; font-size: 12px;")
        layout.addWidget(hint)

        self._redGemEntryPanel = RegularEntryPanel(
            resource_type=RESOURCE_TYPE_RED_GEM, parent=self
        )
        layout.addWidget(self._redGemEntryPanel)
        layout.addStretch()
        return group

    def _connectSignals(self) -> None:
        """连接信号与槽。"""
        self._taskBoardPanel.dataRefreshed.connect(self._onDataRefreshed)
        self._taskBoardPanel.resultReady.connect(self._onTaskResult)
        self._taskBoardPanel.entryResult.connect(self.entryResult.emit)
        self._redGemEntryPanel.dataRefreshed.connect(self._onDataRefreshed)
        self._redGemEntryPanel.entryRecorded.connect(self.entryResult.emit)

    def _onDataRefreshed(self) -> None:
        """子面板数据刷新完成事件处理。"""
        self.dataRefreshed.emit()

    def _onTaskResult(self, result: CubeTaskWriteResult) -> None:
        """任务看板写操作结果事件处理。"""
        self.taskResult.emit(result)

    def onActivated(self) -> None:
        """页签激活：同步两个看板的时间上下文，必要时刷新看板。"""
        self._taskBoardPanel.onActivated()
        self._redGemEntryPanel.onActivated()

    def syncTimeContext(self) -> None:
        """只同步时间控件（不查库），供全局刷新在重渲染前调用。"""
        self._taskBoardPanel.syncTimeContext()
        self._redGemEntryPanel.syncTimeContext()

    def refreshData(self) -> None:
        """刷新界面数据。"""
        self._taskBoardPanel.refreshData()
        self._redGemEntryPanel.refreshState()
