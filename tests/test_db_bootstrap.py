"""
首次使用数据库自动初始化测试（#8）。

覆盖：
- 没有数据库文件时自动建库、建全部业务表（资源 / 任务 / 活动 / 贸易 / 图鉴 / 指挥官）；
- 首次种子：类型字典、任务定义、等级经验基准、``user.json``；
- 幂等：重复启动不重复写种子、不覆盖已有数据与用户文件；
- 旧库缺图鉴 / 指挥官表时补齐，不影响既有数据；
- 模板可用：在新建库上直接「新增舰娘」成功，主窗口 6 个页签无缺表提示、无模态框。
"""

import json
import os
import shutil
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import main as main_module  # noqa: E402
from PyQt5.QtWidgets import QApplication, QMessageBox  # noqa: E402

from repositories.user_repository import UserRepository  # noqa: E402
from services.codex_ship_create_service import (  # noqa: E402
    CodexShipCreateService,
    ShipCreateDraft,
)
from utils import time_source  # noqa: E402
from utils.constants import BASE_DIR, DATA_DIR  # noqa: E402
from utils.db_bootstrap import DatabaseInitReport, ensureDatabaseReady  # noqa: E402
from utils.db_connection import DatabaseConnection  # noqa: E402
from utils.db_schema import ensureResourceStatisticsSchema  # noqa: E402
from utils.exceptions import DatabaseError  # noqa: E402

APP = QApplication.instance() or QApplication([])

LEVEL_EXP_CSV = os.path.join(BASE_DIR, "data", "commander_level.csv")

# 空白模板应建出的全部业务表（不含 sqlite_ 内部表）
EXPECTED_TABLES = {
    "resource_daily",
    "resource_transaction",
    "resource_category",
    "commander_level_exp",
    "commander_info",
    "cube_task",
    "cube_task_completion",
    "trade_license_purchase",
    "event_record",
    "codex_group",
    "codex_tp",
    "codex_buff",
    "awakening_of_mind",
}


def _tableNames(db_path):
    """读取数据库中的业务表名。"""
    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
            " AND name NOT LIKE 'sqlite_%'"
        ).fetchall()
        return {row[0] for row in rows}
    finally:
        conn.close()


def _scalar(db_path, sql, params=()):
    """执行单值查询。"""
    conn = sqlite3.connect(db_path)
    try:
        return conn.execute(sql, params).fetchone()[0]
    finally:
        conn.close()


