"""
魔方任务看板面板模块。

提供固定奖励任务（日常 / 周常 / 每月签到 / 世界巡游）的看板：
单击完成即自动记账，双击已完成项取消（删除对应明细）。
"""

from datetime import date, datetime
from typing import Dict, List, Optional

from PyQt5.QtCore import QDate, Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QDateEdit, QGridLayout, QGroupBox, QHBoxLayout, QLabel, QMessageBox, QPushButton,
    QSizePolicy, QVBoxLayout, QWidget,
)

from services.cube_task_service import (
    CubeTaskGroupView, CubeTaskService, CubeTaskState, CubeTaskWriteResult,
)
from utils.constants import QT_DATE_DISPLAY_FORMAT, TASK_GROUP_DAILY, TASK_GROUP_WEEKLY
from utils.exceptions import DatabaseError, ValidationError

COMPLETED_STYLE = """
QPushButton {
    background-color: #e8f5e9;
    border: 1px solid #a5d6a7;
    border-radius: 6px;
    color: #2e7d32;
    padding: 6px;
    text-align: left;
}
"""
PENDING_STYLE = """
QPushButton {
    background-color: #ffffff;
    border: 1px solid #e0e0e0;
    border-radius: 6px;
    color: #333333;
    padding: 6px;
    text-align: left;
}
QPushButton:hover {
    background-color: #f5f5f5;
    border: 1px solid #bdbdbd;
}
"""
ORPHAN_STYLE = """
QPushButton {
    background-color: #fff8e1;
    border: 1px solid #ffcc80;
    border-radius: 6px;
    color: #8d6e63;
    padding: 6px;
    text-align: left;
}
"""


class CubeTaskCard(QPushButton):
    """
    单个任务卡片。

    保持控件可用（不调用 ``setEnabled(False)``），否则双击事件收不到，取消功能会失效。
    已完成时单击无效，双击发出取消请求。
    """

    completeRequested = pyqtSignal(str)
    cancelRequested = pyqtSignal(str)

    def __init__(self, state: CubeTaskState, parent: QWidget = None):
        """
        初始化任务卡片。

        Args:
            state: 任务状态。
            parent: 父控件。
        """
        super().__init__(parent)
        self._state = state
        self.setCursor(Qt.PointingHandCursor)
        self.setMinimumHeight(72)
        self.setMinimumWidth(170)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._applyState()
        self.clicked.connect(self._onClicked)

    def _applyState(self) -> None:
        """按完成状态刷新文案、样式与提示。"""
        task = self._state.task
        if self._state.completed:
            self.setText(f"✔  {task.name}\n     +{task.reward}")
            if self._state.orphan:
                self.setStyleSheet(ORPHAN_STYLE)
                self.setToolTip("关联的收入明细已被删除，可单击重新完成，或双击清理该记录")
            else:
                self.setStyleSheet(COMPLETED_STYLE)
                tip = f"完成于 {self._state.completed_at}"
                if self._state.marked_only:
                    tip += "\n（仅标记，未生成收入明细）"
                tip += "\n双击可取消完成"
                self.setToolTip(tip)
        else:
            self.setText(f"      {task.name}\n     +{task.reward}")
            self.setStyleSheet(PENDING_STYLE)
            self.setToolTip(f"{task.category}｜单击标记完成并 +{task.reward} 个魔方")

    def _onClicked(self) -> None:
        """单击：未完成 → 请求完成；已完成 → 忽略（避免双击误触发完成）。"""
        if self._state.completed:
            return
        self.completeRequested.emit(self._state.task.code)

    def mouseDoubleClickEvent(self, event) -> None:
        """双击：已完成 → 请求取消；未完成 → 交给基类（等效单击完成）。"""
        if self._state.completed:
            self.cancelRequested.emit(self._state.task.code)
        super().mouseDoubleClickEvent(event)


