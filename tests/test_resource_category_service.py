"""
资源类型字典维护服务单元测试。

覆盖：列表顺序与使用笔数、新增（重名 / 空名 / 超长 / 去空白）、改名同步历史明细、
上移下移与序号重排、停用 / 启用对录入下拉的影响、重启后自定义不被种子覆盖、
缺失表降级。
"""

import os
import shutil
import sqlite3
import tempfile
import unittest
from datetime import datetime

from services.resource_category_service import (
    CATEGORY_NAME_MAX_LENGTH,
    ResourceCategoryService,
)
from services.resource_entry_service import ResourceEntryService
from utils.constants import (
    RESOURCE_DIRECTION_EXPENSE,
    RESOURCE_DIRECTION_INCOME,
    RESOURCE_TYPE_CUBE,
    RESOURCE_TYPE_RED_GEM,
)
from utils.db_connection import DatabaseConnection
from utils.db_schema import ensureResourceStatisticsSchema
from utils.exceptions import ValidationError

CUBE_EXPENSE_ORDER = ["轻型建造", "重型建造", "特型建造", "活动建造", "祈愿建造", "开发船坞", "军部研究"]
CUBE_INCOME_ORDER = [
    "军事委托", "活动签到", "活动任务", "活动商店", "贸易许可证", "节日奖励", "礼包",
    "军火商店", "军需商店", "作战档案", "主线任务", "手册任务", "海域探索", "直购",
    "补给商店", "未知",
]


class _TempCategoryDatabaseCase(unittest.TestCase):
    """带类型字典种子数据的临时库测试基类。"""

    def setUp(self):
        self._original_db_path = DatabaseConnection.getDbPath()
        self._temp_dir = tempfile.mkdtemp(prefix="azurlane_category_")
        self._db_path = os.path.join(self._temp_dir, "category.db")
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

    def _execute(self, sql, params=()) -> None:
        """执行写入。"""
        conn = sqlite3.connect(self._db_path)
        try:
            conn.execute(sql, params)
            conn.commit()
        finally:
            conn.close()

    def _names(self, resource_type=RESOURCE_TYPE_CUBE, direction=RESOURCE_DIRECTION_EXPENSE):
        """当前分组下的类型名列表。"""
        return [entry.name for entry in self._service.listCategories(resource_type, direction)]

    def _entryNames(self, resource_type=RESOURCE_TYPE_CUBE, direction=RESOURCE_DIRECTION_EXPENSE):
        """常规录入下拉里的类型名列表。"""
        return [
            option.name for option in self._entry_service.getCategories(resource_type)
            if option.direction == direction
        ]

    def _record(self, category, direction=RESOURCE_DIRECTION_EXPENSE, amount=1):
        """记一笔明细，用于制造「类型在用」的场景。"""
        self._entry_service.record(
            category, direction, amount, datetime.now().replace(microsecond=0)
        )


