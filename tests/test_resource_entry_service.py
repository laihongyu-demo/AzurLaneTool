"""
常规录入服务单元测试。

覆盖：可选类型过滤（排除任务看板覆盖的类型）、收入 / 支出记账、
日汇总与末次时刻维护、数量与时刻校验、历史汇总段拦截。
"""

import os
import shutil
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta

from services.resource_entry_service import MAX_ENTRY_AMOUNT, ResourceEntryService
from utils.constants import (
    RESOURCE_DETAIL_MODE_SUMMARY_ONLY,
    RESOURCE_DIRECTION_EXPENSE,
    RESOURCE_DIRECTION_INCOME,
    RESOURCE_TYPE_CUBE,
)
from utils.db_connection import DatabaseConnection
from utils.db_schema import ensureResourceStatisticsSchema
from utils.exceptions import ValidationError

FIXTURE_CATEGORIES = [
    (RESOURCE_TYPE_CUBE, RESOURCE_DIRECTION_EXPENSE, "活动建造", 2),
    (RESOURCE_TYPE_CUBE, RESOURCE_DIRECTION_EXPENSE, "特型建造", 3),
    (RESOURCE_TYPE_CUBE, RESOURCE_DIRECTION_INCOME, "军事委托", 9),
    (RESOURCE_TYPE_CUBE, RESOURCE_DIRECTION_INCOME, "礼包", 20),
    # 任务看板已覆盖，常规录入不应再列出
    (RESOURCE_TYPE_CUBE, RESOURCE_DIRECTION_INCOME, "日常任务", 14),
]


class _TempEntryDatabaseCase(unittest.TestCase):
    """带资源表结构与类型字典的临时库测试基类。"""

    def setUp(self):
        self._original_db_path = DatabaseConnection.getDbPath()
        self._temp_dir = tempfile.mkdtemp(prefix="azurlane_entry_")
        self._db_path = os.path.join(self._temp_dir, "entry.db")
        DatabaseConnection.setDbPath(self._db_path)
        ensureResourceStatisticsSchema(self._db_path)
        self._insertCategories()
        self._service = ResourceEntryService()

    def tearDown(self):
        DatabaseConnection.setDbPath(self._original_db_path)
        shutil.rmtree(self._temp_dir, ignore_errors=True)

    def _insertCategories(self) -> None:
        """写入类型字典。"""
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

    def _query(self, sql, params=()):
        """执行只读查询。"""
        conn = sqlite3.connect(self._db_path)
        try:
            return conn.execute(sql, params).fetchall()
        finally:
            conn.close()

    def _execute(self, sql, params=()) -> None:
        """执行写入。"""
        conn = sqlite3.connect(self._db_path)
        try:
            conn.execute(sql, params)
            conn.commit()
        finally:
            conn.close()

    def _moment(self) -> datetime:
        """当前时刻（到秒）。"""
        return datetime.now().replace(microsecond=0)


class TestCategories(_TempEntryDatabaseCase):
    """可选类型查询测试。"""

    def testExpenseListedBeforeIncome(self):
        """支出类型排在收入类型之前。"""
        options = self._service.getCategories()

        self.assertEqual(
            [option.name for option in options],
            ["活动建造", "特型建造", "军事委托", "礼包"],
        )
        self.assertEqual(options[0].direction, RESOURCE_DIRECTION_EXPENSE)
        self.assertEqual(options[2].direction, RESOURCE_DIRECTION_INCOME)

    def testTaskCoveredCategoryExcluded(self):
        """任务看板覆盖的类型不出现在常规录入。"""
        names = {option.name for option in self._service.getCategories()}

        self.assertNotIn("日常任务", names)
        self.assertIn("军事委托", names)


class TestRecord(_TempEntryDatabaseCase):
    """记账测试。"""

    def testExpenseWritesTransactionAndDaily(self):
        """支出记账写入明细并切换为明细日。"""
        moment = self._moment()
        result = self._service.record("活动建造", 30, moment)

        self.assertTrue(result.success)
        self.assertGreater(result.transaction_id, 0)
        self.assertIn("支出", result.toStatusBarMessage())

        rows = self._query(
            "SELECT direction, record_time, category, amount FROM resource_transaction"
        )
        self.assertEqual(len(rows), 1)
        direction, record_time, category, amount = rows[0]
        self.assertEqual(direction, RESOURCE_DIRECTION_EXPENSE)
        self.assertEqual(record_time, moment.strftime("%Y-%m-%d %H:%M:%S"))
        self.assertEqual(category, "活动建造")
        self.assertEqual(amount, 30)

        daily = self._query("SELECT detail_mode, last_record_time FROM resource_daily")
        self.assertEqual(len(daily), 1)
        self.assertEqual(daily[0][0], "detail")
        self.assertEqual(daily[0][1], moment.strftime("%Y-%m-%d %H:%M:%S"))

    def testIncomeRecordedWithIncomeDirection(self):
        """收入类型写入 income 方向。"""
        self._service.record("军事委托", 4, self._moment())

        rows = self._query("SELECT direction, amount FROM resource_transaction")
        self.assertEqual(rows[0], (RESOURCE_DIRECTION_INCOME, 4))

    def testBackdatedRecordKeepsLatestTime(self):
        """补录更早时刻不会把 last_record_time 改小。"""
        later = self._moment()
        earlier = later - timedelta(hours=2)
        self._service.record("礼包", 1, later)
        self._service.record("礼包", 1, earlier)

        rows = self._query("SELECT last_record_time FROM resource_daily")
        self.assertEqual(rows[0][0], later.strftime("%Y-%m-%d %H:%M:%S"))

    def testFutureMomentRejected(self):
        """未来时刻被拒绝。"""
        future = self._moment() + timedelta(minutes=5)

        with self.assertRaises(ValidationError):
            self._service.record("礼包", 1, future)

    def testNonPositiveAmountRejected(self):
        """数量必须为正。"""
        with self.assertRaises(ValidationError):
            self._service.record("礼包", 0, self._moment())

    def testOverLimitAmountRejected(self):
        """超过上限的数量被拒绝。"""
        with self.assertRaises(ValidationError):
            self._service.record("礼包", MAX_ENTRY_AMOUNT + 1, self._moment())

    def testUnknownCategoryRejected(self):
        """未知类型被拒绝。"""
        with self.assertRaises(ValidationError):
            self._service.record("不存在的类型", 1, self._moment())

    def testSummaryOnlyDayRejected(self):
        """历史汇总段（summary_only）不允许补录明细。"""
        summary_day = (datetime.now() - timedelta(days=400)).strftime("%Y-%m-%d")
        self._execute(
            "INSERT INTO resource_daily (resource_type, record_date, detail_mode, income, expense, note)"
            " VALUES (?, ?, ?, 10, 5, '历史汇总')",
            (RESOURCE_TYPE_CUBE, summary_day, RESOURCE_DETAIL_MODE_SUMMARY_ONLY),
        )
        target = datetime.strptime(summary_day + " 12:00:00", "%Y-%m-%d %H:%M:%S")

        with self.assertRaises(ValidationError) as context:
            self._service.record("礼包", 1, target)

        self.assertIn("历史汇总", str(context.exception))
        self.assertEqual(self._query("SELECT id FROM resource_transaction"), [])


if __name__ == "__main__":
    unittest.main()