class CubeTaskBoardPanel(QWidget):
    """
    魔方任务看板面板。

    顶部选择「记账日期」（补录时切到过去），下方按 3 个分组渲染 18 个任务卡片。
    """

    dataRefreshed = pyqtSignal()
    resultReady = pyqtSignal(object)

    def __init__(self, task_service: Optional[CubeTaskService] = None, parent: QWidget = None):
        """
        初始化任务看板面板。

        Args:
            task_service: 任务看板服务实例。
            parent: 父控件。
        """
        super().__init__(parent)
        self._task_service = task_service or CubeTaskService()
        self._state_by_code: Dict[str, CubeTaskState] = {}
        self._groups: List[CubeTaskGroupView] = []

        self._initUi()
        self._connectSignals()
        self.refreshData()

    # ------------------------------------------------------------------ UI

    def _initUi(self) -> None:
        """初始化用户界面。"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        group = QGroupBox("魔方任务看板")
        group_layout = QVBoxLayout(group)
        group_layout.setContentsMargins(15, 20, 15, 20)
        group_layout.setSpacing(12)

        group_layout.addLayout(self._buildHeader())
        self._boardLayout = QVBoxLayout()
        self._boardLayout.setSpacing(10)
        group_layout.addLayout(self._boardLayout)

        self._hintLabel = QLabel(
            "单击卡片完成并自动记一笔魔方收入；对已完成项双击可取消（会删除对应明细）。",
            self,
        )
        self._hintLabel.setStyleSheet("color: #666;")
        group_layout.addWidget(self._hintLabel)

        layout.addWidget(group)

    def _buildHeader(self) -> QHBoxLayout:
        """
        构建顶部工具条（记账日期 + 周期信息 + 刷新）。

        Returns:
            水平布局。
        """
        header = QHBoxLayout()

        self._dateEdit = QDateEdit(self)
        self._dateEdit.setCalendarPopup(True)
        self._dateEdit.setDisplayFormat(QT_DATE_DISPLAY_FORMAT)
        self._dateEdit.setDate(QDate.currentDate())
        self._dateEdit.setMinimumWidth(120)
        self._dateEdit.setToolTip("补录时切到记录发生的那一天，任务会归属该日期所在周期")

        self._refreshBtn = QPushButton("刷新", self)
        self._refreshBtn.setMinimumWidth(90)
        self._refreshBtn.setMinimumHeight(30)

        self._periodLabel = QLabel("", self)
        self._periodLabel.setStyleSheet("color: #666;")

        header.addWidget(QLabel("记账日期:", self))
        header.addWidget(self._dateEdit)
        header.addWidget(self._refreshBtn)
        header.addSpacing(12)
        header.addWidget(self._periodLabel)
        header.addStretch()
        return header

    def _connectSignals(self) -> None:
        """连接信号与槽。"""
        self._refreshBtn.clicked.connect(self._onRefreshClicked)
        self._dateEdit.dateChanged.connect(self._onDateChanged)

    # --------------------------------------------------------------- 事件

    def _selectedDate(self) -> date:
        """
        读取当前选择的记账日期。

        Returns:
            Python date。
        """
        return self._dateEdit.date().toPyDate()

    def _resolveMoment(self) -> datetime:
        """
        计算完成时刻：所选日期 + 当前时分秒。

        选择今天时直接用当前时间；补录历史日期时保留当前时分秒，便于区分同一天的多笔记录。

        Returns:
            datetime。
        """
        selected = self._selectedDate()
        now = datetime.now()
        if selected == now.date():
            return now.replace(microsecond=0)
        return datetime.combine(selected, now.time().replace(microsecond=0))

    def _onDateChanged(self, _value: QDate) -> None:
        """记账日期变化：刷新该周期的看板状态。"""
        self.refreshData()

    def _onRefreshClicked(self) -> None:
        """刷新按钮点击事件处理。"""
        self.refreshData()
        self.dataRefreshed.emit()

    def _onCompleteRequested(self, task_code: str) -> None:
        """完成请求事件处理。"""
        try:
            result = self._task_service.completeTask(task_code, self._resolveMoment())
        except ValidationError as e:
            QMessageBox.warning(self, "无法完成", str(e))
            return
        except DatabaseError as e:
            QMessageBox.critical(self, "数据库错误", f"记录失败: {e}")
            return

        self._afterWrite(result)

    def _onCancelRequested(self, task_code: str) -> None:
        """取消请求事件处理（双击已完成卡片）。"""
        state = self._state_by_code.get(task_code)
        if state is None:
            return

        message = f"确定取消「{state.task.name}」的完成状态吗？"
        if state.completed_at:
            message += f"\n完成于 {state.completed_at}，将删除对应的 {state.task.reward} 个魔方收入记录。"
        reply = QMessageBox.question(
            self, "确认取消", message, QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        )
        if reply != QMessageBox.Yes:
            return

        try:
            result = self._task_service.cancelTask(task_code, self._selectedDate())
        except ValidationError as e:
            QMessageBox.warning(self, "取消失败", str(e))
            self.refreshData()
            return
        except DatabaseError as e:
            QMessageBox.critical(self, "数据库错误", f"取消失败: {e}")
            return

        self._afterWrite(result)

    def _afterWrite(self, result: CubeTaskWriteResult) -> None:
        """
        写操作成功后的统一收尾：通知外部、刷新看板。

        Args:
            result: 写操作结果。
        """
        self.resultReady.emit(result)
        self.refreshData()
        self.dataRefreshed.emit()

    # --------------------------------------------------------------- 渲染

    def refreshData(self) -> None:
        """按当前记账日期重新渲染看板。"""
        selected = self._selectedDate()
        try:
            self._groups = self._task_service.getBoard(selected)
            period_info = self._task_service.getPeriodInfo(selected)
        except DatabaseError as e:
            self._groups = []
            self._state_by_code = {}
            self._renderBoard()
            self._periodLabel.setText(f"加载失败: {e}")
            return

        self._state_by_code = {
            state.task.code: state
            for group in self._groups for state in group.tasks
        }
        self._renderBoard()
        self._periodLabel.setText(self._formatPeriodSummary(period_info))

    def _formatPeriodSummary(self, period_info: Dict) -> str:
        """
        生成顶部周期信息文案。

        Args:
            period_info: 周期类型 → CubePeriodInfo。

        Returns:
            形如 ``今日 2026-10-17｜本周 2026 第 42 周｜本月 2026-10｜本期 10-01 ~ 11-30``。
        """
        labels = []
        names = {"day": "今日", "week": "本周", "month": "本月", "cruise": "本期"}
        for period_type, prefix in names.items():
            info = period_info.get(period_type)
            if info is None:
                continue
            labels.append(f"{prefix} {info.label}")
        return "｜".join(labels)

    def _clearBoard(self) -> None:
        """清空看板容器。"""
        while self._boardLayout.count():
            item = self._boardLayout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
            elif item.layout() is not None:
                self._clearLayout(item.layout())

    def _clearLayout(self, layout) -> None:
        """
        递归清空布局。

        Args:
            layout: Qt 布局对象。
        """
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
            elif item.layout() is not None:
                self._clearLayout(item.layout())

    def _renderBoard(self) -> None:
        """渲染 3 个分组。"""
        self._clearBoard()
        for group_view in self._groups:
            self._boardLayout.addWidget(self._buildGroupBox(group_view))

    def _buildGroupBox(self, group_view: CubeTaskGroupView) -> QGroupBox:
        """
        构建单个分组的卡片群。

        Args:
            group_view: 分组视图数据。

        Returns:
            分组控件。
        """
        title = (
            f"{group_view.title}（{group_view.earned}/{group_view.total} 个魔方）"
            if group_view.total else group_view.title
        )
        group_box = QGroupBox(title)
        if group_view.earned >= group_view.total and group_view.total:
            group_box.setStyleSheet("QGroupBox { color: #2e7d32; }")

        outer = QVBoxLayout(group_box)
        outer.setContentsMargins(12, 16, 12, 12)
        outer.setSpacing(6)

        if group_view.key == "task":
            # 任务组内再分「日常」「周常」两个小节
            for grp_code, grp_title in ((TASK_GROUP_DAILY, "日常"), (TASK_GROUP_WEEKLY, "周常")):
                tasks = [state for state in group_view.tasks if state.task.grp == grp_code]
                if not tasks:
                    continue
                outer.addWidget(self._buildSubTitle(grp_title, tasks))
                outer.addLayout(self._buildCardGrid(tasks))
        else:
            outer.addLayout(self._buildCardGrid(group_view.tasks))
        return group_box

    def _buildSubTitle(self, text: str, tasks: List[CubeTaskState]) -> QLabel:
        """
        构建分组内小节标题（带合计）。

        Args:
            text: 小节名称。
            tasks: 该小节任务列表。

        Returns:
            标题标签。
        """
        earned = sum(state.task.reward for state in tasks if state.completed)
        total = sum(state.task.reward for state in tasks)
        label = QLabel(f"{text}（{earned}/{total}）")
        label.setStyleSheet("color: #666; font-weight: bold;")
        return label

    def _buildCardGrid(self, tasks: List[CubeTaskState]) -> QGridLayout:
        """
        构建卡片网格（每行 4 个）。

        Args:
            tasks: 任务状态列表。

        Returns:
            网格布局。
        """
        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(10)
        for index, state in enumerate(tasks):
            card = CubeTaskCard(state)
            card.completeRequested.connect(self._onCompleteRequested)
            card.cancelRequested.connect(self._onCancelRequested)
            grid.addWidget(card, index // 4, index % 4)
        return grid
