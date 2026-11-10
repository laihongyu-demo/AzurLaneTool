"""
设置面板模块。

主窗口第 4 个页签「设置」的容器，按分组承载用户可自定义的配置项。
本轮提供「类型字典」维护（#21）：新增、改名（同步历史明细）、上移 / 下移、
停用 / 启用；后续的数据库路径、user.json 编辑按同样的分组方式追加。

设置页不持有时间上下文，``syncTimeContext`` 保留为空实现，以便配合主窗口的
刷新矩阵（切页只同步当前页、跨天刷新当前页）。
"""

from typing import List, Optional, Tuple

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QBrush, QColor
from PyQt5.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QComboBox,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from services.backtest_service import BacktestService, DueStatus
from services.resource_category_service import (
    CategoryEntry,
    CategoryWriteResult,
    ResourceCategoryService,
)
from utils.constants import (
    RESOURCE_DIRECTION_EXPENSE,
    RESOURCE_DIRECTION_INCOME,
    RESOURCE_DIRECTION_NAMES,
    RESOURCE_DISPLAY_NAMES,
    RESOURCE_TYPE_CUBE,
    RESOURCE_TYPES,
)
from utils.exceptions import DatabaseError, ValidationError

# 方向下拉与常规录入保持一致：支出在前、收入在后
DIRECTION_DISPLAY_ORDER = (RESOURCE_DIRECTION_EXPENSE, RESOURCE_DIRECTION_INCOME)

# 停用行用灰色弱化，但仍可选中后启用
INACTIVE_ITEM_COLOR = "#999999"

# 事件方向展示名（用户侧用语）
EVENT_DIRECTION_LABELS = {"up": "变快", "down": "变慢"}


