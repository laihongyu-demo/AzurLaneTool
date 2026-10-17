"""
魔方任务看板面板模块。

提供固定奖励任务（日常 / 周常 / 每月签到 / 世界巡游）的看板：
单击完成即自动记账，双击已完成项取消（删除对应明细）。

布局约定：
- 「魔方任务看板」是页签级分组；其内部 任务 / 每月签到 / 世界巡游 / 常规录入 四个分组同级；
- 分组与卡片都填满所在网格单元（``Expanding``），右边缘对齐、不留缺口；
- 列数按可用宽度自适应：宽屏 2 列、窄屏 1 列，切换时重排；
- 卡片只显示短标签（``short_name``），完整任务名放 tooltip，避免长文本撑宽控件。
"""

from datetime import date, datetime
from typing import Dict, List, Optional

from PyQt5.QtCore import QDate, Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QDateEdit, QGridLayout, QGroupBox, QHBoxLayout, QLabel, QMessageBox,
    QPushButton, QSizePolicy, QVBoxLayout, QWidget,
)

from services.cube_task_service import (
    CubeTaskGroupView, CubeTaskService, CubeTaskState, CubeTaskWriteResult,
)
from utils.constants import QT_DATE_DISPLAY_FORMAT, TASK_GROUP_DAILY, TASK_GROUP_WEEKLY
from utils.exceptions import DatabaseError, ValidationError
from views.widgets.regular_entry_panel import RegularEntryPanel

COMPLETED_STYLE = """
QPushButton {
    background-color: #e8f5e9;
    border: 1px solid #a5d6a7;
    border-radius: 6px;
    color: #2e7d32;
    font-size: 12px;
    padding: 2px 6px;
    text-align: center;
}
"""
PENDING_STYLE = """
QPushButton {
    background-color: #ffffff;
    border: 1px solid #e0e0e0;
    border-radius: 6px;
    color: #333333;
    font-size: 12px;
    padding: 2px 6px;
    text-align: center;
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
    font-size: 12px;
    padding: 2px 6px;
    text-align: center;
}
"""

# 单个分组内每行卡片数：巡游 8 档排成 4 + 4
CARDS_PER_ROW = 4

# 面板宽度达到该值时分组按 2 列排布；再窄就单列，避免卡片文字被挤掉
TWO_COLUMN_MIN_WIDTH = 940


def buildCardText(task, completed: bool) -> str:
    """
    生成卡片文案（短标签 + 奖励）。

    Args:
        task: 任务定义。
        completed: 是否已完成。

    Returns:
        卡片显示文本。
    """
    label = task.short_name or task.name
    prefix = "✔ " if completed else ""
    return f"{prefix}{label}  +{task.reward}"


