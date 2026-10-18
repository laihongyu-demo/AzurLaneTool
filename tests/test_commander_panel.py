"""
指级经验面板与看板卡片接线单元测试。

覆盖：列表渲染、需求经验提示、编辑回填、保存更新、删除确认、
表缺失降级，以及「数据看板」三张卡的取值与错误降级。
"""

import os
import shutil
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtWidgets import QApplication, QMessageBox, QScrollArea  # noqa: E402

from services.commander_service import CommanderService  # noqa: E402
from services.cube_task_service import CubeTaskService  # noqa: E402
from services.resource_service import ResourceService  # noqa: E402
from utils.db_connection import DatabaseConnection  # noqa: E402
from utils.db_schema import ensureResourceStatisticsSchema  # noqa: E402
from utils.exceptions import DatabaseError  # noqa: E402
from views.dialogs.commander_exp_dialog import CommanderExpDialog  # noqa: E402
from views.widgets.commander_exp_panel import CommanderExpPanel  # noqa: E402
from views.widgets.resource_management_panel import ResourceManagementPanel  # noqa: E402
from views.widgets.statistics_panel import StatisticsPanel  # noqa: E402

APP = QApplication.instance() or QApplication([])

CREATE_COMMANDER_SQL = """
CREATE TABLE commander_info (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    statistics_date TEXT DEFAULT CURRENT_TIMESTAMP,
    commander_level INTEGER NOT NULL CHECK (commander_level BETWEEN 1 AND 999),
    commander_exp INTEGER NOT NULL CHECK (commander_exp >= 0)
)
"""

CREATE_LEVEL_EXP_SQL = """
CREATE TABLE commander_level_exp (
    level INTEGER PRIMARY KEY CHECK (level BETWEEN 1 AND 200),
    level_up_exp INTEGER,
    cumulative_exp INTEGER,
    note TEXT NOT NULL DEFAULT ''
)
"""

FIXTURE_COMMANDER = [
    ("2026-10-11 10:31", 162, 344987),
    ("2026-10-16 22:53", 163, 77057),
]

FIXTURE_LEVEL_EXP = [
    (162, 346200, 11214610, ""),
    (163, 354350, 11568960, ""),
]


class _TempDatabaseCase(unittest.TestCase):
    """提供临时数据库的测试基类。"""

    def setUp(self):
        self._original_db_path = DatabaseConnection.getDbPath()
        self._temp_dir = tempfile.mkdtemp(prefix="azurlane_resource_")
        self._db_path = os.path.join(self._temp_dir, "test.db")

    def tearDown(self):
        DatabaseConnection.setDbPath(self._original_db_path)
        shutil.rmtree(self._temp_dir, ignore_errors=True)

    def _createDatabase(self, with_commander=True):
        """建立仅含必要表的测试库。"""
        conn = sqlite3.connect(self._db_path)
        try:
            if with_commander:
                conn.executescript(CREATE_COMMANDER_SQL)
                conn.executescript(CREATE_LEVEL_EXP_SQL)
                conn.executemany(
                    "INSERT INTO commander_info (statistics_date, commander_level, commander_exp)"
                    " VALUES (?, ?, ?)",
                    FIXTURE_COMMANDER,
                )
                conn.executemany(
                    "INSERT INTO commander_level_exp (level, level_up_exp, cumulative_exp, note)"
                    " VALUES (?, ?, ?, ?)",
                    FIXTURE_LEVEL_EXP,
                )
                conn.commit()
        finally:
            conn.close()
        DatabaseConnection.setDbPath(self._db_path)
        # 资源 / 任务看板表（幂等建表，不影响上面缺失表降级的用例）
        ensureResourceStatisticsSchema(self._db_path)