class TestListCategories(_TempCategoryDatabaseCase):
    """列表查询测试。"""

    def testFollowsSeedOrderAndCountsUsage(self):
        """列表按种子顺序返回，并统计每个类型的明细笔数。"""
        self._record("活动建造", amount=30)
        self._record("活动建造", amount=5)

        entries = self._service.listCategories(RESOURCE_TYPE_CUBE, RESOURCE_DIRECTION_EXPENSE)

        self.assertEqual([entry.name for entry in entries], CUBE_EXPENSE_ORDER)
        usage = {entry.name: entry.usage_count for entry in entries}
        self.assertEqual(usage["活动建造"], 2)
        self.assertEqual(usage["轻型建造"], 0)
        self.assertTrue(all(entry.is_active for entry in entries))
        self.assertEqual(entries[0].statusText, "启用")

    def testIncludesInactiveItems(self):
        """维护列表包含已停用的类型，便于重新启用。"""
        target = next(
            entry for entry in self._service.listCategories(
                RESOURCE_TYPE_CUBE, RESOURCE_DIRECTION_EXPENSE
            )
            if entry.name == "活动建造"
        )
        self._service.setCategoryActive(target.id, False)

        entries = self._service.listCategories(RESOURCE_TYPE_CUBE, RESOURCE_DIRECTION_EXPENSE)

        inactive = [entry for entry in entries if not entry.is_active]
        self.assertEqual([entry.name for entry in inactive], ["活动建造"])
        self.assertEqual(inactive[0].statusText, "停用")

    def testUsageCountsArePerResource(self):
        """使用笔数按资源隔离：红尖尖的明细不计入魔方。"""
        self._entry_service.record(
            "军事委托", RESOURCE_DIRECTION_INCOME, 1,
            datetime.now().replace(microsecond=0), RESOURCE_TYPE_RED_GEM,
        )

        cube_usage = {
            entry.name: entry.usage_count
            for entry in self._service.listCategories(RESOURCE_TYPE_CUBE, RESOURCE_DIRECTION_INCOME)
        }
        red_usage = {
            entry.name: entry.usage_count
            for entry in self._service.listCategories(RESOURCE_TYPE_RED_GEM, RESOURCE_DIRECTION_INCOME)
        }

        self.assertEqual(cube_usage["军事委托"], 0)
        self.assertEqual(red_usage["军事委托"], 1)

    def testMissingTableDegradesToEmpty(self):
        """表缺失时返回空列表，不抛异常。"""
        missing_path = os.path.join(self._temp_dir, "missing.db")
        DatabaseConnection.setDbPath(missing_path)

        self.assertEqual(
            ResourceCategoryService().listCategories(
                RESOURCE_TYPE_CUBE, RESOURCE_DIRECTION_INCOME
            ),
            [],
        )

    def testInvalidResourceOrDirectionRejected(self):
        """资源类型 / 方向非法时给出校验错误。"""
        with self.assertRaises(ValidationError):
            self._service.listCategories("gold", RESOURCE_DIRECTION_INCOME)
        with self.assertRaises(ValidationError):
            self._service.listCategories(RESOURCE_TYPE_CUBE, "transfer")


class TestCreateCategory(_TempCategoryDatabaseCase):
    """新增类型测试。"""

    def testAppendsToGroupAndShowsInEntryDropdown(self):
        """新增类型排在分组末尾，并出现在常规录入下拉。"""
        result = self._service.createCategory(RESOURCE_TYPE_CUBE, RESOURCE_DIRECTION_EXPENSE, "活动复刻")

        self.assertTrue(result.success)
        self.assertGreater(result.category_id, 0)
        self.assertIn("已新增", result.toStatusBarMessage())
        self.assertEqual(self._names()[-1], "活动复刻")
        self.assertEqual(self._entryNames()[-1], "活动复刻")

        sort_orders = [
            entry.sort_order
            for entry in self._service.listCategories(RESOURCE_TYPE_CUBE, RESOURCE_DIRECTION_EXPENSE)
        ]
        self.assertEqual(sort_orders, sorted(sort_orders))

    def testStripsWhitespace(self):
        """首尾空白被去掉后落库。"""
        self._service.createCategory(RESOURCE_TYPE_RED_GEM, RESOURCE_DIRECTION_INCOME, "  维护补偿  ")

        self.assertIn("维护补偿", self._names(RESOURCE_TYPE_RED_GEM, RESOURCE_DIRECTION_INCOME))

    def testDuplicateRejectedEvenWhenInactive(self):
        """同名类型不能重复新增；停用后名称仍被占用。"""
        with self.assertRaises(ValidationError):
            self._service.createCategory(RESOURCE_TYPE_CUBE, RESOURCE_DIRECTION_EXPENSE, "活动建造")

        target = next(
            entry for entry in self._service.listCategories(
                RESOURCE_TYPE_CUBE, RESOURCE_DIRECTION_EXPENSE
            )
            if entry.name == "活动建造"
        )
        self._service.setCategoryActive(target.id, False)

        with self.assertRaises(ValidationError) as context:
            self._service.createCategory(RESOURCE_TYPE_CUBE, RESOURCE_DIRECTION_EXPENSE, "活动建造")
        self.assertIn("已存在", str(context.exception))

    def testSameNameAllowedInOtherDirection(self):
        """同名可分别存在于收入与支出（红尖尖「礼包」的既有口径）。"""
        result = self._service.createCategory(RESOURCE_TYPE_RED_GEM, RESOURCE_DIRECTION_EXPENSE, "月卡")

        self.assertTrue(result.success)
        self.assertIn("月卡", self._names(RESOURCE_TYPE_RED_GEM, RESOURCE_DIRECTION_EXPENSE))
        self.assertIn("月卡", self._names(RESOURCE_TYPE_RED_GEM, RESOURCE_DIRECTION_INCOME))

    def testEmptyAndOverlongNamesRejected(self):
        """空名 / 纯空白 / 超长名称被拒绝，且不写库。"""
        before = self._query("SELECT COUNT(*) FROM resource_category")[0][0]

        for bad_name in ("", "   ", "x" * (CATEGORY_NAME_MAX_LENGTH + 1)):
            with self.assertRaises(ValidationError):
                self._service.createCategory(
                    RESOURCE_TYPE_CUBE, RESOURCE_DIRECTION_EXPENSE, bad_name
                )

        self.assertEqual(self._query("SELECT COUNT(*) FROM resource_category")[0][0], before)


