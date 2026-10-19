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
    RESOURCE_TYPE_RED_GEM,
)
from utils.db_connection import DatabaseConnection
from utils.db_schema import ensureResourceStatisticsSchema
from utils.exceptions import ValidationError

# 类型字典由 sql/SeedResourceCategories.sql 在启动时写入，这里只校验顺序


class _TempEntryDatabaseCase(unittest.TestCase):
    """带资源表结构与类型字典的临时库测试基类。"""

    def setUp(self):
        self._original_db_path = DatabaseConnection.getDbPath()
        self._temp_dir = tempfile.mkdtemp(prefix="azurlane_entry_")
        self._db_path = os.path.join(self._temp_dir, "entry.db")
        DatabaseConnection.setDbPath(self._db_path)
        ensureResourceStatisticsSchema(self._db_path)
        self._service = ResourceEntryService()

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

    def testCubeExpenseOrderFollowsUsage(self):
        """魔方支出按使用习惯排序。"""
        options = [
            option.name for option in self._service.getCategories(RESOURCE_TYPE_CUBE)
            if option.direction == RESOURCE_DIRECTION_EXPENSE
        ]

        self.assertEqual(
            options,
            ["轻型建造", "重型建造", "特型建造", "活动建造", "祈愿建造", "开发船坞", "军部研究"],
        )

    def testCubeIncomeOrderFollowsUsage(self):
        """魔方收入按使用习惯排序，任务看板覆盖的类型排在最后之前就被排除。"""
        options = [
            option.name for option in self._service.getCategories(RESOURCE_TYPE_CUBE)
            if option.direction == RESOURCE_DIRECTION_INCOME
        ]

        self.assertEqual(options[:6], ["军事委托", "活动签到", "活动任务", "活动商店", "贸易许可证", "节日奖励"])
        self.assertEqual(options[-3:], ["直购", "补给商店", "未知"])
        self.assertNotIn("日常任务", options)

    def testRedGemOrderFollowsUsage(self):
        """红尖尖收入 / 支出各自按使用习惯排序。"""
        options = self._service.getCategories(RESOURCE_TYPE_RED_GEM)
        income = [o.name for o in options if o.direction == RESOURCE_DIRECTION_INCOME]
        expense = [o.name for o in options if o.direction == RESOURCE_DIRECTION_EXPENSE]

        self.assertEqual(
            income,
            ["军事委托", "礼包", "月卡", "活动任务", "维护奖励", "节日奖励", "岛屿计划", "主线任务", "充值"],
        )
        self.assertEqual(
            expense,
            ["皮肤", "礼包", "石油", "船坞", "戒指", "心智", "密语", "星彩奖", "物资"],
        )

    def testTaskCoveredCategoryExcluded(self):
        """任务看板覆盖的类型不出现在常规录入。"""
        names = {option.name for option in self._service.getCategories()}

        self.assertNotIn("日常任务", names)
        self.assertNotIn("每月签到", names)
        self.assertIn("军事委托", names)

    def testInactiveCategoryExcluded(self):
        """停用的类型不出现在常规录入下拉（#21）。"""
        self._execute(
            "UPDATE resource_category SET is_active = 0"
            " WHERE resource_type = ? AND direction = ? AND name = ?",
            (RESOURCE_TYPE_CUBE, RESOURCE_DIRECTION_EXPENSE, "活动建造"),
        )

        names = {
            option.name for option in self._service.getCategories(RESOURCE_TYPE_CUBE)
            if option.direction == RESOURCE_DIRECTION_EXPENSE
        }

        self.assertNotIn("活动建造", names)
        self.assertIn("轻型建造", names)


class TestRecord(_TempEntryDatabaseCase):
    """记账测试。"""

    def testExpenseWritesTransactionAndDaily(self):
        """支出记账写入明细并切换为明细日。"""
        moment = self._moment()
        result = self._service.record("活动建造", RESOURCE_DIRECTION_EXPENSE, 30, moment)

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
        self._service.record("军事委托", RESOURCE_DIRECTION_INCOME, 4, self._moment())

        rows = self._query("SELECT direction, amount FROM resource_transaction")
        self.assertEqual(rows[0], (RESOURCE_DIRECTION_INCOME, 4))

    def testBackdatedRecordKeepsLatestTime(self):
        """补录更早时刻不会把 last_record_time 改小。"""
        later = self._moment()
        earlier = later - timedelta(hours=2)
        self._service.record("礼包", RESOURCE_DIRECTION_INCOME, 1, later)
        self._service.record("礼包", RESOURCE_DIRECTION_INCOME, 1, earlier)

        rows = self._query("SELECT last_record_time FROM resource_daily")
        self.assertEqual(rows[0][0], later.strftime("%Y-%m-%d %H:%M:%S"))

    def testFutureMomentRejected(self):
        """未来时刻被拒绝。"""
        future = self._moment() + timedelta(minutes=5)

        with self.assertRaises(ValidationError):
            self._service.record("礼包", RESOURCE_DIRECTION_INCOME, 1, future)

    def testNonPositiveAmountRejected(self):
        """数量必须为正。"""
        with self.assertRaises(ValidationError):
            self._service.record("礼包", RESOURCE_DIRECTION_INCOME, 0, self._moment())

    def testOverLimitAmountRejected(self):
        """超过上限的数量被拒绝。"""
        with self.assertRaises(ValidationError):
            self._service.record(
                "礼包", RESOURCE_DIRECTION_INCOME, MAX_ENTRY_AMOUNT + 1, self._moment()
            )

    def testUnknownCategoryRejected(self):
        """未知类型被拒绝。"""
        with self.assertRaises(ValidationError):
            self._service.record("不存在的类型", RESOURCE_DIRECTION_INCOME, 1, self._moment())

    def testInactiveCategoryRejected(self):
        """停用类型即使用旧界面传入也不能记账（#21）。"""
        self._execute(
            "UPDATE resource_category SET is_active = 0"
            " WHERE resource_type = ? AND direction = ? AND name = ?",
            (RESOURCE_TYPE_CUBE, RESOURCE_DIRECTION_EXPENSE, "活动建造"),
        )

        with self.assertRaises(ValidationError):
            self._service.record("活动建造", RESOURCE_DIRECTION_EXPENSE, 1, self._moment())
        self.assertEqual(self._query("SELECT id FROM resource_transaction"), [])

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
            self._service.record("礼包", RESOURCE_DIRECTION_INCOME, 1, target)

        self.assertIn("历史汇总", str(context.exception))
        self.assertEqual(self._query("SELECT id FROM resource_transaction"), [])

    def testDuplicateCategoryResolvedByDirection(self):
        """红尖尖「礼包」同名两向，按传入方向落库。"""
        self._service.record("礼包", RESOURCE_DIRECTION_INCOME, 3, self._moment(), RESOURCE_TYPE_RED_GEM)

        rows = self._query(
            "SELECT direction, amount FROM resource_transaction WHERE resource_type = ?",
            (RESOURCE_TYPE_RED_GEM,),
        )
        self.assertEqual(rows, [(RESOURCE_DIRECTION_INCOME, 3)])

    def testWrongDirectionRejected(self):
        """方向与类型不匹配时被拒绝。"""
        with self.assertRaises(ValidationError):
            self._service.record(
                "月卡", RESOURCE_DIRECTION_EXPENSE, 1, self._moment(), RESOURCE_TYPE_RED_GEM
            )


