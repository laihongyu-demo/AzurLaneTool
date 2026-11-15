"""
日常「建造舰船 1 次」两笔明细的服务单元测试。

覆盖：四种卡池的支出类型与单耗、活动池自动关联进行中活动、建造券只写收入并把
券抽计入活动、取消回滚两笔与券抽、撤销上一笔不误删建造支出、看板状态回填。
"""

import os
import shutil
import sqlite3
import tempfile
import unittest
from datetime import datetime

from models.event_model import EventRecordModel
from repositories.event_repository import EventRepository
from services.cube_task_service import (
    BUILD_POOL_EVENT, BUILD_POOL_HEAVY, BUILD_POOL_LIGHT, BUILD_POOL_SPECIAL,
    BUILD_TASK_CODE, CubeTaskService,
)
from services.resource_entry_service import ResourceEntryService
from utils.constants import EVENT_STATUS_ONGOING, RESOURCE_TYPE_CUBE
from utils.db_connection import DatabaseConnection
from utils.db_schema import ensureResourceStatisticsSchema
from utils.exceptions import ValidationError


class _BuildTaskCase(unittest.TestCase):
    """带任务看板表结构的临时库测试基类。"""

    def setUp(self):
        self._original_db_path = DatabaseConnection.getDbPath()
        self._temp_dir = tempfile.mkdtemp(prefix="azurlane_build_")
        self._db_path = os.path.join(self._temp_dir, "build.db")
        DatabaseConnection.setDbPath(self._db_path)
        ensureResourceStatisticsSchema(self._db_path)
        self._service = CubeTaskService()
        self._event_repository = EventRepository()

    def tearDown(self):
        DatabaseConnection.setDbPath(self._original_db_path)
        shutil.rmtree(self._temp_dir, ignore_errors=True)

    def _moment(self) -> datetime:
        """当前时刻（到秒）。"""
        return datetime.now().replace(microsecond=0)

    def _query(self, sql, params=()):
        """执行只读查询。"""
        conn = sqlite3.connect(self._db_path)
        try:
            return conn.execute(sql, params).fetchall()
        finally:
            conn.close()

    def _addEvent(
        self, name: str = "测试活动", status: str = EVENT_STATUS_ONGOING, build_cost: int = 2
    ) -> int:
        """插入一条活动记录并返回 ID。"""
        record = EventRecordModel(
            event_date=datetime.now().strftime("%Y-%m-%d"),
            event_type="测试",
            name=name,
            status=status,
            build_cost=build_cost,
        )
        return self._event_repository.insert(record)

    def _transactions(self):
        """按时间、ID 顺序返回 (方向, 类型, 数量)。"""
        return self._query(
            "SELECT direction, category, amount FROM resource_transaction"
            " ORDER BY record_time, id"
        )


class TestBuildPoolTransactions(_BuildTaskCase):
    """各卡池的两笔明细。"""

    def testLightPoolWritesExpenseAndIncome(self):
        """轻型池：扣 1 魔方 + 任务奖励 1。"""
        moment = self._moment()
        result = self._service.completeBuildTask(BUILD_TASK_CODE, moment, BUILD_POOL_LIGHT)

        self.assertTrue(result.success)
        self.assertIn("轻型建造 1", result.toStatusBarMessage())
        self.assertEqual(
            self._transactions(),
            [("expense", "轻型建造", 1), ("income", "日常任务", 1)],
        )
        completion = self._query(
            "SELECT transaction_id, expense_transaction_id, event_id"
            " FROM cube_task_completion"
        )
        self.assertEqual(len(completion), 1)
        self.assertIsNotNone(completion[0][0])
        self.assertIsNotNone(completion[0][1])
        self.assertIsNone(completion[0][2])

    def testHeavyAndSpecialPoolsCostTwo(self):
        """重型 / 特型池各扣 2 魔方。"""
        moment = self._moment()
        self._service.completeBuildTask(BUILD_TASK_CODE, moment, BUILD_POOL_HEAVY)
        self.assertEqual(
            self._query(
                "SELECT category, amount FROM resource_transaction WHERE direction = 'expense'"
            ),
            [("重型建造", 2)],
        )

        self._service.cancelTask(BUILD_TASK_CODE, moment.date())
        self._service.completeBuildTask(BUILD_TASK_CODE, moment, BUILD_POOL_SPECIAL)
        self.assertEqual(
            self._query(
                "SELECT category, amount FROM resource_transaction WHERE direction = 'expense'"
            ),
            [("特型建造", 2)],
        )

    def testEventPoolLinksOngoingEvent(self):
        """活动池：按进行中活动单耗扣减，并把明细关联到该活动。"""
        event_id = self._addEvent(build_cost=2)
        moment = self._moment()

        result = self._service.completeBuildTask(BUILD_TASK_CODE, moment, BUILD_POOL_EVENT)

        self.assertIn("关联活动", result.toStatusBarMessage())
        self.assertEqual(
            self._query(
                "SELECT category, amount, event_id FROM resource_transaction"
                " WHERE direction = 'expense'"
            ),
            [("活动建造", 2, event_id)],
        )
        self.assertEqual(
            self._query("SELECT event_id FROM cube_task_completion"), [(event_id,)]
        )

    def testEventPoolUsesEventBuildCost(self):
        """活动单耗为 1 时，活动池只扣 1 魔方。"""
        self._addEvent(build_cost=1)
        self._service.completeBuildTask(BUILD_TASK_CODE, self._moment(), BUILD_POOL_EVENT)

        self.assertEqual(
            self._query(
                "SELECT amount FROM resource_transaction WHERE direction = 'expense'"
            ),
            [(1,)],
        )

    def testEventPoolWithoutOngoingEventUsesDefault(self):
        """没有进行中活动：活动池按默认单耗扣减，不关联活动。"""
        self._addEvent(status="毕业")
        self._service.completeBuildTask(BUILD_TASK_CODE, self._moment(), BUILD_POOL_EVENT)

        self.assertEqual(
            self._query(
                "SELECT category, amount, event_id FROM resource_transaction"
                " WHERE direction = 'expense'"
            ),
            [("活动建造", 2, None)],
        )
        self.assertEqual(
            self._query("SELECT event_id FROM cube_task_completion"), [(None,)]
        )