class TestRenameCategory(_TempCategoryDatabaseCase):
    """改名测试。"""

    def testRenameSyncsTransactions(self):
        """改名同步已有关联明细，其它类型的明细不受影响。"""
        self._record("活动建造", amount=30)
        self._record("活动建造", amount=5)
        self._record("轻型建造", amount=1)
        target = next(
            entry for entry in self._service.listCategories(
                RESOURCE_TYPE_CUBE, RESOURCE_DIRECTION_EXPENSE
            )
            if entry.name == "活动建造"
        )

        result = self._service.renameCategory(target.id, "活动建造复刻")

        self.assertTrue(result.success)
        self.assertIn("同步 2 笔", result.toStatusBarMessage())
        rows = self._query(
            "SELECT category, amount FROM resource_transaction ORDER BY amount DESC"
        )
        self.assertEqual(rows[0], ("活动建造复刻", 30))
        self.assertEqual(rows[1], ("活动建造复刻", 5))
        self.assertEqual(rows[2], ("轻型建造", 1))
        self.assertEqual(self._query("SELECT COUNT(*) FROM resource_transaction")[0][0], 3)
        self.assertNotIn("活动建造", self._names())
        self.assertIn("活动建造复刻", self._entryNames())

    def testRenameWithoutUsageSkipsSyncMessage(self):
        """没有关联明细时改名不提示同步。"""
        target = next(
            entry for entry in self._service.listCategories(
                RESOURCE_TYPE_CUBE, RESOURCE_DIRECTION_EXPENSE
            )
            if entry.name == "军部研究"
        )

        result = self._service.renameCategory(target.id, "军部研发")

        self.assertTrue(result.success)
        self.assertNotIn("同步", result.toStatusBarMessage())
        self.assertIn("军部研发", self._names())

    def testRenameRejectsDuplicate(self):
        """改名撞上同组已有名称时被拒绝，两个名称都保留。"""
        target = next(
            entry for entry in self._service.listCategories(
                RESOURCE_TYPE_CUBE, RESOURCE_DIRECTION_EXPENSE
            )
            if entry.name == "活动建造"
        )

        with self.assertRaises(ValidationError) as context:
            self._service.renameCategory(target.id, "轻型建造")

        self.assertIn("已存在", str(context.exception))
        self.assertIn("活动建造", self._names())
        self.assertIn("轻型建造", self._names())

    def testRenameToSameNameIsNoop(self):
        """改成原名不算写入。"""
        target = next(
            entry for entry in self._service.listCategories(
                RESOURCE_TYPE_CUBE, RESOURCE_DIRECTION_EXPENSE
            )
            if entry.name == "活动建造"
        )

        result = self._service.renameCategory(target.id, " 活动建造 ")

        self.assertFalse(result.success)
        self.assertIn("名称未变化", result.toStatusBarMessage())

    def testRenameMissingItemRejected(self):
        """字典项不存在时给出可读错误。"""
        with self.assertRaises(ValidationError):
            self._service.renameCategory(999999, "不存在的类型")

    def testRenameKeepsUniqueKey(self):
        """改名后唯一键仍成立，且原名的种子不会在重启时复活。"""
        target = next(
            entry for entry in self._service.listCategories(
                RESOURCE_TYPE_CUBE, RESOURCE_DIRECTION_INCOME
            )
            if entry.name == "补给商店"
        )
        self._service.renameCategory(target.id, "补给兑换")

        ensureResourceStatisticsSchema(self._db_path)

        names = self._names(RESOURCE_TYPE_CUBE, RESOURCE_DIRECTION_INCOME)
        self.assertIn("补给兑换", names)
        self.assertNotIn("补给商店", names)


