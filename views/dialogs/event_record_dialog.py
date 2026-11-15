"""
活动记录新增 / 编辑对话框模块。

提供活动的日期、类型、名称、状态、单次消耗、建造次数、建造券与备注录入；保存时经
:class:`EventRecordService` 校验并写库，成功后发出 ``saved`` 信号。

口径说明：
- 有明细关联时，建造次数 = 关联魔方合计 ÷ 单次消耗 + 建造券次数，表单里只读展示；
- 没有明细关联时，建造次数按手工 / 历史值填写；
- 建造券抽不消耗魔方，勾选后单独补填次数；
- 本活动的魔方支出需在「常规录入 → 支出 · 活动建造」中记录并选择本活动。
"""

from typing import Optional

from PyQt5.QtCore import QDate, pyqtSignal
from PyQt5.QtGui import QIntValidator
from PyQt5.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QGridLayout, QHBoxLayout, QLabel, QLineEdit,
    QMessageBox, QPushButton, QVBoxLayout, QWidget,
)

from models.event_model import EventRecordModel
from services.event_record_service import EventRecordService
from utils import time_source
from utils.constants import (
    EVENT_BUILD_COST_OPTIONS,
    EVENT_DEFAULT_BUILD_COST,
    EVENT_STATUS_ONGOING,
    EVENT_STATUS_OPTIONS,
    MAX_EVENT_BUILD_COUNT,
    MAX_EVENT_NAME_LENGTH,
    MAX_EVENT_NOTE_LENGTH,
    MAX_EVENT_STATUS_NOTE_LENGTH,
    MAX_EVENT_TYPE_LENGTH,
    QT_DATE_DISPLAY_FORMAT,
)
from utils.exceptions import DatabaseError, ValidationError
from views.widgets.calendar_only_date_edit import CalendarOnlyDateEdit


def _toQDate(value) -> QDate:
    """
    Python 日期转 ``QDate``。

    Args:
        value: ``datetime.date`` / ``datetime.datetime``。

    Returns:
        Qt 日期。
    """
    return QDate(value.year, value.month, value.day)


