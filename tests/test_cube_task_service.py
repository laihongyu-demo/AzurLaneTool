"""
魔方任务看板服务单元测试。

覆盖：周期键计算（日 / ISO 周 / 自然月 / 双月巡游期）、任务定义校验、
完成与取消的事务联动、重复检测、孤儿检测与降级。
"""

import os
import shutil
import sqlite3
import tempfile
import unittest
from datetime import date, datetime, timedelta

from repositories.cube_task_repository import CubeTaskRepository
from repositories.resource_repository import ResourceRepository
from services.cube_task_service import (
    CubeTaskService, buildPeriodKey, cruisePeriodEnd, cruisePeriodStart, periodRange,
)
from utils.constants import RESOURCE_TYPE_CUBE
from utils.db_connection import DatabaseConnection
from utils.db_schema import ensureResourceStatisticsSchema
from utils.exceptions import ValidationError


class TestPeriodKeys(unittest.TestCase):
    """周期键与区间计算测试（纯函数）。"""

    def testDayKey(self):
        """日键为 yyyy-MM-dd。"""
        self.assertEqual(buildPeriodKey("day", date(2026, 10, 17)), "2026-10-17")

    def testWeekKeyUsesIsoWeek(self):
        """周键为 ISO 周（周一为一周起点）。"""
        self.assertEqual(buildPeriodKey("week", date(2026, 10, 17)), "2026-W42")
        self.assertEqual(buildPeriodKey("week", date(2026, 10, 12)), "2026-W42")
        self.assertEqual(buildPeriodKey("week", date(2026, 10, 11)), "2026-W41")

    def testWeekKeyAcrossYear(self):
        """跨年周按 ISO 规则归属（2027-01-01 属于 2026 年第 53 周）。"""
        self.assertEqual(buildPeriodKey("week", date(2027, 1, 1)), "2026-W53")

    def testMonthKey(self):
        """月键为 yyyy-MM。"""
        self.assertEqual(buildPeriodKey("month", date(2026, 10, 17)), "2026-10")

    def testCruisePeriodStartsOnEvenMonth(self):
        """巡游期每 2 个自然月一期，起点为偶数月 1 日。"""
        self.assertEqual(cruisePeriodStart(date(2026, 10, 17)), date(2026, 10, 1))
        self.assertEqual(cruisePeriodStart(date(2026, 11, 30)), date(2026, 10, 1))
        self.assertEqual(cruisePeriodStart(date(2026, 12, 5)), date(2026, 12, 1))
        self.assertEqual(cruisePeriodStart(date(2026, 1, 20)), date(2025, 12, 1))
        self.assertEqual(cruisePeriodStart(date(2026, 2, 1)), date(2026, 2, 1))

    def testCruisePeriodEnd(self):
        """巡游期结束日为期末最后一天。"""
        self.assertEqual(cruisePeriodEnd(date(2026, 10, 17)), date(2026, 11, 30))
        self.assertEqual(cruisePeriodEnd(date(2026, 12, 5)), date(2027, 1, 31))

    def testCruisePeriodKey(self):
        """巡游期键为起始月 yyyy-MM，10 月与 11 月同属一期。"""
        self.assertEqual(buildPeriodKey("cruise", date(2026, 10, 1)), "2026-10")
        self.assertEqual(buildPeriodKey("cruise", date(2026, 11, 30)), "2026-10")

    def testPeriodRanges(self):
        """各周期区间包含首尾。"""
        self.assertEqual(periodRange("day", date(2026, 10, 17)), (date(2026, 10, 17), date(2026, 10, 17)))
        self.assertEqual(periodRange("week", date(2026, 10, 17)), (date(2026, 10, 12), date(2026, 10, 18)))
        self.assertEqual(periodRange("month", date(2026, 10, 17)), (date(2026, 10, 1), date(2026, 10, 31)))
        self.assertEqual(periodRange("cruise", date(2026, 10, 17)), (date(2026, 10, 1), date(2026, 11, 30)))


class _TempTaskDatabaseCase(unittest.TestCase):
    """带任务看板表结构的临时库测试基类。"""

    def setUp(self):
        self._original_db_path = DatabaseConnection.getDbPath()
        self._temp_dir = tempfile.mkdtemp(prefix="azurlane_task_")
        self._db_path = os.path.join(self._temp_dir, "task.db")
        DatabaseConnection.setDbPath(self._db_path)
        ensureResourceStatisticsSchema(self._db_path)
        self._service = CubeTaskService()

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