class TestBuildTicket(_BuildTaskCase):
    """建造券：不扣魔方，但要计入进行中活动的券抽次数。"""

    def testTicketWritesOnlyIncome(self):
        """建造券：只写收入，不产生支出。"""
        result = self._service.completeBuildTask(
            BUILD_TASK_CODE, self._moment(), BUILD_POOL_HEAVY, use_ticket=True
        )

        self.assertIn("建造券", result.toStatusBarMessage())
        self.assertEqual(self._transactions(), [("income", "日常任务", 1)])
        note = self._query("SELECT note FROM resource_transaction")[0][0]
        self.assertIn("建造券", note)
        completion = self._query(
            "SELECT transaction_id, expense_transaction_id, event_id"
            " FROM cube_task_completion"
        )
        self.assertEqual(len(completion), 1)
        self.assertIsNotNone(completion[0][0])
        self.assertIsNone(completion[0][1])
        self.assertIsNone(completion[0][2])

    def testTicketIncrementsOngoingEventTicketCount(self):
        """有进行中活动时，券抽次数 +1 且开启建造券口径。"""
        event_id = self._addEvent()
        result = self._service.completeBuildTask(
            BUILD_TASK_CODE, self._moment(), BUILD_POOL_LIGHT, use_ticket=True
        )

        self.assertIn("券抽 1 次", result.toStatusBarMessage())
        self.assertEqual(
            self._query(
                "SELECT use_ticket, ticket_build_count FROM event_record WHERE id = ?",
                (event_id,),
            ),
            [(1, 1)],
        )
        self.assertEqual(
            self._query("SELECT event_id FROM cube_task_completion"), [(event_id,)]
        )

    def testTicketWithoutOngoingEventSkipsEventCount(self):
        """没有进行中活动：只记奖励，不动活动表。"""
        self._service.completeBuildTask(
            BUILD_TASK_CODE, self._moment(), BUILD_POOL_LIGHT, use_ticket=True
        )

        self.assertEqual(self._query("SELECT COUNT(*) FROM event_record"), [(0,)])


