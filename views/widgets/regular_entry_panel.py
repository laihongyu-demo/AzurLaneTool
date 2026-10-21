"""
常规录入面板模块。

放在「魔方任务看板 → 常规录入」与「红尖尖任务看板 → 常规录入」分组里，用于补记
非固定收支（活动建造、礼包、军事委托等）。表单有四项：数量、类型、时刻、备注（可选），
类型来自类型字典，方向由类型决定（同一名称可能两个方向都存在，因此按「类型 + 方向」落库）。

时刻默认取当前时间（精确到秒），可选择过去时间做补录，但不能晚于当前时间。
备注只写入 ``resource_transaction.note``，暂不提供列表展示入口（见 #29）。

另提供「撤销上一笔」：删除最近一笔**非任务来源**的录入，用于记错时回退；
任务卡片的完成/取消由看板自己负责，不会被这个按钮误伤。
"""

from datetime import datetime
from typing import Optional

from PyQt5.QtCore import QDateTime, pyqtSignal
from PyQt5.QtWidgets import (
    QComboBox, QDateTimeEdit, QGridLayout, QLabel, QLineEdit, QMessageBox, QPushButton,
    QSizePolicy, QSpinBox, QWidget,
)

from services.resource_entry_service import (
    MAX_ENTRY_AMOUNT, MAX_NOTE_LENGTH, ResourceCategoryOption, ResourceEntryResult,
    ResourceEntryService,
)
from utils import time_source
from utils.constants import (
    QT_RECORD_TIME_DISPLAY_FORMAT,
    RESOURCE_DIRECTION_NAMES,
    RESOURCE_TYPE_CUBE,
)
from utils.exceptions import DatabaseError, ValidationError

# 表单最大宽度：放在占满整行的分组里时保持紧凑，不把输入框拉成一条长条
MAX_FORM_WIDTH = 520