class TestTaskDefinitions(_TempTaskDatabaseCase):
    """任务定义与分组测试。"""

    def testDefinitionsSeeded(self):
        """18 项任务按分组定义，奖励合计符合 4 / 12 / 30 / 50。"""
        rows = self._query("SELECT grp, COUNT(*), SUM(reward) FROM cube_task GROUP BY grp")
        summary = {grp: (count, total) for grp, count, total in rows}

        self.assertEqual(summary["daily"], (3, 4))
        self.assertEqual(summary["weekly"], (3, 12))
        self.assertEqual(summary["signin"], (4, 30))
        self.assertEqual(summary["cruise"], (8, 50))

    def testBoardGroupsAndTotals(self):
        """看板返回 3 个展示分组，合计口径正确。"""
        groups = self._service.getBoard(date.today())
        by_key = {group.key: group for group in groups}

        self.assertEqual(list(by_key), ["task", "signin", "cruise"])
        self.assertEqual(by_key["task"].total, 16)      # 每日 4 + 每周 12
        self.assertEqual(by_key["signin"].total, 30)
        self.assertEqual(by_key["cruise"].total, 50)
        self.assertEqual(by_key["task"].earned, 0)
        self.assertEqual(len(by_key["task"].tasks), 6)

    def testPeriodInfoLabels(self):
        """顶部周期信息包含日 / 周 / 月 / 期四种。"""
        info = self._service.getPeriodInfo(date(2026, 10, 17))

        self.assertEqual(info["day"].label, "2026-10-17")
        self.assertEqual(info["week"].label, "2026 第 42 周（10-12 ~ 10-18）")
        self.assertEqual(info["month"].label, "2026-10")
        self.assertEqual(info["cruise"].label, "2026-10-01 ~ 2026-11-30")


class TestCompleteAndCancel(_TempTaskDatabaseCase):
    """完成 / 取消的事务联动测试。"""

    def _moment(self) -> datetime:
        """当前时刻（到秒）。"""
        return datetime.now().replace(microsecond=0)

    def testCompleteWritesTransactionAndCompletion(self):
        """完成会写一笔收入明细并登记完成记录。"""
        moment = self._moment()
        result = self._service.completeTask("daily_build_once", moment)

        self.assertTrue(result.success)
        self.assertIn("+1", result.toStatusBarMessage())

        transactions = self._query(
            "SELECT direction, record_time, category, amount, note FROM resource_transaction"
        )
        self.assertEqual(len(transactions), 1)
        direction, record_time, category, amount, note = transactions[0]
        self.assertEqual(direction, "income")
        self.assertEqual(record_time, moment.strftime("%Y-%m-%d %H:%M:%S"))
        self.assertEqual(category, "日常任务")
        self.assertEqual(amount, 1)
        self.assertIn("建造舰船", note)

        completions = self._query(
            "SELECT task_code, period_key, transaction_id FROM cube_task_completion"
        )
        self.assertEqual(len(completions), 1)
        self.assertEqual(completions[0][0], "daily_build_once")
        self.assertEqual(completions[0][1], moment.strftime("%Y-%m-%d"))
        self.assertIsNotNone(completions[0][2])

    def testCompleteMaintainsLastRecordTime(self):
        """完成会维护当日 last_record_time。"""
        moment = self._moment()
        self._service.completeTask("daily_battle_win", moment)

        rows = self._query(
            "SELECT detail_mode, last_record_time FROM resource_daily WHERE record_date = ?",
            (moment.strftime("%Y-%m-%d"),),
        )
        self.assertEqual(rows[0][0], "detail")
        self.assertEqual(rows[0][1], moment.strftime("%Y-%m-%d %H:%M:%S"))

    def testDuplicateCompleteRejected(self):
        """同一周期重复完成被拒绝。"""
        moment = self._moment()
        self._service.completeTask("signin_1", moment)

        with self.assertRaises(ValidationError) as ctx:
            self._service.completeTask("signin_1", moment)

        self.assertIn("已完成", str(ctx.exception))
        self.assertEqual(len(self._query("SELECT id FROM resource_transaction")), 1)

    def testDifferentPeriodsAllowed(self):
        """不同周期的同一任务可以分别完成。"""
        today = date.today()
        self._service.completeTask("daily_build_once", datetime.now().replace(microsecond=0))
        # 昨天属于上一个「日」周期
        yesterday = today - timedelta(days=1)
        self._service.completeTask(
            "daily_build_once", datetime.combine(yesterday, datetime.min.time()).replace(hour=12)
        )

        self.assertEqual(len(self._query("SELECT id FROM cube_task_completion")), 2)

    def testFutureMomentRejected(self):
        """未来时刻被拒绝。"""
        future = datetime.now() + timedelta(days=1)

        with self.assertRaises(ValidationError):
            self._service.completeTask("daily_build_once", future)

    def testUnknownTaskRejected(self):
        """未知任务编码被拒绝。"""
        with self.assertRaises(ValidationError):
            self._service.completeTask("not_exists", self._moment())

    def testCancelDeletesTransactionAndCompletion(self):
        """取消会删除明细与完成记录，并清空 last_record_time。"""
        moment = self._moment()
        self._service.completeTask("weekly_pt_150", moment)

        result = self._service.cancelTask("weekly_pt_150", moment.date())

        self.assertTrue(result.success)
        self.assertEqual(self._query("SELECT id FROM resource_transaction"), [])
        self.assertEqual(self._query("SELECT id FROM cube_task_completion"), [])
        rows = self._query(
            "SELECT last_record_time FROM resource_daily WHERE record_date = ?",
            (moment.strftime("%Y-%m-%d"),),
        )
        self.assertEqual(rows[0][0], None)

    def testCancelThenCompleteAgain(self):
        """取消后可重新完成。"""
        moment = self._moment()
        self._service.completeTask("cruise_lv05", moment)
        self._service.cancelTask("cruise_lv05", moment.date())

        result = self._service.completeTask("cruise_lv05", moment)

        self.assertTrue(result.success)
        self.assertEqual(len(self._query("SELECT id FROM resource_transaction")), 1)

    def testCancelWithoutCompletionRejected(self):
        """未完成的任务不能取消。"""
        with self.assertRaises(ValidationError):
            self._service.cancelTask("daily_build_once", date.today())


