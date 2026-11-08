"""
指级经验面板模块。

提供指挥官等级快照的录入、查询、编辑与删除界面。
"""

from datetime import date, datetime, timedelta
from typing import Dict, List, Optional

from PyQt5.QtCore import QDate, QDateTime, Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QAbstractItemView, QDateEdit, QDateTimeEdit, QGridLayout, QGroupBox, QHBoxLayout,
    QHeaderView, QLabel, QMessageBox, QPushButton, QSizePolicy, QSpinBox, QTableWidget,
    QTableWidgetItem, QVBoxLayout, QWidget,
)

from models.commander_model import CommanderSnapshotModel
from services.commander_service import (
    CommanderService, TargetLevelProjection,
)
from utils import time_source
from utils.constants import (
    COMMANDER_LEVEL_MAX, COMMANDER_LEVEL_MIN, COMMANDER_SNAPSHOT_RECENT_LIMIT,
    QT_DATE_DISPLAY_FORMAT, QT_DATETIME_DISPLAY_FORMAT,
)
from utils.db_schema import isMissingTableError
from utils.exceptions import DatabaseError, ValidationError
from utils.unit_formatter import formatExact

TABLE_HEADERS = ["时间", "等级", "当前经验", "本级所需", "进度"]
PREDICTION_HEADERS = ["目标等级", "还需经验", "30 天口径", "90 天口径", "预计日期"]
ID_ROLE = Qt.UserRole
DEFAULT_QUERY_RANGE_DAYS = 90
# 超过这个天数时，预测属于“长期外推”，按 #35 方案标注误差量级
LONG_HORIZON_DAYS = 90.0
LONG_HORIZON_HINT = "长期估算，误差约 ±20%"