class TestCommanderExpPanel(_TempDatabaseCase):
    """指级经验面板测试。"""

    def testRendersSnapshotsAndRequirement(self):
        """列表渲染快照，需求经验来自基准表。"""
        self._createDatabase()
        panel = CommanderExpPanel(CommanderService())

        self.assertEqual(panel._table.rowCount(), 2)
        self.assertEqual(panel._countLabel.text(), "2 条")
        self.assertIn("354,350", panel._requirementLabel.text())
        self.assertIn("11,568,960", panel._requirementLabel.text())

    def testFirstRowIsLatestSnapshot(self):
        """列表首行为最新快照。"""
        self._createDatabase()
        panel = CommanderExpPanel(CommanderService())

        self.assertEqual(panel._table.item(0, 0).text(), "2026-10-16 22:53")
        self.assertEqual(panel._table.item(0, 2).text(), "77,057")
        self.assertEqual(panel._table.item(0, 4).text(), "21.7%")

    def testSelectingRowEntersEditMode(self):
        """选中行后回填表单并切换为更新模式。"""
        self._createDatabase()
        panel = CommanderExpPanel(CommanderService())

        panel._table.selectRow(0)

        self.assertIsNotNone(panel._editing_id)
        self.assertEqual(panel._saveBtn.text(), "更新快照")
        self.assertEqual(panel._levelSpin.value(), 163)
        self.assertEqual(panel._expSpin.value(), 77057)

    def testSaveUpdatesSelectedSnapshot(self):
        """更新快照写回数据库，不新增行。"""
        self._createDatabase()
        panel = CommanderExpPanel(CommanderService())
        panel._table.selectRow(0)

        panel._expSpin.setValue(1000)
        panel._onSaveClicked()

        conn = sqlite3.connect(self._db_path)
        try:
            rows = conn.execute(
                "SELECT statistics_date, commander_level, commander_exp FROM commander_info"
                " ORDER BY statistics_date"
            ).fetchall()
        finally:
            conn.close()

        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[-1], ("2026-10-16 22:53", 163, 1000))
        self.assertEqual(panel._table.rowCount(), 2)

    @patch("views.widgets.commander_exp_panel.QMessageBox.question",
           return_value=QMessageBox.Yes)
    def testDeleteRemovesSnapshotAfterConfirm(self, _question):
        """确认后删除选中快照，列表同步减少。"""
        self._createDatabase()
        panel = CommanderExpPanel(CommanderService())
        panel._table.selectRow(0)

        panel._onDeleteClicked()

        conn = sqlite3.connect(self._db_path)
        try:
            count = conn.execute("SELECT COUNT(*) FROM commander_info").fetchone()[0]
        finally:
            conn.close()

        self.assertEqual(count, 1)
        self.assertEqual(panel._table.rowCount(), 1)

    def testMissingTableDegradesToEmpty(self):
        """旧库没有 commander_info 时面板为空且不报错。"""
        self._createDatabase(with_commander=False)

        panel = CommanderExpPanel(CommanderService())

        self.assertEqual(panel._table.rowCount(), 0)
        self.assertEqual(panel._countLabel.text(), "0 条")

    def testEnsureSchemaCreatesResourceTables(self):
        """启动建表可重复执行，并能补齐缺失的资源表。"""
        self._createDatabase()

        ensureResourceStatisticsSchema(self._db_path)
        ensureResourceStatisticsSchema(self._db_path)

        conn = sqlite3.connect(self._db_path)
        try:
            names = {
                row[0] for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                )
            }
        finally:
            conn.close()

        self.assertTrue({"resource_daily", "resource_transaction", "resource_category"} <= names)


class TestResourceManagementPanel(_TempDatabaseCase):
    """页签容器测试（指级经验已迁出，仅保留任务看板 + 预留区）。"""

    def testContainerHostsTaskBoardOnly(self):
        """容器承载任务看板与预留分组，不再内嵌指级经验面板。"""
        self._createDatabase()
        panel = ResourceManagementPanel(CubeTaskService())

        self.assertTrue(hasattr(panel, "_taskBoardPanel"))
        self.assertFalse(hasattr(panel, "_commanderPanel"))
        self.assertIsNotNone(panel.findChild(QScrollArea))

    def testContainerRelaysRefresh(self):
        """容器刷新子面板并转发 dataRefreshed。"""
        self._createDatabase()
        panel = ResourceManagementPanel(CubeTaskService())
        received = []
        panel.dataRefreshed.connect(lambda: received.append(True))

        panel.refreshData()
        panel._taskBoardPanel.dataRefreshed.emit()

        self.assertEqual(len(panel._taskBoardPanel._state_by_code), 18)
        self.assertEqual(received, [True])


