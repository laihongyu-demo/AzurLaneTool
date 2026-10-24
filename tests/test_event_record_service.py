"""
活动记录服务单元测试。

覆盖：新增 / 更新 / 删除、字段校验、筛选与建议值、与「活动建造」明细的关联汇总、
删除活动时解除关联但保留明细、批量导入事务。
"""

import os
import shutil
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta

from models.event_model import EventOption, EventRecordModel
from services.event_record_service import EventRecordService
from services.resource_entry_service import ResourceEntryService
from utils import time_source
from utils.constants import (
    EVENT_BUILD_CATEGORY,
    EVENT_DEFAULT_BUILD_COST,
    EVENT_STATUS_GRADUATED,
    EVENT_STATUS_MISSING,
    EVENT_STATUS_ONGOING,
    EVENT_STATUS_OPTIONS,
    EVENT_STATUS_UNSET_LABEL,
    EVENT_UNNAMED_LABEL,
    RESOURCE_DIRECTION_EXPENSE,
    RESOURCE_TYPE_CUBE,
    RESOURCE_TYPE_RED_GEM,
)
from utils.db_connection import DatabaseConnection
from utils.db_schema import ensureResourceStatisticsSchema
from utils.exceptions import ValidationError


class _TempEventDatabaseCase(unittest.TestCase):
    """带资源 / 活动表结构的临时库测试基类。"""

    def setUp(self):
        self._original_db_path = DatabaseConnection.getDbPath()
        self._temp_dir = tempfile.mkdtemp(prefix="azurlane_event_")
        self._db_path = os.path.join(self._temp_dir, "event.db")
        DatabaseConnection.setDbPath(self._db_path)
        ensureResourceStatisticsSchema(self._db_path)
        self._service = EventRecordService()
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

    def _execute(self, sql, params=()) -> None:
        """执行写入。"""
        conn = sqlite3.connect(self._db_path)
        try:
            conn.execute(sql, params)
            conn.commit()
        finally:
            conn.close()

    def _date(self, days_ago: int = 0):
        """相对今天的历史日期。"""
        return time_source.today() - timedelta(days=days_ago)

    def _create(
        self,
        days_ago: int = 0,
        event_type: str = "大型海域",
        name: str = "飓风与雾霭回廊",
        status: str = EVENT_STATUS_ONGOING,
        status_note: str = "",
        build_cost: int = EVENT_DEFAULT_BUILD_COST,
        use_ticket: int = 0,
        ticket_build_count=None,
        build_count=None,
        note: str = "",
    ) -> EventRecordModel:
        """新增一条活动记录并返回规范化后的模型。"""
        result = self._service.create(
            EventRecordModel(
                event_date=self._date(days_ago).strftime("%Y-%m-%d"),
                event_type=event_type,
                name=name,
                status=status,
                status_note=status_note,
                build_cost=build_cost,
                use_ticket=use_ticket,
                ticket_build_count=ticket_build_count,
                build_count=build_count,
                note=note,
            )
        )
        self.assertTrue(result.success)
        return self._service.getRecord(result.record_id)

    def _record(
        self,
        event_id=None,
        category: str = EVENT_BUILD_CATEGORY,
        amount: int = 60,
        resource_type: str = RESOURCE_TYPE_CUBE,
        direction: str = RESOURCE_DIRECTION_EXPENSE,
    ) -> int:
        """记一笔明细并返回明细 ID。"""
        moment = datetime.now().replace(microsecond=0)
        result = self._entry_service.record(
            category=category,
            direction=direction,
            amount=amount,
            moment=moment,
            resource_type=resource_type,
            event_id=event_id,
        )
        return result.transaction_id