class CubeTaskCard(QPushButton):
    """
    单个任务卡片。

    保持控件可用（不调用 ``setEnabled(False)``），否则双击事件收不到，取消功能会失效。
    已完成时单击无效，双击发出取消请求；宽度随网格单元拉伸，保证行内无缺口。
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
        self.setMinimumHeight(38)
        self.setMaximumHeight(44)
        self.setMinimumWidth(84)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._applyState()
        self.clicked.connect(self._onClicked)

    def _applyState(self) -> None:
        """按完成状态刷新文案、样式与提示。"""
        task = self._state.task
        self.setText(buildCardText(task, self._state.completed))

        if self._state.completed:
            if self._state.orphan:
                self.setStyleSheet(ORPHAN_STYLE)
                self.setToolTip(
                    f"{task.name}\n关联的收入明细已被删除，可单击重新完成，或双击清理该记录"
                )
            else:
                self.setStyleSheet(COMPLETED_STYLE)
                tip = f"{task.name}\n完成于 {self._state.completed_at}"
                if self._state.marked_only:
                    tip += "\n（仅标记，未生成收入明细）"
                tip += "\n双击可取消完成"
                self.setToolTip(tip)
        else:
            self.setStyleSheet(PENDING_STYLE)
            self.setToolTip(f"{task.name}\n{task.category}｜单击标记完成并 +{task.reward} 个魔方")

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

    顶部选择「记账日期」（补录时切到过去）；下方四个同级分组按网格铺满，
    宽屏两列、窄屏单列，右边缘对齐不留缺口。
    """

    dataRefreshed = pyqtSignal()
    resultReady = pyqtSignal(object)
    entryResult = pyqtSignal(object)

    def __init__(
        self,
        task_service: Optional[CubeTaskService] = None,
        entry_panel: Optional[RegularEntryPanel] = None,
        parent: QWidget = None
    ):
        """
        初始化任务看板面板。

        Args:
            task_service: 任务看板服务实例。
            entry_panel: 常规录入面板（可注入以便测试）。
            parent: 父控件。
        """
        super().__init__(parent)
        self._task_service = task_service or CubeTaskService()
        self._entry_panel = entry_panel or RegularEntryPanel()
        self._state_by_code: Dict[str, CubeTaskState] = {}
        self._groups: List[CubeTaskGroupView] = []
        self._current_columns = 0

        self._initUi()
        self._connectSignals()
        self.refreshData()

    # ------------------------------------------------------------------ UI

    def _initUi(self) -> None:
        """初始化用户界面。"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._group = QGroupBox("魔方任务看板")
        group_layout = QVBoxLayout(self._group)
        group_layout.setContentsMargins(12, 16, 12, 12)
        group_layout.setSpacing(8)

        group_layout.addLayout(self._buildHeader())

        self._boardLayout = QGridLayout()
        self._boardLayout.setHorizontalSpacing(12)
        self._boardLayout.setVerticalSpacing(12)
        group_layout.addLayout(self._boardLayout)

        self._hintLabel = QLabel(
            "单击卡片完成并自动记一笔魔方收入；对已完成项双击可取消（会删除对应明细）。",
            self,
        )
        self._hintLabel.setStyleSheet("color: #666; font-size: 12px;")
        group_layout.addWidget(self._hintLabel)

        layout.addWidget(self._group)

    def _buildHeader(self) -> QHBoxLayout:
        """
        构建顶部工具条（记账日期 + 周期信息 + 刷新）。

        Returns:
            水平布局。
        """
        header = QHBoxLayout()
        header.setSpacing(8)

        self._dateEdit = QDateEdit(self)
        self._dateEdit.setCalendarPopup(True)
        self._dateEdit.setDisplayFormat(QT_DATE_DISPLAY_FORMAT)
        self._dateEdit.setDate(QDate.currentDate())
        self._dateEdit.setFixedWidth(120)
        self._dateEdit.setMaximumHeight(28)
        self._dateEdit.setToolTip("补录时切到记录发生的那一天，任务会归属该日期所在周期")

        self._refreshBtn = QPushButton("刷新", self)
        self._refreshBtn.setFixedWidth(70)
        self._refreshBtn.setMaximumHeight(28)

        self._periodLabel = QLabel("", self)
        self._periodLabel.setStyleSheet("color: #666; font-size: 12px;")
        self._periodLabel.setWordWrap(True)

        header.addWidget(QLabel("记账日期:", self))
        header.addWidget(self._dateEdit)
        header.addWidget(self._refreshBtn)
        header.addSpacing(8)
        header.addWidget(self._periodLabel, 1)
        return header

    def _connectSignals(self) -> None:
        """连接信号与槽。"""
        self._refreshBtn.clicked.connect(self._onRefreshClicked)
        self._dateEdit.dateChanged.connect(self._onDateChanged)
        self._entry_panel.dataRefreshed.connect(self._onEntryDataRefreshed)
        self._entry_panel.entryRecorded.connect(self.entryResult.emit)

    def _onEntryDataRefreshed(self) -> None:
        """常规录入写入成功：通知外部刷新看板卡片。"""
        self.dataRefreshed.emit()

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

    def resizeEvent(self, event) -> None:
        """宽度变化导致列数改变时重新排布（保持右边缘对齐）。"""
        super().resizeEvent(event)
        if self._groups and self._columnCount() != self._current_columns:
            self._renderBoard()

    def _columnCount(self) -> int:
        """
        当前宽度下分组的列数。

        Returns:
            2（宽屏）或 1（窄屏）。
        """
        width = self.width()
        if width <= 0 and self.parentWidget() is not None:
            width = self.parentWidget().width()
        return 2 if width >= TWO_COLUMN_MIN_WIDTH else 1

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
        self._entry_panel.refreshState()

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

    def _renderBoard(self) -> None:
        """把四个同级分组按当前列数铺进网格（右边缘对齐、不留缺口）。"""
        self._clearBoard()
        columns = self._columnCount()
        self._current_columns = columns

        widgets: List[QWidget] = [self._buildGroupBox(view) for view in self._groups]
        widgets.append(self._buildReservedGroup())

        # 先清空历史列伸缩：从 2 列切到 1 列时，遗留的列伸缩会占住空白列，导致右侧出现大片缺口
        for column in range(6):
            self._boardLayout.setColumnStretch(column, 0)

        for index, widget in enumerate(widgets):
            self._boardLayout.addWidget(widget, index // columns, index % columns)

        for column in range(columns):
            self._boardLayout.setColumnStretch(column, 1)

        # 重排可能发生在 resizeEvent 中，立即激活一次，避免沿用旧几何导致右侧留白
        self._boardLayout.activate()

    def _buildGroupBox(self, group_view: CubeTaskGroupView) -> QGroupBox:
        """
        构建单个分组的卡片群。

        Args:
            group_view: 分组视图数据。

        Returns:
            分组控件。
        """
        title = (
            f"{group_view.title}（{group_view.earned}/{group_view.total}）"
            if group_view.total else group_view.title
        )
        group_box = QGroupBox(title)
        group_box.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        if group_view.earned >= group_view.total and group_view.total:
            group_box.setStyleSheet("QGroupBox { color: #2e7d32; }")

        outer = QVBoxLayout(group_box)
        outer.setContentsMargins(10, 14, 10, 10)
        outer.setSpacing(4)
        # 行内分组等高，内容垂直居中，避免短分组顶部对齐后底部留出突兀的空白
        outer.addStretch()

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

        outer.addStretch()
        return group_box

    def _buildReservedGroup(self) -> QGroupBox:
        """
        构建「常规录入」分组（与任务 / 签到 / 巡游同级）。

        Returns:
            常规录入分组控件。
        """
        group_box = QGroupBox("常规录入")
        group_box.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        layout = QVBoxLayout(group_box)
        layout.setContentsMargins(10, 14, 10, 12)
        layout.setSpacing(6)

        layout.addStretch()
        layout.addWidget(self._entry_panel)

        hint = QLabel("补记非固定收支（活动建造、礼包、军事委托等）；方向由类型决定。", self)
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #888; font-size: 12px;")
        layout.addWidget(hint)
        layout.addStretch()
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
        label.setStyleSheet("color: #666; font-size: 12px; font-weight: bold;")
        return label

    def _buildCardGrid(self, tasks: List[CubeTaskState]) -> QGridLayout:
        """
        构建卡片网格：卡片均分所在分组宽度，行内不留缺口。

        Args:
            tasks: 任务状态列表。

        Returns:
            网格布局。
        """
        grid = QGridLayout()
        grid.setHorizontalSpacing(6)
        grid.setVerticalSpacing(6)

        columns = max(1, min(CARDS_PER_ROW, len(tasks)))
        for index, state in enumerate(tasks):
            card = CubeTaskCard(state)
            card.completeRequested.connect(self._onCompleteRequested)
            card.cancelRequested.connect(self._onCancelRequested)
            grid.addWidget(card, index // columns, index % columns)
        for column in range(columns):
            grid.setColumnStretch(column, 1)
        return grid
