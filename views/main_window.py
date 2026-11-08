"""
主窗口模块。

定义应用程序的主窗口界面。
"""

from datetime import datetime, time as datetime_time, timedelta

from PyQt5.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QStatusBar, QAction, QMessageBox, QTabWidget
)
from PyQt5.QtCore import QEvent, QTimer
from PyQt5.QtGui import QIcon

from services.data_service import DataService
from services.calc_service import CalcService
from services.codex_unlock_service import CodexUnlockService, UnlockResult
from services.codex_ship_create_service import CodexShipCreateService, ShipCreateResult
from services.awaken_service import AwakenService, AwakenResult
from services.limit_break_service import LimitBreakService, LimitBreakResult
from services.codex_oath_service import CodexOathService, OathResult
from services.statistics_service import StatisticsService
from services.mental_calculation_service import MentalCalculationService
from services.commander_service import CommanderService, CommanderWriteResult
from services.cube_task_service import CubeTaskService, CubeTaskWriteResult
from services.resource_service import ResourceService
from services.resource_category_service import ResourceCategoryService
from services.event_record_service import EventRecordService
from views.widgets.statistics_panel import StatisticsPanel
from views.widgets.ship_management_panel import ShipManagementPanel
from views.widgets.resource_management_panel import ResourceManagementPanel
from views.widgets.event_record_panel import EventRecordPanel
from views.widgets.settings_panel import SettingsPanel
from utils import time_source
from utils.constants import (
    WINDOW_DEFAULT_WIDTH, WINDOW_DEFAULT_HEIGHT, APP_NAME, APP_ICON_PATH
)


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
        create_service: CodexShipCreateService = None,
        awaken_service: AwakenService = None,
        limit_break_service: LimitBreakService = None,
        oath_service: CodexOathService = None,
        statistics_service: StatisticsService = None,
        mental_calculation_service: MentalCalculationService = None,
        commander_service: CommanderService = None,
        cube_task_service: CubeTaskService = None,
        resource_service: ResourceService = None,
        category_service: ResourceCategoryService = None,
        event_record_service: EventRecordService = None
    ):
        """
        初始化主窗口。

        Args:
            data_service: 数据服务实例。
            calc_service: 计算服务实例。
            unlock_service: 解锁服务实例。
            create_service: 舰娘新增服务实例。
            awaken_service: 觉醒服务实例。
            limit_break_service: 界限突破服务实例。
            oath_service: 誓约服务实例。
            statistics_service: 统计服务实例。
            mental_calculation_service: 心智计算服务实例。
            commander_service: 指挥官服务实例。
            cube_task_service: 魔方任务看板服务实例。
            resource_service: 资源统计服务实例（只读）。
            category_service: 资源类型字典维护服务实例。
            event_record_service: 活动记录服务实例。
        """
        super().__init__()
        self._data_service = data_service or DataService()
        self._calc_service = calc_service or CalcService()
        self._unlock_service = unlock_service or CodexUnlockService()
        self._create_service = create_service or CodexShipCreateService()
        self._awaken_service = awaken_service or AwakenService()
        self._limit_break_service = limit_break_service or LimitBreakService()
        self._oath_service = oath_service or CodexOathService()
        self._statistics_service = statistics_service or StatisticsService()
        self._mental_calculation_service = mental_calculation_service or MentalCalculationService()
        self._commander_service = commander_service or CommanderService()
        self._cube_task_service = cube_task_service or CubeTaskService()
        self._resource_service = resource_service or ResourceService()
        self._category_service = category_service or ResourceCategoryService()
        self._event_record_service = event_record_service or EventRecordService()
        self._last_seen_date = time_source.today()
        self._midnightTimer = None

        self._initUi()
        self._initMenuBar()
        self._initStatusBar()
        self._connectSignals()
        self._initMidnightTimer()

    def _initUi(self) -> None:
        """初始化用户界面。"""
        self.setWindowTitle(APP_NAME)
        self.setWindowIcon(QIcon(APP_ICON_PATH))
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

        self._statisticsPanel = StatisticsPanel(
            self._statistics_service,
            mental_calculation_service=self._mental_calculation_service,
            commander_service=self._commander_service,
            resource_service=self._resource_service
        )
        self._tabWidget.addTab(self._statisticsPanel, "数据看板")

        self._shipManagementPanel = ShipManagementPanel(
            unlock_service=self._unlock_service,
            create_service=self._create_service,
            awaken_service=self._awaken_service,
            limit_break_service=self._limit_break_service,
            oath_service=self._oath_service
        )
        self._tabWidget.addTab(self._shipManagementPanel, "舰娘管理")

        self._resourceManagementPanel = ResourceManagementPanel(
            cube_task_service=self._cube_task_service
        )
        self._tabWidget.addTab(self._resourceManagementPanel, "资源统计")

        self._eventRecordPanel = EventRecordPanel(self._event_record_service)
        self._tabWidget.addTab(self._eventRecordPanel, "活动记录")

        self._settingsPanel = SettingsPanel(category_service=self._category_service)
        self._tabWidget.addTab(self._settingsPanel, "设置")

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

        settings_action = QAction("设置…", self)
        settings_action.setShortcut("Ctrl+,")
        settings_action.triggered.connect(self._onSettingsClicked)
        file_menu.addAction(settings_action)

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
        self._tabWidget.currentChanged.connect(self._onTabChanged)
        self._shipManagementPanel.dataRefreshed.connect(self._onShipManagementDataRefreshed)
        self._statisticsPanel.dataRefreshed.connect(self._onStatisticsDataRefreshed)
        self._statisticsPanel.commanderResult.connect(self._onCommanderSnapshotResult)
        self._shipManagementPanel.unlockResult.connect(self._onUnlockResult)
        self._shipManagementPanel.shipCreateResult.connect(self._onShipCreateResult)
        self._shipManagementPanel.awakenResult.connect(self._onAwakenResult)
        self._shipManagementPanel.limitBreakResult.connect(self._onLimitBreakResult)
        self._shipManagementPanel.oathResult.connect(self._onOathResult)
        self._resourceManagementPanel.dataRefreshed.connect(self._onResourceDataRefreshed)
        self._resourceManagementPanel.taskResult.connect(self._onCubeTaskResult)
        self._resourceManagementPanel.entryResult.connect(self._onResourceEntryResult)
        self._eventRecordPanel.dataChanged.connect(self._onEventRecordsChanged)
        self._eventRecordPanel.resultReady.connect(self._onEventRecordResult)
        self._settingsPanel.categoriesChanged.connect(self._onCategoriesChanged)
        self._settingsPanel.resultReady.connect(self._onSettingsResult)

    def _initMidnightTimer(self) -> None:
        """初始化跨天定时器：每天零点后触发一次，不做秒级轮询。"""
        self._midnightTimer = QTimer(self)
        self._midnightTimer.setSingleShot(True)
        self._midnightTimer.timeout.connect(self._onMidnightTick)
        self._scheduleMidnightTick()

    def _scheduleMidnightTick(self) -> None:
        """把单次定时器排到下一个零点之后。"""
        if self._midnightTimer is None:
            return
        now = time_source.now()
        next_midnight = datetime.combine(now.date() + timedelta(days=1), datetime_time.min)
        delay_ms = int((next_midnight - now).total_seconds() * 1000) + 1000
        delay_ms = max(1000, min(delay_ms, 24 * 60 * 60 * 1000))
        self._midnightTimer.start(delay_ms)

    def _onMidnightTick(self) -> None:
        """零点触发：刷新当前页的时间上下文，并重排下一次。"""
        try:
            self._last_seen_date = time_source.today()
            self._activatePanel(self._tabWidget.currentIndex())
        finally:
            self._scheduleMidnightTick()

    def _onTabChanged(self, index: int) -> None:
        """页签切换：只激活当前页，避免一次切换刷新所有面板。"""
        self._last_seen_date = time_source.today()
        self._activatePanel(index)

    def _activatePanel(self, index: int) -> None:
        """
        调用指定页签的 ``onActivated``。

        Args:
            index: 页签下标。
        """
        if index < 0:
            return
        panel = self._tabWidget.widget(index)
        if panel is None:
            return
        on_activated = getattr(panel, "onActivated", None)
        if callable(on_activated):
            on_activated()

    def _panels(self):
        """
        当前四个页签面板。

        Returns:
            面板元组。
        """
        return (
            self._statisticsPanel,
            self._shipManagementPanel,
            self._resourceManagementPanel,
            self._eventRecordPanel,
            self._settingsPanel,
        )

    def _onWindowActivated(self) -> None:
        """窗口重新激活：同步当前页时间；跨天时再补一次数据刷新。"""
        if getattr(self, "_tabWidget", None) is None:
            return
        today = time_source.today()
        date_changed = today != self._last_seen_date
        self._last_seen_date = today
        self._activatePanel(self._tabWidget.currentIndex())
        if date_changed:
            self._scheduleMidnightTick()

    def showEvent(self, event) -> None:
        """窗口显示时检查是否已经跨天。"""
        super().showEvent(event)
        self._onWindowActivated()

    def changeEvent(self, event) -> None:
        """窗口激活事件：兜底处理休眠恢复跨天。"""
        super().changeEvent(event)
        if event.type() == QEvent.WindowActivate:
            self._onWindowActivated()

    def _onRefreshClicked(self) -> None:
        """刷新按钮点击事件处理。"""
        try:
            self._statusBar.showMessage("正在刷新数据...")
            self.refreshData()
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

    def _onShipCreateResult(self, result: ShipCreateResult) -> None:
        """
        舰娘新增结果事件处理。

        Args:
            result: 新增结果对象。
        """
        self._statusBar.showMessage(result.toStatusBarMessage())

    def _onAwakenResult(self, result: AwakenResult) -> None:
        """
        觉醒结果事件处理。

        Args:
            result: 觉醒结果对象。
        """
        self._statusBar.showMessage(result.toStatusBarMessage())

    def _onLimitBreakResult(self, result: LimitBreakResult) -> None:
        """
        界限突破结果事件处理。

        Args:
            result: 界限突破结果对象。
        """
        self._statusBar.showMessage(result.toStatusBarMessage())

    def _onOathResult(self, result: OathResult) -> None:
        """
        誓约结果事件处理。

        Args:
            result: 誓约结果对象。
        """
        self._statusBar.showMessage(result.toStatusBarMessage())

    def _onResourceDataRefreshed(self) -> None:
        """资源统计数据刷新完成事件处理（看板同步刷新）。"""
        self._statisticsPanel.refreshData()
        self._statusBar.showMessage("资源统计数据已更新")

    def _onCommanderSnapshotResult(self, result: CommanderWriteResult) -> None:
        """
        指挥官快照写操作结果事件处理。

        Args:
            result: 写操作结果对象。
        """
        self._statusBar.showMessage(result.toStatusBarMessage())

    def _onCubeTaskResult(self, result: CubeTaskWriteResult) -> None:
        """
        魔方任务看板写操作结果事件处理。

        Args:
            result: 写操作结果对象。
        """
        self._statusBar.showMessage(result.toStatusBarMessage())

    def _onResourceEntryResult(self, result) -> None:
        """
        常规录入结果事件处理。

        关联了活动的明细会改变活动页的「关联魔方」，因此这里顺带刷新活动记录页。

        Args:
            result: `ResourceEntryResult` 实例。
        """
        self._statusBar.showMessage(result.toStatusBarMessage())
        self._eventRecordPanel.refreshData()

    def _onEventRecordsChanged(self) -> None:
        """活动记录变化：让常规录入的「所属活动」下拉立即跟上。"""
        self._resourceManagementPanel.refreshEntryEvents()

    def _onEventRecordResult(self, result) -> None:
        """
        活动记录写操作结果事件处理。

        Args:
            result: `EventWriteResult` 实例。
        """
        self._statusBar.showMessage(result.toStatusBarMessage())

    def _onCategoriesChanged(self) -> None:
        """类型字典变化：让两个常规录入面板的下拉立即跟上。"""
        self._resourceManagementPanel.refreshEntryCategories()

    def _onSettingsResult(self, result) -> None:
        """
        设置页写操作结果事件处理。

        Args:
            result: `CategoryWriteResult` 实例。
        """
        self._statusBar.showMessage(result.toStatusBarMessage())

    def _onSettingsClicked(self) -> None:
        """文件 → 设置…：切到设置页签。"""
        self._tabWidget.setCurrentWidget(self._settingsPanel)

    def _onStatisticsDataRefreshed(self) -> None:
        """统计数据刷新完成事件处理。"""
        self._statusBar.showMessage("统计数据已更新")

    def refreshData(self) -> None:
        """刷新界面数据：先同步时间上下文，再重算各页。"""
        for panel in self._panels():
            panel.syncTimeContext()
        self._statisticsPanel.refreshData()
        self._shipManagementPanel.refreshData()
        self._resourceManagementPanel.refreshData()
        self._eventRecordPanel.refreshData()
        self._settingsPanel.refreshData()
        self._last_seen_date = time_source.today()

    def _showAbout(self) -> None:
        """显示关于对话框。"""
        QMessageBox.about(
            self,
            "关于 碧蓝航线数据管理工具",
            "碧蓝航线数据管理工具 v0.0.1\n\n"
            "一款用于管理碧蓝航线游戏数据的桌面应用。\n\n"
            "技术栈: Python + PyQt5 + SQLite"
        )
