"""
空库 / 缺表启动回归测试（#28）。

覆盖：
- 读取数据的异常被翻译成可区分的中文提示（缺表 / 缺列 / 库损坏 / 其它）；
- 四个图鉴面板在缺表时不再弹模态框，改为面板内提示，恢复后自动隐藏；
- 空库（只有资源统计相关表）构造 ``MainWindow`` 时全程没有模态弹窗，
  四个图鉴面板都给出「缺表」提示。
"""

import os
import shutil
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtWidgets import QApplication, QMessageBox  # noqa: E402

from utils.db_connection import DatabaseConnection  # noqa: E402
from utils.db_schema import ensureResourceStatisticsSchema  # noqa: E402
from utils.error_messages import describeDataLoadError  # noqa: E402
from utils.exceptions import DatabaseError  # noqa: E402
from views.widgets.awaken_panel import AwakenPanel  # noqa: E402
from views.widgets.codex_oath_panel import CodexOathPanel  # noqa: E402
from views.widgets.codex_unlock_panel import CodexUnlockPanel  # noqa: E402
from views.widgets.limit_break_panel import LimitBreakPanel  # noqa: E402

APP = QApplication.instance() or QApplication([])

# 与服务层实际抛出的文本保持一致（见 services/codex_unlock_service.py）
MISSING_CODEX_TABLE_TEXT = "查询未解锁舰娘列表失败: no such table: codex_group"


class _MissingTableUnlockService:
    """缺表桩：解锁面板读取时抛 DatabaseError。"""

    def getLockedShips(self):
        """模拟查询图鉴表失败。"""
        raise DatabaseError(MISSING_CODEX_TABLE_TEXT)


class _EmptyUnlockService:
    """正常桩：没有可解锁舰娘。"""

    def getLockedShips(self):
        """返回空列表。"""
        return []


class _MissingTableAwakenService:
    """缺表桩：觉醒面板读取时抛 DatabaseError。"""

    def getAwakenableShips(self):
        """模拟查询图鉴表失败。"""
        raise DatabaseError("查询可觉醒舰娘列表失败: no such table: codex_group")


class _MissingTableLimitBreakService:
    """缺表桩：突破面板读取时抛 DatabaseError。"""

    def getLimitBreakableShips(self):
        """模拟查询图鉴表失败。"""
        raise DatabaseError("查询可突破舰娘列表失败: no such table: codex_group")


class _MissingTableOathService:
    """缺表桩：誓约面板读取时抛 DatabaseError。"""

    def getOathableShips(self):
        """模拟查询图鉴表失败。"""
        raise DatabaseError("查询可誓约舰娘列表失败: no such table: codex_group")


class TestDescribeDataLoadError(unittest.TestCase):
    """异常文案：缺表 / 缺列 / 库损坏 / 其它四种场景可区分。"""

    def testMissingCodexTable(self):
        """缺图鉴表时提示初始化数据库，并点明表名。"""
        text = describeDataLoadError(DatabaseError(MISSING_CODEX_TABLE_TEXT))

        self.assertIn("codex_group", text)
        self.assertIn("缺失", text)
        self.assertIn("初始化数据库", text)
        self.assertNotIn("no such table", text)

    def testMissingOtherTable(self):
        """缺资源类表时同样提示缺表，但不套用图鉴口径。"""
        text = describeDataLoadError(DatabaseError("查询失败: no such table: resource_daily"))

        self.assertIn("resource_daily", text)
        self.assertIn("缺失", text)
        self.assertNotIn("图鉴", text)

    def testMissingColumn(self):
        """缺列时提示结构过旧、需要重启升级。"""
        text = describeDataLoadError(DatabaseError("查询失败: no such column: fleet_position"))

        self.assertIn("缺少列 fleet_position", text)
        self.assertIn("结构升级", text)

    def testCorruptDatabase(self):
        """库文件损坏与缺表区分开。"""
        text = describeDataLoadError(DatabaseError("查询失败: file is not a database"))

        self.assertIn("损坏", text)
        self.assertIn("备份", text)

    def testUnknownErrorKeepsOriginalMessage(self):
        """其它异常保留原始信息，便于排查。"""
        text = describeDataLoadError(DatabaseError("连接已关闭"))

        self.assertTrue(text.startswith("读取数据失败"))
        self.assertIn("连接已关闭", text)


