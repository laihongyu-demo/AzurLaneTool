"""
活动记录面板模块。

主窗口「活动记录」页签：按年份 / 类型 / 状态筛选活动列表，提供新增、编辑、删除，
并在行内展示该活动关联的魔方支出（来自常规录入「支出 · 活动建造」）。

口径：
- 有明细时建造次数 = 关联魔方 ÷ 单次消耗 + 建造券次数；无明细时显示手工 / 历史值；
- 除不尽单耗时显示 ⚠ 并在 tooltip 给出余数，提醒核对明细金额；
- 删除活动只解除明细关联，明细本身保留；
- 活动记录不持有时间上下文，``onActivated`` / ``syncTimeContext`` 为空实现，
  数据变更由本页写操作与主窗口信号驱动。
"""

from typing import List, Optional

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QColor
from PyQt5.QtWidgets import (
    QAbstractItemView, QComboBox, QGroupBox, QHBoxLayout, QHeaderView, QLabel,
    QLineEdit, QMessageBox, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout,
    QWidget,
)

from models.event_model import EventRecordModel
from services.event_record_service import (
    EventRecordService, EventRecordView, EventSummary, EventWriteResult,
)
from utils.constants import (
    EVENT_STATUS_GRADUATED,
    EVENT_STATUS_MISSING,
    EVENT_STATUS_ONGOING,
    EVENT_STATUS_UNSET_LABEL,
)
from utils.exceptions import DatabaseError, ValidationError
from utils.unit_formatter import formatExact
from views.dialogs.event_record_dialog import EventRecordDialog

TABLE_HEADERS = (
    "日期", "类型", "活动", "状态", "单耗", "建造次数", "关联魔方", "笔数",
    "状态备注", "备注",
)

# 状态列配色：毕业绿、缺红、进行中蓝；其余保持默认色
STATUS_COLORS = {
    EVENT_STATUS_GRADUATED: QColor("#2e7d32"),
    EVENT_STATUS_MISSING: QColor("#c62828"),
    EVENT_STATUS_ONGOING: QColor("#1565c0"),
}

# 「全部」筛选项的 data 值；状态列额外用空串表示「未标记」
FILTER_ALL = None
STATUS_UNSET_FILTER = ""


