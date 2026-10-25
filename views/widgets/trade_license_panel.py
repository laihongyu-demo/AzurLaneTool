"""
贸易许可证面板模块。

显示当前剩余天数 / 到期日，提供购买、续约、期初登记，以及最近一条记录的
修正 / 删除。每日 1 魔方不在这里自动记账，只给出常规录入提示。
"""

from datetime import date, timedelta
from typing import Optional

from PyQt5.QtCore import QDate, pyqtSignal
from PyQt5.QtWidgets import (
    QDateEdit, QDialog, QDialogButtonBox, QGroupBox, QHBoxLayout, QLabel,
    QMessageBox, QPushButton, QVBoxLayout, QWidget,
)

from models.trade_license_model import TradeLicenseStatus
from services.trade_license_service import TradeLicenseService
from utils import time_source
from utils.constants import (
    QT_DATE_DISPLAY_FORMAT, TRADE_LICENSE_DAYS, TRADE_LICENSE_RENEWAL_WINDOW_DAYS,
    TRADE_LICENSE_REWARD,
)
from utils.exceptions import DatabaseError, ValidationError


class _DateDialog(QDialog):
    """只选日期的简单对话框。"""

    def __init__(self, title: str, value: date, parent: QWidget = None):
        """
        初始化日期对话框。

        Args:
            title: 窗口标题。
            value: 初始日期。
            parent: 父控件。
        """
        super().__init__(parent)
        self.setWindowTitle(title)
        layout = QVBoxLayout(self)

        self._edit = QDateEdit(self)
        self._edit.setCalendarPopup(True)
        self._edit.setDisplayFormat(QT_DATE_DISPLAY_FORMAT)
        self._edit.setDate(QDate(value.year, value.month, value.day))
        layout.addWidget(self._edit)

        buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel, self
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def selectedDate(self) -> date:
        """
        读取用户选择的日期。

        Returns:
            Python 日期。
        """
        return self._edit.date().toPyDate()


