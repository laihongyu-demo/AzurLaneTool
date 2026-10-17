"""
常规录入面板模块。

放在「魔方任务看板 → 常规录入」分组里，用于补记非固定收支（活动建造、礼包、
军事委托等）。表单只有三项：数量、类型、时刻，类型来自类型字典，方向由类型决定。

时刻默认取当前时间（精确到秒），可选择过去时间做补录，但不能晚于当前时间。
"""

from typing import List, Optional

from PyQt5.QtCore import QDateTime, Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QComboBox, QDateTimeEdit, QGridLayout, QLabel, QMessageBox, QPushButton,
    QSizePolicy, QSpinBox, QWidget,
)

from services.resource_entry_service import (
    MAX_ENTRY_AMOUNT, ResourceCategoryOption, ResourceEntryResult, ResourceEntryService,
)
from utils.constants import (
    QT_RECORD_TIME_DISPLAY_FORMAT,
    RESOURCE_DIRECTION_EXPENSE,
    RESOURCE_DIRECTION_NAMES,
    RESOURCE_TYPE_CUBE,
)
from utils.exceptions import DatabaseError, ValidationError


class RegularEntryPanel(QWidget):
    """
    常规录入表单。

    只负责收集三项输入并调用 `ResourceEntryService`；写入结果通过信号交给外层
    刷新看板卡片与状态栏。
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
            resource_type: 资源类型，默认魔方。
            parent: 父控件。
        """
        super().__init__(parent)
        self._entry_service = entry_service or ResourceEntryService()
        self._resource_type = resource_type

        self._initUi()
        self._connectSignals()
        self.refreshCategories()
        self._syncTimeLimit()

    # ------------------------------------------------------------------ UI

    def _initUi(self) -> None:
        """初始化用户界面。"""
        layout = QGridLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setHorizontalSpacing(8)
        layout.setVerticalSpacing(8)

        self._amountSpin = QSpinBox(self)
        self._amountSpin.setRange(1, MAX_ENTRY_AMOUNT)
        self._amountSpin.setValue(1)
        self._amountSpin.setMinimumWidth(90)
        self._amountSpin.setMaximumHeight(28)
        self._amountSpin.setToolTip("本次记入的魔方数量")

        self._typeCombo = QComboBox(self)
        self._typeCombo.setMinimumWidth(150)
        self._typeCombo.setMaximumHeight(28)
        self._typeCombo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._typeCombo.setToolTip("收支类型；方向由类型决定（支出在前，收入在后）")

        self._timeEdit = QDateTimeEdit(self)
        self._timeEdit.setDisplayFormat(QT_RECORD_TIME_DISPLAY_FORMAT)
        self._timeEdit.setCalendarPopup(True)
        self._timeEdit.setDateTime(QDateTime.currentDateTime())
        self._timeEdit.setMinimumWidth(170)
        self._timeEdit.setMaximumHeight(28)
        self._timeEdit.setToolTip("发生时刻，默认当前时间；可改到过去补录，不能晚于现在")

        self._recordBtn = QPushButton("记录", self)
        self._recordBtn.setMinimumWidth(70)
        self._recordBtn.setMaximumHeight(28)

        layout.addWidget(QLabel("数量", self), 0, 0)
        layout.addWidget(self._amountSpin, 0, 1)
        layout.addWidget(QLabel("类型", self), 0, 2)
        layout.addWidget(self._typeCombo, 0, 3, 1, 3)

        layout.addWidget(QLabel("时间", self), 1, 0)
        layout.addWidget(self._timeEdit, 1, 1, 1, 3)
        layout.addWidget(self._recordBtn, 1, 4, 1, 2, Qt.AlignRight)

        layout.setColumnStretch(1, 1)
        layout.setColumnStretch(3, 1)

    def _connectSignals(self) -> None:
        """连接信号与槽。"""
        self._recordBtn.clicked.connect(self._onRecordClicked)

    # --------------------------------------------------------------- 数据

    def refreshCategories(self) -> None:
        """重新加载可选类型（类型字典变化后调用）。"""
        current = self._typeCombo.currentData()
        try:
            options = self._entry_service.getCategories(self._resource_type)
        except DatabaseError as e:
            options = []
            self._typeCombo.clear()
            self._typeCombo.addItem(f"类型加载失败：{e}", None)
            self._typeCombo.setEnabled(False)
            return

        self._typeCombo.setEnabled(True)
        self._typeCombo.clear()
        for option in options:
            self._typeCombo.addItem(self._formatOption(option), option.name)

        if current is not None:
            index = self._typeCombo.findData(current)
            if index >= 0:
                self._typeCombo.setCurrentIndex(index)

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

    def _selectedCategory(self) -> Optional[str]:
        """
        当前选中的类型名称。

        Returns:
            类型名称；未选择时返回 None。
        """
        return self._typeCombo.currentData()

    def _selectedMoment(self):
        """
        当前选择的时刻。

        Returns:
            Python datetime。
        """
        return self._timeEdit.dateTime().toPyDateTime()

    # --------------------------------------------------------------- 事件

    def _onRecordClicked(self) -> None:
        """记录按钮点击事件处理。"""
        self._syncTimeLimit()
        category = self._selectedCategory()
        if not category:
            QMessageBox.warning(self, "无法记录", "请先选择收支类型")
            return

        try:
            result = self._entry_service.record(
                category=category,
                amount=self._amountSpin.value(),
                moment=self._selectedMoment(),
                resource_type=self._resource_type,
            )
        except ValidationError as e:
            QMessageBox.warning(self, "无法记录", str(e))
            return
        except DatabaseError as e:
            QMessageBox.critical(self, "数据库错误", f"记录失败: {e}")
            return

        self._afterRecord(result)

    def _afterRecord(self, result: ResourceEntryResult) -> None:
        """
        记录成功后的收尾：重置时刻上限、通知外部刷新。

        Args:
            result: 录入结果。
        """
        self._syncTimeLimit()
        # 先刷新数据、再回报结果：避免刷新过程中的状态栏文案覆盖「已记录 …」
        self.dataRefreshed.emit()
        self.entryRecorded.emit(result)

    def _syncTimeLimit(self) -> None:
        """把可选时刻上限对齐到当前时间，避免选到未来。"""
        self._timeEdit.setMaximumDateTime(QDateTime.currentDateTime())

    def showEvent(self, event) -> None:
        """面板显示时刷新时间上限。"""
        super().showEvent(event)
        self._syncTimeLimit()
