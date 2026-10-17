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
from PyQt5.QtWidgets import QApplication  # noqa: E402

from services.resource_entry_service import ResourceEntryService  # noqa: E402
from utils.constants import (  # noqa: E402
    RESOURCE_DIRECTION_EXPENSE,
    RESOURCE_DIRECTION_INCOME,
    RESOURCE_TYPE_CUBE,
)
from utils.db_connection import DatabaseConnection  # noqa: E402
from utils.db_schema import ensureResourceStatisticsSchema  # noqa: E402
from views.widgets.regular_entry_panel import RegularEntryPanel  # noqa: E402

APP = QApplication.instance() or QApplication([])

FIXTURE_CATEGORIES = [
    (RESOURCE_TYPE_CUBE, RESOURCE_DIRECTION_EXPENSE, "活动建造", 2),
    (RESOURCE_TYPE_CUBE, RESOURCE_DIRECTION_INCOME, "军事委托", 9),
    (RESOURCE_TYPE_CUBE, RESOURCE_DIRECTION_INCOME, "日常任务", 14),
]


class TestRegularEntryPanel(unittest.TestCase):
    """常规录入面板测试。"""

    def setUp(self):
        self._original_db_path = DatabaseConnection.getDbPath()
        self._temp_dir = tempfile.mkdtemp(prefix="azurlane_entry_panel_")
        self._db_path = os.path.join(self._temp_dir, "entry.db")
        DatabaseConnection.setDbPath(self._db_path)
        ensureResourceStatisticsSchema(self._db_path)

        conn = sqlite3.connect(self._db_path)
        try:
            conn.executemany(
                "INSERT INTO resource_category (resource_type, direction, name, sort_order)"
                " VALUES (?, ?, ?, ?)",
                FIXTURE_CATEGORIES,
            )
            conn.commit()
        finally:
            conn.close()

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

    def testComboExcludesTaskCoveredTypes(self):
        """下拉框排除任务看板覆盖的类型，并带方向前缀。"""
        panel = self._buildPanel()

        labels = [panel._typeCombo.itemText(i) for i in range(panel._typeCombo.count())]
        self.assertEqual(labels, ["支出 · 活动建造", "收入 · 军事委托"])
        self.assertEqual(panel._typeCombo.currentData(), "活动建造")

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
        self.assertEqual(rows[0][1], "活动建造")
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


if __name__ == "__main__":
    unittest.main()
