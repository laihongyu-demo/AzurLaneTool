"""
设置页（类型字典维护）单元测试。

覆盖：默认分组与列表渲染、资源 / 方向切换、新增 / 改名 / 上下移动 / 停用启用
的界面流程与信号、边界提示、与资源统计页常规录入下拉的联动。
"""

import os
import shutil
import sqlite3
import tempfile
import unittest
from datetime import datetime
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtWidgets import QApplication, QMessageBox  # noqa: E402

from services.cube_task_service import CubeTaskService  # noqa: E402
from services.resource_category_service import ResourceCategoryService  # noqa: E402
from services.resource_entry_service import ResourceEntryService  # noqa: E402
from utils.constants import (  # noqa: E402
    RESOURCE_DIRECTION_EXPENSE,
    RESOURCE_TYPE_CUBE,
)
from utils.db_connection import DatabaseConnection  # noqa: E402
from utils.db_schema import ensureResourceStatisticsSchema  # noqa: E402
from views.widgets.resource_management_panel import ResourceManagementPanel  # noqa: E402
from views.widgets.settings_panel import SettingsPanel  # noqa: E402

APP = QApplication.instance() or QApplication([])


class _TempSettingsCase(unittest.TestCase):
    """带临时库的设置页测试基类。"""

    def setUp(self):
        self._original_db_path = DatabaseConnection.getDbPath()
        self._temp_dir = tempfile.mkdtemp(prefix="azurlane_settings_")
        self._db_path = os.path.join(self._temp_dir, "settings.db")
        DatabaseConnection.setDbPath(self._db_path)
        ensureResourceStatisticsSchema(self._db_path)
        self._service = ResourceCategoryService()
        self._entry_service = ResourceEntryService()

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

    def _buildPanel(self) -> SettingsPanel:
        """构建设置页。"""
        panel = SettingsPanel(ResourceCategoryService())
        panel.refreshData()
        return panel

    def _labels(self, section) -> list:
        """当前列表的行文案。"""
        return [section._listWidget.item(row).text() for row in range(section._listWidget.count())]

    def _selectRowByName(self, section, name: str) -> None:
        """按类型名选中列表行。"""
        for row, entry in enumerate(section._entries):
            if entry.name == name:
                section._listWidget.setCurrentRow(row)
                return
        raise AssertionError(f"列表中没有类型：{name}")

    def _record(self, category: str, amount: int = 1) -> None:
        """记一笔魔方支出明细。"""
        self._entry_service.record(
            category, RESOURCE_DIRECTION_EXPENSE, amount, datetime.now().replace(microsecond=0)
        )


class TestCategoryListRendering(_TempSettingsCase):
    """列表与筛选测试。"""

    def testDefaultFilterShowsCubeExpense(self):
        """默认展示魔方支出，顺序与种子一致。"""
        panel = self._buildPanel()
        section = panel._categorySection

        self.assertEqual(section._resourceCombo.currentData(), RESOURCE_TYPE_CUBE)
        self.assertEqual(section._directionCombo.currentData(), RESOURCE_DIRECTION_EXPENSE)
        labels = self._labels(section)
        self.assertEqual(len(labels), 7)
        self.assertTrue(labels[0].startswith("1. 轻型建造"))
        self.assertTrue(labels[-1].startswith("7. 军部研究"))
        self.assertIn("0 笔明细", labels[0])

    def testNoSelectionDisablesActions(self):
        """未选中行时改名 / 排序 / 停用不可用，新增始终可用。"""
        panel = self._buildPanel()
        section = panel._categorySection

        self.assertTrue(section._createBtn.isEnabled())
        self.assertFalse(section._renameBtn.isEnabled())
        self.assertFalse(section._upBtn.isEnabled())
        self.assertFalse(section._downBtn.isEnabled())
        self.assertFalse(section._toggleBtn.isEnabled())

    def testEdgeRowsDisableMove(self):
        """首行不能上移、末行不能下移。"""
        panel = self._buildPanel()
        section = panel._categorySection

        section._listWidget.setCurrentRow(0)
        self.assertFalse(section._upBtn.isEnabled())
        self.assertTrue(section._downBtn.isEnabled())

        section._listWidget.setCurrentRow(section._listWidget.count() - 1)
        self.assertTrue(section._upBtn.isEnabled())
        self.assertFalse(section._downBtn.isEnabled())

    def testSwitchToRedGemLoadsItsOwnDictionary(self):
        """资源切换后加载红尖尖自己的字典，且清空旧选中项。"""
        panel = self._buildPanel()
        section = panel._categorySection
        section._listWidget.setCurrentRow(0)

        section._resourceCombo.setCurrentIndex(1)

        labels = self._labels(section)
        self.assertEqual(len(labels), 9)
        self.assertTrue(labels[0].startswith("1. 皮肤"))
        self.assertIsNone(section._selectedEntry())

    def testUsageCountShownInList(self):
        """列表行展示关联明细笔数。"""
        self._record("活动建造", amount=30)
        self._record("活动建造", amount=5)
        panel = self._buildPanel()
        section = panel._categorySection

        labels = self._labels(section)
        row = next(label for label in labels if "活动建造" in label)
        self.assertIn("2 笔明细", row)

    def testActivationReloadsFromDatabase(self):
        """页签再次激活时读取库内最新状态。"""
        panel = self._buildPanel()
        section = panel._categorySection
        self.assertNotIn("活动复刻", " ".join(self._labels(section)))

        ResourceCategoryService().createCategory(
            RESOURCE_TYPE_CUBE, RESOURCE_DIRECTION_EXPENSE, "活动复刻"
        )
        panel.onActivated()

        self.assertIn("活动复刻", " ".join(self._labels(section)))


