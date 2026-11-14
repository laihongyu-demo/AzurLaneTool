"""
科技属性看板单元测试。

覆盖：Repository 按 boost_typ × buff_typ 汇总、Service 补齐 15×9 矩阵与缺表降级、
窗口矩阵渲染（含空组合与合计行）与错误降级。
"""

import os
import shutil
import sqlite3
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtWidgets import QApplication  # noqa: E402

from repositories.codex_repository import CodexBuffRepository  # noqa: E402
from services.statistics_service import (  # noqa: E402
    CodexBuffMatrix,
    CodexBuffMatrixCell,
    CodexBuffValueSummary,
    StatisticsService,
)
from utils import codex_options as options  # noqa: E402
from utils.exceptions import DatabaseError  # noqa: E402
from views.dialogs.codex_buff_dialog import CodexBuffDialog  # noqa: E402

APP = QApplication.instance() or QApplication([])

CREATE_BUFF_TABLE_SQL = """
CREATE TABLE codex_buff (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    codex_id TEXT NOT NULL,
    ship_name TEXT,
    ship_camp TEXT,
    ship_typ TEXT,
    boost_typ TEXT NOT NULL,
    buff_typ TEXT,
    buff_value INTEGER,
    buff_cond TEXT,
    buff_unlock TEXT NOT NULL DEFAULT 'N'
)
"""

FIXTURE_BUFF = [
    ("1", "战列", "耐久", 2, "解锁", "Y"),
    ("1", "战列", "炮击", 1, "Lv.120", "N"),
    ("2", "战列", "耐久", 1, "解锁", "Y"),
    ("2", "战列", "炮击", 2, "Lv.120", "Y"),
    ("3", "战巡", "耐久", 1, "解锁", "Y"),
    ("4", "未知舰种", "未知属性", 9, "解锁", "Y"),
]


class _TempDatabaseCase(unittest.TestCase):
    """提供带 codex_buff 表的临时数据库。"""

    def setUp(self):
        self._temp_dir = tempfile.mkdtemp(prefix="azurlane_buff_")
        self._db_path = os.path.join(self._temp_dir, "test.db")
        conn = sqlite3.connect(self._db_path)
        try:
            conn.executescript(CREATE_BUFF_TABLE_SQL)
            conn.executemany(
                "INSERT INTO codex_buff "
                "(codex_id, boost_typ, buff_typ, buff_value, buff_cond, buff_unlock) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                FIXTURE_BUFF,
            )
            conn.commit()
        finally:
            conn.close()

    def tearDown(self):
        shutil.rmtree(self._temp_dir, ignore_errors=True)


class TestCodexBuffRepository(_TempDatabaseCase):
    """Repository 按舰种 × 属性汇总测试。"""

    def testAggregatesByBoostTypAndBuffTyp(self):
        """战列×耐久 / 战列×炮击分别汇总总值、已获得值与条数。"""
        rows = CodexBuffRepository(self._db_path).getMatrixByBoostTypAndBuffTyp()
        by_pair = {(row["boost_typ"], row["buff_typ"]): row for row in rows}

        durability = by_pair[("战列", "耐久")]
        self.assertEqual(durability["total_value"], 3)
        self.assertEqual(durability["unlocked_value"], 3)
        self.assertEqual(durability["record_count"], 2)

        gunnery = by_pair[("战列", "炮击")]
        self.assertEqual(gunnery["total_value"], 3)
        self.assertEqual(gunnery["unlocked_value"], 2)
        self.assertEqual(gunnery["record_count"], 2)

    def testMissingTableRaisesDatabaseError(self):
        """缺表时 Repository 抛 DatabaseError，由 Service 负责降级。"""
        empty_db = os.path.join(self._temp_dir, "empty.db")
        with self.assertRaises(DatabaseError):
            CodexBuffRepository(empty_db).getMatrixByBoostTypAndBuffTyp()