class EventRecordDialog(QDialog):
    """
    活动记录新增 / 编辑对话框。

    通过构造函数传入 ``record`` 区分新增（None）与编辑；``linked_count`` /
    ``linked_cube_expense`` 用于在有明细关联时展示自动折算的建造次数。
    """

    saved = pyqtSignal(object)

    def __init__(
        self,
        record_service: Optional[EventRecordService] = None,
        record: Optional[EventRecordModel] = None,
        parent: Optional[QWidget] = None,
        linked_count: int = 0,
        linked_cube_expense: int = 0,
    ):
        """
        初始化对话框。

        Args:
            record_service: 活动记录服务实例。
            record: 待编辑的活动记录；None 表示新增。
            parent: 父控件。
            linked_count: 关联明细笔数；>0 时建造次数自动折算。
            linked_cube_expense: 关联魔方合计。
        """
        super().__init__(parent)
        self._service = record_service or EventRecordService()
        self._record = record
        self._linked_count = max(0, int(linked_count or 0))
        self._linked_cube_expense = max(0, int(linked_cube_expense or 0))
        self._initUi()
        self._loadOptions()
        self._fillForm(record)
        self._refreshDerivedCount()

    # ------------------------------------------------------------------ UI

    def _initUi(self) -> None:
        """初始化用户界面。"""
        self.setWindowTitle("编辑活动" if self._record is not None else "新增活动")
        self.setMinimumWidth(560)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(15, 15, 15, 15)
        layout.setSpacing(10)

        hint = QLabel(
            "有明细关联时，建造次数 = 关联魔方 ÷ 单次消耗 + 建造券次数；"
            "没有明细时按手工 / 历史值填写。魔方支出请到「常规录入 → 支出 · 活动建造」记录。",
            self,
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #666; font-size: 12px;")
        layout.addWidget(hint)

        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(8)

        self._dateEdit = CalendarOnlyDateEdit(self)
        self._dateEdit.setDisplayFormat(QT_DATE_DISPLAY_FORMAT)
        self._dateEdit.setMaximumDate(_toQDate(time_source.today()))
        self._dateEdit.setMinimumWidth(140)

        self._typeCombo = QComboBox(self)
        self._typeCombo.setEditable(True)
        self._typeCombo.setMinimumWidth(240)
        if self._typeCombo.lineEdit() is not None:
            self._typeCombo.lineEdit().setPlaceholderText("如 大型海域、轻量化复刻·大型海域")

        self._nameEdit = QLineEdit(self)
        self._nameEdit.setMaxLength(MAX_EVENT_NAME_LENGTH)
        self._nameEdit.setPlaceholderText("活动名称（历史数据允许为空）")

        self._statusCombo = QComboBox(self)
        self._statusCombo.setEditable(True)
        self._statusCombo.setMinimumWidth(140)

        self._buildCostCombo = QComboBox(self)
        for cost in EVENT_BUILD_COST_OPTIONS:
            self._buildCostCombo.addItem(f"{cost} 魔方/次", cost)
        self._buildCostCombo.setCurrentIndex(
            self._buildCostCombo.findData(EVENT_DEFAULT_BUILD_COST)
        )
        self._buildCostCombo.setToolTip(
            "单抽消耗的魔方数：轻型 1，重型 / 特型 / 多数活动池 2"
        )

        self._buildCountEdit = QLineEdit(self)
        self._buildCountEdit.setValidator(QIntValidator(0, MAX_EVENT_BUILD_COUNT, self))
        self._buildCountEdit.setPlaceholderText("留空表示未统计")
        self._buildCountEdit.setToolTip(
            "手工 / 历史建造次数；有明细关联时改为自动折算并只读"
        )

        self._derivedHint = QLabel("", self)
        self._derivedHint.setWordWrap(True)
        self._derivedHint.setStyleSheet("color: #1565c0; font-size: 12px;")

        self._useTicketCheck = QCheckBox("使用建造券（不消耗魔方）", self)
        self._ticketCountEdit = QLineEdit(self)
        self._ticketCountEdit.setValidator(
            QIntValidator(0, MAX_EVENT_BUILD_COUNT, self)
        )
        self._ticketCountEdit.setPlaceholderText("券抽次数")
        self._ticketCountEdit.setToolTip(
            "不消耗魔方的建造券抽次数；仅在有关联明细时计入建造次数"
        )

        self._statusNoteEdit = QLineEdit(self)
        self._statusNoteEdit.setMaxLength(MAX_EVENT_STATUS_NOTE_LENGTH)
        self._statusNoteEdit.setPlaceholderText("如 缺吉尚、200 保底全毕业")

        self._noteEdit = QLineEdit(self)
        self._noteEdit.setMaxLength(MAX_EVENT_NOTE_LENGTH)
        self._noteEdit.setPlaceholderText("其它备注（可选）")

        grid.addWidget(QLabel("活动日期", self), 0, 0)
        grid.addWidget(self._dateEdit, 0, 1)
        grid.addWidget(QLabel("类型", self), 1, 0)
        grid.addWidget(self._typeCombo, 1, 1)
        grid.addWidget(QLabel("活动名称", self), 2, 0)
        grid.addWidget(self._nameEdit, 2, 1)
        grid.addWidget(QLabel("状态", self), 3, 0)
        grid.addWidget(self._statusCombo, 3, 1)
        grid.addWidget(QLabel("单次消耗", self), 4, 0)
        grid.addWidget(self._buildCostCombo, 4, 1)
        grid.addWidget(QLabel("建造次数", self), 5, 0)
        grid.addWidget(self._buildCountEdit, 5, 1)
        grid.addWidget(self._derivedHint, 6, 0, 1, 2)

        ticket_row = QHBoxLayout()
        ticket_row.setSpacing(8)
        ticket_row.addWidget(self._useTicketCheck)
        ticket_row.addWidget(QLabel("券抽次数", self))
        ticket_row.addWidget(self._ticketCountEdit, 1)
        grid.addWidget(QLabel("建造券", self), 7, 0)
        grid.addLayout(ticket_row, 7, 1)

        grid.addWidget(QLabel("状态备注", self), 8, 0)
        grid.addWidget(self._statusNoteEdit, 8, 1)
        grid.addWidget(QLabel("备注", self), 9, 0)
        grid.addWidget(self._noteEdit, 9, 1)
        grid.setColumnStretch(1, 1)
        layout.addLayout(grid)

        buttons = QHBoxLayout()
        buttons.addStretch()
        self._cancelBtn = QPushButton("取消", self)
        self._cancelBtn.setMinimumWidth(90)
        self._cancelBtn.clicked.connect(self.reject)
        self._saveBtn = QPushButton("保存", self)
        self._saveBtn.setMinimumWidth(90)
        self._saveBtn.setDefault(True)
        self._saveBtn.clicked.connect(self._onSaveClicked)
        buttons.addWidget(self._cancelBtn)
        buttons.addWidget(self._saveBtn)
        layout.addLayout(buttons)

        self._buildCostCombo.currentIndexChanged.connect(self._refreshDerivedCount)
        self._useTicketCheck.toggled.connect(self._onTicketToggled)
        self._ticketCountEdit.textChanged.connect(self._refreshDerivedCount)

    def _loadOptions(self) -> None:
        """加载类型与状态建议值；失败时保留下拉可手工输入。"""
        try:
            types = self._service.getTypeOptions()
        except DatabaseError:
            types = []
        try:
            statuses = self._service.getStatusOptions()
        except DatabaseError:
            statuses = list(EVENT_STATUS_OPTIONS)
        self._typeCombo.addItems(types)
        self._statusCombo.addItems(statuses)

    def _fillForm(self, record: Optional[EventRecordModel]) -> None:
        """
        按记录填充表单；新增时给出默认值。

        Args:
            record: 待编辑记录；None 表示新增。
        """
        if record is None:
            self._dateEdit.setDate(_toQDate(time_source.today()))
            self._statusCombo.setCurrentText(EVENT_STATUS_ONGOING)
            return

        parsed = QDate.fromString(record.event_date, QT_DATE_DISPLAY_FORMAT)
        self._dateEdit.setDate(parsed if parsed.isValid() else _toQDate(time_source.today()))
        self._typeCombo.setCurrentText(record.event_type)
        self._nameEdit.setText(record.name)
        self._statusCombo.setCurrentText(record.status)

        cost_index = self._buildCostCombo.findData(record.build_cost)
        self._buildCostCombo.setCurrentIndex(
            cost_index if cost_index >= 0 else self._buildCostCombo.findData(
                EVENT_DEFAULT_BUILD_COST
            )
        )
        self._buildCountEdit.setText(
            "" if record.build_count is None else str(record.build_count)
        )
        self._useTicketCheck.setChecked(bool(record.use_ticket))
        self._ticketCountEdit.setText(
            "" if record.ticket_build_count is None else str(record.ticket_build_count)
        )
        self._statusNoteEdit.setText(record.status_note)
        self._noteEdit.setText(record.note)

    # ------------------------------------------------------------- 计算

    def _onTicketToggled(self, _checked: bool) -> None:
        """建造券勾选变化：启用 / 禁用次数输入并刷新合计。"""
        self._refreshDerivedCount()

    def _ticketCountValue(self) -> int:
        """
        读取券抽次数（空值按 0）。

        Returns:
            非负整数。
        """
        text = self._ticketCountEdit.text().strip()
        return int(text) if text else 0

    def _refreshDerivedCount(self) -> None:
        """按关联明细与单耗刷新建造次数；无明细时保持手工输入。"""
        linked = self._linked_count > 0
        self._useTicketCheck.setEnabled(linked)
        self._ticketCountEdit.setEnabled(linked and self._useTicketCheck.isChecked())
        self._buildCountEdit.setReadOnly(linked)

        if not linked:
            self._derivedHint.setText(
                "无关联明细：建造次数按手工 / 历史值填写；录入「活动建造」后自动按单耗折算。"
            )
            return

        cost = self._buildCostCombo.currentData() or EVENT_DEFAULT_BUILD_COST
        cube_builds, remainder = divmod(self._linked_cube_expense, cost)
        ticket = self._ticketCountValue() if self._useTicketCheck.isChecked() else 0
        total = cube_builds + ticket
        self._buildCountEdit.setText(str(total))

        text = (
            f"由 {self._linked_count} 笔关联明细自动计算："
            f"{self._linked_cube_expense} 魔方 ÷ {cost} = {cube_builds} 次"
        )
        if remainder:
            text += f"；余 {remainder} 魔方未计入，请核对明细金额"
        if ticket:
            text += f"；建造券 +{ticket} 次"
        self._derivedHint.setText(text)

    # ------------------------------------------------------------------ 保存

    def _buildRecord(self) -> EventRecordModel:
        """
        从表单构造活动记录模型。

        Returns:
            未校验的记录模型。
        """
        build_count_text = self._buildCountEdit.text().strip()
        ticket_text = self._ticketCountEdit.text().strip()
        use_ticket = self._useTicketCheck.isChecked()
        return EventRecordModel(
            id=self._record.id if self._record is not None else None,
            event_date=self._dateEdit.date().toString(QT_DATE_DISPLAY_FORMAT),
            event_type=self._typeCombo.currentText(),
            name=self._nameEdit.text(),
            status=self._statusCombo.currentText(),
            status_note=self._statusNoteEdit.text(),
            build_cost=self._buildCostCombo.currentData() or EVENT_DEFAULT_BUILD_COST,
            use_ticket=1 if use_ticket else 0,
            ticket_build_count=(
                int(ticket_text) if use_ticket and ticket_text else None
            ),
            build_count=int(build_count_text) if build_count_text else None,
            note=self._noteEdit.text(),
        )

    def _onSaveClicked(self) -> None:
        """保存按钮：校验后新增 / 更新，成功后关闭对话框。"""
        build_count_text = self._buildCountEdit.text().strip()
        if build_count_text:
            try:
                int(build_count_text)
            except ValueError:
                QMessageBox.warning(
                    self, "校验失败", "建造次数需为 0 或正整数，留空表示未统计"
                )
                return

        ticket_text = self._ticketCountEdit.text().strip()
        if ticket_text and self._useTicketCheck.isChecked():
            try:
                int(ticket_text)
            except ValueError:
                QMessageBox.warning(
                    self, "校验失败", "建造券次数需为 0 或正整数"
                )
                return

        record = self._buildRecord()
        if self._record is None:
            try:
                result = self._service.create(record)
            except ValidationError as e:
                QMessageBox.warning(self, "校验失败", str(e))
                return
            except DatabaseError as e:
                QMessageBox.critical(self, "数据库错误", f"新增失败: {e}")
                return
        else:
            try:
                result = self._service.update(self._record.id, record)
            except ValidationError as e:
                QMessageBox.warning(self, "校验失败", str(e))
                return
            except DatabaseError as e:
                QMessageBox.critical(self, "数据库错误", f"更新失败: {e}")
                return

        self.saved.emit(result)
        self.accept()