class TestEventCrud(_TempEventDatabaseCase):
    """活动记录增删改查测试。"""

    def testCreateListAndSummary(self):
        """新增后可按日期倒序查出，字段完整。"""
        record = self._create(days_ago=1, build_count=30, status_note="缺吉尚", note="十连")

        self.assertGreater(record.id, 0)
        self.assertEqual(record.event_date, self._date(1).strftime("%Y-%m-%d"))
        self.assertEqual(record.event_type, "大型海域")
        self.assertEqual(record.name, "飓风与雾霭回廊")
        self.assertEqual(record.status, EVENT_STATUS_ONGOING)
        self.assertEqual(record.status_note, "缺吉尚")
        self.assertEqual(record.build_count, 30)
        self.assertEqual(record.note, "十连")

        views = self._service.listRecords()
        self.assertEqual(len(views), 1)
        self.assertEqual(views[0].record.id, record.id)
        self.assertEqual(views[0].transaction_count, 0)
        self.assertEqual(views[0].cube_expense, 0)

        summary = self._service.getSummary(views)
        self.assertEqual(summary.total, 1)
        self.assertEqual(summary.ongoing, 1)
        self.assertEqual(summary.build_count_known, 1)
        self.assertEqual(summary.build_count_total, 30)

    def testTextFieldsAreTrimmedAndEmptyNameAllowed(self):
        """文本去除首尾空白；历史数据允许空活动名。"""
        record = self._create(name="  ", event_type=" 联动海域 ", status=" 毕业 ", note="  ")
        self.assertEqual(record.name, "")
        self.assertEqual(record.event_type, "联动海域")
        self.assertEqual(record.status, EVENT_STATUS_GRADUATED)
        self.assertEqual(record.displayName, EVENT_UNNAMED_LABEL)

    def testUnsetStatusLabelNormalizedToEmpty(self):
        """「未标记」是展示兜底文案，不作为真实状态落库。"""
        record = self._create(status=EVENT_STATUS_UNSET_LABEL)
        self.assertEqual(record.status, "")

    def testFutureDateRejected(self):
        """活动日期不能晚于今天。"""
        with self.assertRaises(ValidationError):
            self._service.create(
                EventRecordModel(
                    event_date=(time_source.today() + timedelta(days=1)).strftime("%Y-%m-%d")
                )
            )

    def testInvalidDateRejected(self):
        """非法日期格式被拒绝。"""
        for value in ("2026/10/22", "2026-13-01", "", "not-a-date"):
            with self.assertRaises(ValidationError):
                self._service.create(EventRecordModel(event_date=value))

    def testBuildCountValidation(self):
        """建造次数允许 None / 0 / 正整数，拒绝负数与非整数。"""
        self.assertIsNone(self._create(days_ago=3, build_count=None).build_count)
        self.assertEqual(self._create(days_ago=2, build_count=0).build_count, 0)

        for value in (-1, 1.5, "abc", True):
            with self.assertRaises(ValidationError):
                self._service.create(
                    EventRecordModel(
                        event_date=self._date(1).strftime("%Y-%m-%d"), build_count=value
                    )
                )

    def testBuildCostValidation(self):
        """单次消耗只能是 1 或 2 魔方。"""
        for value in (1, 2):
            record = self._create(days_ago=value, build_cost=value)
            self.assertEqual(record.build_cost, value)

        for value in (0, 3, -1, "abc", True):
            with self.assertRaises(ValidationError):
                self._service.create(
                    EventRecordModel(
                        event_date=self._date(1).strftime("%Y-%m-%d"),
                        build_cost=value,
                    )
                )

    def testTicketBuildCountValidation(self):
        """券抽次数需要非负；未勾选建造券时清空。"""
        record = self._create(days_ago=1, use_ticket=1, ticket_build_count=10)
        self.assertEqual(record.use_ticket, 1)
        self.assertEqual(record.ticket_build_count, 10)

        off = self._create(days_ago=2, use_ticket=0, ticket_build_count=10)
        self.assertEqual(off.use_ticket, 0)
        self.assertIsNone(off.ticket_build_count)

        for value in (-1, "abc", True):
            with self.assertRaises(ValidationError):
                self._service.create(
                    EventRecordModel(
                        event_date=self._date(1).strftime("%Y-%m-%d"),
                        use_ticket=1,
                        ticket_build_count=value,
                    )
                )

    def testOverlongNameRejected(self):
        """活动名称超长被拒绝。"""
        with self.assertRaises(ValidationError):
            self._service.create(
                EventRecordModel(
                    event_date=self._date(1).strftime("%Y-%m-%d"), name="活" * 101
                )
            )

    def testUpdateAndMissingRecord(self):
        """更新写入新值；更新不存在的记录抛校验错误。"""
        record = self._create(days_ago=1, name="旧名", build_count=10)

        result = self._service.update(
            record.id,
            EventRecordModel(
                event_date=record.event_date,
                event_type="轻量化复刻·大型海域",
                name="新名",
                status=EVENT_STATUS_GRADUATED,
                status_note="全毕业",
                build_count=20,
                note="补记",
            ),
        )

        self.assertTrue(result.success)
        updated = self._service.getRecord(record.id)
        self.assertEqual(updated.name, "新名")
        self.assertEqual(updated.event_type, "轻量化复刻·大型海域")
        self.assertEqual(updated.status, EVENT_STATUS_GRADUATED)
        self.assertEqual(updated.build_count, 20)

        with self.assertRaises(ValidationError):
            self._service.update(9999, EventRecordModel(event_date=record.event_date))

    def testDeleteUnlinksButKeepsTransactions(self):
        """删除活动只把明细 event_id 置空，明细本身保留。"""
        record = self._create(days_ago=1)
        transaction_id = self._record(event_id=record.id)

        rows = self._query("SELECT event_id FROM resource_transaction WHERE id = ?", (transaction_id,))
        self.assertEqual(rows, [(record.id,)])

        result = self._service.delete(record.id)

        self.assertTrue(result.success)
        self.assertIn("解除 1 笔", result.toStatusBarMessage())
        self.assertIsNone(self._service.getRecord(record.id))
        self.assertEqual(
            self._query("SELECT event_id FROM resource_transaction WHERE id = ?", (transaction_id,)),
            [(None,)],
        )

    def testDeleteMissingRecordRejected(self):
        """删除不存在的活动抛校验错误。"""
        with self.assertRaises(ValidationError):
            self._service.delete(9999)

    def testImportRecordsAtomicOnValidationFailure(self):
        """批量导入任一行非法时整批不写入。"""
        valid = EventRecordModel(
            event_date=self._date(1).strftime("%Y-%m-%d"), name="有效活动"
        )
        invalid = EventRecordModel(
            event_date=(time_source.today() + timedelta(days=1)).strftime("%Y-%m-%d"),
            name="未来活动",
        )

        with self.assertRaises(ValidationError):
            self._service.importRecords([valid, invalid])

        self.assertEqual(self._service.countAll(), 0)