class EventRecordPanel(QWidget):
    """
    活动记录页面板。

    自身负责筛选与 CRUD；写操作结果通过 ``resultReady`` 交给主窗口状态栏，
    ``dataChanged`` 用于让常规录入的活动下拉立即跟上。
    """

    dataChanged = pyqtSignal()
    resultReady = pyqtSignal(object)

    def __init__(
        self,
        event_service: Optional[EventRecordService] = None,
        parent: Optional[QWidget] = None,
    ):
        """
        初始化活动记录面板。

        Args:
            event_service: 活动记录服务实例。
            parent: 父控件。
        """
        super().__init__(parent)
        self._service = event_service or EventRecordService()
        self._views: List[EventRecordView] = []
        self._syncing_filters = False

        self._initUi()
        self._connectSignals()
        self.refreshData()

    # ------------------------------------------------------------------ UI

    def _initUi(self) -> None:
        """初始化用户界面。"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        self._group = QGroupBox("活动记录")
        group_layout = QVBoxLayout(self._group)
        group_layout.setContentsMargins(12, 16, 12, 12)
        group_layout.setSpacing(8)

        group_layout.addLayout(self._buildFilterRow())
        group_layout.addLayout(self._buildToolbar())

        self._table = self._buildTable()
        group_layout.addWidget(self._table, 1)

        hint = QLabel(
            "有明细时建造次数 = 关联魔方 ÷ 单次消耗 + 建造券次数；无明细时用手工 / 历史值。"
            "除不尽单耗时显示 ⚠，请核对明细金额。删除活动只解除关联，明细保留。",
            self,
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #666; font-size: 12px;")
        group_layout.addWidget(hint)

        layout.addWidget(self._group)

    def _buildFilterRow(self) -> QHBoxLayout:
        """
        构建筛选行（年份 / 类型 / 状态 / 关键词 / 刷新）。

        Returns:
            水平布局。
        """
        row = QHBoxLayout()
        row.setSpacing(8)

        self._yearCombo = QComboBox(self)
        self._yearCombo.setMinimumWidth(110)
        self._yearCombo.setMaximumHeight(28)

        self._typeCombo = QComboBox(self)
        self._typeCombo.setMinimumWidth(180)
        self._typeCombo.setMaximumHeight(28)

        self._statusCombo = QComboBox(self)
        self._statusCombo.setMinimumWidth(110)
        self._statusCombo.setMaximumHeight(28)

        self._searchEdit = QLineEdit(self)
        self._searchEdit.setPlaceholderText("搜索活动名 / 备注 / 状态备注")
        self._searchEdit.setMaximumHeight(28)
        self._searchEdit.setClearButtonEnabled(True)

        self._refreshBtn = QPushButton("刷新", self)
        self._refreshBtn.setFixedWidth(70)
        self._refreshBtn.setMaximumHeight(28)
        self._refreshBtn.setToolTip("重新加载活动记录与筛选选项")

        row.addWidget(QLabel("年份", self))
        row.addWidget(self._yearCombo)
        row.addWidget(QLabel("类型", self))
        row.addWidget(self._typeCombo, 1)
        row.addWidget(QLabel("状态", self))
        row.addWidget(self._statusCombo)
        row.addWidget(self._searchEdit, 1)
        row.addWidget(self._refreshBtn)
        return row

    def _buildToolbar(self) -> QHBoxLayout:
        """
        构建操作行（新增 / 编辑 / 删除 + 汇总）。

        Returns:
            水平布局。
        """
        row = QHBoxLayout()
        row.setSpacing(8)

        self._addBtn = QPushButton("新增", self)
        self._addBtn.setFixedWidth(80)
        self._addBtn.setMaximumHeight(28)

        self._editBtn = QPushButton("编辑", self)
        self._editBtn.setFixedWidth(80)
        self._editBtn.setMaximumHeight(28)
        self._editBtn.setEnabled(False)

        self._deleteBtn = QPushButton("删除", self)
        self._deleteBtn.setFixedWidth(80)
        self._deleteBtn.setMaximumHeight(28)
        self._deleteBtn.setEnabled(False)

        self._summaryLabel = QLabel("", self)
        self._summaryLabel.setStyleSheet("color: #666; font-size: 12px;")
        self._summaryLabel.setWordWrap(True)

        row.addWidget(self._addBtn)
        row.addWidget(self._editBtn)
        row.addWidget(self._deleteBtn)
        row.addSpacing(8)
        row.addWidget(self._summaryLabel, 1)
        return row

    def _buildTable(self) -> QTableWidget:
        """
        构建活动列表表格。

        Returns:
            表格控件。
        """
        table = QTableWidget(0, len(TABLE_HEADERS), self)
        table.setHorizontalHeaderLabels(TABLE_HEADERS)
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.setSelectionBehavior(QAbstractItemView.SelectRows)
        table.setSelectionMode(QAbstractItemView.SingleSelection)
        table.setAlternatingRowColors(True)
        table.setSortingEnabled(False)
        table.verticalHeader().setVisible(False)
        table.verticalHeader().setDefaultSectionSize(26)
        table.setWordWrap(False)
        table.setToolTip("双击一行可编辑；活动名称放不下时悬停查看完整内容")

        header = table.horizontalHeader()
        header.setStretchLastSection(True)
        header.setSectionResizeMode(QHeaderView.Interactive)
        header.setSectionResizeMode(2, QHeaderView.Stretch)
        header.setSectionResizeMode(9, QHeaderView.Stretch)
        table.setColumnWidth(0, 95)
        table.setColumnWidth(1, 150)
        table.setColumnWidth(3, 60)
        table.setColumnWidth(4, 64)
        table.setColumnWidth(5, 76)
        table.setColumnWidth(6, 80)
        table.setColumnWidth(7, 50)
        table.setColumnWidth(8, 150)
        return table

    def _connectSignals(self) -> None:
        """连接信号与槽。"""
        self._yearCombo.currentIndexChanged.connect(self._onFilterChanged)
        self._typeCombo.currentIndexChanged.connect(self._onFilterChanged)
        self._statusCombo.currentIndexChanged.connect(self._onFilterChanged)
        self._searchEdit.textChanged.connect(self._onFilterChanged)
        self._refreshBtn.clicked.connect(self.refreshData)
        self._addBtn.clicked.connect(self._onAddClicked)
        self._editBtn.clicked.connect(self._onEditClicked)
        self._deleteBtn.clicked.connect(self._onDeleteClicked)
        self._table.itemSelectionChanged.connect(self._onSelectionChanged)
        self._table.itemDoubleClicked.connect(self._onRowDoubleClicked)

    # --------------------------------------------------------------- 刷新

    def refreshData(self) -> None:
        """重新加载筛选选项与活动记录。"""
        self._reloadFilterOptions()
        self._reloadRecords()

    def _reloadFilterOptions(self) -> None:
        """按库中已有数据重建年份 / 类型 / 状态下拉，并尽量保留当前选择。"""
        try:
            options = self._service.getFilterOptions()
        except DatabaseError as e:
            self._syncing_filters = True
            try:
                self._yearCombo.clear()
                self._yearCombo.addItem(f"加载失败：{e}", FILTER_ALL)
                self._typeCombo.clear()
                self._typeCombo.addItem(f"加载失败：{e}", FILTER_ALL)
                self._statusCombo.clear()
                self._statusCombo.addItem(f"加载失败：{e}", FILTER_ALL)
            finally:
                self._syncing_filters = False
            return

        self._syncing_filters = True
        try:
            self._rebuildCombo(
                self._yearCombo,
                [("全部年份", FILTER_ALL)] + [(year, year) for year in options.years],
            )
            self._rebuildCombo(
                self._typeCombo,
                [("全部类型", FILTER_ALL)] + [(name, name) for name in options.types],
            )
            self._rebuildCombo(
                self._statusCombo,
                [("全部状态", FILTER_ALL)]
                + [(name, name) for name in options.statuses]
                + [(EVENT_STATUS_UNSET_LABEL, STATUS_UNSET_FILTER)],
            )
        finally:
            self._syncing_filters = False

    def _rebuildCombo(self, combo: QComboBox, entries) -> None:
        """
        重建下拉项并保留原选择（找不到时回退到第一项）。

        Args:
            combo: 目标下拉。
            entries: ``(文案, data)`` 列表。
        """
        previous = combo.currentData()
        combo.blockSignals(True)
        try:
            combo.clear()
            for label, data in entries:
                combo.addItem(label, data)
            index = combo.findData(previous)
            combo.setCurrentIndex(index if index >= 0 else 0)
        finally:
            combo.blockSignals(False)

    def _currentFilters(self):
        """
        读取当前筛选条件。

        Returns:
            ``(year, event_type, status, keyword)``；状态「全部」为 None。
        """
        keyword = self._searchEdit.text().strip() or None
        return (
            self._yearCombo.currentData(),
            self._typeCombo.currentData(),
            self._statusCombo.currentData(),
            keyword,
        )

    def _reloadRecords(self) -> None:
        """按当前筛选条件重新查询并渲染表格。"""
        year, event_type, status, keyword = self._currentFilters()
        try:
            self._views = self._service.listRecords(year, event_type, status, keyword)
        except DatabaseError as e:
            self._views = []
            self._populateTable()
            self._summaryLabel.setText(f"加载失败：{e}")
            self._onSelectionChanged()
            return

        self._populateTable()
        self._summaryLabel.setText(self._formatSummary(self._service.getSummary(self._views)))
        self._onSelectionChanged()

    def _populateTable(self) -> None:
        """把当前视图数据渲染到表格。"""
        self._table.blockSignals(True)
        try:
            self._table.setRowCount(0)
            self._table.setRowCount(len(self._views))
            for row, view in enumerate(self._views):
                record = view.record
                build_text = "—" if view.build_count is None else str(view.build_count)
                if view.derived and view.remainder:
                    build_text += " ⚠"
                values = (
                    record.event_date,
                    record.event_type or "—",
                    record.displayName,
                    record.displayStatus,
                    f"{record.build_cost} 魔方",
                    build_text,
                    formatExact(view.cube_expense) if view.transaction_count else "—",
                    str(view.transaction_count) if view.transaction_count else "—",
                    record.status_note,
                    record.note,
                )
                for column, value in enumerate(values):
                    item = QTableWidgetItem(value)
                    item.setData(Qt.UserRole, record.id)
                    if column in (5, 6, 7):
                        item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                    elif column in (3, 4):
                        item.setTextAlignment(Qt.AlignCenter)
                        if column == 3:
                            color = STATUS_COLORS.get(record.status)
                            if color is not None:
                                item.setForeground(color)
                    self._table.setItem(row, column, item)
                # 长文本用 tooltip 兜底，避免列宽压缩后看不到
                self._table.item(row, 2).setToolTip(record.displayName)
                self._table.item(row, 5).setToolTip(self._buildCountTooltip(view))
                if record.status_note:
                    self._table.item(row, 8).setToolTip(record.status_note)
                if record.note:
                    self._table.item(row, 9).setToolTip(record.note)
        finally:
            self._table.blockSignals(False)

    def _buildCountTooltip(self, view: EventRecordView) -> str:
        """
        生成建造次数单元格的提示（自动折算明细或手工值）。

        Args:
            view: 活动展示行。

        Returns:
            提示文本。
        """
        if not view.derived:
            return "手工 / 历史建造次数（该活动没有关联明细）"

        record = view.record
        if not view.transaction_count:
            return (
                f"该活动没有关联魔方明细：手工值 {record.build_count or 0}"
                f" + 建造券 {view.ticket_build_count} 次"
            )

        text = (
            f"由关联明细自动计算：{formatExact(view.cube_expense)} 魔方 ÷ "
            f"{record.build_cost} 魔方/次 = {view.cube_build_count} 次"
        )
        if view.ticket_build_count:
            text += f"；建造券 +{view.ticket_build_count} 次"
        if view.remainder:
            text += f"；余 {view.remainder} 魔方未计入，请核对明细金额"
        return text

    def _formatSummary(self, summary: EventSummary) -> str:
        """
        生成汇总文案。

        Args:
            summary: 口径汇总。

        Returns:
            单行文案。
        """
        parts = [
            f"共 {summary.total} 条",
            f"毕业 {summary.graduated}",
            f"缺 {summary.missing}",
            f"进行中 {summary.ongoing}",
            f"未标记 {summary.unset}",
        ]
        if summary.other:
            parts.append(f"其它 {summary.other}")
        parts.extend([
            f"建造次数合计 {formatExact(summary.build_count_total)}"
            f"（{summary.build_count_known} 条已统计）",
            f"关联魔方 {formatExact(summary.cube_expense)}（{summary.linked_count} 条活动有明细）",
        ])
        return "｜".join(parts)

    # --------------------------------------------------------------- 事件

    def _onFilterChanged(self) -> None:
        """筛选条件变化：只重查列表，不重建筛选下拉。"""
        if self._syncing_filters:
            return
        self._reloadRecords()

    def _onSelectionChanged(self) -> None:
        """选中行变化：启用 / 禁用编辑与删除按钮。"""
        enabled = self._table.currentRow() >= 0 and bool(self._views)
        self._editBtn.setEnabled(enabled)
        self._deleteBtn.setEnabled(enabled)

    def _onRowDoubleClicked(self, _item: QTableWidgetItem) -> None:
        """双击行：进入编辑。"""
        self._onEditClicked()

    def _selectedRecordId(self) -> Optional[int]:
        """
        当前选中行的活动 ID。

        Returns:
            活动记录 ID；未选中时返回 None。
        """
        row = self._table.currentRow()
        if row < 0 or row >= len(self._views):
            return None
        return self._views[row].record.id

    def _onAddClicked(self) -> None:
        """新增按钮：打开空白对话框。"""
        dialog = EventRecordDialog(self._service, None, self)
        dialog.saved.connect(self._onSaved)
        dialog.exec_()

    def _onEditClicked(self) -> None:
        """编辑按钮：按当前行重新取数后打开对话框。"""
        record_id = self._selectedRecordId()
        if record_id is None:
            return
        view = self._views[self._table.currentRow()]
        try:
            record = self._service.getRecord(record_id)
        except DatabaseError as e:
            QMessageBox.critical(self, "数据库错误", f"读取活动失败: {e}")
            return
        if record is None:
            QMessageBox.information(self, "记录不存在", "该活动记录可能已被删除，请刷新后重试")
            self.refreshData()
            return

        dialog = EventRecordDialog(
            self._service,
            record,
            self,
            linked_count=view.transaction_count,
            linked_cube_expense=view.cube_expense,
        )
        dialog.saved.connect(self._onSaved)
        dialog.exec_()

    def _onDeleteClicked(self) -> None:
        """删除按钮：确认后删除活动并解除明细关联。"""
        record_id = self._selectedRecordId()
        if record_id is None:
            return
        view = self._views[self._table.currentRow()]
        record: EventRecordModel = view.record

        message = (
            "确定删除这条活动记录吗？\n\n"
            f"日期：{record.event_date}\n"
            f"活动：{record.displayName}\n"
        )
        if view.transaction_count:
            message += (
                f"关联明细：{view.transaction_count} 笔 / "
                f"{formatExact(view.cube_expense)} 魔方\n"
                "删除后只解除关联，明细本身保留。"
            )
        else:
            message += "该活动没有关联明细。"

        reply = QMessageBox.question(
            self, "确认删除", message, QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        )
        if reply != QMessageBox.Yes:
            return

        try:
            result = self._service.delete(record_id)
        except ValidationError as e:
            QMessageBox.warning(self, "无法删除", str(e))
            self.refreshData()
            return
        except DatabaseError as e:
            QMessageBox.critical(self, "数据库错误", f"删除失败: {e}")
            return

        self._onSaved(result)

    def _onSaved(self, result: EventWriteResult) -> None:
        """
        写操作成功后的统一收尾。

        Args:
            result: 写操作结果。
        """
        self.refreshData()
        self.resultReady.emit(result)
        self.dataChanged.emit()

    # ------------------------------------------------- 时间上下文（空实现）

    def onActivated(self) -> None:
        """页签激活：活动记录不持有时间上下文，不在这里查库。"""
        return

    def syncTimeContext(self) -> None:
        """同步时间上下文：活动记录与「今天」无关，保留空实现。"""
        return
