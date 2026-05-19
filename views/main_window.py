"""
主窗口模块。

定义应用程序的主窗口界面。
"""

from PyQt5.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QStatusBar, QMenuBar, QMenu,
    QAction, QMessageBox, QTabWidget
)
from PyQt5.QtCore import Qt

from services.data_service import DataService
from services.calc_service import CalcService
from services.codex_unlock_service import CodexUnlockService, UnlockResult
from services.awaken_service import AwakenService, AwakenResult
from services.statistics_service import StatisticsService
from views.widgets.statistics_panel import StatisticsPanel
from views.widgets.ship_management_panel import ShipManagementPanel
from utils.constants import WINDOW_DEFAULT_WIDTH, WINDOW_DEFAULT_HEIGHT, APP_NAME


class MainWindow(QMainWindow):
    """
    应用程序主窗口类。

    继承 QMainWindow，提供主界面布局和交互功能。
    """

    def __init__(
        self,
        data_service: DataService = None,
        calc_service: CalcService = None,
        unlock_service: CodexUnlockService = None,
        awaken_service: AwakenService = None,
        statistics_service: StatisticsService = None
    ):
        """
        初始化主窗口。

        Args:
            data_service: 数据服务实例。
            calc_service: 计算服务实例。
            unlock_service: 解锁服务实例。
            awaken_service: 觉醒服务实例。
            statistics_service: 统计服务实例。
        """
        super().__init__()
        self._data_service = data_service or DataService()
        self._calc_service = calc_service or CalcService()
        self._unlock_service = unlock_service or CodexUnlockService()
        self._awaken_service = awaken_service or AwakenService()
        self._statistics_service = statistics_service or StatisticsService()

        self._initUi()
        self._initMenuBar()
        self._initStatusBar()
        self._connectSignals()

    def _initUi(self) -> None:
        """初始化用户界面。"""
        self.setWindowTitle(APP_NAME)
        self.setMinimumSize(800, 600)
        self.resize(WINDOW_DEFAULT_WIDTH, WINDOW_DEFAULT_HEIGHT)

        central_widget = QWidget()
        self.setCentralWidget(central_widget)

        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(20, 20, 20, 20)
        main_layout.setSpacing(15)

        header_layout = QHBoxLayout()
        self._titleLabel = QLabel("碧蓝航线数据管理工具")
        self._titleLabel.setStyleSheet("font-size: 26px; font-weight: bold;")
        header_layout.addWidget(self._titleLabel)
        header_layout.addStretch()
        main_layout.addLayout(header_layout)

        self._tabWidget = QTabWidget()
        self._tabWidget.setDocumentMode(True)

        self._statisticsPanel = StatisticsPanel(self._statistics_service)
        self._tabWidget.addTab(self._statisticsPanel, "数据看板")

        self._shipManagementPanel = ShipManagementPanel(
            self._unlock_service,
            self._awaken_service
        )
        self._tabWidget.addTab(self._shipManagementPanel, "舰娘管理")

        main_layout.addWidget(self._tabWidget)

    def _initMenuBar(self) -> None:
        """初始化菜单栏。"""
        menubar = self.menuBar()

        file_menu = menubar.addMenu("文件")

        refresh_action = QAction("刷新", self)
        refresh_action.setShortcut("Ctrl+R")
        refresh_action.triggered.connect(self._onRefreshClicked)
        file_menu.addAction(refresh_action)

        file_menu.addSeparator()

        exit_action = QAction("退出", self)
        exit_action.setShortcut("Ctrl+Q")
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)

        help_menu = menubar.addMenu("帮助")

        about_action = QAction("关于", self)
        about_action.triggered.connect(self._showAbout)
        help_menu.addAction(about_action)

    def _initStatusBar(self) -> None:
        """初始化状态栏。"""
        self._statusBar = QStatusBar()
        self.setStatusBar(self._statusBar)
        self._statusBar.showMessage("就绪")

    def _connectSignals(self) -> None:
        """连接信号与槽。"""
        self._shipManagementPanel.dataRefreshed.connect(self._onShipManagementDataRefreshed)
        self._statisticsPanel.dataRefreshed.connect(self._onStatisticsDataRefreshed)
        self._shipManagementPanel.unlockResult.connect(self._onUnlockResult)
        self._shipManagementPanel.awakenResult.connect(self._onAwakenResult)

    def _onRefreshClicked(self) -> None:
        """刷新按钮点击事件处理。"""
        try:
            self._statusBar.showMessage("正在刷新数据...")
            self._statisticsPanel.refreshData()
            self._shipManagementPanel.refreshData()
            self._statusBar.showMessage("数据刷新完成")
        except Exception as e:
            self._statusBar.showMessage("刷新失败")
            QMessageBox.warning(self, "错误", f"数据刷新失败: {e}")

    def _onShipManagementDataRefreshed(self) -> None:
        """舰娘管理数据刷新完成事件处理。"""
        self._statisticsPanel.refreshData()

    def _onUnlockResult(self, result: UnlockResult) -> None:
        """
        解锁结果事件处理。

        Args:
            result: 解锁结果对象。
        """
        self._statusBar.showMessage(result.toStatusBarMessage())

    def _onAwakenResult(self, result: AwakenResult) -> None:
        """
        觉醒结果事件处理。

        Args:
            result: 觉醒结果对象。
        """
        self._statusBar.showMessage(result.toStatusBarMessage())

    def _onStatisticsDataRefreshed(self) -> None:
        """统计数据刷新完成事件处理。"""
        self._statusBar.showMessage("统计数据已更新")

    def refreshData(self) -> None:
        """刷新界面数据。"""
        self._statisticsPanel.refreshData()
        self._shipManagementPanel.refreshData()

    def _showAbout(self) -> None:
        """显示关于对话框。"""
        QMessageBox.about(
            self,
            "关于 碧蓝航线数据管理工具",
            "碧蓝航线数据管理工具 v0.0.1\n\n"
            "一款用于管理碧蓝航线游戏数据的桌面应用。\n\n"
            "技术栈: Python + PyQt5 + SQLite"
        )