class TestMoveCategory(_TempCategoryDatabaseCase):
    """排序测试。"""

    def testMoveUpAndDownPersist(self):
        """上移 / 下移改变顺序，重启后仍保留。"""
        entries = self._service.listCategories(RESOURCE_TYPE_CUBE, RESOURCE_DIRECTION_INCOME)
        moved = entries[-1]

        result = self._service.moveCategory(moved.id, -1)

        self.assertTrue(result.success)
        self.assertIn("已上移", result.toStatusBarMessage())
        expected = CUBE_INCOME_ORDER[:-2] + [CUBE_INCOME_ORDER[-1], CUBE_INCOME_ORDER[-2]]
        self.assertEqual(self._names(RESOURCE_TYPE_CUBE, RESOURCE_DIRECTION_INCOME), expected)

        ensureResourceStatisticsSchema(self._db_path)
        self.assertEqual(self._names(RESOURCE_TYPE_CUBE, RESOURCE_DIRECTION_INCOME), expected)

        entries = self._service.listCategories(RESOURCE_TYPE_CUBE, RESOURCE_DIRECTION_INCOME)
        self._service.moveCategory(entries[0].id, 1)
        expected_down = expected[:]
        expected_down[0], expected_down[1] = expected_down[1], expected_down[0]
        self.assertEqual(
            self._names(RESOURCE_TYPE_CUBE, RESOURCE_DIRECTION_INCOME), expected_down
        )

        ensureResourceStatisticsSchema(self._db_path)
        self.assertEqual(
            self._names(RESOURCE_TYPE_CUBE, RESOURCE_DIRECTION_INCOME), expected_down
        )

    def testMoveRenumbersSortOrder(self):
        """移动后整组序号重排为 10、20、30……不留重复值。"""
        entries = self._service.listCategories(RESOURCE_TYPE_CUBE, RESOURCE_DIRECTION_EXPENSE)
        self._service.moveCategory(entries[1].id, -1)

        sort_orders = [
            row[0] for row in self._query(
                "SELECT sort_order FROM resource_category"
                " WHERE resource_type = 'cube' AND direction = 'expense'"
                " ORDER BY sort_order"
            )
        ]
        self.assertEqual(sort_orders, [10, 20, 30, 40, 50, 60, 70])

    def testMoveAtEdgesReportsWithoutWriting(self):
        """首项上移、末项下移只给提示，不写库。"""
        entries = self._service.listCategories(RESOURCE_TYPE_CUBE, RESOURCE_DIRECTION_EXPENSE)

        top_result = self._service.moveCategory(entries[0].id, -1)
        bottom_result = self._service.moveCategory(entries[-1].id, 1)

        self.assertFalse(top_result.success)
        self.assertIn("已经是最前", top_result.toStatusBarMessage())
        self.assertFalse(bottom_result.success)
        self.assertIn("已经是最后", bottom_result.toStatusBarMessage())
        self.assertEqual(self._names(), CUBE_EXPENSE_ORDER)

    def testMoveAcrossInactiveItem(self):
        """停用的类型仍占排位，移动时按完整列表计算。"""
        entries = self._service.listCategories(RESOURCE_TYPE_CUBE, RESOURCE_DIRECTION_EXPENSE)
        self._service.setCategoryActive(entries[1].id, False)

        self._service.moveCategory(entries[2].id, -1)

        self.assertEqual(self._names()[:3], ["轻型建造", "特型建造", "重型建造"])

    def testInvalidOffsetRejected(self):
        """偏移量只能是 ±1。"""
        entries = self._service.listCategories(RESOURCE_TYPE_CUBE, RESOURCE_DIRECTION_EXPENSE)

        with self.assertRaises(ValidationError):
            self._service.moveCategory(entries[0].id, 2)