class _StubStatisticsService:
    """统计服务桩：返回全零统计，避免依赖舰娘表。"""

    def getAllStatistics(self):
        return {
            "unlock": {"total": 0, "total_excluding_collab": 0, "locked": 0,
                       "locked_excluding_collab": 0, "unlocked": 0,
                       "unlocked_excluding_collab": 0, "unlock_rate": 0},
            "oath": {"total": 0, "oathed": 0, "oath_rate": 0},
            "tp": {"total_tp": 0, "unlocked_tp": 0, "completion_rate": 0},
            "bulin": {"universal_bulin": 0, "trial_bulin_mkii": 0, "specialized_bulin_mkiii": 0},
            "remaining_leveling": 0,
            "material_pending": 0,
            "leveling_required": 0,
        }


class _FailingStatisticsService(_StubStatisticsService):
    """统计服务桩：模拟数据库异常，用于验证错误降级。"""

    def getAllStatistics(self):
        raise DatabaseError("simulated failure")


class _StubUserService:
    """用户服务桩：固定执勤天数。"""

    def getDutyDaysText(self):
        return "1,000天"


class _StubCommanderService:
    """指挥官服务桩。"""

    def __init__(self, text="-", tooltip="tip", efficiency_text="-", efficiency_tooltip="效率tip"):
        self._text = text
        self._tooltip = tooltip
        self._efficiency_text = efficiency_text
        self._efficiency_tooltip = efficiency_tooltip

    def getCommanderLevelCardText(self):
        return self._text

    def getCommanderLevelCardTooltip(self):
        return self._tooltip

    def getExpEfficiencyText(self):
        return self._efficiency_text

    def getExpEfficiencyTooltip(self):
        return self._efficiency_tooltip


class _StubResourceService:
    """资源服务桩。"""

    def __init__(self, texts=None, tooltips=None):
        self._texts = texts or {}
        self._tooltips = tooltips or {}

    def getCardView(self, resource_type):
        return (
            self._texts.get(resource_type, "-"),
            self._tooltips.get(resource_type, ""),
        )

    def getCardText(self, resource_type):
        return self._texts.get(resource_type, "-")

    def getCardTooltip(self, resource_type):
        return self._tooltips.get(resource_type, "")