class _StubBuffRepository:
    """返回固定矩阵行的仓储桩。"""

    def __init__(self, rows):
        self._rows = rows

    def getMatrixByBoostTypAndBuffTyp(self):
        return self._rows


class _MissingTableBuffRepository:
    """模拟旧库缺表。"""

    def getMatrixByBoostTypAndBuffTyp(self):
        raise DatabaseError("no such table: codex_buff")


class TestStatisticsServiceBuffMatrix(unittest.TestCase):
    """Service 15×9 补齐与降级测试。"""

    def testBuildsFullMatrixAndColumnTotals(self):
        """按白名单顺序补齐 15×9；空组合为无记录，列合计由单元格累加。"""
        service = StatisticsService(
            buff_repository=_StubBuffRepository([
                {
                    "boost_typ": "战列",
                    "buff_typ": "耐久",
                    "total_value": 3,
                    "unlocked_value": 2,
                    "record_count": 2,
                },
                {
                    "boost_typ": "风帆",
                    "buff_typ": "机动",
                    "total_value": 5,
                    "unlocked_value": 0,
                    "record_count": 5,
                },
                {
                    "boost_typ": "未知舰种",
                    "buff_typ": "未知属性",
                    "total_value": 9,
                    "unlocked_value": 9,
                    "record_count": 1,
                },
            ])
        )

        matrix = service.getBuffMatrix()

        self.assertEqual(matrix.boost_typs, options.BOOST_TYPS)
        self.assertEqual(matrix.buff_typs, options.BUFF_TYPS)
        self.assertEqual(len(matrix.cells), len(options.BOOST_TYPS) * len(options.BUFF_TYPS))

        battleship = matrix.getCell("战列", "耐久")
        self.assertEqual(battleship.total_value, 3)
        self.assertEqual(battleship.unlocked_value, 2)
        self.assertEqual(battleship.record_count, 2)
        self.assertEqual(battleship.completion_rate, 2 / 3 * 100)

        empty_cell = matrix.getCell("驱逐", "航空")
        self.assertFalse(empty_cell.has_records)

        sail = matrix.getCell("风帆", "机动")
        self.assertTrue(sail.has_records)
        self.assertEqual(sail.unlocked_value, 0)

        totals = {item.buff_typ: item for item in matrix.column_totals}
        self.assertEqual(totals["耐久"].total_value, 3)
        self.assertEqual(totals["耐久"].unlocked_value, 2)
        self.assertEqual(totals["机动"].total_value, 5)
        self.assertEqual(totals["机动"].unlocked_value, 0)

    def testCompatibilitySummaryUsesColumnTotals(self):
        """兼容接口返回矩阵列合计。"""
        service = StatisticsService(
            buff_repository=_StubBuffRepository([
                {
                    "boost_typ": "战列",
                    "buff_typ": "耐久",
                    "total_value": 3,
                    "unlocked_value": 2,
                    "record_count": 2,
                },
            ])
        )

        summaries = service.getBuffStatisticsByBuffTyp()

        self.assertEqual([item.buff_typ for item in summaries], options.BUFF_TYPS)
        self.assertEqual(len(summaries), 9)
        durability = next(item for item in summaries if item.buff_typ == "耐久")
        self.assertEqual(durability.total_value, 3)
        self.assertEqual(durability.unlocked_value, 2)

    def testMissingTableDegradesToEmptyMatrix(self):
        """缺表时返回 15×9 全空矩阵与 9 项 0 合计。"""
        service = StatisticsService(
            buff_repository=_MissingTableBuffRepository()
        )

        matrix = service.getBuffMatrix()

        self.assertEqual(len(matrix.cells), 135)
        self.assertTrue(all(not cell.has_records for cell in matrix.cells.values()))
        self.assertTrue(all(item.total_value == 0 for item in matrix.column_totals))