class TestCategoryActions(_TempSettingsCase):
    """新增 / 改名 / 排序 / 停用的界面流程。"""

    def testCreateThroughDialog(self):
        """新增成功后写库、刷新列表、选中新行并发出信号。"""
        panel = self._buildPanel()
        section = panel._categorySection
        changed = []
        results = []
        panel.categoriesChanged.connect(lambda: changed.append(True))
        panel.resultReady.connect(results.append)

        with patch(
            "views.widgets.settings_panel.QInputDialog.getText",
            return_value=("活动复刻", True),
        ):
            section._createBtn.click()

        rows = self._query(
            "SELECT name, sort_order FROM resource_category"
            " WHERE resource_type = 'cube' AND direction = 'expense' ORDER BY sort_order"
        )
        self.assertEqual(rows[-1][0], "活动复刻")
        self.assertGreater(rows[-1][1], rows[-2][1])
        self.assertIn("活动复刻", " ".join(self._labels(section)))
        self.assertEqual(section._selectedEntry().name, "活动复刻")
        self.assertEqual(changed, [True])
        self.assertIn("已新增", results[-1].toStatusBarMessage())

    def testCreateCancelledWritesNothing(self):
        """取消弹窗不写库、不发信号。"""
        panel = self._buildPanel()
        section = panel._categorySection
        changed = []
        panel.categoriesChanged.connect(lambda: changed.append(True))

        with patch(
            "views.widgets.settings_panel.QInputDialog.getText", return_value=("", False)
        ):
            section._createBtn.click()

        self.assertEqual(self._query("SELECT COUNT(*) FROM resource_category")[0][0], 41)
        self.assertEqual(changed, [])

    def testCreateDuplicateShowsWarning(self):
        """重名时弹警告，不写库。"""
        panel = self._buildPanel()
        section = panel._categorySection

        with patch(
            "views.widgets.settings_panel.QInputDialog.getText",
            return_value=("活动建造", True),
        ), patch("views.widgets.settings_panel.QMessageBox.warning") as warning:
            section._createBtn.click()

        warning.assert_called_once()
        self.assertIn("已存在", warning.call_args[0][2])
        self.assertEqual(self._query("SELECT COUNT(*) FROM resource_category")[0][0], 41)

    def testRenameThroughDialogSyncsTransactions(self):
        """改名弹窗预填原名，成功后同步明细并刷新列表。"""
        self._record("活动建造", amount=30)
        panel = self._buildPanel()
        section = panel._categorySection
        changed = []
        panel.categoriesChanged.connect(lambda: changed.append(True))
        self._selectRowByName(section, "活动建造")

        with patch(
            "views.widgets.settings_panel.QInputDialog.getText",
            return_value=("活动建造复刻", True),
        ) as get_text:
            section._renameBtn.click()

        self.assertEqual(get_text.call_args.kwargs.get("text"), "活动建造")
        self.assertEqual(
            self._query("SELECT category FROM resource_transaction"), [("活动建造复刻",)]
        )
        self.assertIn("活动建造复刻", " ".join(self._labels(section)))
        self.assertEqual(section._selectedEntry().name, "活动建造复刻")
        self.assertEqual(changed, [True])

    def testMoveUpKeepsSelectionAndNotifies(self):
        """上移后列表顺序变化、选中项跟随、发出联动信号。"""
        panel = self._buildPanel()
        section = panel._categorySection
        changed = []
        panel.categoriesChanged.connect(lambda: changed.append(True))
        self._selectRowByName(section, "重型建造")

        section._upBtn.click()

        labels = self._labels(section)
        self.assertTrue(labels[0].startswith("1. 重型建造"))
        self.assertTrue(labels[1].startswith("2. 轻型建造"))
        self.assertEqual(section._selectedEntry().name, "重型建造")
        self.assertEqual(changed, [True])

    def testMoveAtTopOnlyReportsMessage(self):
        """在首位仍触发上移（如按钮状态滞后）时只提示，不写库、不联动。"""
        panel = self._buildPanel()
        section = panel._categorySection
        changed = []
        results = []
        panel.categoriesChanged.connect(lambda: changed.append(True))
        panel.resultReady.connect(results.append)
        self._selectRowByName(section, "轻型建造")

        section._onMoveUpClicked()

        self.assertEqual(changed, [])
        self.assertFalse(results[-1].success)
        self.assertIn("已经是最前", results[-1].toStatusBarMessage())
        self.assertTrue(self._labels(section)[0].startswith("1. 轻型建造"))

    def testRetireWithConfirmation(self):
        """停用需确认，成功后下拉配置联动、按钮切到「启用」。"""
        self._record("活动建造", amount=30)
        panel = self._buildPanel()
        section = panel._categorySection
        changed = []
        panel.categoriesChanged.connect(lambda: changed.append(True))
        self._selectRowByName(section, "活动建造")

        with patch(
            "views.widgets.settings_panel.QMessageBox.question",
            return_value=QMessageBox.Yes,
        ) as question:
            section._toggleBtn.click()

        self.assertIn("1 笔历史明细", question.call_args[0][2])
        self.assertEqual(
            self._query(
                "SELECT is_active FROM resource_category"
                " WHERE resource_type = 'cube' AND direction = 'expense' AND name = '活动建造'"
            ),
            [(0,)],
        )
        self.assertIn("（已停用）", " ".join(self._labels(section)))
        self.assertEqual(section._toggleBtn.text(), "启用")
        self.assertEqual(changed, [True])

    def testRetireCancelledKeepsActive(self):
        """取消确认不改库。"""
        panel = self._buildPanel()
        section = panel._categorySection
        self._selectRowByName(section, "活动建造")

        with patch(
            "views.widgets.settings_panel.QMessageBox.question",
            return_value=QMessageBox.No,
        ):
            section._toggleBtn.click()

        self.assertEqual(
            self._query(
                "SELECT is_active FROM resource_category"
                " WHERE resource_type = 'cube' AND direction = 'expense' AND name = '活动建造'"
            ),
            [(1,)],
        )

    def testRetireLastActiveWarns(self):
        """停用最后一个启用类型时给出警告，库内状态不变。"""
        service = ResourceCategoryService()
        entries = service.listCategories(RESOURCE_TYPE_CUBE, RESOURCE_DIRECTION_EXPENSE)
        for entry in entries[:-1]:
            service.setCategoryActive(entry.id, False)
        panel = self._buildPanel()
        section = panel._categorySection
        self._selectRowByName(section, entries[-1].name)

        with patch(
            "views.widgets.settings_panel.QMessageBox.question",
            return_value=QMessageBox.Yes,
        ), patch("views.widgets.settings_panel.QMessageBox.warning") as warning:
            section._toggleBtn.click()

        warning.assert_called_once()
        self.assertIn("至少保留一个", warning.call_args[0][2])
        self.assertEqual(
            self._query(
                "SELECT is_active FROM resource_category"
                " WHERE resource_type = 'cube' AND direction = 'expense' AND name = ?",
                (entries[-1].name,),
            ),
            [(1,)],
        )

    def testEnableInactiveItem(self):
        """停用项可从维护列表重新启用。"""
        service = ResourceCategoryService()
        target = next(
            entry for entry in service.listCategories(
                RESOURCE_TYPE_CUBE, RESOURCE_DIRECTION_EXPENSE
            )
            if entry.name == "活动建造"
        )
        service.setCategoryActive(target.id, False)
        panel = self._buildPanel()
        section = panel._categorySection
        self._selectRowByName(section, "活动建造")
        self.assertEqual(section._toggleBtn.text(), "启用")

        section._toggleBtn.click()

        self.assertNotIn("（已停用）", " ".join(self._labels(section)))
        self.assertEqual(section._toggleBtn.text(), "停用")


class TestSettingsPanelRelay(_TempSettingsCase):
    """设置页与资源统计页的联动。"""

    def testCategoryChangeRefreshesEntryDropdowns(self):
        """类型字典变化后，两个常规录入面板的下拉同步刷新。"""
        resource_panel = ResourceManagementPanel(CubeTaskService())
        panel = self._buildPanel()
        panel.categoriesChanged.connect(resource_panel.refreshEntryCategories)
        section = panel._categorySection

        with patch(
            "views.widgets.settings_panel.QInputDialog.getText",
            return_value=("活动复刻", True),
        ):
            section._createBtn.click()

        cube_combo = resource_panel._taskBoardPanel._entry_panel._typeCombo
        cube_labels = [cube_combo.itemText(index) for index in range(cube_combo.count())]
        red_combo = resource_panel._redGemEntryPanel._typeCombo
        red_labels = [red_combo.itemText(index) for index in range(red_combo.count())]

        self.assertIn("支出 · 活动复刻", cube_labels)
        self.assertNotIn("支出 · 活动复刻", red_labels)


if __name__ == "__main__":
    unittest.main()