class TestCancelAndUndo(_BuildTaskCase):
    """取消与撤销。"""

    def testCancelDeletesBothTransactions(self):
        """取消：删除收入与支出两笔。"""
        moment = self._moment()
        self._service.completeBuildTask(BUILD_TASK_CODE, moment, BUILD_POOL_LIGHT)

        result = self._service.cancelTask(BUILD_TASK_CODE, moment.date())

        self.assertTrue(result.success)
        self.assertIn("收入 1", result.toStatusBarMessage())
        self.assertIn("支出 1", result.toStatusBarMessage())
        self.assertEqual(self._query("SELECT id FROM resource_transaction"), [])
        self.assertEqual(self._query("SELECT id FROM cube_task_completion"), [])

    def testCancelRollsBackTicketCount(self):
        """取消建造券记录：券抽次数 -1，并在归零时清掉建造券开关。"""
        event_id = self._addEvent()
        moment = self._moment()
        self._service.completeBuildTask(
            BUILD_TASK_CODE, moment, BUILD_POOL_LIGHT, use_ticket=True
        )

        result = self._service.cancelTask(BUILD_TASK_CODE, moment.date())

        self.assertIn("回滚活动券抽 1 次", result.toStatusBarMessage())
        self.assertEqual(
            self._query(
                "SELECT use_ticket, ticket_build_count FROM event_record WHERE id = ?",
                (event_id,),
            ),
            [(0, 0)],
        )
        self.assertEqual(self._query("SELECT id FROM resource_transaction"), [])

    def testCancelToleratesDeletedExpense(self):
        """支出被手工删除后，取消仍要清理收入、完成记录与券抽。"""
        self._addEvent()
        moment = self._moment()
        self._service.completeBuildTask(
            BUILD_TASK_CODE, moment, BUILD_POOL_LIGHT, use_ticket=True
        )

        conn = sqlite3.connect(self._db_path)
        try:
            conn.execute("DELETE FROM resource_transaction")
            conn.commit()
        finally:
            conn.close()

        result = self._service.cancelTask(BUILD_TASK_CODE, moment.date())

        self.assertTrue(result.success)
        self.assertIn("关联明细已不存在", result.toStatusBarMessage())

    def testUndoLastSkipsBuildRecords(self):
        """撤销上一笔不会命中建造任务的收入 / 支出。"""
        moment = self._moment()
        self._service.completeBuildTask(BUILD_TASK_CODE, moment, BUILD_POOL_LIGHT)

        entry_service = ResourceEntryService()
        self.assertIsNone(entry_service.getUndoableEntry(RESOURCE_TYPE_CUBE))

        entry_service.record("军事委托", "income", 5, moment)
        undoable = entry_service.getUndoableEntry(RESOURCE_TYPE_CUBE)
        self.assertIsNotNone(undoable)
        self.assertEqual(undoable.category, "军事委托")


class TestValidationAndBoard(_BuildTaskCase):
    """校验与看板回填。"""

    def testCompleteTaskRejectsBuildTask(self):
        """通用完成路径不允许绕过卡池选择。"""
        with self.assertRaises(ValidationError) as ctx:
            self._service.completeTask(BUILD_TASK_CODE, self._moment())

        self.assertIn("建造", str(ctx.exception))
        self.assertEqual(self._query("SELECT id FROM resource_transaction"), [])

    def testUnknownPoolRejected(self):
        """未知卡池被拒绝。"""
        with self.assertRaises(ValidationError):
            self._service.completeBuildTask(BUILD_TASK_CODE, self._moment(), "nope")

    def testNonBuildTaskRejectedByBuildPath(self):
        """非建造任务不能走建造路径。"""
        with self.assertRaises(ValidationError):
            self._service.completeBuildTask("daily_battle_win", self._moment())

    def testDuplicateBuildRejected(self):
        """同一天重复完成被拒绝，且不留下第二笔明细。"""
        moment = self._moment()
        self._service.completeBuildTask(BUILD_TASK_CODE, moment, BUILD_POOL_LIGHT)

        with self.assertRaises(ValidationError):
            self._service.completeBuildTask(BUILD_TASK_CODE, moment, BUILD_POOL_LIGHT)

        self.assertEqual(len(self._transactions()), 2)

    def testBoardCarriesExpenseInfo(self):
        """看板状态带上建造支出类型与金额，券抽时为空。"""
        moment = self._moment()
        self._service.completeBuildTask(BUILD_TASK_CODE, moment, BUILD_POOL_HEAVY)
        groups = {group.key: group for group in self._service.getBoard(moment.date())}
        state = next(
            item for item in groups["task"].tasks if item.task.code == BUILD_TASK_CODE
        )
        self.assertTrue(state.completed)
        self.assertEqual(state.expense_category, "重型建造")
        self.assertEqual(state.expense_amount, 2)

        self._service.cancelTask(BUILD_TASK_CODE, moment.date())
        self._service.completeBuildTask(
            BUILD_TASK_CODE, moment, BUILD_POOL_LIGHT, use_ticket=True
        )
        groups = {group.key: group for group in self._service.getBoard(moment.date())}
        state = next(
            item for item in groups["task"].tasks if item.task.code == BUILD_TASK_CODE
        )
        self.assertIsNone(state.expense_transaction_id)
        self.assertEqual(state.expense_amount, 0)

    def testGetBuildPlanFollowsOngoingEvent(self):
        """确认信息：活动池单耗跟随进行中活动。"""
        plan = self._service.getBuildPlan()
        self.assertIsNone(plan.ongoing_event)
        self.assertEqual(
            [pool.cost for pool in plan.pools], [1, 2, 2, 2]
        )

        self._addEvent(name="正在进行", build_cost=1)
        plan = self._service.getBuildPlan()
        self.assertEqual(plan.ongoing_event.displayName, "正在进行")
        self.assertEqual(
            [pool.cost for pool in plan.pools], [1, 2, 2, 1]
        )


if __name__ == "__main__":
    unittest.main()
