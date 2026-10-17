"""
舰娘誓约面板模块。

定义舰娘誓约功能的界面组件。
"""

from typing import Optional, List

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QMessageBox, QGroupBox, QFormLayout
)
from PyQt5.QtCore import Qt, pyqtSignal

from models.codex_model import CodexGroupModel
from services.codex_oath_service import CodexOathService, OathResult
from views.widgets.searchable_combo_box import SearchableComboBox
from utils.exceptions import DatabaseError, ValidationError


class CodexOathPanel(QWidget):
    """
    舰娘誓约面板控件。

    提供舰娘誓约功能的界面交互。
    """

    dataRefreshed = pyqtSignal()
    oathResult = pyqtSignal(object)

    def __init__(self, oath_service: Optional[CodexOathService] = None, parent: QWidget = None):
        """
        初始化誓约面板。

        Args:
            oath_service: 誓约服务实例。
            parent: 父控件。
        """
        super().__init__(parent)
        self._oath_service = oath_service or CodexOathService()
        self._oathable_ships: List[CodexGroupModel] = []
        self._initUi()
        self._connectSignals()
        self.refreshData()

    def _initUi(self) -> None:
        """初始化用户界面。"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(15, 15, 15, 15)
        layout.setSpacing(15)

        oath_group = QGroupBox("舰娘誓约")
        oath_layout = QVBoxLayout(oath_group)

        select_layout = QHBoxLayout()
        select_label = QLabel("选择舰娘:")
        self._shipComboBox = SearchableComboBox()
        self._shipComboBox.setMinimumWidth(250)
        self._shipComboBox.setPlaceholderText("请选择或输入舰娘名称...")
        select_layout.addWidget(select_label)
        select_layout.addWidget(self._shipComboBox)
        select_layout.addStretch()
        oath_layout.addLayout(select_layout)

        info_layout = QFormLayout()
        self._shipIdLabel = QLabel("-")
        self._shipTypeLabel = QLabel("-")
        self._shipRarityLabel = QLabel("-")
        self._shipCampLabel = QLabel("-")

        info_layout.addRow("图鉴ID:", self._shipIdLabel)
        info_layout.addRow("舰船类型:", self._shipTypeLabel)
        info_layout.addRow("稀有度:", self._shipRarityLabel)
        info_layout.addRow("阵营:", self._shipCampLabel)

        oath_layout.addLayout(info_layout)

        button_layout = QHBoxLayout()
        button_layout.addStretch()
        self._oathBtn = QPushButton("誓约")
        self._oathBtn.setMinimumWidth(100)
        self._oathBtn.setMinimumHeight(35)
        self._oathBtn.setEnabled(False)
        button_layout.addWidget(self._oathBtn)
        self._refreshBtn = QPushButton("刷新")
        self._refreshBtn.setMinimumWidth(100)
        self._refreshBtn.setMinimumHeight(35)
        button_layout.addWidget(self._refreshBtn)
        oath_layout.addLayout(button_layout)

        layout.addWidget(oath_group)
        layout.addStretch()

    def _connectSignals(self) -> None:
        """连接信号与槽。"""
        self._shipComboBox.currentIndexChanged.connect(self._onShipSelected)
        self._oathBtn.clicked.connect(self._onOathClicked)
        self._refreshBtn.clicked.connect(self._onRefreshClicked)

    def _onShipSelected(self, index: int) -> None:
        """舰娘选择事件处理。"""
        if index < 0 or index >= len(self._oathable_ships):
            self._clearShipInfo()
            self._oathBtn.setEnabled(False)
            return

        ship = self._oathable_ships[index]
        self._shipIdLabel.setText(str(ship.codex_id))
        self._shipTypeLabel.setText(ship.ship_typ or "-")
        self._shipRarityLabel.setText(ship.ship_rarity or "-")
        self._shipCampLabel.setText(ship.ship_camp or "-")
        self._oathBtn.setEnabled(True)

    def _clearShipInfo(self) -> None:
        """清空舰娘信息显示。"""
        self._shipIdLabel.setText("-")
        self._shipTypeLabel.setText("-")
        self._shipRarityLabel.setText("-")
        self._shipCampLabel.setText("-")

    def _onOathClicked(self) -> None:
        """誓约按钮点击事件处理。"""
        index = self._shipComboBox.currentIndex()
        if index < 0 or index >= len(self._oathable_ships):
            return

        ship = self._oathable_ships[index]
        reply = QMessageBox.question(
            self,
            "确认誓约",
            f"确定要与舰娘 '{ship.ship_name}' 缔结誓约吗？",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )

        if reply != QMessageBox.Yes:
            return

        try:
            result = self._oath_service.oathShip(ship.codex_id)
            self.oathResult.emit(result)
            if result.success:
                self.refreshData()
                self.dataRefreshed.emit()
        except ValidationError as e:
            error_result = OathResult(success=False, message=str(e))
            self.oathResult.emit(error_result)
        except DatabaseError as e:
            error_result = OathResult(success=False, message=str(e))
            self.oathResult.emit(error_result)
        except Exception as e:
            error_result = OathResult(success=False, message=f"誓约操作发生异常: {e}")
            self.oathResult.emit(error_result)

    def _onRefreshClicked(self) -> None:
        """刷新按钮点击事件处理。"""
        self.refreshData()

    def refreshData(self) -> None:
        """刷新界面数据。"""
        self._shipComboBox.clear()
        self._oathable_ships = []
        self._clearShipInfo()
        self._oathBtn.setEnabled(False)

        try:
            self._oathable_ships = self._oath_service.getOathableShips()

            for ship in self._oathable_ships:
                display_name = str(ship.ship_name) if ship.ship_name is not None else ""
                self._shipComboBox.addItem(display_name, ship.codex_id)

        except DatabaseError as e:
            QMessageBox.critical(self, "数据库错误", f"加载数据失败: {e}")
        except Exception as e:
            QMessageBox.critical(self, "错误", f"刷新数据失败: {e}")