class TestEventFilters(_TempEventDatabaseCase):
    """筛选与下拉选项测试。"""

    def setUp(self):
        super().setUp()
        self._old = self._create(
            days_ago=400,
            event_type="轻量化复刻·大型海域",
            name="复刻：愚者的天平",
            status=EVENT_STATUS_GRADUATED,
            status_note="20 券出",
            build_count=20,
        )
        self._current = self._create(
            days_ago=1,
            event_type="大型海域",
            name="飓风与雾霭回廊",
            status=EVENT_STATUS_ONGOING,
            build_count=30,
            note="新活动",
        )
        self._missing = self._create(
            days_ago=2,
            event_type="大型海域",
            name="飓风与青春之泉",
            status=EVENT_STATUS_MISSING,
            status_note="缺圣马丁",
            build_count=None,
        )
        self._unset = self._create(
            days_ago=3,
            event_type="活动海域",
            name="",
            status="",
            build_count=0,
        )

    def testFilterByYearTypeStatusAndKeyword(self):
        """年份 / 类型 / 状态 / 关键词组合筛选。"""
        current_year = self._date(1).strftime("%Y")
        old_year = self._date(400).strftime("%Y")

        all_views = self._service.listRecords()
        self.assertEqual(
            len(self._service.listRecords(year=current_year)),
            sum(1 for view in all_views if view.record.event_date.startswith(current_year)),
        )
        self.assertEqual(
            len(self._service.listRecords(year=old_year)),
            sum(1 for view in all_views if view.record.event_date.startswith(old_year)),
        )
        self.assertEqual(len(self._service.listRecords(event_type="活动海域")), 1)
        self.assertEqual(len(self._service.listRecords(status=EVENT_STATUS_MISSING)), 1)
        self.assertEqual(len(self._service.listRecords(status="")), 1)
        self.assertEqual(len(self._service.listRecords(keyword="圣马丁")), 1)
        self.assertEqual(len(self._service.listRecords(keyword="新活动")), 1)

    def testRecordsSortedByDateDesc(self):
        """列表按开始日期倒序，同一天按 ID 倒序。"""
        views = self._service.listRecords()
        dates = [view.record.event_date for view in views]
        self.assertEqual(dates, sorted(dates, reverse=True))
        self.assertEqual(views[0].record.id, self._current.id)

    def testFilterOptions(self):
        """年份、类型建议值来自已有记录。"""
        options = self._service.getFilterOptions()
        self.assertEqual(options.years[0], self._date(1).strftime("%Y"))
        self.assertEqual(set(options.types), {"轻量化复刻·大型海域", "大型海域", "活动海域"})

    def testSelectableEventOptions(self):
        """常规录入下拉按日期倒序，文案含日期、名称与状态。"""
        options = self._service.getSelectableEvents()
        self.assertEqual(len(options), 4)
        self.assertEqual(options[0].id, self._current.id)
        self.assertIsInstance(options[0], EventOption)
        self.assertIn(self._date(1).strftime("%Y"), options[0].label)
        self.assertIn("飓风与雾霭回廊", options[0].label)
        self.assertIn(EVENT_STATUS_ONGOING, options[0].label)

    def testCustomStatusAppearsInOptionsAndFilter(self):
        """自由输入的状态也能出现在筛选与编辑候选里。"""
        self._create(days_ago=5, name="自定义状态", status="放弃")

        options = self._service.getStatusOptions()
        self.assertEqual(options[:3], list(EVENT_STATUS_OPTIONS))
        self.assertIn("放弃", options)
        self.assertEqual(len(self._service.listRecords(status="放弃")), 1)
        self.assertIn("放弃", self._service.getFilterOptions().statuses)

        summary = self._service.getSummary(self._service.listRecords(status="放弃"))
        self.assertEqual(summary.other, 1)