class TradeLicensePanel(QGroupBox):
    """贸易许可证面板。"""

    dataRefreshed = pyqtSignal()
    resultReady = pyqtSignal(object)

    def __init__(
        self,
        service: Optional[TradeLicenseService] = None,
        parent: QWidget = None,
    ):
        """
        初始化贸易许可证面板。

        Args:
            service: 贸易许可证服务实例。
            parent: 父控件。
        """
        super().__init__("贸易许可证", parent)
        self._service = service or TradeLicenseService()
        self._status: Optional[TradeLicenseStatus] = None
        self._last_day = time_source.today()
        self._initUi()
        self.refreshState()

    def _initUi(self) -> None:
        """初始化用户界面。"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 12, 8, 10)
        layout.setSpacing(6)

        status_row = QHBoxLayout()
        self._statusLabel = QLabel("", self)
        self._statusLabel.setStyleSheet("font-weight: bold;")
        status_row.addWidget(self._statusLabel)
        status_row.addStretch()
        layout.addLayout(status_row)

        self._detailLabel = QLabel("", self)
        self._detailLabel.setStyleSheet("color: #666; font-size: 12px;")
        self._detailLabel.setWordWrap(True)
        layout.addWidget(self._detailLabel)

        button_row = QHBoxLayout()
        self._primaryBtn = QPushButton("购买月卡（+500 红尖尖）", self)
        self._primaryBtn.setMaximumHeight(28)
        self._registerBtn = QPushButton("登记已有月卡", self)
        self._registerBtn.setMaximumHeight(28)
        self._editBtn = QPushButton("修正到期日", self)
        self._editBtn.setMaximumHeight(28)
        self._deleteBtn = QPushButton("删除最近记录", self)
        self._deleteBtn.setMaximumHeight(28)
        for button in (self._primaryBtn, self._registerBtn, self._editBtn, self._deleteBtn):
            button_row.addWidget(button)
        button_row.addStretch()
        layout.addLayout(button_row)

        hint = QLabel(
            "每日 1 魔方不在此自动记账；请到「魔方任务看板 → 常规录入」手动补记"
            "（类型：贸易许可证）。",
            self,
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #888; font-size: 12px;")
        layout.addWidget(hint)

        self._primaryBtn.clicked.connect(self._onPrimaryClicked)
        self._registerBtn.clicked.connect(self._onRegisterClicked)
        self._editBtn.clicked.connect(self._onEditClicked)
        self._deleteBtn.clicked.connect(self._onDeleteClicked)

    # --------------------------------------------------------------- 状态

    def refreshState(self) -> None:
        """从数据库重新读取状态并刷新界面。"""
        self._last_day = time_source.today()
        try:
            self._status = self._service.getStatus(self._last_day)
        except DatabaseError as e:
            self._status = None
            self._statusLabel.setText("贸易许可证数据不可用")
            self._detailLabel.setText(str(e))
            self._setButtonsEnabled(False, False, False, False)
            return
        self._applyStatus(self._status)

    def syncTimeContext(self) -> None:
        """跨天时按缓存的到期日重算剩余天数，不查库。"""
        today = time_source.today()
        if self._status is None:
            self.refreshState()
            return
        if today == self._last_day:
            return
        self._last_day = today
        self._status = self._status.recalculate(today)
        self._applyStatus(self._status)

    def onActivated(self) -> None:
        """页签激活：有缓存时只重算天数，无缓存时读库。"""
        if self._status is None:
            self.refreshState()
        else:
            self.syncTimeContext()

    def _applyStatus(self, status: TradeLicenseStatus) -> None:
        """
        按状态刷新文案与按钮。

        Args:
            status: 当前状态。
        """
        self._status = status
        if not status.has_purchase:
            self._statusLabel.setText("未购买（剩余 0 天）")
            self._detailLabel.setText("可购买月卡，或登记当前已在使用的月卡到期日。")
            self._primaryBtn.setText(f"购买月卡（+{TRADE_LICENSE_REWARD} 红尖尖）")
            self._primaryBtn.setEnabled(True)
            self._primaryBtn.setToolTip("购买后立即记入 500 红尖尖，有效期 30 天")
            self._registerBtn.setVisible(True)
            self._registerBtn.setEnabled(True)
            self._editBtn.setVisible(False)
            self._editBtn.setEnabled(False)
            self._deleteBtn.setVisible(False)
            self._deleteBtn.setEnabled(False)
            return

        if status.remaining_days > 0:
            self._statusLabel.setText(
                f"剩余 {status.remaining_days} 天（至 {status.expire_date}）"
            )
        else:
            self._statusLabel.setText(f"已过期（至 {status.expire_date}）")
        self._detailLabel.setText(
            f"最近记录：{status.last_purchase_time or '—'}；"
            f"剩余 {TRADE_LICENSE_RENEWAL_WINDOW_DAYS} 天及以下可续约。"
        )
        self._primaryBtn.setText(f"续约（+{TRADE_LICENSE_REWARD} 红尖尖）")
        self._primaryBtn.setEnabled(status.can_renew)
        if status.can_renew:
            self._primaryBtn.setToolTip("续约后立即记入 500 红尖尖，并顺延 30 天")
        else:
            self._primaryBtn.setToolTip(
                f"剩余 {status.remaining_days} 天，"
                f"剩余 {TRADE_LICENSE_RENEWAL_WINDOW_DAYS} 天及以下才可续约"
            )
        self._registerBtn.setVisible(False)
        self._registerBtn.setEnabled(False)
        self._editBtn.setVisible(True)
        self._editBtn.setEnabled(True)
        self._deleteBtn.setVisible(True)
        self._deleteBtn.setEnabled(True)

    def _setButtonsEnabled(
        self, primary: bool, register: bool, edit: bool, delete: bool
    ) -> None:
        """统一设置按钮可用状态。"""
        self._primaryBtn.setEnabled(primary)
        self._registerBtn.setEnabled(register)
        self._editBtn.setEnabled(edit)
        self._deleteBtn.setEnabled(delete)

    # --------------------------------------------------------------- 事件

    def _onPrimaryClicked(self) -> None:
        """购买 / 续约按钮。"""
        today = time_source.today()
        message = "购买贸易许可证？"
        if self._status is not None and self._status.has_purchase:
            current_end = date.fromisoformat(self._status.expire_date)
            start = current_end + timedelta(days=1) if current_end >= today else today
            end = start + timedelta(days=TRADE_LICENSE_DAYS - 1)
            message = (
                f"续约贸易许可证？\n"
                f"将立即记入 {TRADE_LICENSE_REWARD} 红尖尖，"
                f"到期日从 {self._status.expire_date} 延长至 {end:%Y-%m-%d}。"
            )
        else:
            end = today + timedelta(days=TRADE_LICENSE_DAYS - 1)
            message = (
                f"购买贸易许可证？\n"
                f"将立即记入 {TRADE_LICENSE_REWARD} 红尖尖，"
                f"有效期至 {end:%Y-%m-%d}。"
            )
        reply = QMessageBox.question(
            self, "确认", message, QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        )
        if reply != QMessageBox.Yes:
            return
        self._runWrite(self._service.renew)

    def _onRegisterClicked(self) -> None:
        """登记当前已在使用的月卡到期日。"""
        default = time_source.today() + timedelta(days=TRADE_LICENSE_DAYS - 1)
        dialog = _DateDialog("登记已有月卡", default, self)
        if dialog.exec_() != QDialog.Accepted:
            return
        expire = dialog.selectedDate()
        self._runWrite(lambda: self._service.registerInitialExpiry(expire))

    def _onEditClicked(self) -> None:
        """修正最近一条记录的到期日。"""
        if self._status is None or not self._status.has_purchase:
            return
        current = date.fromisoformat(self._status.expire_date)
        dialog = _DateDialog("修正到期日", current, self)
        if dialog.exec_() != QDialog.Accepted:
            return
        new_end = dialog.selectedDate()
        self._runWrite(lambda: self._service.updateLatestEndDate(new_end))

    def _onDeleteClicked(self) -> None:
        """删除最近一条记录。"""
        if self._status is None or not self._status.has_purchase:
            return
        message = (
            f"删除最近一条贸易许可证记录？\n"
            f"到期日：{self._status.expire_date}\n"
            "如该记录关联 500 红尖尖，将一并回滚。"
        )
        reply = QMessageBox.question(
            self, "确认删除", message, QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        )
        if reply != QMessageBox.Yes:
            return
        self._runWrite(self._service.deleteLatest)

    def _runWrite(self, action) -> None:
        """
        执行写操作并刷新界面。

        Args:
            action: 返回 TradeLicenseResult 的无参函数。
        """
        try:
            result = action()
        except ValidationError as e:
            QMessageBox.warning(self, "无法操作", str(e))
            return
        except DatabaseError as e:
            QMessageBox.critical(self, "数据库错误", f"操作失败: {e}")
            return

        if result.status is not None:
            self._applyStatus(result.status)
        else:
            self.refreshState()
        # 先通知数据刷新，再回报结果，避免全局刷新把状态栏文案覆盖掉
        self.dataRefreshed.emit()
        self.resultReady.emit(result)
