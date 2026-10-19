"""
时间刷新与跨天行为单元测试。

覆盖：
- 常规录入：自动态时刻跨天推进、未触碰控件时按点击瞬间写入、手动补录保持不变；
- 魔方任务看板：记账日期自动前进、补录日期保留、刷新按钮不再级联统计刷新；
- 数据看板：跨天更新执勤天数与资源卡角标，不重算统计聚合；
- 指级经验：时间与查询区间自动前进、手动值保留；
- 主窗口：页签激活与跨天/窗口激活的轻量触发、午夜定时器只排一次。
"""

import os
import shutil
import sqlite3
import tempfile
import unittest
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtCore import QDate  # noqa: E402
from PyQt5.QtWidgets import QApplication  # noqa: E402

from services.commander_service import CommanderService  # noqa: E402
from services.cube_task_service import CubeTaskService  # noqa: E402
from services.resource_entry_service import ResourceEntryService  # noqa: E402
from services.resource_service import ResourceCardView, ResourceDailyDelta  # noqa: E402
from utils.db_connection import DatabaseConnection  # noqa: E402
from utils.db_schema import ensureResourceStatisticsSchema  # noqa: E402
from views.dialogs.commander_exp_dialog import CommanderExpDialog  # noqa: E402
from views.main_window import MainWindow  # noqa: E402
from views.widgets.commander_exp_panel import CommanderExpPanel  # noqa: E402
from views.widgets.cube_task_board_panel import CubeTaskBoardPanel  # noqa: E402
from views.widgets.regular_entry_panel import RegularEntryPanel  # noqa: E402
from views.widgets.statistics_panel import StatisticsPanel  # noqa: E402

APP = QApplication.instance() or QApplication([])


@contextmanager
def freeze_time(moment: datetime):
    """把统一时间源固定到指定时刻。"""
    with patch("utils.time_source.now", return_value=moment), patch(
        "utils.time_source.today", return_value=moment.date()
    ):
        yield