def _columns(db_path, table):
    """读取表的列名集合。"""
    conn = sqlite3.connect(db_path)
    try:
        return {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
    finally:
        conn.close()


class TestFreshDatabaseBootstrap(unittest.TestCase):
    """无数据库文件：建库、建表、写种子、补 user.json。"""

    def setUp(self):
        """准备临时目录与尚未存在的库路径。"""
        self._temp_dir = tempfile.mkdtemp(prefix="azurlane_bootstrap_")
        self._db_path = os.path.join(self._temp_dir, "AzurLaneStatisticalOfficeDB.db")
        self._user_path = os.path.join(self._temp_dir, "user.json")

    def tearDown(self):
        """清理临时目录。"""
        shutil.rmtree(self._temp_dir, ignore_errors=True)

    def _bootstrap(self):
        """按默认 CSV、临时 user.json 执行一次初始化。"""
        return ensureDatabaseReady(
            self._db_path,
            level_exp_csv=LEVEL_EXP_CSV,
            user_file=self._user_path,
        )

    def testCreatesBlankTemplate(self):
        """首次运行建出 13 张业务表、索引/触发器与三类种子。"""
        report = self._bootstrap()

        self.assertTrue(report.database_created)
        self.assertTrue(os.path.exists(self._db_path))
        self.assertEqual(report.db_path, os.path.abspath(self._db_path))
        self.assertEqual(set(report.created_tables), EXPECTED_TABLES)
        self.assertEqual(report.table_count, len(EXPECTED_TABLES))
        self.assertEqual(_tableNames(self._db_path), EXPECTED_TABLES)

        # 图鉴表结构需与真实库一致（应用会写 fleet_position，并依赖 date_edit 触发器）
        self.assertIn("fleet_position", _columns(self._db_path, "codex_group"))
        self.assertIn("codex_id", _columns(self._db_path, "codex_tp"))
        self.assertIn("buff_unlock", _columns(self._db_path, "codex_buff"))

        conn = sqlite3.connect(self._db_path)
        try:
            trigger = conn.execute(
                "SELECT COUNT(*) FROM sqlite_master WHERE type = 'trigger'"
                " AND name = 'update_codex_group_modtime'"
            ).fetchone()[0]
            commander_index = conn.execute(
                "SELECT COUNT(*) FROM sqlite_master WHERE type = 'index'"
                " AND name = 'uq_commander_info_date'"
            ).fetchone()[0]
        finally:
            conn.close()
        self.assertEqual(trigger, 1)
        self.assertEqual(commander_index, 1)

        # 种子：类型字典 43 项、任务定义 24 项、等级经验 200 行
        self.assertEqual(_scalar(self._db_path, "SELECT COUNT(*) FROM resource_category"), 43)
        self.assertEqual(_scalar(self._db_path, "SELECT COUNT(*) FROM cube_task"), 24)
        self.assertEqual(_scalar(self._db_path, "SELECT COUNT(*) FROM commander_level_exp"), 200)
        self.assertEqual(report.level_exp_rows, 200)

        # 满级行：经验为 NULL，文本进 note（与迁移脚本口径一致）
        conn = sqlite3.connect(self._db_path)
        try:
            level_200 = conn.execute(
                "SELECT level_up_exp, cumulative_exp, note FROM commander_level_exp"
                " WHERE level = 200"
            ).fetchone()
            empty_tables = {
                table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                for table in ("codex_group", "codex_tp", "codex_buff", "commander_info")
            }
        finally:
            conn.close()
        self.assertEqual(level_200, (None, None, "当前版本最高等级"))
        self.assertEqual(
            empty_tables,
            {"codex_group": 0, "codex_tp": 0, "codex_buff": 0, "commander_info": 0},
        )

    def testCreatesDefaultUserFile(self):
        """缺失的 user.json 写入默认用户名与今日开始日期，且能被用户仓库读取。"""
        report = self._bootstrap()

        self.assertTrue(report.user_file_created)
        self.assertEqual(report.user_file_path, os.path.abspath(self._user_path))
        with open(self._user_path, "r", encoding="utf-8") as fp:
            content = json.load(fp)
        self.assertEqual(content["username"], "指挥官")
        self.assertEqual(content["start_date"], time_source.today().isoformat())

        user = UserRepository(self._user_path).loadUser()
        self.assertIsNotNone(user)
        self.assertEqual(user.username, "指挥官")
        self.assertEqual(user.getStartDateAsDate().date(), time_source.today())

    def testSecondRunIsIdempotent(self):
        """重复启动：不新建库、不重复建表、不重复写种子、不改 user.json。"""
        first = self._bootstrap()
        second = self._bootstrap()

        self.assertTrue(first.database_created)
        self.assertFalse(second.database_created)
        self.assertEqual(second.created_tables, ())
        self.assertEqual(second.level_exp_rows, 0)
        self.assertFalse(second.user_file_created)

        self.assertEqual(_scalar(self._db_path, "SELECT COUNT(*) FROM resource_category"), 43)
        self.assertEqual(_scalar(self._db_path, "SELECT COUNT(*) FROM cube_task"), 24)
        self.assertEqual(_scalar(self._db_path, "SELECT COUNT(*) FROM commander_level_exp"), 200)

    def testPreservesExistingDataAndUserFile(self):
        """已有库：已录入的舰娘、人工修正的等级经验、user.json 内容都不被覆盖。"""
        self._bootstrap()

        conn = sqlite3.connect(self._db_path)
        try:
            conn.execute(
                "INSERT INTO codex_group (codex_id, ship_name, ship_aid)"
                " VALUES ('1', '测试舰娘', '2026/01/01')"
            )
            conn.execute(
                "UPDATE commander_level_exp SET note = '人工修正' WHERE level = 1"
            )
            conn.commit()
        finally:
            conn.close()
        with open(self._user_path, "w", encoding="utf-8") as fp:
            json.dump({"username": "自定义", "start_date": "2020-01-01"}, fp)

        report = self._bootstrap()

        self.assertFalse(report.database_created)
        self.assertFalse(report.user_file_created)
        self.assertEqual(_scalar(self._db_path, "SELECT COUNT(*) FROM codex_group"), 1)
        self.assertEqual(
            _scalar(self._db_path, "SELECT note FROM commander_level_exp WHERE level = 1"),
            "人工修正",
        )
        with open(self._user_path, "r", encoding="utf-8") as fp:
            self.assertEqual(json.load(fp)["username"], "自定义")

    def testAddsCodexAndCommanderTablesToLegacyDatabase(self):
        """旧库只有资源类表：补建图鉴 4 表与指挥官快照表，既有字典不重复播种。"""
        sqlite3.connect(self._db_path).close()
        ensureResourceStatisticsSchema(self._db_path)
        before = _tableNames(self._db_path)

        report = self._bootstrap()

        self.assertFalse(report.database_created)
        self.assertEqual(
            set(report.created_tables),
            {"codex_group", "codex_tp", "codex_buff", "awakening_of_mind", "commander_info"},
        )
        self.assertEqual(_tableNames(self._db_path) - before, set(report.created_tables))
        self.assertEqual(_scalar(self._db_path, "SELECT COUNT(*) FROM resource_category"), 43)
        self.assertEqual(_scalar(self._db_path, "SELECT COUNT(*) FROM commander_level_exp"), 200)

    def testMissingLevelExpCsvStillBootstraps(self):
        """等级经验 CSV 缺失时跳过播种，其它表照常建出。"""
        report = ensureDatabaseReady(
            self._db_path,
            level_exp_csv=os.path.join(self._temp_dir, "not_exists.csv"),
            user_file=self._user_path,
        )

        self.assertTrue(report.database_created)
        self.assertEqual(report.level_exp_rows, 0)
        self.assertEqual(_scalar(self._db_path, "SELECT COUNT(*) FROM commander_level_exp"), 0)
        self.assertTrue(os.path.exists(self._user_path))

    def testInvalidLevelExpRowRaisesDatabaseError(self):
        """CSV 数据违反等级约束时抛 DatabaseError，不静默写入半截数据。"""
        csv_path = os.path.join(self._temp_dir, "bad_level_exp.csv")
        with open(csv_path, "w", encoding="utf-8") as fp:
            fp.write("等级,本次升级所需经验,与上一级所需经验差值,升级累计所需经验\n")
            fp.write("300,1,/,1\n")

        with self.assertRaises(DatabaseError) as ctx:
            ensureDatabaseReady(
                self._db_path, level_exp_csv=csv_path, user_file=self._user_path
            )

        self.assertIn("等级经验基准", str(ctx.exception))
        self.assertEqual(_scalar(self._db_path, "SELECT COUNT(*) FROM commander_level_exp"), 0)
        self.assertFalse(os.path.exists(self._user_path))

    def testCreatesMissingParentDirectory(self):
        """数据库所在子目录不存在时一并创建。"""
        db_path = os.path.join(self._temp_dir, "nested", "data", "new.db")

        report = ensureDatabaseReady(db_path, level_exp_csv=LEVEL_EXP_CSV)

        self.assertTrue(report.database_created)
        self.assertTrue(os.path.exists(db_path))
        self.assertTrue(os.path.exists(os.path.join(self._temp_dir, "nested", "data", "user.json")))

    def testDefaultUserFileFollowsDatabaseDirectory(self):
        """未指定 user_file 时写在数据库同目录（便携目录语义）。"""
        report = ensureDatabaseReady(self._db_path, level_exp_csv=LEVEL_EXP_CSV)

        self.assertEqual(
            report.user_file_path,
            os.path.join(os.path.dirname(os.path.abspath(self._db_path)), "user.json"),
        )
        self.assertTrue(os.path.exists(report.user_file_path))

    def testUsesConfiguredDatabasePath(self):
        """未传 db_path 时使用 DatabaseConnection 配置的路径。"""
        original = DatabaseConnection.getDbPath()
        DatabaseConnection.setDbPath(self._db_path)
        try:
            report = ensureDatabaseReady(
                level_exp_csv=LEVEL_EXP_CSV, user_file=self._user_path
            )
        finally:
            DatabaseConnection.setDbPath(original)

        self.assertEqual(report.db_path, os.path.abspath(self._db_path))
        self.assertTrue(report.database_created)


class TestTemplateIsUsable(unittest.TestCase):
    """新建模板可以直接承接业务写入。"""

    def setUp(self):
        """建立临时空白库并指向它。"""
        self._temp_dir = tempfile.mkdtemp(prefix="azurlane_bootstrap_use_")
        self._db_path = os.path.join(self._temp_dir, "template.db")
        ensureDatabaseReady(self._db_path, level_exp_csv=LEVEL_EXP_CSV)
        self._original_path = DatabaseConnection.getDbPath()
        DatabaseConnection.setDbPath(self._db_path)

    def tearDown(self):
        """恢复数据库路径并清理临时目录。"""
        DatabaseConnection.setDbPath(self._original_path)
        shutil.rmtree(self._temp_dir, ignore_errors=True)

    def testCanCreateShipOnTemplate(self):
        """在模板库上「新增舰娘」：图鉴 / 科技点 / 科技属性三表都能写入。"""
        draft = ShipCreateDraft(
            codex_id="1",
            ship_name="测试舰娘",
            ship_group="常规",
            ship_typ="战列巡洋舰",
            ship_rarity="UR",
            ship_star=3,
            ship_camp="重樱群岛",
            ship_aid="2026/08/08",
            tp_values={"解锁": "26", "满星": "52", "Lv.120": "39"},
            buff_text={"解锁": "战巡/战列/航战 耐久+1"},
        )

        result = CodexShipCreateService().createShip(draft)

        self.assertTrue(result.success)
        self.assertEqual(result.tp_count, 3)
        self.assertEqual(result.buff_count, 3)
        self.assertEqual(_scalar(self._db_path, "SELECT COUNT(*) FROM codex_group"), 1)
        self.assertEqual(_scalar(self._db_path, "SELECT COUNT(*) FROM codex_tp"), 3)
        self.assertEqual(_scalar(self._db_path, "SELECT COUNT(*) FROM codex_buff"), 3)
        self.assertEqual(
            _scalar(self._db_path, "SELECT ship_level FROM codex_group WHERE codex_id = '1'"),
            "未觉醒",
        )


class TestFirstRunUi(unittest.TestCase):
    """首次初始化后的界面表现。"""

    def setUp(self):
        """建立临时空白库、挂起模态框。"""
        self._temp_dir = tempfile.mkdtemp(prefix="azurlane_bootstrap_ui_")
        self._db_path = os.path.join(self._temp_dir, "ui.db")
        self._report = ensureDatabaseReady(self._db_path, level_exp_csv=LEVEL_EXP_CSV)
        self._original_path = DatabaseConnection.getDbPath()
        DatabaseConnection.setDbPath(self._db_path)
        self._modal_calls = []

    def tearDown(self):
        """恢复数据库路径并清理临时目录。"""
        DatabaseConnection.setDbPath(self._original_path)
        shutil.rmtree(self._temp_dir, ignore_errors=True)

    def _recordModal(self, *args, **kwargs):
        """记录模态框调用并返回确定值。"""
        self._modal_calls.append(args)
        return QMessageBox.Ok

    def testMainWindowOnFreshTemplateHasNoMissingTableNotice(self):
        """新建模板上主窗口 6 个页签正常，图鉴面板不再提示缺表。"""
        from views.main_window import MainWindow

        window = None
        with patch.object(QMessageBox, "critical", self._recordModal), patch.object(
            QMessageBox, "warning", self._recordModal
        ), patch.object(QMessageBox, "question", self._recordModal), patch.object(
            QMessageBox, "information", self._recordModal
        ):
            window = MainWindow()
            window.refreshData()
        try:
            self.assertEqual(self._modal_calls, [])
            self.assertEqual(window._tabWidget.count(), 6)

            ship_panel = window._shipManagementPanel
            for panel in (
                ship_panel._unlockPanel,
                ship_panel._awakenPanel,
                ship_panel._limitBreakPanel,
                ship_panel._oathPanel,
            ):
                self.assertFalse(panel._notice.hasError(), type(panel).__name__)
        finally:
            if window is not None:
                window.deleteLater()

    def testFirstRunNoticeMentionsCreatedPathAndEntry(self):
        """首次运行提示包含库路径、表数量与图鉴录入入口。"""
        report = DatabaseInitReport(
            db_path=r"C:\data\AzurLaneStatisticalOfficeDB.db",
            database_created=True,
            created_tables=tuple(sorted(EXPECTED_TABLES)),
            level_exp_rows=200,
            user_file_path=r"C:\data\user.json",
            user_file_created=True,
        )

        with patch.object(main_module.QMessageBox, "information") as info:
            main_module._showFirstRunNotice(None, report)

        args = info.call_args[0]
        self.assertEqual(args[1], "首次运行")
        self.assertIn(report.db_path, args[2])
        self.assertIn("13 张业务表", args[2])
        self.assertIn("200 条", args[2])
        self.assertIn("新增舰娘", args[2])


class TestUserFileLocation(unittest.TestCase):
    """自动生成的 user.json 必须落在应用实际读取的位置。"""

    def testDefaultUserFileIsUnderDataDir(self):
        """UserRepository 默认路径与初始化写入位置一致（打包后为 exe 同目录 data/）。"""
        self.assertEqual(
            os.path.abspath(UserRepository()._filePath),
            os.path.abspath(os.path.join(DATA_DIR, "user.json")),
        )


if __name__ == "__main__":
    unittest.main()