class _StubDialogService:
    """窗口测试用的统计服务桩。"""

    def __init__(self, matrix):
        self._matrix = matrix

    def getBuffMatrix(self):
        return self._matrix


class _FailingDialogService:
    """窗口错误降级测试桩。"""

    def getBuffMatrix(self):
        raise DatabaseError("no such table: codex_buff")


def _buildMatrix() -> CodexBuffMatrix:
    """构造 15×9 测试矩阵，含一个正常格、一个 0 解锁格与空组合。"""
    boost_typs = list(options.BOOST_TYPS)
    buff_typs = list(options.BUFF_TYPS)
    cells = {
        (boost_typ, buff_typ): CodexBuffMatrixCell(boost_typ, buff_typ)
        for boost_typ in boost_typs
        for buff_typ in buff_typs
    }
    cells[("驱逐", "耐久")] = CodexBuffMatrixCell(
        "驱逐", "耐久", total_value=258, unlocked_value=238, record_count=247
    )
    cells[("风帆", "机动")] = CodexBuffMatrixCell(
        "风帆", "机动", total_value=5, unlocked_value=0, record_count=5
    )
    cells[("维修", "耐久")] = CodexBuffMatrixCell(
        "维修", "耐久", total_value=6, unlocked_value=6, record_count=6
    )

    totals = []
    for buff_typ in buff_typs:
        totals.append(
            CodexBuffValueSummary(
                buff_typ=buff_typ,
                total_value=sum(cells[(boost_typ, buff_typ)].total_value for boost_typ in boost_typs),
                unlocked_value=sum(cells[(boost_typ, buff_typ)].unlocked_value for boost_typ in boost_typs),
            )
        )
    return CodexBuffMatrix(
        boost_typs=boost_typs,
        buff_typs=buff_typs,
        cells=cells,
        column_totals=totals,
    )


class TestCodexBuffDialog(unittest.TestCase):
    """窗口矩阵渲染与错误降级测试。"""

    def testRendersMatrixEmptyCellsAndTotalRow(self):
        """窗口为 16 行 × 10 列，空组合 —，底部合计行按属性汇总。"""
        dialog = CodexBuffDialog(_StubDialogService(_buildMatrix()))

        self.assertEqual(dialog._table.rowCount(), 16)
        self.assertEqual(dialog._table.columnCount(), 10)
        self.assertEqual(dialog._table.item(0, 0).text(), "驱逐")
        self.assertEqual(dialog._table.item(0, 1).text(), "238/258")
        self.assertIn("247 条记录", dialog._table.item(0, 1).toolTip())

        aviation_column = 1 + options.BUFF_TYPS.index("航空")
        self.assertEqual(dialog._table.item(0, aviation_column).text(), "—")

        sail_row = options.BOOST_TYPS.index("风帆")
        mobility_column = 1 + options.BUFF_TYPS.index("机动")
        self.assertEqual(dialog._table.item(sail_row, mobility_column).text(), "0/5")

        maintenance_row = options.BOOST_TYPS.index("维修")
        completed_item = dialog._table.item(maintenance_row, 1)
        self.assertEqual(completed_item.text(), "6/6")
        self.assertEqual(completed_item.background().color().name(), "#e8f5e9")
        self.assertIn("已完成", completed_item.toolTip())

        self.assertEqual(dialog._table.item(15, 0).text(), "合计")
        self.assertEqual(dialog._table.item(15, 1).text(), "244/264")
        self.assertEqual(dialog._table.item(15, mobility_column).text(), "0/5")
        self.assertIn("3 个组合有记录", dialog._statusLabel.text())

    def testDatabaseErrorRendersMessageWithoutModal(self):
        """缺表时表格清空并显示错误文案，不弹模态框。"""
        dialog = CodexBuffDialog(_FailingDialogService())

        self.assertEqual(dialog._table.rowCount(), 0)
        self.assertIn("数据库错误", dialog._statusLabel.text())