class TestPanelNoticeInsteadOfModal(unittest.TestCase):
    """四个图鉴面板：缺表时就地提示、不弹模态框，恢复后自动隐藏。"""

    def _recordModal(self, *args, **kwargs):
        """记录被调用的模态框并返回确定值（避免测试阻塞）。"""
        self._modal_calls.append(args)
        return QMessageBox.Ok

    def setUp(self):
        """挂起模态框，准备记录容器。"""
        self._modal_calls = []
        self._patchCritical = patch.object(QMessageBox, "critical", self._recordModal)
        self._patchWarning = patch.object(QMessageBox, "warning", self._recordModal)
        self._patchCritical.start()
        self._patchWarning.start()

    def tearDown(self):
        """恢复模态框。"""
        self._patchCritical.stop()
        self._patchWarning.stop()

    def testUnlockPanelShowsNoticeAndRecovers(self):
        """缺表显示提示条；换成正常服务后提示条隐藏。"""
        panel = CodexUnlockPanel(unlock_service=_MissingTableUnlockService())
        try:
            self.assertEqual(self._modal_calls, [])
            self.assertTrue(panel._notice.hasError())
            self.assertIn("codex_group", panel._notice.text())

            panel._unlock_service = _EmptyUnlockService()
            panel.refreshData()

            self.assertFalse(panel._notice.hasError())
            self.assertEqual(panel._notice.text(), "")
        finally:
            panel.deleteLater()

    def testOtherCodexPanelsShowNotice(self):
        """觉醒 / 突破 / 誓约面板同样改为面板内提示。"""
        panels = [
            AwakenPanel(awaken_service=_MissingTableAwakenService()),
            LimitBreakPanel(limit_break_service=_MissingTableLimitBreakService()),
            CodexOathPanel(oath_service=_MissingTableOathService()),
        ]
        try:
            self.assertEqual(self._modal_calls, [])
            for panel in panels:
                self.assertTrue(panel._notice.hasError(), type(panel).__name__)
                self.assertIn("codex_group", panel._notice.text())
        finally:
            for panel in panels:
                panel.deleteLater()


class TestEmptyDatabaseStartup(unittest.TestCase):
    """空库（只有资源统计相关表）构造主窗口：不崩溃、不弹模态框。"""

    def setUp(self):
        """建立临时空库并只建资源统计相关表。"""
        self._temp_dir = tempfile.mkdtemp(prefix="azurlane_empty_startup_")
        self._db_path = os.path.join(self._temp_dir, "empty.db")
        self._original_path = DatabaseConnection.getDbPath()
        sqlite3.connect(self._db_path).close()
        DatabaseConnection.setDbPath(self._db_path)
        ensureResourceStatisticsSchema(self._db_path)
        self._modal_calls = []

    def tearDown(self):
        """恢复数据库路径并清理临时目录。"""
        DatabaseConnection.setDbPath(self._original_path)
        shutil.rmtree(self._temp_dir, ignore_errors=True)

    def _recordModal(self, *args, **kwargs):
        """记录模态框调用并返回确定值。"""
        self._modal_calls.append(args)
        return QMessageBox.Ok

    def testMainWindowWithoutCodexTables(self):
        """主窗口能建全 6 个页签，且图鉴面板给出缺表提示。"""
        from views.main_window import MainWindow

        window = None
        with patch.object(QMessageBox, "critical", self._recordModal), patch.object(
            QMessageBox, "warning", self._recordModal
        ), patch.object(QMessageBox, "question", self._recordModal), patch.object(
            QMessageBox, "information", self._recordModal
        ):
            window = MainWindow()
        try:
            self.assertEqual(self._modal_calls, [])
            self.assertEqual(window._tabWidget.count(), 6)

            ship_panel = window._shipManagementPanel
            figure_panels = (
                ship_panel._unlockPanel,
                ship_panel._awakenPanel,
                ship_panel._limitBreakPanel,
                ship_panel._oathPanel,
            )
            for panel in figure_panels:
                self.assertTrue(panel._notice.hasError(), type(panel).__name__)
                self.assertIn("缺失", panel._notice.text())
        finally:
            if window is not None:
                window.deleteLater()


if __name__ == "__main__":
    unittest.main()