class RegularEntryPanel(QWidget):
    """
    常规录入表单。

    只负责收集四项输入并调用 `ResourceEntryService`；写入 / 撤销结果通过信号交给
    外层刷新看板卡片与状态栏。
    """

    dataRefreshed = pyqtSignal()
    entryRecorded = pyqtSignal(object)

    def __init__(
        self,
        entry_service: Optional[ResourceEntryService] = None,
        resource_type: str = RESOURCE_TYPE_CUBE,
        parent: QWidget = None
    ):
        """
        初始化常规录入面板。

        Args:
            entry_service: 常规录入服务实例。
            resource_type: 资源类型，魔方或红尖尖。
            parent: 父控件。
        """
        super().__init__(parent)
        self._entry_service = entry_service or ResourceEntryService()
        self._resource_type = resource_type
        self._auto_moment: Optional[datetime] = time_source.now()
        self._undo_state_synced = False

        self._initUi()
        self._connectSignals()
        self.refreshCategories()
        self._syncTimeLimit()
        self._syncUndoState()

    # ------------------------------------------------------------------ UI

    def _initUi(self) -> None:
        """初始化用户界面。"""
        self.setMaximumWidth(MAX_FORM_WIDTH)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)

        layout = QGridLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setHorizontalSpacing(8)
        layout.setVerticalSpacing(8)

        self._amountSpin = QSpinBox(self)
        self._amountSpin.setRange(1, MAX_ENTRY_AMOUNT)
        self._amountSpin.setValue(1)
        self._amountSpin.setFixedWidth(100)
        self._amountSpin.setMaximumHeight(28)
        self._amountSpin.setToolTip("本次记入的数量")

        self._typeCombo = QComboBox(self)
        self._typeCombo.setMinimumWidth(140)
        self._typeCombo.setMaximumHeight(28)
        self._typeCombo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._typeCombo.setToolTip("收支类型；方向由类型决定（支出在前，收入在后）")

        self._timeEdit = QDateTimeEdit(self)
        self._timeEdit.setDisplayFormat(QT_RECORD_TIME_DISPLAY_FORMAT)
        self._timeEdit.setCalendarPopup(True)
        self._timeEdit.setDateTime(QDateTime(self._auto_moment))
        self._timeEdit.setFixedWidth(180)
        self._timeEdit.setMaximumHeight(28)
        self._timeEdit.setToolTip("发生时刻，默认当前时间；可改到过去补录，不能晚于现在")

        self._recordBtn = QPushButton("记录", self)
        self._recordBtn.setFixedWidth(64)
        self._recordBtn.setMaximumHeight(28)
        self._recordBtn.setToolTip("写入一笔明细")

        self._undoBtn = QPushButton("撤销上一笔", self)
        self._undoBtn.setFixedWidth(92)
        self._undoBtn.setMaximumHeight(28)
        self._undoBtn.setToolTip("删除最近一笔常规录入（不含任务卡片产生的记录）")

        self._nowBtn = QPushButton("现在", self)
        self._nowBtn.setFixedWidth(50)
        self._nowBtn.setMaximumHeight(28)
        self._nowBtn.setToolTip("把时刻切回当前时间并恢复自动跟随")

        self._noteEdit = QLineEdit(self)
        self._noteEdit.setMaxLength(MAX_NOTE_LENGTH)
        self._noteEdit.setPlaceholderText(f"备注（可选，≤{MAX_NOTE_LENGTH} 字）")
        self._noteEdit.setMaximumHeight(28)
        self._noteEdit.setToolTip("本次记录的备注；暂不提供历史列表展示入口")

        layout.addWidget(QLabel("数量", self), 0, 0)
        layout.addWidget(self._amountSpin, 0, 1)
        layout.addWidget(QLabel("类型", self), 0, 2)
        layout.addWidget(self._typeCombo, 0, 3, 1, 3)

        layout.addWidget(QLabel("时间", self), 1, 0)
        layout.addWidget(self._timeEdit, 1, 1, 1, 2)
        layout.addWidget(self._recordBtn, 1, 3)
        layout.addWidget(self._undoBtn, 1, 4)
        layout.addWidget(self._nowBtn, 1, 5)

        layout.addWidget(QLabel("备注", self), 2, 0)
        layout.addWidget(self._noteEdit, 2, 1, 1, 5)

        layout.setColumnStretch(3, 1)

    def _connectSignals(self) -> None:
        """连接信号与槽。"""
        self._recordBtn.clicked.connect(self._onRecordClicked)
        self._undoBtn.clicked.connect(self._onUndoClicked)
        self._nowBtn.clicked.connect(self._onNowClicked)

    # --------------------------------------------------------------- 数据

    def refreshCategories(self) -> None:
        """重新加载可选类型（类型字典变化后调用）。"""
        current = self._typeCombo.currentData()
        try:
            options = self._entry_service.getCategories(self._resource_type)
        except DatabaseError as e:
            self._typeCombo.clear()
            self._typeCombo.addItem(f"类型加载失败：{e}", None)
            self._typeCombo.setEnabled(False)
            return

        self._typeCombo.setEnabled(True)
        self._typeCombo.clear()
        for option in options:
            self._typeCombo.addItem(self._formatOption(option), option)

        if isinstance(current, ResourceCategoryOption):
            index = self._findOption(current)
            if index >= 0:
                self._typeCombo.setCurrentIndex(index)

    def refreshState(self) -> None:
        """刷新类型、时刻上限与撤销状态（外部数据变化后调用）。"""
        self.syncTimeContext()
        self.refreshCategories()
        self._syncUndoState()

    def syncTimeContext(self) -> bool:
        """
        把「自动态」时刻同步到当前时间；用户改过的时刻保持不变。

        只改控件，不查数据库。判定依据是控件值是否仍等于上次自动设置的值：
        一旦用户手动改过（补录），控件值就不再等于哨兵，之后不再自动覆盖。

        Returns:
            是否更新了控件。
        """
        # 先抬高上限再改值，否则新时刻会被旧上限夹回旧值
        moment = time_source.now()
        self._timeEdit.setMaximumDateTime(QDateTime(moment))
        if self._auto_moment is None:
            return False
        current = self._timeEdit.dateTime().toPyDateTime()
        if current != self._auto_moment:
            return False

        if moment == self._auto_moment:
            return False

        self._auto_moment = moment
        self._setTimeValue(moment)
        return True

    def onActivated(self) -> None:
        """页签激活 / 跨天检查：同步自动态时刻与上限，按需刷新撤销态。"""
        self.syncTimeContext()
        if not self._undo_state_synced:
            self._syncUndoState()

    def _setTimeValue(self, moment: datetime) -> None:
        """
        程序化设置时刻控件。

        Args:
            moment: 目标时刻。
        """
        self._timeEdit.setDateTime(QDateTime(moment))

    def _findOption(self, target: ResourceCategoryOption) -> int:
        """
        找到与目标选项同名同向的下标。

        Args:
            target: 目标选项。

        Returns:
            下标；找不到返回 -1。
        """
        for index in range(self._typeCombo.count()):
            option = self._typeCombo.itemData(index)
            if (
                isinstance(option, ResourceCategoryOption)
                and option.name == target.name
                and option.direction == target.direction
            ):
                return index
        return -1

    def _formatOption(self, option: ResourceCategoryOption) -> str:
        """
        生成下拉项文案：``支出 · 活动建造``。

        Args:
            option: 类型选项。

        Returns:
            下拉项文案。
        """
        direction_name = RESOURCE_DIRECTION_NAMES.get(option.direction, option.direction)
        return f"{direction_name} · {option.name}"

    def _selectedOption(self) -> Optional[ResourceCategoryOption]:
        """
        当前选中的类型选项。

        Returns:
            类型选项；未选择时返回 None。
        """
        option = self._typeCombo.currentData()
        return option if isinstance(option, ResourceCategoryOption) else None

    def _selectedMoment(self):
        """
        当前选择的时刻。

        若控件仍处于自动态（未手动改过），以点击「记录」的瞬间为准，
        而不是构造时写入控件、之后可能已经过期的旧值。

        Returns:
            Python datetime。
        """
        current = self._timeEdit.dateTime().toPyDateTime()
        if self._auto_moment is not None and current == self._auto_moment:
            return time_source.now()
        return current

    # --------------------------------------------------------------- 事件

    def _onNowClicked(self) -> None:
        """「现在」按钮：切回当前时间并恢复自动跟随。"""
        moment = time_source.now()
        self._auto_moment = moment
        self._timeEdit.setMaximumDateTime(QDateTime(moment))
        self._setTimeValue(moment)

    def _onRecordClicked(self) -> None:
        """记录按钮点击事件处理。"""
        self._syncTimeLimit()
        option = self._selectedOption()
        if option is None:
            QMessageBox.warning(self, "无法记录", "请先选择收支类型")
            return

        try:
            result = self._entry_service.record(
                category=option.name,
                direction=option.direction,
                amount=self._amountSpin.value(),
                moment=self._selectedMoment(),
                resource_type=self._resource_type,
                note=self._noteEdit.text(),
            )
        except ValidationError as e:
            QMessageBox.warning(self, "无法记录", str(e))
            return
        except DatabaseError as e:
            QMessageBox.critical(self, "数据库错误", f"记录失败: {e}")
            return

        self._afterWrite(result)
        self._noteEdit.clear()

    def _onUndoClicked(self) -> None:
        """撤销按钮点击事件处理：确认后删除最近一笔常规录入。"""
        try:
            target = self._entry_service.getUndoableEntry(self._resource_type)
        except DatabaseError as e:
            QMessageBox.critical(self, "数据库错误", f"查询失败: {e}")
            return

        if target is None:
            QMessageBox.information(self, "无可撤销", "没有可撤销的常规录入")
            self._syncUndoState()
            return

        direction_name = RESOURCE_DIRECTION_NAMES.get(target.direction, target.direction)
        message = (
            "撤销最近一笔录入？\n\n"
            f"类型：{target.category}（{direction_name}）\n"
            f"数量：{target.amount}\n"
            f"时间：{target.record_time}"
        )
        reply = QMessageBox.question(
            self, "确认撤销", message, QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        )
        if reply != QMessageBox.Yes:
            return

        try:
            result = self._entry_service.undoLast(self._resource_type)
        except ValidationError as e:
            QMessageBox.warning(self, "无法撤销", str(e))
            self._syncUndoState()
            return
        except DatabaseError as e:
            QMessageBox.critical(self, "数据库错误", f"撤销失败: {e}")
            return

        self._afterWrite(result)

    def _afterWrite(self, result: ResourceEntryResult) -> None:
        """
        写入 / 撤销成功后的收尾：刷新状态、通知外部。

        Args:
            result: 操作结果。
        """
        self._syncTimeLimit()
        self._syncUndoState()
        # 自动态写入后推进到当前时间；手动补录则保留用户选择，便于连续补记
        if self._auto_moment is not None and self._selectedMomentIsAuto():
            moment = time_source.now()
            self._auto_moment = moment
            self._timeEdit.setMaximumDateTime(QDateTime(moment))
            self._setTimeValue(moment)
        # 先刷新数据、再回报结果：避免刷新过程中的状态栏文案覆盖操作提示
        self.dataRefreshed.emit()
        self.entryRecorded.emit(result)

    def _selectedMomentIsAuto(self) -> bool:
        """
        控件当前值是否仍是自动态哨兵。

        Returns:
            仍为自动态时返回 True。
        """
        if self._auto_moment is None:
            return False
        return self._timeEdit.dateTime().toPyDateTime() == self._auto_moment

    def _syncTimeLimit(self) -> None:
        """把可选时刻上限对齐到当前时间，避免选到未来。"""
        self._timeEdit.setMaximumDateTime(QDateTime(time_source.now()))

    def _syncUndoState(self) -> None:
        """按是否存在可撤销记录，启用/禁用撤销按钮。"""
        self._undo_state_synced = True
        try:
            target = self._entry_service.getUndoableEntry(self._resource_type)
        except DatabaseError:
            target = None

        if target is None:
            self._undoBtn.setEnabled(False)
            self._undoBtn.setToolTip("暂无可撤销的常规录入")
            return

        direction_name = RESOURCE_DIRECTION_NAMES.get(target.direction, target.direction)
        self._undoBtn.setEnabled(True)
        self._undoBtn.setToolTip(
            f"撤销最近一笔：{target.category}（{direction_name}）{target.amount}"
            f"（{target.record_time}）"
        )

    def showEvent(self, event) -> None:
        """面板显示时同步自动态时刻、上限与撤销状态。"""
        super().showEvent(event)
        self.onActivated()
