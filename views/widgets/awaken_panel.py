"""
认知觉醒面板模块。

定义认知觉醒功能的界面组件。
"""

from typing import Optional, List

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QComboBox, QMessageBox, QGroupBox, QFormLayout
)
from PyQt5.QtCore import Qt, pyqtSignal

from models.codex_model import CodexGroupModel
from services.awaken_service import AwakenService, AwakenResult, AWAKEN_LEVELS
from views.widgets.searchable_combo_box import SearchableComboBox
from utils.exceptions import DatabaseError, ValidationError


class AwakenPanel(QWidget):
    """
    认知觉醒面板控件。

    提供认知觉醒功能的界面交互。
    """

    dataRefreshed = pyqtSignal()
    awakenResult = pyqtSignal(object)

    def __init__(self, awaken_service: Optional[AwakenService] = None, parent: QWidget = None):
        """
        初始化觉醒面板。

        Args:
            awaken_service: 觉醒服务实例。
            parent: 父控件。
        """
        super().__init__(parent)
        self._awaken_service = awaken_service or AwakenService()
        self._awakenable_ships: List[CodexGroupModel] = []
        self._available_levels: List[str] = []
        self._initUi()
        self._connectSignals()
        self.refreshData()

    def _initUi(self) -> None:
        """初始化用户界面。"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(15, 15, 15, 15)
        layout.setSpacing(15)

        awaken_group = QGroupBox("认知觉醒")
        awaken_layout = QVBoxLayout(awaken_group)

        select_layout = QHBoxLayout()
        select_label = QLabel("选择舰娘:")
        self._shipComboBox = SearchableComboBox()
        self._shipComboBox.setMinimumWidth(250)
        self._shipComboBox.setPlaceholderText("请选择或输入舰娘名称...")
        select_layout.addWidget(select_label)
        select_layout.addWidget(self._shipComboBox)
        select_layout.addStretch()
        awaken_layout.addLayout(select_layout)

        level_layout = QHBoxLayout()
        level_label = QLabel("觉醒阶段:")
        self._levelComboBox = QComboBox()
        self._levelComboBox.setMinimumWidth(250)
        self._levelComboBox.setPlaceholderText("请选择觉醒阶段")
        self._levelComboBox.setEnabled(False)
        level_layout.addWidget(level_label)
        level_layout.addWidget(self._levelComboBox)
        level_layout.addStretch()
        awaken_layout.addLayout(level_layout)

        info_layout = QFormLayout()
        self._shipIdLabel = QLabel("-")
        self._shipCampLabel = QLabel("-")
        self._currentLevelLabel = QLabel("-")

        info_layout.addRow("图鉴ID:", self._shipIdLabel)
        info_layout.addRow("阵营:", self._shipCampLabel)
        info_layout.addRow("当前觉醒等级:", self._currentLevelLabel)

        awaken_layout.addLayout(info_layout)

        button_layout = QHBoxLayout()
        button_layout.addStretch()
        self._awakenBtn = QPushButton("觉醒")
        self._awakenBtn.setMinimumWidth(100)
        self._awakenBtn.setMinimumHeight(35)
        self._awakenBtn.setEnabled(False)
        button_layout.addWidget(self._awakenBtn)
        self._refreshBtn = QPushButton("刷新")
        self._refreshBtn.setMinimumWidth(100)
        self._refreshBtn.setMinimumHeight(35)
        button_layout.addWidget(self._refreshBtn)
        awaken_layout.addLayout(button_layout)

        layout.addWidget(awaken_group)
        layout.addStretch()

    def _connectSignals(self) -> None:
        """连接信号与槽。"""
        self._shipComboBox.currentIndexChanged.connect(self._onShipSelected)
        self._levelComboBox.currentIndexChanged.connect(self._onLevelSelected)
        self._awakenBtn.clicked.connect(self._onAwakenClicked)
        self._refreshBtn.clicked.connect(self._onRefreshClicked)

    def _onShipSelected(self, index: int) -> None:
        """舰娘选择事件处理。"""
        if index < 0 or index >= len(self._awakenable_ships):
            self._clearShipInfo()
            self._levelComboBox.clear()
            self._levelComboBox.setEnabled(False)
            self._awakenBtn.setEnabled(False)
            return

        ship = self._awakenable_ships[index]
        self._shipIdLabel.setText(str(ship.codex_id))
        self._shipCampLabel.setText(ship.ship_camp or "-")
        self._currentLevelLabel.setText(ship.ship_level or "-")

        self._available_levels = self._awaken_service.getAvailableLevels(ship.ship_level or "未觉醒")

        self._levelComboBox.clear()
        self._levelComboBox.setEnabled(True)
        for level in self._available_levels:
            self._levelComboBox.addItem(level)

        self._awakenBtn.setEnabled(False)

    def _onLevelSelected(self, index: int) -> None:
        """觉醒阶段选择事件处理。"""
        if index < 0 or index >= len(self._available_levels):
            self._awakenBtn.setEnabled(False)
            return

        self._awakenBtn.setEnabled(True)

    def _clearShipInfo(self) -> None:
        """清空舰娘信息显示。"""
        self._shipIdLabel.setText("-")
        self._shipCampLabel.setText("-")
        self._currentLevelLabel.setText("-")

    def _onAwakenClicked(self) -> None:
        """觉醒按钮点击事件处理。"""
        ship_index = self._shipComboBox.currentIndex()
        level_index = self._levelComboBox.currentIndex()

        if ship_index < 0 or ship_index >= len(self._awakenable_ships):
            return
        if level_index < 0 or level_index >= len(self._available_levels):
            return

        ship = self._awakenable_ships[ship_index]
        new_level = self._available_levels[level_index]

        reply = QMessageBox.question(
            self,
            "确认觉醒",
            f"确定要将舰娘 '{ship.ship_name}' 觉醒到 '{new_level}' 吗？",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )

        if reply != QMessageBox.Yes:
            return

        try:
            result = self._awaken_service.awakenShip(ship.codex_id, new_level)
            self.awakenResult.emit(result)
            if result.success:
                self.refreshData()
                self.dataRefreshed.emit()
        except ValidationError as e:
            error_result = AwakenResult(success=False, message=str(e))
            self.awakenResult.emit(error_result)
        except DatabaseError as e:
            error_result = AwakenResult(success=False, message=str(e))
            self.awakenResult.emit(error_result)
        except Exception as e:
            error_result = AwakenResult(success=False, message=f"觉醒操作发生异常: {e}")
            self.awakenResult.emit(error_result)

    def _onRefreshClicked(self) -> None:
        """刷新按钮点击事件处理。"""
        self.refreshData()

    def refreshData(self) -> None:
        """刷新界面数据。"""
        self._shipComboBox.clear()
        self._levelComboBox.clear()
        self._awakenable_ships = []
        self._available_levels = []
        self._clearShipInfo()
        self._levelComboBox.setEnabled(False)
        self._awakenBtn.setEnabled(False)

        try:
            self._awakenable_ships = self._awaken_service.getAwakenableShips()

            for ship in self._awakenable_ships:
                display_name = str(ship.ship_name) if ship.ship_name is not None else ""
                self._shipComboBox.addItem(display_name, ship.codex_id)

        except DatabaseError as e:
            QMessageBox.critical(self, "数据库错误", f"加载数据失败: {e}")
        except Exception as e:
            QMessageBox.critical(self, "错误", f"刷新数据失败: {e}")