class _TempDatabaseCase(unittest.TestCase):
    """提供带资源 / 任务表结构的临时数据库。"""

    def setUp(self):
        self._original_db_path = DatabaseConnection.getDbPath()
        self._temp_dir = tempfile.mkdtemp(prefix="azurlane_time_refresh_")
        self._db_path = os.path.join(self._temp_dir, "time.db")
        DatabaseConnection.setDbPath(self._db_path)
        ensureResourceStatisticsSchema(self._db_path)

    def tearDown(self):
        DatabaseConnection.setDbPath(self._original_db_path)
        shutil.rmtree(self._temp_dir, ignore_errors=True)

    def _query(self, sql, params=()):
        """执行只读查询。"""
        conn = sqlite3.connect(self._db_path)
        try:
            return conn.execute(sql, params).fetchall()
        finally:
            conn.close()

    def _createCommanderTables(self):
        """建立指级经验面板所需的最小表。"""
        conn = sqlite3.connect(self._db_path)
        try:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS commander_info (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    statistics_date TEXT DEFAULT CURRENT_TIMESTAMP,
                    commander_level INTEGER NOT NULL CHECK (commander_level BETWEEN 1 AND 999),
                    commander_exp INTEGER NOT NULL CHECK (commander_exp >= 0)
                );
                CREATE TABLE IF NOT EXISTS commander_level_exp (
                    level INTEGER PRIMARY KEY CHECK (level BETWEEN 1 AND 200),
                    level_up_exp INTEGER,
                    cumulative_exp INTEGER,
                    note TEXT NOT NULL DEFAULT ''
                );
                """
            )
            conn.commit()
        finally:
            conn.close()


class TestRegularEntryTime(_TempDatabaseCase):
    """常规录入时刻的自动态 / 手动态。"""

    def _buildPanel(self, moment: datetime) -> RegularEntryPanel:
        """在指定时刻构造面板。"""
        with freeze_time(moment):
            return RegularEntryPanel(ResourceEntryService())

    def testActivationAdvancesAutoMoment(self):
        """跨天后激活，自动态时刻推进到当前时间。"""
        base = datetime(2026, 10, 18, 23, 50, 0)
        next_day = datetime(2026, 10, 19, 0, 5, 0)
        panel = self._buildPanel(base)

        with freeze_time(next_day):
            panel.onActivated()

        self.assertEqual(panel._timeEdit.dateTime().toPyDateTime(), next_day)

    def testRecordWithoutTouchUsesClickMoment(self):
        """未触碰时间控件时，写入以点击「记录」的瞬间为准。"""
        base = datetime(2026, 10, 18, 23, 50, 0)
        next_day = datetime(2026, 10, 19, 0, 5, 0)
        panel = self._buildPanel(base)

        with freeze_time(next_day):
            panel._recordBtn.click()

        rows = self._query("SELECT record_time FROM resource_transaction")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][0], next_day.strftime("%Y-%m-%d %H:%M:%S"))

    def testManualMomentSurvivesActivation(self):
        """手动补录的时刻在激活后保持不变，并按该时刻写入。"""
        base = datetime(2026, 10, 18, 23, 50, 0)
        next_day = datetime(2026, 10, 19, 0, 5, 0)
        manual = base - timedelta(hours=2)
        panel = self._buildPanel(base)
        panel._timeEdit.setDateTime(manual)

        with freeze_time(next_day):
            panel.onActivated()
            panel._recordBtn.click()

        self.assertEqual(panel._timeEdit.dateTime().toPyDateTime(), manual)
        rows = self._query("SELECT record_time FROM resource_transaction")
        self.assertEqual(rows[0][0], manual.strftime("%Y-%m-%d %H:%M:%S"))

    def testAutoMomentAdvancesAfterWrite(self):
        """自动态写入成功后，控件推进到写入时刻。"""
        base = datetime(2026, 10, 18, 23, 50, 0)
        moment = base + timedelta(minutes=10)
        panel = self._buildPanel(base)

        with freeze_time(moment):
            panel._recordBtn.click()

        self.assertEqual(panel._timeEdit.dateTime().toPyDateTime(), moment)
        self.assertEqual(panel._auto_moment, moment)

    def testNowButtonRestoresAutoFollow(self):
        """「现在」按钮把时刻切回当前时间，并恢复自动跟随。"""
        base = datetime(2026, 10, 18, 23, 50, 0)
        next_day = datetime(2026, 10, 19, 0, 5, 0)
        panel = self._buildPanel(base)
        panel._timeEdit.setDateTime(base - timedelta(hours=2))

        with freeze_time(next_day):
            panel._nowBtn.click()

        self.assertEqual(panel._timeEdit.dateTime().toPyDateTime(), next_day)
        self.assertEqual(panel._auto_moment, next_day)


class TestCubeTaskBoardTime(_TempDatabaseCase):
    """魔方任务看板记账日期的自动态 / 手动态。"""

    def _buildBoard(self, moment: datetime) -> CubeTaskBoardPanel:
        """在指定时刻构造看板。"""
        with freeze_time(moment):
            return CubeTaskBoardPanel(CubeTaskService())

    def testActivationAdvancesAutoDate(self):
        """跨天后激活，记账日期与周期信息推进到今天。"""
        base = datetime(2026, 10, 18, 23, 50, 0)
        next_day = datetime(2026, 10, 19, 0, 5, 0)
        board = self._buildBoard(base)

        with freeze_time(next_day):
            board.onActivated()

        self.assertEqual(board._dateEdit.date().toPyDate(), next_day.date())
        self.assertIn("2026-10-19", board._periodLabel.text())
        self.assertIn("今日", board._periodLabel.text())

    def testCompleteWithoutTouchUsesToday(self):
        """未触碰日期控件时，完成任务写入新的一天。"""
        base = datetime(2026, 10, 18, 23, 50, 0)
        next_day = datetime(2026, 10, 19, 0, 5, 0)
        board = self._buildBoard(base)

        with freeze_time(next_day):
            board._onCompleteRequested("daily_build_once")

        rows = self._query("SELECT record_time FROM resource_transaction")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][0], next_day.strftime("%Y-%m-%d %H:%M:%S"))

    def testManualDatePreserved(self):
        """手动补录日期在激活后保持不变，并归属所选日期。"""
        base = datetime(2026, 10, 18, 23, 50, 0)
        next_day = datetime(2026, 10, 19, 0, 5, 0)
        board = self._buildBoard(base)
        board._dateEdit.setDate(QDate(2026, 10, 17))

        with freeze_time(next_day):
            board.onActivated()
            board._onCompleteRequested("daily_build_once")

        self.assertEqual(board._dateEdit.date().toPyDate(), date(2026, 10, 17))
        self.assertIn("所选日", board._periodLabel.text())
        rows = self._query("SELECT record_time FROM resource_transaction")
        self.assertEqual(rows[0][0], "2026-10-17 00:05:00")

    def testRefreshButtonDoesNotCascadeDataRefreshed(self):
        """刷新按钮只重渲染看板，不再通知统计面板全量刷新。"""
        base = datetime(2026, 10, 18, 23, 50, 0)
        board = self._buildBoard(base)
        refreshed = []
        board.dataRefreshed.connect(lambda: refreshed.append(True))

        with freeze_time(base):
            board._refreshBtn.click()

        self.assertEqual(refreshed, [])

    def testTodayButtonRestoresAutoFollow(self):
        """「今天」按钮回到今天，并恢复跨天自动前进。"""
        base = datetime(2026, 10, 18, 23, 50, 0)
        next_day = datetime(2026, 10, 19, 0, 5, 0)
        board = self._buildBoard(base)
        board._dateEdit.setDate(QDate(2026, 10, 17))

        with freeze_time(next_day):
            board._todayBtn.click()
            self.assertEqual(board._dateEdit.date().toPyDate(), next_day.date())

            following = next_day + timedelta(days=1)
            with freeze_time(following):
                board.onActivated()
        self.assertEqual(board._dateEdit.date().toPyDate(), following.date())

    def testMaximumDateIsToday(self):
        """记账日期控件不允许选择未来。"""
        base = datetime(2026, 10, 18, 23, 50, 0)
        board = self._buildBoard(base)

        self.assertEqual(board._dateEdit.maximumDate().toPyDate(), base.date())


class _StubUserService:
    """执勤天数桩。"""

    def __init__(self):
        self.calls = 0

    def getDutyDaysText(self):
        self.calls += 1
        return f"{self.calls}天"


class _StubStatisticsService:
    """统计服务桩。"""

    def __init__(self):
        self.calls = 0

    def getAllStatistics(self):
        self.calls += 1
        return {}


class _StubCommanderService:
    """指挥官服务桩。"""

    def getCommanderLevelCardText(self):
        return "-"

    def getCommanderLevelCardTooltip(self):
        return ""

    def getExpEfficiencyText(self):
        return "-"

    def getExpEfficiencyTooltip(self):
        return ""


class _StubResourceService:
    """资源卡服务桩。"""

    def __init__(self):
        self.calls = 0

    def getCardView(self, _resource_type):
        self.calls += 1
        return ResourceCardView("-", "", None)


class TestStatisticsDateSensitive(_TempDatabaseCase):
    """数据看板跨天只刷新日期敏感项。"""

    def _buildPanel(self, moment: datetime):
        with freeze_time(moment):
            user = _StubUserService()
            statistics = _StubStatisticsService()
            resource = _StubResourceService()
            panel = StatisticsPanel(
                statistics_service=statistics,
                user_service=user,
                commander_service=_StubCommanderService(),
                resource_service=resource,
            )
        return panel, user, statistics, resource

    def testDateChangeRefreshesDutyDaysAndResourceBadges(self):
        """跨天激活更新执勤天数与资源卡角标，不重算统计聚合。"""
        base = datetime(2026, 10, 18, 23, 50, 0)
        next_day = datetime(2026, 10, 19, 0, 5, 0)
        panel, user, statistics, resource = self._buildPanel(base)
        self.assertEqual(user.calls, 1)
        self.assertEqual(statistics.calls, 1)
        self.assertEqual(resource.calls, 2)

        with freeze_time(next_day):
            panel.onActivated()

        self.assertEqual(user.calls, 2)
        self.assertEqual(statistics.calls, 1)
        self.assertEqual(resource.calls, 4)
        self.assertEqual(panel._dutyDaysCard.value(), "2天")

    def testSameDayActivationDoesNotTouchServices(self):
        """同一天重复激活不查任何服务。"""
        base = datetime(2026, 10, 18, 23, 50, 0)
        panel, user, statistics, resource = self._buildPanel(base)

        with freeze_time(base + timedelta(minutes=5)):
            panel.onActivated()

        self.assertEqual(user.calls, 1)
        self.assertEqual(statistics.calls, 1)
        self.assertEqual(resource.calls, 2)


class _BadgeResourceService:
    """返回固定资源卡视图的服务桩。"""

    def __init__(self, view):
        self._view = view

    def getCardView(self, _resource_type):
        return self._view


class TestResourceBadgeRendering(unittest.TestCase):
    """资源卡角标状态（未记录 / 数字）的视图接线。"""

    def _buildPanel(self, view):
        return StatisticsPanel(
            statistics_service=_StubStatisticsService(),
            user_service=_StubUserService(),
            commander_service=_StubCommanderService(),
            resource_service=_BadgeResourceService(view),
        )

    def testNotRecordedBadgeShownGrey(self):
        panel = self._buildPanel(ResourceCardView("4.1K", "tip", None, "未记录", "flat"))

        self.assertEqual(panel._cubeCard.badgeText(), "未记录")
        self.assertEqual(panel._cubeCard.badgeTone(), "flat")

    def testDeltaFallbackStillWorks(self):
        delta = ResourceDailyDelta(10, "2026-10-18", "2026-10-17", 4087, 4076)
        panel = self._buildPanel(ResourceCardView("4.1K", "tip", delta))

        self.assertEqual(panel._cubeCard.badgeText(), "↑10")
        self.assertEqual(panel._cubeCard.badgeTone(), "up")


class TestCommanderExpTime(_TempDatabaseCase):
    """指级经验时间与查询区间的自动态。"""

    def setUp(self):
        super().setUp()
        self._createCommanderTables()

    def _buildPanel(self, moment: datetime) -> CommanderExpPanel:
        with freeze_time(moment):
            return CommanderExpPanel(CommanderService())

    def testActivationAdvancesTimeAndRange(self):
        """跨天后时间、结束日与起始日一起前进。"""
        base = datetime(2026, 10, 18, 23, 50, 0)
        next_day = datetime(2026, 10, 19, 0, 5, 0)
        panel = self._buildPanel(base)

        with freeze_time(next_day):
            panel.onActivated()

        self.assertEqual(panel._timeEdit.dateTime().toPyDateTime(), next_day)
        self.assertEqual(panel._endDateEdit.date().toPyDate(), next_day.date())
        self.assertEqual(
            panel._startDateEdit.date().toPyDate(),
            (next_day - timedelta(days=90)).date(),
        )

    def testManualTimeSurvivesActivation(self):
        """手动改过的快照时间不被自动覆盖。"""
        base = datetime(2026, 10, 18, 23, 50, 0)
        next_day = datetime(2026, 10, 19, 0, 5, 0)
        manual = base - timedelta(days=2)
        panel = self._buildPanel(base)
        panel._timeEdit.setDateTime(manual)

        with freeze_time(next_day):
            panel.onActivated()

        self.assertEqual(panel._timeEdit.dateTime().toPyDateTime(), manual)

    def testEditingStateIsNotReset(self):
        """编辑已有快照时，激活不重置时间。"""
        base = datetime(2026, 10, 18, 23, 50, 0)
        next_day = datetime(2026, 10, 19, 0, 5, 0)
        panel = self._buildPanel(base)
        panel._editing_id = 1

        with freeze_time(next_day):
            panel.onActivated()

        self.assertEqual(panel._timeEdit.dateTime().toPyDateTime(), base)

    def testSaveWithoutTouchUsesClickMoment(self):
        """未触碰时间控件时，保存快照以点击「保存」的瞬间为准。"""
        base = datetime(2026, 10, 18, 23, 50, 0)
        next_day = datetime(2026, 10, 19, 0, 5, 0)
        panel = self._buildPanel(base)

        with freeze_time(next_day):
            panel._saveBtn.click()

        rows = self._query("SELECT statistics_date FROM commander_info")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][0], "2026-10-19 00:05")

    def testDialogShowAdvancesTime(self):
        """打开缓存的指级经验窗口时，时间随当前时间前进。"""
        base = datetime(2026, 10, 18, 23, 50, 0)
        next_day = datetime(2026, 10, 19, 0, 5, 0)
        with freeze_time(base):
            dialog = CommanderExpDialog(CommanderService())

        with freeze_time(next_day):
            dialog.show()
            APP.processEvents()

        try:
            self.assertEqual(dialog._panel._timeEdit.dateTime().toPyDateTime(), next_day)
        finally:
            dialog.close()


class _StubPanel:
    """记录激活次数的面板桩。"""

    def __init__(self):
        self.calls = 0

    def onActivated(self):
        self.calls += 1


class _StubTabs:
    """最小页签控件桩。"""

    def __init__(self, panels):
        self.panels = panels
        self.index = 0

    def currentIndex(self):
        return self.index

    def widget(self, index):
        return self.panels[index]


class _StubTimer:
    """记录 start 参数的定时器桩。"""

    def __init__(self):
        self.started_ms = None

    def start(self, delay_ms):
        self.started_ms = delay_ms


class TestMainWindowTimeTriggers(unittest.TestCase):
    """主窗口的页签 / 跨天触发逻辑（不构造完整窗口）。"""

    def testTabChangeActivatesOnlyCurrentPanel(self):
        """切页只调用当前面板 onActivated。"""
        panel = _StubPanel()
        fake = SimpleNamespace(
            _tabWidget=_StubTabs([panel]),
            _last_seen_date=date(2026, 10, 18),
            _activatePanel=lambda index: panel.onActivated(),
        )

        with freeze_time(datetime(2026, 10, 19, 0, 5, 0)):
            MainWindow._onTabChanged(fake, 0)

        self.assertEqual(panel.calls, 1)

    def testWindowActivationSyncsTimeAndOnlyReschedulesOnNewDay(self):
        """窗口激活同步当前页时间；只有跨天才重排午夜定时器。"""
        activated = []
        scheduled = []
        fake = SimpleNamespace(
            _tabWidget=_StubTabs([_StubPanel()]),
            _last_seen_date=date(2026, 10, 18),
            _activatePanel=lambda index: activated.append(index),
            _scheduleMidnightTick=lambda: scheduled.append(True),
        )

        with freeze_time(datetime(2026, 10, 18, 12, 0, 0)):
            MainWindow._onWindowActivated(fake)
        self.assertEqual(activated, [0])
        self.assertEqual(scheduled, [])

        with freeze_time(datetime(2026, 10, 19, 0, 5, 0)):
            MainWindow._onWindowActivated(fake)
        self.assertEqual(activated, [0, 0])
        self.assertEqual(len(scheduled), 1)

    def testMidnightTimerScheduledOncePerDay(self):
        """定时器只排到下一个零点后，不做秒级轮询。"""
        fake = SimpleNamespace(_midnightTimer=_StubTimer())

        with freeze_time(datetime(2026, 10, 18, 23, 59, 30)):
            MainWindow._scheduleMidnightTick(fake)

        self.assertGreaterEqual(fake._midnightTimer.started_ms, 30_000)
        self.assertLessEqual(fake._midnightTimer.started_ms, 31_500)


if __name__ == "__main__":
    unittest.main()
