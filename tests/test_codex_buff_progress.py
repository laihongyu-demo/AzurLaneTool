"""
科技属性看板单元测试。

覆盖：Repository 按 buff_typ 汇总 buff_value、Service 补齐 9 项与缺表降级、
窗口表格渲染与错误降级。
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
    """Repository 按 buff_typ 汇总测试。"""

    def testAggregatesBuffValueByBuffTyp(self):
        """耐久 / 炮击分别汇总总属性值与已解锁属性值。"""
        rows = CodexBuffRepository(self._db_path).getProgressByBuffTyp()
        by_buff = {row["buff_typ"]: row for row in rows}

        durability = by_buff["耐久"]
        self.assertEqual(durability["total_value"], 4)
        self.assertEqual(durability["unlocked_value"], 4)

        gunnery = by_buff["炮击"]
        self.assertEqual(gunnery["total_value"], 3)
        self.assertEqual(gunnery["unlocked_value"], 2)

    def testMissingTableRaisesDatabaseError(self):
        """缺表时 Repository 抛 DatabaseError，由 Service 负责降级。"""
        empty_db = os.path.join(self._temp_dir, "empty.db")
        with self.assertRaises(DatabaseError):
            CodexBuffRepository(empty_db).getProgressByBuffTyp()


class _StubBuffRepository:
    """返回固定汇总行的仓储桩。"""

    def __init__(self, rows):
        self._rows = rows

    def getProgressByBuffTyp(self):
        return self._rows


class _MissingTableBuffRepository:
    """模拟旧库缺表。"""

    def getProgressByBuffTyp(self):
        raise DatabaseError("no such table: codex_buff")


class TestStatisticsServiceBuffSummary(unittest.TestCase):
    """Service 补齐与降级测试。"""

    def testFillsAllBuffTypsInWhitelistOrder(self):
        """按 BUFF_TYPS 顺序返回 9 项，未知属性被忽略。"""
        service = StatisticsService(
            buff_repository=_StubBuffRepository([
                {"buff_typ": "耐久", "total_value": 5, "unlocked_value": 4},
                {"buff_typ": "炮击", "total_value": 3, "unlocked_value": 2},
                {"buff_typ": "未知属性", "total_value": 9, "unlocked_value": 9},
            ])
        )

        result = service.getBuffStatisticsByBuffTyp()

        self.assertEqual([item.buff_typ for item in result], options.BUFF_TYPS)
        self.assertEqual(len(result), 9)
        durability = next(item for item in result if item.buff_typ == "耐久")
        self.assertEqual(durability.unlocked_value, 4)
        self.assertEqual(durability.total_value, 5)
        self.assertEqual(durability.completion_rate, 80.0)
        self.assertNotIn("未知属性", [item.buff_typ for item in result])

    def testMissingTableDegradesToNineZeros(self):
        """缺表时返回 9 项全 0，不抛异常。"""
        service = StatisticsService(
            buff_repository=_MissingTableBuffRepository()
        )

        result = service.getBuffStatisticsByBuffTyp()

        self.assertEqual(len(result), 9)
        self.assertTrue(all(item.total_value == 0 for item in result))
        self.assertTrue(all(item.completion_rate == 0 for item in result))


class _StubDialogService:
    """窗口测试用的统计服务桩。"""

    def __init__(self, rows):
        self._rows = rows

    def getBuffStatisticsByBuffTyp(self):
        return self._rows


class _FailingDialogService:
    """窗口错误降级测试桩。"""

    def getBuffStatisticsByBuffTyp(self):
        raise DatabaseError("no such table: codex_buff")


class TestCodexBuffDialog(unittest.TestCase):
    """窗口渲染与错误降级测试。"""

    def _summaries(self):
        rows = [CodexBuffValueSummary(buff_typ=buff_typ) for buff_typ in options.BUFF_TYPS]
        rows[0] = CodexBuffValueSummary(
            buff_typ="耐久",
            total_value=5,
            unlocked_value=4,
        )
        return rows

    def testRendersNineRowsAndValueColumns(self):
        """窗口固定渲染 9 行，主值为已获得汇总值。"""
        dialog = CodexBuffDialog(_StubDialogService(self._summaries()))

        self.assertEqual(dialog._table.rowCount(), 9)
        self.assertEqual(dialog._table.columnCount(), 4)
        self.assertEqual(dialog._table.item(0, 0).text(), "耐久")
        self.assertEqual(dialog._table.item(0, 1).text(), "4")
        self.assertEqual(dialog._table.item(0, 2).text(), "5")
        self.assertEqual(dialog._table.item(0, 3).text(), "80.0%")
        self.assertIn("已获得汇总值 4 / 总汇总值 5", dialog._table.item(0, 0).toolTip())

    def testDatabaseErrorRendersMessageWithoutModal(self):
        """缺表时表格清空并显示错误文案，不弹模态框。"""
        dialog = CodexBuffDialog(_FailingDialogService())

        self.assertEqual(dialog._table.rowCount(), 0)
        self.assertIn("数据库错误", dialog._statusLabel.text())