class CategoryDictionarySection(QGroupBox):
    """
    类型字典维护分组。

    左侧按「资源 + 方向」列出类型（含已停用），右侧提供新增 / 改名 / 上移 /
    下移 / 停用（启用）操作；所有写入都经 :class:`ResourceCategoryService`。
    """

    changed = pyqtSignal()
    resultReady = pyqtSignal(object)

    def __init__(
        self,
        category_service: Optional[ResourceCategoryService] = None,
        parent: QWidget = None,
    ):
        """
        初始化类型字典分组。

        Args:
            category_service: 类型字典服务实例。
            parent: 父控件。
        """
        super().__init__("类型字典", parent)
        self._service = category_service or ResourceCategoryService()
        self._entries: List[CategoryEntry] = []
        self._initUi()
        self._connectSignals()
        self.refreshList()

    # ------------------------------------------------------------------ UI

    def _initUi(self) -> None:
        """初始化用户界面。"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 16, 12, 12)
        layout.setSpacing(8)

        hint = QLabel(
            "常规录入下拉的类型来源。停用只影响下拉，历史明细仍按原名保留；"
            "改名会同步已有关联明细。",
            self,
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #666; font-size: 12px;")
        layout.addWidget(hint)

        layout.addLayout(self._buildFilterRow())

        body = QHBoxLayout()
        body.setSpacing(8)

        self._listWidget = QListWidget(self)
        self._listWidget.setSelectionMode(QAbstractItemView.SingleSelection)
        self._listWidget.setMinimumHeight(280)
        self._listWidget.setToolTip("选中一行后可改名、调整顺序或停用 / 启用")
        body.addWidget(self._listWidget, 1)
        body.addLayout(self._buildButtonColumn())
        layout.addLayout(body)

    def _buildFilterRow(self) -> QHBoxLayout:
        """
        构建「资源 + 方向」筛选行。

        Returns:
            水平布局。
        """
        row = QHBoxLayout()
        row.setSpacing(8)

        self._resourceCombo = QComboBox(self)
        for resource_type in RESOURCE_TYPES:
            self._resourceCombo.addItem(
                RESOURCE_DISPLAY_NAMES.get(resource_type, resource_type), resource_type
            )
        self._resourceCombo.setFixedWidth(110)
        self._resourceCombo.setMaximumHeight(28)

        self._directionCombo = QComboBox(self)
        for direction in DIRECTION_DISPLAY_ORDER:
            self._directionCombo.addItem(
                RESOURCE_DIRECTION_NAMES.get(direction, direction), direction
            )
        self._directionCombo.setFixedWidth(90)
        self._directionCombo.setMaximumHeight(28)

        row.addWidget(QLabel("资源", self))
        row.addWidget(self._resourceCombo)
        row.addSpacing(12)
        row.addWidget(QLabel("方向", self))
        row.addWidget(self._directionCombo)
        row.addStretch()
        return row

    def _buildButtonColumn(self) -> QVBoxLayout:
        """
        构建右侧操作按钮列。

        Returns:
            垂直布局。
        """
        column = QVBoxLayout()
        column.setSpacing(6)

        self._createBtn = QPushButton("新增", self)
        self._renameBtn = QPushButton("改名", self)
        self._upBtn = QPushButton("上移", self)
        self._downBtn = QPushButton("下移", self)
        self._toggleBtn = QPushButton("停用", self)

        self._createBtn.setToolTip("在当前分组末尾新增一个类型")
        self._renameBtn.setToolTip("改名会同步已有关联明细的类型名")
        self._upBtn.setToolTip("把选中类型往前移一位")
        self._downBtn.setToolTip("把选中类型往后移一位")
        self._toggleBtn.setToolTip("停用后不出现在常规录入下拉，历史明细保留")

        for button in (
            self._createBtn, self._renameBtn, self._upBtn, self._downBtn, self._toggleBtn
        ):
            button.setFixedWidth(88)
            button.setMaximumHeight(28)
            column.addWidget(button)
        column.addStretch()
        return column

    def _connectSignals(self) -> None:
        """连接信号与槽。"""
        self._resourceCombo.currentIndexChanged.connect(self._onFilterChanged)
        self._directionCombo.currentIndexChanged.connect(self._onFilterChanged)
        self._listWidget.currentItemChanged.connect(self._onSelectionChanged)
        self._createBtn.clicked.connect(self._onCreateClicked)
        self._renameBtn.clicked.connect(self._onRenameClicked)
        self._upBtn.clicked.connect(self._onMoveUpClicked)
        self._downBtn.clicked.connect(self._onMoveDownClicked)
        self._toggleBtn.clicked.connect(self._onToggleActiveClicked)

    # --------------------------------------------------------------- 数据

    def refreshList(
        self, select_id: Optional[int] = None, keep_selection: bool = True
    ) -> None:
        """
        重新读取当前分组的类型列表并刷新按钮状态。

        Args:
            select_id: 刷新后要选中的字典项 ID；为空时按 ``keep_selection`` 决定。
            keep_selection: 没有指定 ``select_id`` 时，是否沿用刷新前的选中项。
                切换资源 / 方向时应传 False。
        """
        if select_id is not None:
            target_id = select_id
        else:
            target_id = self._selectedCategoryId() if keep_selection else None
        resource_type, direction = self._currentFilter()

        try:
            entries = self._service.listCategories(resource_type, direction)
        except DatabaseError as e:
            self._entries = []
            self._listWidget.clear()
            item = QListWidgetItem(f"类型加载失败：{e}")
            item.setFlags(Qt.NoItemFlags)
            self._listWidget.addItem(item)
            self._syncButtons()
            return

        self._entries = entries
        self._listWidget.clear()
        for position, entry in enumerate(entries, start=1):
            item = QListWidgetItem(self._formatEntry(position, entry))
            item.setData(Qt.UserRole, entry.id)
            item.setToolTip(self._formatTooltip(entry))
            if not entry.is_active:
                item.setForeground(QBrush(QColor(INACTIVE_ITEM_COLOR)))
            self._listWidget.addItem(item)

        if target_id is not None:
            self._selectCategory(target_id)
        self._syncButtons()

    def _formatEntry(self, position: int, entry: CategoryEntry) -> str:
        """
        生成列表行文案：``1. 轻型建造  ·  12 笔明细``。

        Args:
            position: 在当前分组中的序号（从 1 开始）。
            entry: 类型条目。

        Returns:
            列表行文案。
        """
        state = "" if entry.is_active else "（已停用）"
        return f"{position}. {entry.name}{state}    ·    {entry.usage_count} 笔明细"

    def _formatTooltip(self, entry: CategoryEntry) -> str:
        """
        生成列表行 tooltip。

        Args:
            entry: 类型条目。

        Returns:
            多行提示文案。
        """
        direction_name = RESOURCE_DIRECTION_NAMES.get(entry.direction, entry.direction)
        return (
            f"类型：{entry.name}\n"
            f"方向：{direction_name}\n"
            f"状态：{entry.statusText}\n"
            f"关联明细：{entry.usage_count} 笔\n"
            f"排序序号：{entry.sort_order}"
        )

    def _currentFilter(self) -> Tuple[str, str]:
        """
        当前选择的资源与方向。

        Returns:
            ``(resource_type, direction)``。
        """
        resource_type = self._resourceCombo.currentData() or RESOURCE_TYPE_CUBE
        direction = self._directionCombo.currentData() or RESOURCE_DIRECTION_EXPENSE
        return resource_type, direction

    def _selectedCategoryId(self) -> Optional[int]:
        """
        当前选中行的字典项 ID。

        Returns:
            字典项 ID；未选中时返回 None。
        """
        item = self._listWidget.currentItem()
        if item is None:
            return None
        return item.data(Qt.UserRole)

    def _selectedEntry(self) -> Optional[CategoryEntry]:
        """
        当前选中的类型条目。

        Returns:
            类型条目；未选中或已刷新掉时返回 None。
        """
        category_id = self._selectedCategoryId()
        if category_id is None:
            return None
        return next((entry for entry in self._entries if entry.id == category_id), None)

    def _selectCategory(self, category_id: int) -> None:
        """
        按 ID 选中列表行。

        Args:
            category_id: 字典项 ID。
        """
        for row in range(self._listWidget.count()):
            item = self._listWidget.item(row)
            if item.data(Qt.UserRole) == category_id:
                self._listWidget.setCurrentRow(row)
                return

    def _syncButtons(self) -> None:
        """按选中行与位置启用 / 禁用操作按钮。"""
        entry = self._selectedEntry()
        if entry is None:
            self._renameBtn.setEnabled(False)
            self._upBtn.setEnabled(False)
            self._downBtn.setEnabled(False)
            self._toggleBtn.setEnabled(False)
            self._toggleBtn.setText("停用")
            return

        row = self._listWidget.currentRow()
        self._renameBtn.setEnabled(True)
        self._upBtn.setEnabled(row > 0)
        self._downBtn.setEnabled(0 <= row < self._listWidget.count() - 1)
        self._toggleBtn.setEnabled(True)
        self._toggleBtn.setText("停用" if entry.is_active else "启用")

    # --------------------------------------------------------------- 事件

    def _onFilterChanged(self) -> None:
        """资源 / 方向切换：重新加载列表，不沿用旧选中项。"""
        self.refreshList(keep_selection=False)

    def _onSelectionChanged(self, *args) -> None:
        """选中行变化：同步按钮状态。"""
        self._syncButtons()

    def _onCreateClicked(self) -> None:
        """新增按钮：弹窗输入名称并调用服务。"""
        resource_type, direction = self._currentFilter()
        label = (
            f"{RESOURCE_DISPLAY_NAMES.get(resource_type, resource_type)} · "
            f"{RESOURCE_DIRECTION_NAMES.get(direction, direction)}"
        )
        name, accepted = QInputDialog.getText(self, "新增类型", f"在「{label}」下新增类型名称：")
        if not accepted:
            return
        self._runWrite(lambda: self._service.createCategory(resource_type, direction, name))

    def _onRenameClicked(self) -> None:
        """改名按钮：弹窗预填原名并调用服务。"""
        entry = self._selectedEntry()
        if entry is None:
            return
        new_name, accepted = QInputDialog.getText(
            self, "改名类型", f"把「{entry.name}」改为：", text=entry.name
        )
        if not accepted:
            return
        self._runWrite(lambda: self._service.renameCategory(entry.id, new_name))

    def _onMoveUpClicked(self) -> None:
        """上移按钮：把选中类型往前移一位。"""
        self._moveSelected(-1)

    def _onMoveDownClicked(self) -> None:
        """下移按钮：把选中类型往后移一位。"""
        self._moveSelected(1)

    def _moveSelected(self, offset: int) -> None:
        """
        按方向移动选中类型。

        Args:
            offset: ``-1`` 上移，``1`` 下移。
        """
        entry = self._selectedEntry()
        if entry is None:
            return
        self._runWrite(lambda: self._service.moveCategory(entry.id, offset))

    def _onToggleActiveClicked(self) -> None:
        """停用 / 启用按钮；停用前先确认影响范围。"""
        entry = self._selectedEntry()
        if entry is None:
            return
        if entry.is_active:
            reply = QMessageBox.question(
                self,
                "停用类型",
                f"停用「{entry.name}」？\n\n"
                "停用后它不再出现在常规录入下拉中；"
                f"已有关联的 {entry.usage_count} 笔历史明细保留原名，统计不受影响。",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if reply != QMessageBox.Yes:
                return
        self._runWrite(lambda: self._service.setCategoryActive(entry.id, not entry.is_active))

    def _runWrite(self, action) -> None:
        """
        执行一次写操作并统一处理异常、刷新与信号。

        Args:
            action: 无参可调用对象，返回 :class:`CategoryWriteResult`。
        """
        try:
            result: CategoryWriteResult = action()
        except ValidationError as e:
            QMessageBox.warning(self, "无法完成", str(e))
            return
        except DatabaseError as e:
            QMessageBox.critical(self, "数据库错误", f"类型字典写入失败: {e}")
            return

        if not result.success:
            # 位置已在首 / 末位等无需写库的提示，只回状态栏，不弹窗
            self.resultReady.emit(result)
            return

        self.refreshList(select_id=result.category_id or None)
        self.changed.emit()
        self.resultReady.emit(result)

    def onActivated(self) -> None:
        """页签激活：重新读取库内最新状态。"""
        self.refreshList()


class BacktestCalibrationSection(QGroupBox):
    """
    效率体检分组（技术上对应「回测与校准」，#35 P3）。

    用用户能看懂的方式展示：上次检查时间、是否需要检查、练级节奏变化与最近报告。
    检查只读数据库，不改主值、不改常量；运行结果通过 ``resultReady`` 转给状态栏。
    """

    resultReady = pyqtSignal(object)

    def __init__(
        self,
        backtest_service: Optional[BacktestService] = None,
        parent: QWidget = None,
    ):
        """
        初始化回测与校准分组。

        Args:
            backtest_service: 回测服务实例。
            parent: 父控件。
        """
        super().__init__("效率体检", parent)
        self._service = backtest_service or BacktestService()
        self._events: List = []
        self.setToolTip(
            "技术口径：回测 = walk-forward 校验 30 天端点与趋势阈值；"
            "事件 = fast/slow 偏离 ±25% 持续 ≥5 天（强事件 ±50%×3）。只读数据，不改常量。"
        )
        self._initUi()
        self._connectSignals()
        self.refresh()

    def _initUi(self) -> None:
        """初始化用户界面。"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 16, 12, 12)
        layout.setSpacing(8)

        hint = QLabel(
            "每 90 天或新增 100 条记录，建议做一次检查：看看「指级效率」的估算还准不准。"
            "练级速度明显变快或变慢时，这里也会提醒你。检查只读数据，不会改动任何数值。",
            self,
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #666; font-size: 12px;")
        layout.addWidget(hint)

        self._statusLabel = QLabel("-", self)
        self._statusLabel.setWordWrap(True)
        layout.addWidget(self._statusLabel)

        self._reasonsLabel = QLabel("", self)
        self._reasonsLabel.setWordWrap(True)
        layout.addWidget(self._reasonsLabel)

        button_row = QHBoxLayout()
        button_row.setSpacing(8)
        self._runBtn = QPushButton("立即检查", self)
        self._runBtn.setToolTip("生成一份体检报告（约 1 秒），不会改动数据")
        self._handleBtn = QPushButton("确认已看过", self)
        self._handleBtn.setToolTip("选中一条「等你确认」的节奏变化后点击；确认后不再重复提醒")
        self._handleBtn.setEnabled(False)
        button_row.addWidget(self._runBtn)
        button_row.addWidget(self._handleBtn)
        button_row.addStretch()
        layout.addLayout(button_row)

        self._eventsTable = QTableWidget(0, 6, self)
        self._eventsTable.setHorizontalHeaderLabels(
            ["变化", "时间", "持续", "最大偏离", "状态", "结论"]
        )
        self._eventsTable.setToolTip(
            "最大偏离：事件期间偏离最厉害的一天，最近两周速度比最近一个月平均快/慢多少"
        )
        self._eventsTable.verticalHeader().setVisible(False)
        self._eventsTable.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._eventsTable.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._eventsTable.setSelectionMode(QAbstractItemView.SingleSelection)
        self._eventsTable.setAlternatingRowColors(True)
        # 短列按内容取宽，时间列保证完整显示；只让「结论」吃掉剩余空间并省略
        header = self._eventsTable.horizontalHeader()
        for column in (0, 1, 2, 3, 4):
            header.setSectionResizeMode(column, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(5, QHeaderView.Stretch)
        self._eventsTable.setTextElideMode(Qt.ElideRight)
        self._eventsTable.setMinimumHeight(140)
        self._eventsTable.setMaximumHeight(180)
        layout.addWidget(self._eventsTable)

        guide = QLabel(
            "看到「等你确认」时：选中那一行，点「确认已看过」即可；不需要改任何设置。",
            self,
        )
        guide.setWordWrap(True)
        guide.setStyleSheet("color: #666; font-size: 12px;")
        layout.addWidget(guide)

        self._reportLabel = QLabel("", self)
        self._reportLabel.setWordWrap(True)
        self._reportLabel.setStyleSheet("color: #666; font-size: 12px;")
        layout.addWidget(self._reportLabel)

    def _connectSignals(self) -> None:
        """连接信号与槽。"""
        self._runBtn.clicked.connect(self._onRunClicked)
        self._handleBtn.clicked.connect(self._onHandleClicked)
        self._eventsTable.itemSelectionChanged.connect(self._onSelectionChanged)
        self._eventsTable.cellDoubleClicked.connect(self._onCellDoubleClicked)

    # ------------------------------------------------------------------ 展示

    def refresh(self) -> None:
        """读取到期状态并刷新展示；任何异常都降级为一行提示。"""
        try:
            status = self._service.getDueStatus()
        except DatabaseError as e:
            self._showError(f"数据库错误：{e}")
            return
        except Exception as e:  # 只读区块兜底，避免设置页整体不可用
            self._showError(f"检查状态不可用：{e}")
            return
        self._renderStatus(status)
        self._renderEvents(status.pending_events, status.ongoing_events, status.handled_events)

    def _renderStatus(self, status: DueStatus) -> None:
        """
        渲染状态摘要与建议。

        Args:
            status: 到期状态。
        """
        if status.last_run_at:
            days = "时间未知" if status.days_since is None else f"{status.days_since} 天前"
            self._statusLabel.setText(
                f"上次检查：{status.last_run_at}（{days}）· "
                f"之后新增 {status.new_points} 条记录"
            )
        else:
            self._statusLabel.setText("还没做过检查")

        ongoing_text = (
            f"{len(status.ongoing_events)} 段变化还在发生，暂不用确认"
            if status.ongoing_events
            else ""
        )
        if status.due:
            text = "建议检查：" + "；".join(status.reasons)
            if ongoing_text:
                text += "；" + ongoing_text
            self._reasonsLabel.setText(text)
            self._reasonsLabel.setStyleSheet("color: #b26a00;")
        else:
            self._reasonsLabel.setText(
                "现在不需要检查" + (f"（{ongoing_text}）" if ongoing_text else "")
            )
            self._reasonsLabel.setStyleSheet("color: #2e7d32;")

        self._reportLabel.setText(
            f"最近报告：{status.report_path}" if status.report_path else ""
        )

    @staticmethod
    def _formatChange(event) -> str:
        """
        把事件峰值换算成「快 N% / 慢 N%」。

        Args:
            event: 事件记录。

        Returns:
            展示文本。
        """
        word = "快" if event.direction == "up" else "慢"
        return f"{word} {round(abs(event.peak_ratio - 1) * 100)}%"

    @staticmethod
    def _formatEventRange(event) -> str:
        """
        时间列：同年只显示「月-日 → 月-日」，跨年显示完整日期。

        Args:
            event: 事件记录。

        Returns:
            展示文本；完整日期放在单元格 tooltip 里。
        """
        start, end = event.start_date, event.end_date
        if start[:4] == end[:4]:
            return f"{start[5:]} → {end[5:]}"
        return f"{start} → {end}"

    def _renderEvents(self, pending: List, ongoing: List, handled: List) -> None:
        """
        渲染事件表：待确认 → 还在发生 → 最近已确认（新到旧）。

        Args:
            pending: 已结束、未复核的事件。
            ongoing: 仍在持续的事件（不计入到期，可提前确认）。
            handled: 最近已确认的事件（用于回看结论）。
        """
        self._events = list(pending) + list(ongoing) + list(reversed(handled))
        self._eventsTable.setRowCount(0)
        for event in self._events:
            row = self._eventsTable.rowCount()
            self._eventsTable.insertRow(row)
            if event.ongoing:
                status_text = "已确认·还在发生" if event.handled_at else "还在发生"
            elif event.handled_at:
                status_text = "已确认"
            else:
                status_text = "等你确认"
            values = [
                EVENT_DIRECTION_LABELS.get(event.direction, event.direction),
                self._formatEventRange(event),
                f"{event.days} 天",
                self._formatChange(event),
                status_text,
                event.note or "—",
            ]
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                if column in (2, 3):
                    item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                else:
                    item.setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter)
                if column == 1:
                    item.setToolTip(f"{event.start_date} → {event.end_date}")
                if column == 5:
                    item.setToolTip(event.note or "")
                if event.ongoing or event.handled_at:
                    item.setForeground(QBrush(QColor("#757575")))
                self._eventsTable.setItem(row, column, item)
        self._handleBtn.setEnabled(False)

    def _showError(self, message: str) -> None:
        """
        降级展示。

        Args:
            message: 提示文本。
        """
        self._statusLabel.setText("-")
        self._reasonsLabel.setText(message)
        self._reasonsLabel.setStyleSheet("color: #c62828;")
        self._events = []
        self._eventsTable.setRowCount(0)
        self._handleBtn.setEnabled(False)
        self._reportLabel.setText("")

    # ------------------------------------------------------------------ 操作

    def _onRunClicked(self) -> None:
        """跑一次检查：同步执行，期间禁用按钮并显示等待光标。"""
        self._runBtn.setEnabled(False)
        self._runBtn.setText("正在检查…")
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            run = self._service.run()
        except (DatabaseError, ValidationError) as e:
            QMessageBox.critical(self, "检查失败", str(e))
            return
        except Exception as e:  # 兜底，不让未知异常拖垮设置页
            QMessageBox.critical(self, "检查失败", f"检查未完成：{e}")
            return
        finally:
            QApplication.restoreOverrideCursor()
            self._runBtn.setEnabled(True)
            self._runBtn.setText("立即检查")

        self.resultReady.emit(run)
        self.refresh()

    def _onSelectionChanged(self) -> None:
        """事件选中状态变化：只有未确认的记录可以填写结论。"""
        row = self._eventsTable.currentRow()
        enabled = 0 <= row < len(self._events) and not self._events[row].handled_at
        self._handleBtn.setEnabled(enabled)

    def _onHandleClicked(self) -> None:
        """弹出结论输入框，把选中事件标记为已确认。"""
        row = self._eventsTable.currentRow()
        if row < 0 or row >= len(self._events):
            return
        event = self._events[row]
        if event.handled_at:
            return
        note, ok = QInputDialog.getMultiLineText(
            self, "复核结论", "填写复核结论（可留空）：", event.note or ""
        )
        if not ok:
            return
        try:
            changed = self._service.markEventHandled(
                event.direction, event.start_date, note
            )
        except DatabaseError as e:
            QMessageBox.critical(self, "节奏变化", f"保存确认状态失败: {e}")
            return
        if not changed:
            QMessageBox.information(self, "节奏变化", "这条记录已确认或已不存在")
        self.refresh()

    def _onCellDoubleClicked(self, row: int, column: int) -> None:
        """
        双击「结论」列查看全文（单元格内只显示省略后的文本）。

        Args:
            row: 行号。
            column: 列号。
        """
        if column != 5 or row < 0 or row >= len(self._events):
            return
        note = self._events[row].note
        QMessageBox.information(self, "复核结论", note or "（未填写结论）")


class SettingsPanel(QWidget):
    """
    设置页签容器。

    以分组块组织设置项；本轮只有「类型字典」，后续设置按需追加分组。
    """

    categoriesChanged = pyqtSignal()
    resultReady = pyqtSignal(object)

    def __init__(
        self,
        category_service: Optional[ResourceCategoryService] = None,
        backtest_service: Optional[BacktestService] = None,
        parent: QWidget = None,
    ):
        """
        初始化设置页。

        Args:
            category_service: 类型字典服务实例。
            backtest_service: 回测服务实例（只读 + 写本地记录）。
            parent: 父控件。
        """
        super().__init__(parent)
        self._categorySection = CategoryDictionarySection(category_service, self)
        self._backtestSection = BacktestCalibrationSection(backtest_service, self)
        self._initUi()
        self._connectSignals()

    def _initUi(self) -> None:
        """初始化用户界面。"""
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, 15, 0, 0)
        layout.setSpacing(15)
        layout.addWidget(self._categorySection)
        layout.addWidget(self._backtestSection)
        layout.addStretch()

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        scroll.setWidget(content)
        outer.addWidget(scroll)

    def _connectSignals(self) -> None:
        """连接信号与槽。"""
        self._categorySection.changed.connect(self.categoriesChanged.emit)
        self._categorySection.resultReady.connect(self.resultReady.emit)
        self._backtestSection.resultReady.connect(self.resultReady.emit)

    def syncTimeContext(self) -> None:
        """设置页没有时间上下文；保留接口以配合主窗口的刷新矩阵。"""

    def onActivated(self) -> None:
        """页签激活：刷新类型字典与回测状态。"""
        self._categorySection.onActivated()
        self._backtestSection.refresh()

    def refreshData(self) -> None:
        """刷新界面数据（全局刷新 / Ctrl+R）。"""
        self._categorySection.refreshList()
        self._backtestSection.refresh()