class TestStatisticsCardWiring(unittest.TestCase):
    """数据看板四张卡接线测试。"""

    def _buildPanel(self, statistics_service=None, commander_service=None, resource_service=None):
        """构造统计面板，依赖全部注入。"""
        return StatisticsPanel(
            statistics_service=statistics_service or _StubStatisticsService(),
            user_service=_StubUserService(),
            commander_service=commander_service or _StubCommanderService(),
            resource_service=resource_service or _StubResourceService(),
        )

    def testResourceCardsAreNotClickable(self):
        """魔方 / 红尖尖卡片不再响应点击（#14 验收结论：无需跳转）。"""
        panel = self._buildPanel()

        self.assertFalse(panel._cubeCard.clickable())
        self.assertFalse(panel._redGemCard.clickable())
        self.assertTrue(panel._commanderLevelCard.clickable())

    def testEmptyDataShowsPlaceholders(self):
        """无数据时三张卡显示 -，不抛异常。"""
        panel = self._buildPanel()

        self.assertEqual(panel._commanderLevelCard.value(), "-")
        self.assertEqual(panel._cubeCard.value(), "-")
        self.assertEqual(panel._redGemCard.value(), "-")
        self.assertEqual(panel._expEfficiencyCard.value(), "-")

    def testCardsShowServiceValues(self):
        """卡片取服务层已格式化的文本，并写入悬停提示。"""
        panel = self._buildPanel(
            commander_service=_StubCommanderService("163（77,057/354,350）", "指挥官tip"),
            resource_service=_StubResourceService(
                {"cube": "4.1K", "red_gem": "3.4K"},
                {"cube": "魔方tip", "red_gem": "红尖尖tip"},
            ),
        )

        self.assertEqual(panel._commanderLevelCard.value(), "163（77,057/354,350）")
        self.assertEqual(panel._cubeCard.value(), "4.1K")
        self.assertEqual(panel._redGemCard.value(), "3.4K")
        self.assertEqual(panel._cubeCard.toolTip(), "魔方tip")
        self.assertEqual(panel._redGemCard.toolTip(), "红尖尖tip")

    def testExpEfficiencyShowsServiceValue(self):
        """指级效率卡取服务层文本与口径提示。"""
        panel = self._buildPanel(
            commander_service=_StubCommanderService(
                "163（77,057/354,350）", "指挥官tip",
                efficiency_text="11,336/天", efficiency_tooltip="近 30 天日均｜…",
            ),
        )

        self.assertEqual(panel._expEfficiencyCard.value(), "11,336/天")
        self.assertIn("近 30 天日均", panel._expEfficiencyCard.toolTip())

    def testExpEfficiencyDegradesToDash(self):
        """数据不足时卡片显示 -，不抛异常。"""
        panel = self._buildPanel()

        self.assertEqual(panel._expEfficiencyCard.value(), "-")

    def testDatabaseErrorFallsBackToErrorCards(self):
        """统计服务异常时三张卡与其余卡片一起显示错误。"""
        panel = self._buildPanel(statistics_service=_FailingStatisticsService())

        self.assertEqual(panel._commanderLevelCard.value(), "错误")
        self.assertEqual(panel._cubeCard.value(), "错误")
        self.assertEqual(panel._redGemCard.value(), "错误")
        self.assertEqual(panel._expEfficiencyCard.value(), "错误")


class TestCommanderExpDialog(_TempDatabaseCase):
    """指级经验独立窗口测试。"""

    def testDialogHostsPanel(self):
        """窗口内嵌指级经验面板，标题正确。"""
        self._createDatabase()

        dialog = CommanderExpDialog(CommanderService())

        self.assertEqual(dialog.windowTitle(), "指级经验")
        self.assertEqual(dialog._panel._table.rowCount(), 2)
        self.assertFalse(dialog.isModal())

    def testCardClickOpensDialog(self):
        """点击指挥官等级卡片打开窗口（非模态），再次点击复用同一实例。"""
        self._createDatabase()
        panel = StatisticsPanel(
            statistics_service=_StubStatisticsService(),
            user_service=_StubUserService(),
            commander_service=CommanderService(),
            resource_service=_StubResourceService(),
        )

        self.assertIsNone(panel._commanderDialog)
        panel._onCommanderLevelClicked()
        first = panel._commanderDialog
        self.assertIsNotNone(first)
        self.assertTrue(first.isVisible())

        panel._onCommanderLevelClicked()
        self.assertIs(panel._commanderDialog, first)

        first.close()

    def testDialogRefreshUpdatesCard(self):
        """窗口内数据变化会刷新看板卡片。"""
        self._createDatabase()
        panel = StatisticsPanel(
            statistics_service=_StubStatisticsService(),
            user_service=_StubUserService(),
            commander_service=CommanderService(),
            resource_service=_StubResourceService(),
        )
        panel._onCommanderLevelClicked()

        panel._commanderDialog.dataRefreshed.emit()

        self.assertEqual(panel._commanderLevelCard.value(), "163（77,057/354,350）")
        panel._commanderDialog.close()


if __name__ == "__main__":
    unittest.main()
