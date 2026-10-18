"""
常规录入面板单元测试。

覆盖：类型下拉的加载与过滤、点击「记录」写入明细与信号、时刻默认值。
"""

import os
import shutil
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtCore import QDateTime  # noqa: E402
from PyQt5.QtWidgets import QApplication, QMessageBox  # noqa: E402

from services.resource_entry_service import ResourceEntryService  # noqa: E402
from utils.constants import (  # noqa: E402
    RESOURCE_DIRECTION_EXPENSE,
    RESOURCE_DIRECTION_INCOME,
    RESOURCE_TYPE_CUBE,
    RESOURCE_TYPE_RED_GEM,
)
from utils.db_connection import DatabaseConnection  # noqa: E402
from utils.db_schema import ensureResourceStatisticsSchema  # noqa: E402
from views.widgets.regular_entry_panel import RegularEntryPanel  # noqa: E402

APP = QApplication.instance() or QApplication([])

CUBE_EXPENSE_ORDER = ["轻型建造", "重型建造", "特型建造", "活动建造", "祈愿建造", "开发船坞", "军部研究"]


class TestRegularEntryPanel(unittest.TestCase):
    """常规录入面板测试。"""

    def setUp(self):
        self._original_db_path = DatabaseConnection.getDbPath()
        self._temp_dir = tempfile.mkdtemp(prefix="azurlane_entry_panel_")
        self._db_path = os.path.join(self._temp_dir, "entry.db")
        DatabaseConnection.setDbPath(self._db_path)
        # 类型字典由 sql/SeedResourceCategories.sql 在启动时写入
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

    def _buildPanel(self) -> RegularEntryPanel:
        """构建面板实例。"""
        return RegularEntryPanel(ResourceEntryService())

    def testComboFollowsUsageOrder(self):
        """下拉框按使用习惯排序，且排除任务看板覆盖的类型。"""
        panel = self._buildPanel()

        labels = [panel._typeCombo.itemText(i) for i in range(panel._typeCombo.count())]
        self.assertEqual(labels[0], "支出 · 轻型建造")
        self.assertEqual(labels[:3], ["支出 · 轻型建造", "支出 · 重型建造", "支出 · 特型建造"])
        self.assertEqual(labels[7], "收入 · 军事委托")
        self.assertNotIn("收入 · 日常任务", labels)
        self.assertEqual(labels[-1], "收入 · 未知")

        current = panel._typeCombo.currentData()
        self.assertEqual(current.name, "轻型建造")
        self.assertEqual(current.direction, RESOURCE_DIRECTION_EXPENSE)

    def testAmountDefaultsToOne(self):
        """数量默认 1，时刻默认当前时间。"""
        panel = self._buildPanel()

        self.assertEqual(panel._amountSpin.value(), 1)
        self.assertLessEqual(
            abs((panel._timeEdit.dateTime().toPyDateTime() - datetime.now()).total_seconds()),
            5,
        )

    def testRecordWritesTransactionAndEmitsSignals(self):
        """点击记录后写入明细并触发刷新与结果信号。"""
        panel = self._buildPanel()
        recorded = []
        refreshed = []
        panel.entryRecorded.connect(recorded.append)
        panel.dataRefreshed.connect(lambda: refreshed.append(True))

        panel._typeCombo.setCurrentIndex(0)
        panel._amountSpin.setValue(30)
        moment = datetime.now().replace(microsecond=0) - timedelta(minutes=3)
        panel._timeEdit.setDateTime(QDateTime(moment))

        panel._recordBtn.click()

        rows = self._query("SELECT direction, category, amount, record_time FROM resource_transaction")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][0], RESOURCE_DIRECTION_EXPENSE)
        self.assertEqual(rows[0][1], CUBE_EXPENSE_ORDER[0])
        self.assertEqual(rows[0][2], 30)
        self.assertEqual(rows[0][3], moment.strftime("%Y-%m-%d %H:%M:%S"))

        self.assertEqual(len(recorded), 1)
        self.assertTrue(recorded[0].success)
        self.assertEqual(refreshed, [True])

    def testTimeLimitBlocksFuture(self):
        """时刻控件的上限不晚于当前时间。"""
        panel = self._buildPanel()

        self.assertLessEqual(
            panel._timeEdit.maximumDateTime().toPyDateTime(),
            datetime.now() + timedelta(seconds=2),
        )

    def testRedGemPanelUsesRedGemCategories(self):
        """红尖尖表单使用自己的类型字典，同名两向分别列出。"""
        panel = RegularEntryPanel(ResourceEntryService(), resource_type=RESOURCE_TYPE_RED_GEM)

        labels = [panel._typeCombo.itemText(i) for i in range(panel._typeCombo.count())]
        self.assertEqual(labels[0], "支出 · 皮肤")
        self.assertIn("支出 · 礼包", labels)
        self.assertIn("收入 · 礼包", labels)
        self.assertEqual(labels[-1], "收入 · 充值")
        self.assertEqual(len(labels), 18)

    def testUndoDisabledWithoutEntries(self):
        """没有录入时撤销按钮不可用。"""
        panel = self._buildPanel()

        self.assertFalse(panel._undoBtn.isEnabled())

    def testUndoRemovesLastEntry(self):
        """录入后撤销按钮可用，点击后删除该笔明细并恢复禁用。"""
        panel = self._buildPanel()
        panel._typeCombo.setCurrentIndex(0)
        panel._amountSpin.setValue(7)
        panel._timeEdit.setDateTime(QDateTime(datetime.now() - timedelta(minutes=1)))
        panel._recordBtn.click()
        self.assertTrue(panel._undoBtn.isEnabled())

        recorded = []
        panel.entryRecorded.connect(recorded.append)
        original = QMessageBox.question
        QMessageBox.question = staticmethod(lambda *args, **kwargs: QMessageBox.Yes)
        try:
            panel._undoBtn.click()
        finally:
            QMessageBox.question = original

        self.assertEqual(self._query("SELECT id FROM resource_transaction"), [])
        self.assertFalse(panel._undoBtn.isEnabled())
        self.assertIn("已撤销", recorded[-1].toStatusBarMessage())


if __name__ == "__main__":
    unittest.main()
