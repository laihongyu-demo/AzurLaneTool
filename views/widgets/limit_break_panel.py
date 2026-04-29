"""
界限突破面板模块。

定义界限突破功能的界面组件。
"""

from typing import Optional, List

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QMessageBox, QGroupBox, QFormLayout
)
from PyQt5.QtCore import pyqtSignal

from models.codex_model import CodexGroupModel
from services.limit_break_service import LimitBreakService, LimitBreakResult
from views.widgets.searchable_combo_box import SearchableComboBox
from utils.exceptions import DatabaseError, ValidationError
from utils.logger import log


class LimitBreakPanel(QWidget):
    """
    界限突破面板控件。

    提供界限突破功能的界面交互。
    """

    dataRefreshed = pyqtSignal()
    limitBreakResult = pyqtSignal(object)

    def __init__(self, service: LimitBreakService, parent: QWidget = None):
        """
        初始化界限突破面板。

        Args:
            service: 界限突破服务实例。
            parent: 父控件。
        """
        super().__init__(parent)
        self._service = service
        self._limit_breakable_ships: List[CodexGroupModel] = []
        self._initUi()
        self._connectSignals()
        self.refreshData()

    def _initUi(self) -> None:
        """初始化用户界面。"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(15, 15, 15, 15)
        layout.setSpacing(15)

        group = QGroupBox("界限突破")
        group_layout = QVBoxLayout(group)

        select_layout = QHBoxLayout()
        select_label = QLabel("选择舰娘:")
        self._shipComboBox = SearchableComboBox()
        self._shipComboBox.setMinimumWidth(250)
        self._shipComboBox.setPlaceholderText("请选择或输入舰娘名称...")
        select_layout.addWidget(select_label)
        select_layout.addWidget(self._shipComboBox)
        select_layout.addStretch()
        group_layout.addLayout(select_layout)

        info_layout = QFormLayout()
        self._shipIdLabel = QLabel("-")
        self._shipTypeLabel = QLabel("-")
        self._shipRarityLabel = QLabel("-")
        self._shipCampLabel = QLabel("-")
        self._shipStarLabel = QLabel("-")
        self._maxStarLabel = QLabel("-")

        info_layout.addRow("图鉴ID:", self._shipIdLabel)
        info_layout.addRow("舰船类型:", self._shipTypeLabel)
        info_layout.addRow("稀有度:", self._shipRarityLabel)
        info_layout.addRow("阵营:", self._shipCampLabel)
        info_layout.addRow("当前星级:", self._shipStarLabel)
        info_layout.addRow("满星:", self._maxStarLabel)

        group_layout.addLayout(info_layout)

        button_layout = QHBoxLayout()
        button_layout.addStretch()
        self._limitBreakBtn = QPushButton("界限突破")
        self._limitBreakBtn.setMinimumWidth(100)
        self._limitBreakBtn.setMinimumHeight(35)
        self._limitBreakBtn.setEnabled(False)
        button_layout.addWidget(self._limitBreakBtn)
        self._limitBreakMaxBtn = QPushButton("界限突破·MAX")
        self._limitBreakMaxBtn.setMinimumWidth(120)
        self._limitBreakMaxBtn.setMinimumHeight(35)
        self._limitBreakMaxBtn.setEnabled(False)
        button_layout.addWidget(self._limitBreakMaxBtn)
        self._refreshBtn = QPushButton("刷新")
        self._refreshBtn.setMinimumWidth(100)
        self._refreshBtn.setMinimumHeight(35)
        button_layout.addWidget(self._refreshBtn)
        group_layout.addLayout(button_layout)

        layout.addWidget(group)
        layout.addStretch()

    def _connectSignals(self) -> None:
        """连接信号与槽。"""
        self._shipComboBox.currentIndexChanged.connect(self._onShipSelected)
        self._limitBreakBtn.clicked.connect(self._onLimitBreakClicked)
        self._limitBreakMaxBtn.clicked.connect(self._onLimitBreakMaxClicked)
        self._refreshBtn.clicked.connect(self._onRefreshClicked)

    def _onShipSelected(self, index: int) -> None:
        """舰娘选择事件处理。"""
        if index < 0 or index >= len(self._limit_breakable_ships):
            self._clearShipInfo()
            self._limitBreakBtn.setEnabled(False)
            self._limitBreakMaxBtn.setEnabled(False)
            return

        ship = self._limit_breakable_ships[index]
        self._shipIdLabel.setText(str(ship.codex_id))
        self._shipTypeLabel.setText(ship.ship_typ or "-")
        self._shipRarityLabel.setText(ship.ship_rarity or "-")
        self._shipCampLabel.setText(ship.ship_camp or "-")
        self._shipStarLabel.setText(str(ship.ship_star))
        
        max_star = self._service.getMaxStar(ship.ship_rarity)
        self._maxStarLabel.setText(str(max_star))
        
        self._limitBreakBtn.setEnabled(True)
        self._limitBreakMaxBtn.setEnabled(True)

    def _clearShipInfo(self) -> None:
        """清空舰娘信息显示。"""
        self._shipIdLabel.setText("-")
        self._shipTypeLabel.setText("-")
        self._shipRarityLabel.setText("-")
        self._shipCampLabel.setText("-")
        self._shipStarLabel.setText("-")
        self._maxStarLabel.setText("-")

    def _onLimitBreakClicked(self) -> None:
        """界限突破按钮点击事件处理。"""
        index = self._shipComboBox.currentIndex()
        if index < 0 or index >= len(self._limit_breakable_ships):
            return

        ship = self._limit_breakable_ships[index]
        max_star = self._service.getMaxStar(ship.ship_rarity)
        
        reply = QMessageBox.question(
            self,
            "确认界限突破",
            f"确定要将舰娘 '{ship.ship_name}' 从 {ship.ship_star}星 突破到 {ship.ship_star + 1}星 吗？\n\n"
            f"满星为 {max_star}星",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )

        if reply != QMessageBox.Yes:
            return

        try:
            result = self._service.limitBreak(ship.codex_id)
            self.limitBreakResult.emit(result)
            if result.success:
                self.refreshData()
                self.dataRefreshed.emit()
        except ValidationError as e:
            error_result = LimitBreakResult(success=False, message=str(e))
            self.limitBreakResult.emit(error_result)
        except DatabaseError as e:
            error_result = LimitBreakResult(success=False, message=str(e))
            self.limitBreakResult.emit(error_result)
        except Exception as e:
            log.error(f"界限突破操作发生异常: {e}")
            error_result = LimitBreakResult(success=False, message=f"界限突破操作发生异常: {e}")
            self.limitBreakResult.emit(error_result)

    def _onLimitBreakMaxClicked(self) -> None:
        """界限突破·MAX按钮点击事件处理。"""
        index = self._shipComboBox.currentIndex()
        if index < 0 or index >= len(self._limit_breakable_ships):
            return

        ship = self._limit_breakable_ships[index]
        max_star = self._service.getMaxStar(ship.ship_rarity)
        
        reply = QMessageBox.question(
            self,
            "确认界限突破·MAX",
            f"确定要将舰娘 '{ship.ship_name}' 直接突破到满星 {max_star}星 吗？\n\n"
            f"当前星级: {ship.ship_star}星",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )

        if reply != QMessageBox.Yes:
            return

        try:
            result = self._service.limitBreakMax(ship.codex_id)
            self.limitBreakResult.emit(result)
            if result.success:
                self.refreshData()
                self.dataRefreshed.emit()
        except ValidationError as e:
            error_result = LimitBreakResult(success=False, message=str(e))
            self.limitBreakResult.emit(error_result)
        except DatabaseError as e:
            error_result = LimitBreakResult(success=False, message=str(e))
            self.limitBreakResult.emit(error_result)
        except Exception as e:
            log.error(f"界限突破·MAX操作发生异常: {e}")
            error_result = LimitBreakResult(success=False, message=f"界限突破·MAX操作发生异常: {e}")
            self.limitBreakResult.emit(error_result)

    def _onRefreshClicked(self) -> None:
        """刷新按钮点击事件处理。"""
        self.refreshData()

    def refreshData(self) -> None:
        """刷新界面数据。"""
        self._shipComboBox.clear()
        self._limit_breakable_ships = []
        self._clearShipInfo()
        self._limitBreakBtn.setEnabled(False)
        self._limitBreakMaxBtn.setEnabled(False)

        try:
            self._limit_breakable_ships = self._service.getLimitBreakableShips()

            for ship in self._limit_breakable_ships:
                display_name = str(ship.ship_name) if ship.ship_name is not None else ""
                self._shipComboBox.addItem(display_name, ship.codex_id)

            log.debug(f"界限突破数据刷新完成，共 {len(self._limit_breakable_ships)} 艘舰娘")
            self.dataRefreshed.emit()

        except DatabaseError as e:
            QMessageBox.critical(self, "数据库错误", f"加载数据失败: {e}")
        except Exception as e:
            log.error(f"刷新界限突破数据失败: {e}")
            QMessageBox.critical(self, "错误", f"刷新数据失败: {e}")
