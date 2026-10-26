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

# 事件方向展示名
EVENT_DIRECTION_LABELS = {"up": "加速", "down": "放缓"}


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
    回测与校准分组（#35 P3）。

    显示到期状态、待复核事件与最近报告，并提供「立即回测」「标记已复核」。
    回测只读数据库，不改主值、不改常量；运行结果通过 ``resultReady`` 转给状态栏。
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
        super().__init__("回测与校准", parent)
        self._service = backtest_service or BacktestService()
        self._pending_events: List = []
        self._initUi()
        self._connectSignals()
        self.refresh()

    def _initUi(self) -> None:
        """初始化用户界面。"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 16, 12, 12)
        layout.setSpacing(8)

        hint = QLabel(
            "到期：距上次回测 ≥90 天或新增 ≥100 条有效快照；"
            "事件：近期节奏偏离 30 天基线 ±25% 持续 5 天（强事件 ±50% 持续 3 天）。"
            "回测只读数据库，不改主值与常量。",
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
        self._runBtn = QPushButton("立即回测", self)
        self._runBtn.setToolTip("生成候选口径对比报告与运行记录（约 1 秒）")
        self._handleBtn = QPushButton("标记已复核", self)
        self._handleBtn.setToolTip("选中待复核事件后标记，表示已人工确认")
        self._handleBtn.setEnabled(False)
        button_row.addWidget(self._runBtn)
        button_row.addWidget(self._handleBtn)
        button_row.addStretch()
        layout.addLayout(button_row)

        self._eventsTable = QTableWidget(0, 5, self)
        self._eventsTable.setHorizontalHeaderLabels(["方向", "区间", "天数", "峰值", "状态"])
        self._eventsTable.verticalHeader().setVisible(False)
        self._eventsTable.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._eventsTable.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._eventsTable.setSelectionMode(QAbstractItemView.SingleSelection)
        self._eventsTable.setAlternatingRowColors(True)
        self._eventsTable.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self._eventsTable.setMinimumHeight(140)
        self._eventsTable.setMaximumHeight(180)
        layout.addWidget(self._eventsTable)

        self._reportLabel = QLabel("", self)
        self._reportLabel.setWordWrap(True)
        self._reportLabel.setStyleSheet("color: #666; font-size: 12px;")
        layout.addWidget(self._reportLabel)

    def _connectSignals(self) -> None:
        """连接信号与槽。"""
        self._runBtn.clicked.connect(self._onRunClicked)
        self._handleBtn.clicked.connect(self._onHandleClicked)
        self._eventsTable.itemSelectionChanged.connect(self._onSelectionChanged)

    # ------------------------------------------------------------------ 展示

    def refresh(self) -> None:
        """读取到期状态并刷新展示；任何异常都降级为一行提示。"""
        try:
            status = self._service.getDueStatus()
        except DatabaseError as e:
            self._showError(f"数据库错误：{e}")
            return
        except Exception as e:  # 只读区块兜底，避免设置页整体不可用
            self._showError(f"回测状态不可用：{e}")
            return
        self._renderStatus(status)
        self._renderEvents(status.pending_events)

    def _renderStatus(self, status: DueStatus) -> None:
        """
        渲染状态摘要与建议。

        Args:
            status: 到期状态。
        """
        if status.last_run_at:
            days = "" if status.days_since is None else f"（{status.days_since} 天前）"
            self._statusLabel.setText(
                f"上次回测：{status.last_run_at}{days}｜"
                f"距上次新增 {status.new_points} 条有效快照"
            )
        else:
            self._statusLabel.setText("尚未运行过回测")

        if status.due:
            self._reasonsLabel.setText("建议复核：" + "；".join(status.reasons))
            self._reasonsLabel.setStyleSheet("color: #b26a00;")
        else:
            self._reasonsLabel.setText("当前无需复跑")
            self._reasonsLabel.setStyleSheet("color: #2e7d32;")

        self._reportLabel.setText(
            f"最近报告：{status.report_path}" if status.report_path else ""
        )

    def _renderEvents(self, events: List) -> None:
        """
        渲染待复核事件表。

        Args:
            events: 待复核事件列表。
        """
        self._pending_events = list(events)
        self._eventsTable.setRowCount(0)
        for event in events:
            row = self._eventsTable.rowCount()
            self._eventsTable.insertRow(row)
            values = [
                EVENT_DIRECTION_LABELS.get(event.direction, event.direction),
                f"{event.start_date} → {event.end_date}",
                f"{event.days} 天",
                f"{event.peak_ratio:.2f}",
                "待复核",
            ]
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                if column in (2, 3):
                    item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                else:
                    item.setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter)
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
        self._pending_events = []
        self._eventsTable.setRowCount(0)
        self._handleBtn.setEnabled(False)
        self._reportLabel.setText("")

    # ------------------------------------------------------------------ 操作

    def _onRunClicked(self) -> None:
        """运行一次回测：同步执行，期间禁用按钮并显示等待光标。"""
        self._runBtn.setEnabled(False)
        self._runBtn.setText("正在回测…")
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            run = self._service.run()
        except (DatabaseError, ValidationError) as e:
            QMessageBox.critical(self, "回测失败", str(e))
            return
        except Exception as e:  # 兜底，不让未知异常拖垮设置页
            QMessageBox.critical(self, "回测失败", f"回测未完成：{e}")
            return
        finally:
            QApplication.restoreOverrideCursor()
            self._runBtn.setEnabled(True)
            self._runBtn.setText("立即回测")

        self.resultReady.emit(run)
        self.refresh()

    def _onSelectionChanged(self) -> None:
        """事件选中状态变化：决定「标记已复核」是否可用。"""
        row = self._eventsTable.currentRow()
        self._handleBtn.setEnabled(0 <= row < len(self._pending_events))

    def _onHandleClicked(self) -> None:
        """把选中事件标记为已复核。"""
        row = self._eventsTable.currentRow()
        if row < 0 or row >= len(self._pending_events):
            return
        event = self._pending_events[row]
        try:
            changed = self._service.markEventHandled(event.direction, event.start_date)
        except DatabaseError as e:
            QMessageBox.critical(self, "回测记录", f"保存复核状态失败: {e}")
            return
        if not changed:
            QMessageBox.information(self, "回测记录", "该事件已复核或已不存在")
        self.refresh()


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