class TestUndo(_TempEntryDatabaseCase):
    """撤销最近一笔常规录入的测试。"""

    def testUndoRemovesTransactionAndEmptyDaily(self):
        """撤销后明细与当日空汇总行一起清掉。"""
        moment = self._moment()
        self._service.record("活动建造", RESOURCE_DIRECTION_EXPENSE, 30, moment)

        result = self._service.undoLast()

        self.assertTrue(result.success)
        self.assertIn("已撤销", result.toStatusBarMessage())
        self.assertEqual(self._query("SELECT id FROM resource_transaction"), [])
        self.assertEqual(self._query("SELECT id FROM resource_daily"), [])
        self.assertIsNone(self._service.getUndoableEntry())

    def testUndoKeepsDailyWhenOtherEntriesRemain(self):
        """同一天还有其它明细时保留汇总行并重算末次时刻。"""
        later = self._moment()
        earlier = later - timedelta(hours=3)
        self._service.record("活动建造", RESOURCE_DIRECTION_EXPENSE, 30, earlier)
        self._service.record("礼包", RESOURCE_DIRECTION_INCOME, 2, later)

        self._service.undoLast()

        rows = self._query("SELECT record_time, category FROM resource_transaction")
        self.assertEqual(rows, [(earlier.strftime("%Y-%m-%d %H:%M:%S"), "活动建造")])
        daily = self._query("SELECT last_record_time FROM resource_daily")
        self.assertEqual(daily[0][0], earlier.strftime("%Y-%m-%d %H:%M:%S"))

    def testUndoSkipsTaskLinkedTransactions(self):
        """任务看板写入的明细不会被撤销按钮删掉。"""
        moment = self._moment()
        task_time = (moment - timedelta(minutes=5)).strftime("%Y-%m-%d %H:%M:%S")
        self._execute(
            "INSERT INTO resource_transaction (resource_type, direction, record_time, category, amount, note)"
            " VALUES (?, 'income', ?, '日常任务', 2, '任务')",
            (RESOURCE_TYPE_CUBE, task_time),
        )
        task_tx_id = self._query("SELECT id FROM resource_transaction")[0][0]
        self._execute(
            "INSERT INTO cube_task_completion (task_code, period_key, completed_at, transaction_id)"
            " VALUES ('daily_battle_win', ?, ?, ?)",
            (task_time[:10], task_time, task_tx_id),
        )

        self._service.record("活动建造", RESOURCE_DIRECTION_EXPENSE, 30, moment)
        self._service.undoLast()

        rows = self._query("SELECT id, category FROM resource_transaction")
        self.assertEqual(rows, [(task_tx_id, "日常任务")])

    def testUndoWithoutEntryRejected(self):
        """没有常规录入时提示无可撤销。"""
        with self.assertRaises(ValidationError) as context:
            self._service.undoLast()

        self.assertIn("没有可撤销", str(context.exception))

    def testUndoIsPerResource(self):
        """撤销只作用于指定资源。"""
        moment = self._moment()
        self._service.record("活动建造", RESOURCE_DIRECTION_EXPENSE, 30, moment)
        self._service.record("月卡", RESOURCE_DIRECTION_INCOME, 5, moment, RESOURCE_TYPE_RED_GEM)

        self._service.undoLast(RESOURCE_TYPE_RED_GEM)

        cube_rows = self._query(
            "SELECT category FROM resource_transaction WHERE resource_type = ?",
            (RESOURCE_TYPE_CUBE,),
        )
        red_rows = self._query(
            "SELECT category FROM resource_transaction WHERE resource_type = ?",
            (RESOURCE_TYPE_RED_GEM,),
        )
        self.assertEqual(cube_rows, [("活动建造",)])
        self.assertEqual(red_rows, [])


if __name__ == "__main__":
    unittest.main()