class TestToggleActive(_TempCategoryDatabaseCase):
    """停用 / 启用测试。"""

    def testRetireHidesFromEntryDropdownButKeepsHistory(self):
        """停用后下拉不再出现，历史明细与统计口径不变。"""
        self._record("活动建造", amount=30)
        target = next(
            entry for entry in self._service.listCategories(
                RESOURCE_TYPE_CUBE, RESOURCE_DIRECTION_EXPENSE
            )
            if entry.name == "活动建造"
        )

        result = self._service.setCategoryActive(target.id, False)

        self.assertTrue(result.success)
        self.assertIn("已停用", result.toStatusBarMessage())
        self.assertNotIn("活动建造", self._entryNames())
        self.assertEqual(
            self._query("SELECT category, amount FROM resource_transaction"),
            [("活动建造", 30)],
        )
        retired = next(
            entry for entry in self._service.listCategories(
                RESOURCE_TYPE_CUBE, RESOURCE_DIRECTION_EXPENSE
            )
            if entry.name == "活动建造"
        )
        self.assertFalse(retired.is_active)
        self.assertEqual(retired.usage_count, 1)

    def testRecordWithRetiredCategoryRejected(self):
        """停用类型即便从别处传入也不能再记账。"""
        target = next(
            entry for entry in self._service.listCategories(
                RESOURCE_TYPE_CUBE, RESOURCE_DIRECTION_EXPENSE
            )
            if entry.name == "活动建造"
        )
        self._service.setCategoryActive(target.id, False)

        with self.assertRaises(ValidationError):
            self._record("活动建造")

    def testEnableBringsBackToDropdown(self):
        """重新启用后回到下拉，并保持原排序。"""
        target = next(
            entry for entry in self._service.listCategories(
                RESOURCE_TYPE_CUBE, RESOURCE_DIRECTION_EXPENSE
            )
            if entry.name == "活动建造"
        )
        self._service.setCategoryActive(target.id, False)

        result = self._service.setCategoryActive(target.id, True)

        self.assertTrue(result.success)
        self.assertIn("已启用", result.toStatusBarMessage())
        self.assertIn("活动建造", self._entryNames())
        self.assertEqual(self._entryNames().index("活动建造"), CUBE_EXPENSE_ORDER.index("活动建造"))

    def testCannotRetireLastActive(self):
        """每组至少保留一个启用中的类型。"""
        entries = self._service.listCategories(RESOURCE_TYPE_CUBE, RESOURCE_DIRECTION_EXPENSE)
        for entry in entries[:-1]:
            self._service.setCategoryActive(entry.id, False)

        with self.assertRaises(ValidationError) as context:
            self._service.setCategoryActive(entries[-1].id, False)

        self.assertIn("至少保留一个", str(context.exception))
        active = [entry for entry in self._service.listCategories(
            RESOURCE_TYPE_CUBE, RESOURCE_DIRECTION_EXPENSE
        ) if entry.is_active]
        self.assertEqual([entry.name for entry in active], ["军部研究"])

    def testToggleToSameStateIsNoop(self):
        """重复启用 / 停用不再写库。"""
        target = next(
            entry for entry in self._service.listCategories(
                RESOURCE_TYPE_CUBE, RESOURCE_DIRECTION_EXPENSE
            )
            if entry.name == "活动建造"
        )

        result = self._service.setCategoryActive(target.id, True)

        self.assertFalse(result.success)
        self.assertIn("已经是启用状态", result.toStatusBarMessage())


class TestRestartKeepsCustomizations(_TempCategoryDatabaseCase):
    """启动流程不再覆盖用户维护结果。"""

    def testRenameMoveRetireSurviveRestart(self):
        """改名、排序、停用在重复执行建表引导后保持不变。"""
        entries = self._service.listCategories(RESOURCE_TYPE_CUBE, RESOURCE_DIRECTION_EXPENSE)
        last = entries[-1]
        self._service.moveCategory(last.id, -1)
        self._service.renameCategory(last.id, "军部研发")
        self._service.setCategoryActive(entries[0].id, False)

        ensureResourceStatisticsSchema(self._db_path)
        ensureResourceStatisticsSchema(self._db_path)

        rows = self._query(
            "SELECT name, sort_order, is_active FROM resource_category"
            " WHERE resource_type = 'cube' AND direction = 'expense' ORDER BY sort_order"
        )
        self.assertEqual(
            rows,
            [
                ("轻型建造", 10, 0),
                ("重型建造", 20, 1),
                ("特型建造", 30, 1),
                ("活动建造", 40, 1),
                ("祈愿建造", 50, 1),
                ("军部研发", 60, 1),
                ("开发船坞", 70, 1),
            ],
        )
        self.assertEqual(self._query("SELECT COUNT(*) FROM resource_category")[0][0], 41)


if __name__ == "__main__":
    unittest.main()