class TestBoardState(_TempTaskDatabaseCase):
    """看板状态与孤儿检测测试。"""

    def testCompletedStateReflected(self):
        """完成后看板对应任务标记为已完成，分组累计增加。"""
        moment = datetime.now().replace(microsecond=0)
        self._service.completeTask("daily_battle_win", moment)

        groups = {group.key: group for group in self._service.getBoard(moment.date())}
        task_states = {state.task.code: state for state in groups["task"].tasks}

        self.assertTrue(task_states["daily_battle_win"].completed)
        self.assertFalse(task_states["daily_build_once"].completed)
        self.assertEqual(groups["task"].earned, 2)

    def testOrphanDetectedWhenTransactionRemoved(self):
        """手工删掉明细后，看板把完成记录标记为孤儿。"""
        moment = datetime.now().replace(microsecond=0)
        self._service.completeTask("daily_build_once", moment)

        conn = sqlite3.connect(self._db_path)
        try:
            conn.execute("DELETE FROM resource_transaction")
            conn.commit()
        finally:
            conn.close()

        groups = {group.key: group for group in self._service.getBoard(moment.date())}
        task_states = {state.task.code: state for state in groups["task"].tasks}

        self.assertTrue(task_states["daily_build_once"].completed)
        self.assertTrue(task_states["daily_build_once"].orphan)

    def testCancelToleratesMissingTransaction(self):
        """明细已被删除时，取消仍能清理完成记录。"""
        moment = datetime.now().replace(microsecond=0)
        self._service.completeTask("daily_build_once", moment)

        conn = sqlite3.connect(self._db_path)
        try:
            conn.execute("DELETE FROM resource_transaction")
            conn.commit()
        finally:
            conn.close()

        result = self._service.cancelTask("daily_build_once", moment.date())

        self.assertTrue(result.success)
        self.assertIn("关联明细已不存在", result.toStatusBarMessage())
        self.assertEqual(self._query("SELECT id FROM cube_task_completion"), [])


class TestRepositoryBasics(_TempTaskDatabaseCase):
    """数据访问层基础能力测试。"""

    def testFindByCode(self):
        """按编码取任务定义。"""
        task = CubeTaskRepository().findByCode("cruise_lv75")

        self.assertIsNotNone(task)
        self.assertEqual(task.reward, 8)
        self.assertEqual(task.period_type, "cruise")

    def testResourceTransactionRoundTrip(self):
        """明细写入后可读回，删除后不可见。"""
        from models.resource_model import ResourceTransactionModel

        repository = ResourceRepository()
        record = ResourceTransactionModel(
            resource_type=RESOURCE_TYPE_CUBE, direction="income",
            record_time="2026-10-17 12:00:00", category="日常任务", amount=2, note="测试",
        )
        transaction_id = repository.insertTransaction(record)
        loaded = repository.findTransactionById(transaction_id)

        self.assertEqual(loaded.amount, 2)
        self.assertTrue(repository.deleteTransaction(transaction_id))
        self.assertIsNone(repository.findTransactionById(transaction_id))


if __name__ == "__main__":
    unittest.main()