class TestEventLink(_TempEventDatabaseCase):
    """活动与「支出 · 活动建造」明细的关联测试。"""

    def testActivityBuildLinksEvent(self):
        """活动建造明细写入 event_id，活动页汇总魔方支出与笔数。"""
        record = self._create(days_ago=1, build_count=30)
        first_id = self._record(event_id=record.id, amount=60)
        second_id = self._record(event_id=record.id, amount=20)

        rows = self._query(
            "SELECT id, event_id, amount FROM resource_transaction ORDER BY id"
        )
        self.assertEqual(rows, [(first_id, record.id, 60), (second_id, record.id, 20)])

        view = self._service.listRecords()[0]
        self.assertEqual(view.record.id, record.id)
        self.assertEqual(view.transaction_count, 2)
        self.assertEqual(view.cube_expense, 80)
        self.assertEqual(view.cube_build_count, 40)
        self.assertEqual(view.build_count, 40)
        self.assertEqual(view.remainder, 0)
        self.assertTrue(view.derived)

        summary = self._service.getSummary([view])
        self.assertEqual(summary.linked_count, 1)
        self.assertEqual(summary.cube_expense, 80)
        self.assertEqual(summary.build_count_total, 40)

    def testDerivedBuildCountUsesOneOrTwoCubeCost(self):
        """建造次数 = 关联魔方 ÷ 单耗，支持 1 魔方和 2 魔方两种池。"""
        two_cost = self._create(days_ago=2, name="两魔方池", build_cost=2)
        one_cost = self._create(days_ago=1, name="一魔方池", build_cost=1)
        self._record(event_id=two_cost.id, amount=160)
        self._record(event_id=one_cost.id, amount=20)

        views = {view.record.id: view for view in self._service.listRecords()}
        self.assertEqual(views[two_cost.id].build_count, 80)
        self.assertEqual(views[one_cost.id].build_count, 20)

    def testTicketBuildCountAdded(self):
        """建造券次数在魔方折算之外单独补加。"""
        record = self._create(days_ago=1, build_cost=2, use_ticket=1, ticket_build_count=5)
        self._record(event_id=record.id, amount=20)

        view = self._service.listRecords()[0]
        self.assertEqual(view.cube_build_count, 10)
        self.assertEqual(view.ticket_build_count, 5)
        self.assertEqual(view.build_count, 15)

    def testNoLinkedUsesManualBuildCount(self):
        """无关联明细时继续使用手工 / 历史建造次数。"""
        record = self._create(days_ago=1, build_count=30)
        view = self._service.listRecords()[0]

        self.assertFalse(view.derived)
        self.assertEqual(view.build_count, 30)
        self.assertEqual(view.cube_build_count, 0)

    def testRemainderFlagged(self):
        """关联魔方除不尽单耗时给出余数，便于核对。"""
        record = self._create(days_ago=1, build_cost=2)
        transaction_id = self._record(event_id=record.id, amount=20)
        self._execute(
            "UPDATE resource_transaction SET amount = 21 WHERE id = ?", (transaction_id,)
        )

        view = self._service.listRecords()[0]
        self.assertEqual(view.cube_expense, 21)
        self.assertEqual(view.cube_build_count, 10)
        self.assertEqual(view.remainder, 1)
        self.assertEqual(view.build_count, 10)

    def testEntryRejectsAmountNotMultipleOfCost(self):
        """关联活动时金额必须是单耗整数倍，否则无法折算。"""
        two_cost = self._create(days_ago=2, build_cost=2)
        one_cost = self._create(days_ago=1, build_cost=1)

        with self.assertRaises(ValidationError):
            self._record(event_id=two_cost.id, amount=21)
        self.assertGreater(self._record(event_id=one_cost.id, amount=21), 0)

    def testEventOptionLabelIncludesCost(self):
        """常规录入下拉显示单次消耗，提醒金额应为整数倍。"""
        record = self._create(days_ago=1, build_cost=2)
        option = self._service.getSelectableEvents()[0]
        self.assertEqual(option.id, record.id)
        self.assertIn("2魔方/次", option.label)

    def testOtherCategoriesCannotLink(self):
        """只有「魔方 · 支出 · 活动建造」允许关联。"""
        record = self._create(days_ago=1)

        with self.assertRaises(ValidationError):
            self._record(event_id=record.id, category="轻型建造")
        with self.assertRaises(ValidationError):
            self._record(event_id=record.id, category="军事委托", direction="income")
        with self.assertRaises(ValidationError):
            self._record(event_id=record.id, resource_type=RESOURCE_TYPE_RED_GEM)

    def testMissingEventRejected(self):
        """关联不存在的活动被拒绝。"""
        with self.assertRaises(ValidationError):
            self._record(event_id=9999)

    def testUnlinkedActivityBuildAllowed(self):
        """不关联活动也可以记录活动建造。"""
        transaction_id = self._record(event_id=None)
        rows = self._query(
            "SELECT event_id FROM resource_transaction WHERE id = ?", (transaction_id,)
        )
        self.assertEqual(rows, [(None,)])

    def testUndoKeepsEventLinkStatsConsistent(self):
        """撤销关联明细后，活动页汇总回到 0。"""
        record = self._create(days_ago=1)
        self._record(event_id=record.id, amount=60)

        undo = self._entry_service.undoLast()
        self.assertTrue(undo.success)

        view = self._service.listRecords()[0]
        self.assertEqual(view.transaction_count, 0)
        self.assertEqual(view.cube_expense, 0)


if __name__ == "__main__":
    unittest.main()