class CommanderExpPanel(QWidget):
    """
    指级经验面板控件。

    上半部分为快照表单（新增 / 编辑共用），下半部分为历史列表与查询。
    """

    dataRefreshed = pyqtSignal()
    snapshotResult = pyqtSignal(object)

    def __init__(self, commander_service: Optional[CommanderService] = None, parent: QWidget = None):
        """
        初始化指级经验面板。

        Args:
            commander_service: 指挥官服务实例。
            parent: 父控件。
        """
        super().__init__(parent)
        self._commander_service = commander_service or CommanderService()
        self._editing_id: Optional[int] = None
        self._rows: Dict[int, Dict] = {}
        self._loading = False
        self._updating = False
        self._auto_moment: Optional[datetime] = None
        self._auto_start_date: Optional[date] = None
        self._auto_end_date: Optional[date] = None
        self._syncing_dates = False
        # 升级预测：首次拿到有效当前等级时把目标设为「当前+1」，之后保留用户选择
        self._prediction_initialized = False
        self._prediction_loading = False

        self._initUi()
        self._connectSignals()
        self._resetForm()
        self.refreshData()

    # ------------------------------------------------------------------ UI

    def _initUi(self) -> None:
        """初始化用户界面。"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(15)

        group = QGroupBox("指级经验")
        group_layout = QVBoxLayout(group)
        group_layout.setContentsMargins(15, 20, 15, 20)
        group_layout.setSpacing(12)

        group_layout.addLayout(self._buildFormLayout())
        group_layout.addWidget(self._buildRequirementLabel())
        group_layout.addLayout(self._buildButtonLayout())
        group_layout.addLayout(self._buildQueryLayout())
        group_layout.addWidget(self._buildTable())
        layout.addWidget(group)
        layout.addWidget(self._buildPredictionGroup())
        layout.addStretch()

    def _buildFormLayout(self) -> QGridLayout:
        """
        构建快照表单布局。

        Returns:
            表单网格布局。
        """
        form = QGridLayout()
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(10)

        self._timeEdit = QDateTimeEdit(self)
        self._timeEdit.setDisplayFormat(QT_DATETIME_DISPLAY_FORMAT)
        self._timeEdit.setCalendarPopup(True)
        self._timeEdit.setDateTime(QDateTime(time_source.now()))
        self._timeEdit.setMaximumDateTime(QDateTime(time_source.now()))
        self._timeEdit.setMinimumWidth(150)
        # 限定宽度：QDateTimeEdit 的 minimumSizeHint 约 300px，不封顶会把整行撑到 750px+。
        # 注意不能用 QSizePolicy.Ignored——布局会把列宽压到比控件还窄，控件就会互相重叠。
        self._timeEdit.setMaximumWidth(180)

        self._levelSpin = QSpinBox(self)
        self._levelSpin.setRange(COMMANDER_LEVEL_MIN, COMMANDER_LEVEL_MAX)
        self._levelSpin.setMinimumWidth(90)

        self._expSpin = QSpinBox(self)
        self._expSpin.setRange(0, 1_000_000)
        self._expSpin.setSingleStep(1000)
        self._expSpin.setMinimumWidth(140)
        self._expSpin.setToolTip("当前等级内已累积的经验，不含此前等级")

        self._modeLabel = QLabel("新增记录", self)
        self._modeLabel.setStyleSheet("color: #1565c0;")

        form.addWidget(QLabel("时间:", self), 0, 0)
        form.addWidget(self._timeEdit, 0, 1)
        form.addWidget(QLabel("等级:", self), 0, 2)
        form.addWidget(self._levelSpin, 0, 3)
        form.addWidget(QLabel("当前经验:", self), 0, 4)
        form.addWidget(self._expSpin, 0, 5)
        form.addWidget(self._modeLabel, 1, 0, 1, 6)
        form.setColumnStretch(6, 1)
        return form

    def _buildRequirementLabel(self) -> QLabel:
        """
        构建需求经验与进度提示标签。

        Returns:
            提示标签。
        """
        self._requirementLabel = QLabel("-", self)
        self._requirementLabel.setStyleSheet("color: #666;")
        # 需求经验文案较长，允许换行，否则会把整个面板的最小宽度撑到 1000px 以上
        self._requirementLabel.setWordWrap(True)
        return self._requirementLabel

    def _buildButtonLayout(self) -> QHBoxLayout:
        """
        构建操作按钮布局。

        Returns:
            按钮水平布局。
        """
        buttons = QHBoxLayout()
        self._saveBtn = self._makeButton("保存快照")
        self._cancelBtn = self._makeButton("取消编辑")
        self._deleteBtn = self._makeButton("删除选中")
        self._refreshBtn = self._makeButton("刷新")

        buttons.addWidget(self._saveBtn)
        buttons.addWidget(self._cancelBtn)
        buttons.addWidget(self._deleteBtn)
        buttons.addStretch()
        buttons.addWidget(self._refreshBtn)
        return buttons

    def _makeButton(self, text: str) -> QPushButton:
        """
        创建统一样式的按钮。

        Args:
            text: 按钮文案。

        Returns:
            按钮控件。
        """
        button = QPushButton(text, self)
        button.setMinimumWidth(90)
        button.setMinimumHeight(32)
        return button

    def _buildQueryLayout(self) -> QHBoxLayout:
        """
        构建查询条件布局。

        Returns:
            查询条件水平布局。
        """
        query = QHBoxLayout()
        today = time_source.today()
        self._auto_start_date = today - timedelta(days=DEFAULT_QUERY_RANGE_DAYS)
        self._auto_end_date = today

        self._startDateEdit = self._makeDateEdit(self._toQDate(self._auto_start_date))
        self._endDateEdit = self._makeDateEdit(self._toQDate(self._auto_end_date))
        self._startDateEdit.dateChanged.connect(
            lambda _value: self._onQueryDateChanged("start")
        )
        self._endDateEdit.dateChanged.connect(
            lambda _value: self._onQueryDateChanged("end")
        )

        self._queryBtn = self._makeButton("查询区间")
        self._recentBtn = self._makeButton(f"最近 {COMMANDER_SNAPSHOT_RECENT_LIMIT} 条")

        query.addWidget(QLabel("起始:", self))
        query.addWidget(self._startDateEdit)
        query.addWidget(QLabel("结束:", self))
        query.addWidget(self._endDateEdit)
        query.addWidget(self._queryBtn)
        query.addWidget(self._recentBtn)
        query.addStretch()
        self._countLabel = QLabel("", self)
        self._countLabel.setStyleSheet("color: #666;")
        query.addWidget(self._countLabel)
        return query

    def _toQDate(self, value: date) -> QDate:
        """
        Python 日期转 ``QDate``。

        Args:
            value: Python 日期。

        Returns:
            Qt 日期。
        """
        return QDate(value.year, value.month, value.day)

    def _setQueryDate(self, edit: QDateEdit, value: date) -> None:
        """
        程序化设置查询日期（不视为用户手动态）。

        Args:
            edit: 日期控件。
            value: 目标日期。
        """
        self._syncing_dates = True
        try:
            edit.setDate(self._toQDate(value))
        finally:
            self._syncing_dates = False

    def _onQueryDateChanged(self, which: str) -> None:
        """
        用户改了查询日期：退出自动跟随。

        Args:
            which: ``start`` 或 ``end``。
        """
        if self._syncing_dates:
            return
        if which == "start":
            self._auto_start_date = None
        else:
            self._auto_end_date = None

    def _makeDateEdit(self, value: QDate) -> QDateEdit:
        """
        创建日期选择控件。

        Args:
            value: 初始日期。

        Returns:
            日期控件。
        """
        edit = QDateEdit(self)
        edit.setCalendarPopup(True)
        edit.setDisplayFormat(QT_DATE_DISPLAY_FORMAT)
        edit.setDate(value)
        edit.setMinimumWidth(105)
        edit.setMaximumWidth(125)
        return edit

    def _buildTable(self) -> QTableWidget:
        """
        构建历史列表。

        Returns:
            表格控件。
        """
        self._table = QTableWidget(0, len(TABLE_HEADERS), self)
        self._table.setHorizontalHeaderLabels(TABLE_HEADERS)
        self._table.verticalHeader().setVisible(False)
        self._table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SingleSelection)
        self._table.setAlternatingRowColors(True)
        self._table.setMinimumHeight(200)
        self._table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self._table.setToolTip("选中一行可编辑该条记录；双击亦可进入编辑")
        return self._table

    def _buildPredictionGroup(self) -> QGroupBox:
        """
        构建「升级预测」分组（#35）。

        只读展示：自选目标等级 + 剩余经验 / 预计天数 / 长期参考 / 近期情景，
        下方列出常用里程碑。不写库、不改卡片。

        Returns:
            预测分组控件。
        """
        group = QGroupBox("升级预测", self)
        layout = QVBoxLayout(group)
        layout.setContentsMargins(15, 20, 15, 15)
        layout.setSpacing(8)

        row = QHBoxLayout()
        row.setSpacing(10)
        row.addWidget(QLabel("目标等级", self))
        self._targetSpin = QSpinBox(self)
        self._targetSpin.setRange(COMMANDER_LEVEL_MIN, COMMANDER_LEVEL_MAX)
        self._targetSpin.setFixedWidth(80)
        self._targetSpin.setToolTip("自选目标等级；到 200 级按满级累计经验计算")
        row.addWidget(self._targetSpin)
        self._targetSummaryLabel = QLabel("-", self)
        self._targetSummaryLabel.setMinimumWidth(180)
        row.addWidget(self._targetSummaryLabel)
        row.addStretch()
        layout.addLayout(row)

        self._targetDetailLabel = QLabel("-", self)
        self._targetDetailLabel.setWordWrap(True)
        self._targetDetailLabel.setToolTip(
            "主口径为近 30 天日均；超过 90 天的目标属于长期外推，误差约 ±20%，"
            "因此只给单值，不写区间"
        )
        layout.addWidget(self._targetDetailLabel)

        self._predictionTable = QTableWidget(0, len(PREDICTION_HEADERS), self)
        self._predictionTable.setHorizontalHeaderLabels(PREDICTION_HEADERS)
        self._predictionTable.verticalHeader().setVisible(False)
        self._predictionTable.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._predictionTable.setSelectionMode(QAbstractItemView.NoSelection)
        self._predictionTable.setAlternatingRowColors(True)
        self._predictionTable.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self._predictionTable.setFixedHeight(8 * 24 + 30)
        layout.addWidget(self._predictionTable)
        return group

    # ------------------------------------------------------------- signals

    def _connectSignals(self) -> None:
        """连接信号与槽。"""
        self._levelSpin.valueChanged.connect(self._onLevelChanged)
        self._expSpin.valueChanged.connect(self._onExpChanged)
        self._saveBtn.clicked.connect(self._onSaveClicked)
        self._cancelBtn.clicked.connect(self._onCancelClicked)
        self._deleteBtn.clicked.connect(self._onDeleteClicked)
        self._refreshBtn.clicked.connect(self._onRefreshClicked)
        self._queryBtn.clicked.connect(self._onQueryClicked)
        self._recentBtn.clicked.connect(self._onRecentClicked)
        self._table.itemSelectionChanged.connect(self._onSelectionChanged)
        self._table.doubleClicked.connect(self._onSelectionChanged)
        self._targetSpin.valueChanged.connect(self._onTargetLevelChanged)

    # ---------------------------------------------------------- form state

    def _resetForm(self) -> None:
        """把表单恢复为"新增记录"状态。"""
        try:
            latest_rows = self._commander_service.listSnapshotRows(limit=1)
        except DatabaseError:
            latest_rows = []
        latest = latest_rows[0] if latest_rows else None

        self._editing_id = None
        self._modeLabel.setText("新增记录")
        self._saveBtn.setText("保存快照")
        moment = time_source.now()
        self._auto_moment = moment
        self._syncTimeLimit()
        self._setTimeValue(moment)

        level = latest["commander_level"] if latest else 100
        self._loading = True
        self._levelSpin.setValue(level)
        self._expSpin.setValue(latest["commander_exp"] if latest else 0)
        self._loading = False
        self._updateRequirementLabels()

    def _onLevelChanged(self, _value: int) -> None:
        """等级变化事件处理：刷新经验上限与需求提示。"""
        self._updateRequirementLabels()

    def _onExpChanged(self, _value: int) -> None:
        """经验变化事件处理：刷新进度提示。"""
        self._updateRequirementLabels()

    def _updateRequirementLabels(self) -> None:
        """根据当前等级与经验刷新需求经验、累计经验与进度提示。"""
        if self._updating:
            return

        self._updating = True
        try:
            level = self._levelSpin.value()
            current_exp = self._expSpin.value()
            overview = self._commander_service.getLevelOverview(level, current_exp)

            if overview.required_exp is not None:
                self._expSpin.setMaximum(overview.required_exp)
                required_text = formatExact(overview.required_exp)
            else:
                self._expSpin.setMaximum(1_000_000)
                required_text = "-"

            cumulative_text = (
                formatExact(overview.cumulative_exp) if overview.cumulative_exp is not None else "-"
            )
            progress_text = (
                f"{overview.progress_rate:.1f}%" if overview.progress_rate is not None else "-"
            )
            self._requirementLabel.setText(
                f"本级所需：{required_text}｜累计所需：{cumulative_text}｜当前进度：{progress_text}"
            )
        finally:
            self._updating = False

    def _enterEditMode(self, row: Dict) -> None:
        """
        把某条快照回填到表单，进入编辑状态。

        Args:
            row: 列表行数据字典。
        """
        self._editing_id = row["id"]
        self._modeLabel.setText(f"正在编辑：{row['statistics_date']}")
        self._saveBtn.setText("更新快照")

        timestamp = QDateTime.fromString(row["statistics_date"], QT_DATETIME_DISPLAY_FORMAT)
        if timestamp.isValid():
            self._timeEdit.setDateTime(timestamp)

        self._loading = True
        self._levelSpin.setValue(row["commander_level"])
        self._loading = False
        self._updateRequirementLabels()

        self._updating = True
        self._expSpin.setValue(row["commander_exp"])
        self._updating = False
        self._updateRequirementLabels()

    def _selectedRow(self) -> Optional[Dict]:
        """
        获取当前选中行对应的数据。

        Returns:
            行数据字典；未选中时返回 None。
        """
        selected = self._table.selectionModel().selectedRows()
        if not selected:
            return None
        item = self._table.item(selected[0].row(), 0)
        if item is None:
            return None
        record_id = item.data(ID_ROLE)
        return self._rows.get(record_id)

    # --------------------------------------------------------------- slots

    def _onSelectionChanged(self, *_args) -> None:
        """列表选中事件处理：回填表单进入编辑状态。"""
        if self._loading:
            return
        row = self._selectedRow()
        if row is not None:
            self._enterEditMode(row)

    def _onCancelClicked(self) -> None:
        """取消编辑事件处理。"""
        self._loading = True
        self._table.clearSelection()
        self._loading = False
        self._resetForm()

    def _onRefreshClicked(self) -> None:
        """刷新按钮点击事件处理。"""
        self.refreshData()
        self.dataRefreshed.emit()

    def _onQueryClicked(self) -> None:
        """按日期区间查询事件处理。"""
        self.syncTimeContext()
        start = self._startDateEdit.date().toString(QT_DATE_DISPLAY_FORMAT)
        end = self._endDateEdit.date().toString(QT_DATE_DISPLAY_FORMAT)
        if start > end:
            QMessageBox.information(self, "提示", "起始日期不能晚于结束日期")
            return
        self._loadRows(start_date=start, end_date=end)

    def _onRecentClicked(self) -> None:
        """查看最近若干条记录事件处理。"""
        self._loadRows(limit=COMMANDER_SNAPSHOT_RECENT_LIMIT)

    def _onSaveClicked(self) -> None:
        """保存快照事件处理：新增或更新。"""
        snapshot = CommanderSnapshotModel(
            id=self._editing_id,
            statistics_date=QDateTime(self._selectedMoment()).toString(QT_DATETIME_DISPLAY_FORMAT),
            commander_level=self._levelSpin.value(),
            commander_exp=self._expSpin.value(),
        )

        try:
            if self._editing_id is None:
                result = self._commander_service.addSnapshot(snapshot)
            else:
                result = self._commander_service.updateSnapshot(snapshot)
        except ValidationError as e:
            QMessageBox.warning(self, "校验未通过", str(e))
            return
        except DatabaseError as e:
            QMessageBox.critical(self, "数据库错误", f"保存失败: {e}")
            return

        self.snapshotResult.emit(result)
        self._loading = True
        self._table.clearSelection()
        self._loading = False
        self._resetForm()
        self.refreshData()
        self.dataRefreshed.emit()

    def _onDeleteClicked(self) -> None:
        """删除选中快照事件处理。"""
        row = self._selectedRow()
        if row is None:
            QMessageBox.information(self, "提示", "请先在列表中选择要删除的记录")
            return

        reply = QMessageBox.question(
            self,
            "确认删除",
            f"确定删除 {row['statistics_date']} 的指挥官 {row['commander_level']} 级快照吗？",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return

        try:
            result = self._commander_service.deleteSnapshot(row["id"])
        except ValidationError as e:
            QMessageBox.warning(self, "删除失败", str(e))
            self.refreshData()
            return
        except DatabaseError as e:
            QMessageBox.critical(self, "数据库错误", f"删除失败: {e}")
            return

        self.snapshotResult.emit(result)
        self._loading = True
        self._table.clearSelection()
        self._loading = False
        self._resetForm()
        self.refreshData()
        self.dataRefreshed.emit()

    # --------------------------------------------------------------- data

    def refreshData(self) -> None:
        """刷新历史列表与升级预测（默认展示最近若干条）。"""
        self._loadRows(limit=COMMANDER_SNAPSHOT_RECENT_LIMIT)
        self._refreshPrediction()

    # ---------------------------------------------------------- prediction

    def _onTargetLevelChanged(self, _value: int) -> None:
        """目标等级变化：只重算预测，不写库。"""
        if self._prediction_loading:
            return
        self._refreshPrediction()

    def _refreshPrediction(self) -> None:
        """
        刷新「升级预测」：里程碑只取一次最新快照，随后渲染当前目标。

        任何异常都降级为一行提示，不让只读区块影响快照录入。
        """
        try:
            milestones = self._commander_service.listTargetLevelProjections()
        except DatabaseError as e:
            self._showPredictionError(f"数据库错误：{e}")
            return
        except Exception as e:  # 只读区块兜底，避免整个窗口不可用
            self._showPredictionError(f"预测不可用：{e}")
            return

        self._renderMilestones(milestones)
        self._syncDefaultTarget(milestones)

        try:
            projection = self._commander_service.getTargetLevelProjection(
                self._targetSpin.value()
            )
        except DatabaseError as e:
            self._showPredictionError(f"数据库错误：{e}")
            return
        except Exception as e:
            self._showPredictionError(f"预测不可用：{e}")
            return
        self._renderProjection(projection)

    def _syncDefaultTarget(self, milestones: List[TargetLevelProjection]) -> None:
        """
        首次拿到有效当前等级时，把目标设为「当前+1」并固定下来。

        Args:
            milestones: 里程碑预测结果（用于读取当前等级）。
        """
        if self._prediction_initialized or not milestones:
            return
        current_level = milestones[0].current_level
        if current_level <= 0:
            return

        self._prediction_loading = True
        try:
            self._targetSpin.setValue(min(current_level + 1, COMMANDER_LEVEL_MAX))
        finally:
            self._prediction_loading = False
        self._prediction_initialized = True

    def _renderProjection(self, projection: TargetLevelProjection) -> None:
        """
        渲染选中目标的剩余经验、天数与情景。

        Args:
            projection: 服务层返回的预测结果。
        """
        if projection.degraded_reason in ("已满级", "已在该等级", "目标低于当前等级"):
            self._targetSummaryLabel.setText(projection.degraded_reason)
            self._targetDetailLabel.setText("")
            return
        if projection.remaining_exp is None:
            self._targetSummaryLabel.setText("-")
            self._targetDetailLabel.setText(projection.degraded_reason or "暂无法计算")
            return

        self._targetSummaryLabel.setText(
            f"还需 {formatExact(projection.remaining_exp)} 经验"
        )
        if projection.days_slow is None:
            self._targetDetailLabel.setText(
                projection.degraded_reason or "指级效率数据不足，暂无法估算天数"
            )
            return

        date_text = f"（{projection.estimated_date}）" if projection.estimated_date else ""
        parts = [f"约 {projection.days_slow:.1f} 天{date_text}"]
        if projection.days_long is not None:
            parts.append(f"近 90 天节奏 {projection.days_long:.1f} 天")
        if projection.days_fast is not None:
            parts.append(f"若维持近期节奏 {projection.days_fast:.1f} 天")
        if projection.days_slow > LONG_HORIZON_DAYS:
            parts.append(LONG_HORIZON_HINT)
        self._targetDetailLabel.setText("｜".join(parts))

    def _renderMilestones(self, projections: List[TargetLevelProjection]) -> None:
        """
        渲染里程碑表格。

        Args:
            projections: 里程碑预测结果（按服务层顺序）。
        """
        self._predictionTable.setRowCount(0)
        for projection in projections:
            row_index = self._predictionTable.rowCount()
            self._predictionTable.insertRow(row_index)
            values = [
                f"{projection.target_level} 级",
                formatExact(projection.remaining_exp) if projection.remaining_exp is not None else "-",
                self._formatDaysText(projection.days_slow),
                self._formatDaysText(projection.days_long),
                projection.estimated_date or "-",
            ]
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                if column in (1, 2, 3):
                    item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                else:
                    item.setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter)
                self._predictionTable.setItem(row_index, column, item)

    @staticmethod
    def _formatDaysText(value: Optional[float]) -> str:
        """
        把天数格式化为 1 位小数；无值时显示 `-`。

        Args:
            value: 天数。

        Returns:
            展示文本。
        """
        return "-" if value is None else f"{value:.1f} 天"

    def _showPredictionError(self, message: str) -> None:
        """
        预测不可用时的降级展示。

        Args:
            message: 提示文本。
        """
        self._targetSummaryLabel.setText("-")
        self._targetDetailLabel.setText(message)
        self._predictionTable.setRowCount(0)

    def syncTimeContext(self) -> bool:
        """
        同步自动态时间、查询区间与时刻上限；编辑中或用户改过的值保持不变。

        只改控件，不查数据库。

        Returns:
            是否有时间控件被更新。
        """
        now = time_source.now()
        self._timeEdit.setMaximumDateTime(QDateTime(now))
        if self._editing_id is not None:
            return False

        changed = False
        if (
            self._auto_moment is not None
            and self._timeEdit.dateTime().toPyDateTime() == self._auto_moment
            and now != self._auto_moment
        ):
            self._auto_moment = now
            self._setTimeValue(now)
            changed = True

        today = time_source.today()
        if (
            self._auto_start_date is not None
            and self._startDateEdit.date() == self._toQDate(self._auto_start_date)
        ):
            new_start = today - timedelta(days=DEFAULT_QUERY_RANGE_DAYS)
            if new_start != self._auto_start_date:
                self._auto_start_date = new_start
                self._setQueryDate(self._startDateEdit, new_start)
                changed = True

        if (
            self._auto_end_date is not None
            and self._endDateEdit.date() == self._toQDate(self._auto_end_date)
        ):
            if today != self._auto_end_date:
                self._auto_end_date = today
                self._setQueryDate(self._endDateEdit, today)
                changed = True

        return changed

    def onActivated(self) -> None:
        """窗口显示 / 跨天检查：同步时间上下文并重新载入列表。"""
        self.syncTimeContext()
        if self._editing_id is not None:
            return
        self.refreshData()

    def _setTimeValue(self, moment: datetime) -> None:
        """
        程序化设置快照时间。

        Args:
            moment: 目标时刻。
        """
        self._timeEdit.setDateTime(QDateTime(moment))

    def _selectedMoment(self) -> datetime:
        """
        当前快照时间：自动态以点击「保存」的瞬间为准。

        Returns:
            Python datetime。
        """
        current = self._timeEdit.dateTime().toPyDateTime()
        if self._auto_moment is not None and current == self._auto_moment:
            return time_source.now()
        return current

    def _syncTimeLimit(self) -> None:
        """把快照时间上限对齐到当前时间，避免选到未来。"""
        self._timeEdit.setMaximumDateTime(QDateTime(time_source.now()))

    def _loadRows(
        self,
        limit: Optional[int] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> None:
        """
        载入并渲染快照列表。

        Args:
            limit: 可选条数上限。
            start_date: 可选起始日期。
            end_date: 可选结束日期。
        """
        try:
            rows = self._commander_service.listSnapshotRows(
                limit=limit, start_date=start_date, end_date=end_date
            )
        except DatabaseError as e:
            self._renderRows([])
            if isMissingTableError(e):
                return
            QMessageBox.critical(self, "数据库错误", f"加载快照失败: {e}")
            return
        except Exception as e:  # 兜底：任何异常都不应让面板崩溃
            self._renderRows([])
            QMessageBox.critical(self, "错误", f"加载快照失败: {e}")
            return

        self._renderRows(rows)

    def _renderRows(self, rows: List[Dict]) -> None:
        """
        渲染表格数据。

        Args:
            rows: 服务层返回的展示行列表。
        """
        self._loading = True
        self._rows = {row["id"]: row for row in rows if row.get("id") is not None}
        self._table.setRowCount(0)

        for row in rows:
            row_index = self._table.rowCount()
            self._table.insertRow(row_index)
            values = [
                row["statistics_date"],
                str(row["commander_level"]),
                row["exp_text"],
                row["required_text"],
                row["progress_text"],
            ]
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                if column < 2:
                    item.setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter)
                else:
                    item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                if column == 0:
                    item.setData(ID_ROLE, row["id"])
                self._table.setItem(row_index, column, item)

        self._loading = False
        self._countLabel.setText(f"{len(rows)} 条")
