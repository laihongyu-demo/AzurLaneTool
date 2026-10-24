"""
贸易许可证服务单元测试。

覆盖：状态计算、期初登记、购买 / 续约窗口、过期重开、修正到期日、
删除最近记录与常规撤销排除。
"""

import os
import shutil
import sqlite3
import tempfile
import unittest
from datetime import date, datetime, timedelta
from unittest.mock import patch

from services.resource_entry_service import ResourceEntryService
from services.trade_license_service import TradeLicenseService
from utils.constants import (
    RESOURCE_DIRECTION_INCOME, RESOURCE_TYPE_RED_GEM, TRADE_LICENSE_CATEGORY,
)
from utils.db_connection import DatabaseConnection
from utils.db_schema import ensureResourceStatisticsSchema
from utils.exceptions import ValidationError

TODAY = date(2026, 10, 24)
NOW = datetime(2026, 10, 24, 12, 0, 0)


class _TempTradeLicenseCase(unittest.TestCase):
    """带贸易许可证表的临时库测试基类。"""

    def setUp(self):
        self._original_db_path = DatabaseConnection.getDbPath()
        self._temp_dir = tempfile.mkdtemp(prefix="azurlane_trade_license_")
        self._db_path = os.path.join(self._temp_dir, "trade.db")
        DatabaseConnection.setDbPath(self._db_path)
        ensureResourceStatisticsSchema(self._db_path)
        self._service = TradeLicenseService()

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

    def _purchaseRows(self):
        """购买记录。"""
        return self._query(
            "SELECT start_date, end_date, days, amount, transaction_id"
            " FROM trade_license_purchase ORDER BY id"
        )


class TestStatus(_TempTradeLicenseCase):
    """状态计算测试。"""

    def testNoRecord(self):
        """无记录时为未购买、剩余 0、可购买。"""
        status = self._service.getStatus(TODAY)

        self.assertFalse(status.has_purchase)
        self.assertEqual(status.remaining_days, 0)
        self.assertIsNone(status.expire_date)
        self.assertTrue(status.can_renew)

    def testRegisterInitialExpiry(self):
        """期初登记不写 500 明细，按 30 天反推生效日。"""
        result = self._service.registerInitialExpiry(TODAY + timedelta(days=10), NOW)

        self.assertTrue(result.success)
        self.assertTrue(result.status.has_purchase)
        self.assertEqual(result.status.remaining_days, 11)
        self.assertEqual(self._query("SELECT COUNT(*) FROM resource_transaction")[0][0], 0)
        rows = self._purchaseRows()
        self.assertEqual(rows, [
            (
                (TODAY + timedelta(days=10) - timedelta(days=29)).strftime("%Y-%m-%d"),
                (TODAY + timedelta(days=10)).strftime("%Y-%m-%d"),
                30, 0, None,
            )
        ])

    def testRegisterRejectedWhenRecordExists(self):
        """已有记录时不能再次期初登记。"""
        self._service.registerInitialExpiry(TODAY + timedelta(days=10), NOW)

        with self.assertRaises(ValidationError):
            self._service.registerInitialExpiry(TODAY + timedelta(days=20), NOW)


class TestRenew(_TempTradeLicenseCase):
    """购买 / 续约测试。"""

    def testFirstPurchaseWrites500(self):
        """首次购买立即写 500 红尖尖并记录 30 天。"""
        result = self._service.renew(NOW)

        self.assertTrue(result.success)
        self.assertEqual(result.status.remaining_days, 30)
        rows = self._query(
            "SELECT resource_type, direction, category, amount FROM resource_transaction"
        )
        self.assertEqual(rows, [(RESOURCE_TYPE_RED_GEM, RESOURCE_DIRECTION_INCOME,
                                 TRADE_LICENSE_CATEGORY, 500)])
        purchase = self._purchaseRows()[0]
        self.assertEqual(purchase[2:], (30, 500, 1))
        self.assertEqual(purchase[0], TODAY.strftime("%Y-%m-%d"))
        self.assertEqual(
            purchase[1], (TODAY + timedelta(days=29)).strftime("%Y-%m-%d")
        )

    def testRenewBlockedBeforeWindow(self):
        """剩余 8 天以上禁止续约。"""
        self._service.registerInitialExpiry(TODAY + timedelta(days=20), NOW)

        with self.assertRaises(ValidationError):
            self._service.renew(NOW)
        self.assertEqual(self._query("SELECT COUNT(*) FROM resource_transaction")[0][0], 0)

    def testRenewWithinWindowExtendsFromCurrentExpiry(self):
        """剩余 7 天时续约从当前到期日次日顺延 30 天。"""
        self._service.registerInitialExpiry(TODAY + timedelta(days=6), NOW)

        result = self._service.renew(NOW)

        self.assertTrue(result.success)
        self.assertEqual(result.status.remaining_days, 37)
        rows = self._purchaseRows()
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[1][0], (TODAY + timedelta(days=7)).strftime("%Y-%m-%d"))
        self.assertEqual(rows[1][1], (TODAY + timedelta(days=36)).strftime("%Y-%m-%d"))
        self.assertEqual(rows[1][2:], (30, 500, 1))

    def testExpiredRenewStartsToday(self):
        """已过期后购买从今天重新开始 30 天。"""
        self._service.registerInitialExpiry(TODAY + timedelta(days=2), NOW)
        later = NOW + timedelta(days=10)

        result = self._service.renew(later)

        self.assertTrue(result.success)
        self.assertEqual(result.status.expire_date, (later.date() + timedelta(days=29)).strftime("%Y-%m-%d"))
        rows = self._purchaseRows()
        self.assertEqual(rows[1][0], later.date().strftime("%Y-%m-%d"))


class TestCorrections(_TempTradeLicenseCase):
    """修正 / 删除最近一条测试。"""

    def testUpdateInitialExpiry(self):
        """修正期初登记的到期日并按 30 天反推生效日。"""
        self._service.registerInitialExpiry(TODAY + timedelta(days=10), NOW)

        result = self._service.updateLatestEndDate(TODAY + timedelta(days=5), NOW)

        self.assertTrue(result.success)
        self.assertEqual(result.status.remaining_days, 6)
        row = self._purchaseRows()[0]
        self.assertEqual(row[0], (TODAY + timedelta(days=5) - timedelta(days=29)).strftime("%Y-%m-%d"))
        self.assertEqual(row[1], (TODAY + timedelta(days=5)).strftime("%Y-%m-%d"))

    def testUpdateRejectsEndBeforeStart(self):
        """续约记录改到期日不能早于生效日。"""
        self._service.registerInitialExpiry(TODAY + timedelta(days=6), NOW)
        self._service.renew(NOW)

        with self.assertRaises(ValidationError):
            self._service.updateLatestEndDate(TODAY, NOW)

    def testDeleteLatestRollsBack500(self):
        """删除最近一次续约会回滚 500 明细并回到上一条记录。"""
        self._service.registerInitialExpiry(TODAY + timedelta(days=6), NOW)
        self._service.renew(NOW)
        self.assertEqual(self._query("SELECT COUNT(*) FROM resource_transaction")[0][0], 1)

        with patch("utils.time_source.today", return_value=TODAY):
            result = self._service.deleteLatest()

        self.assertTrue(result.success)
        self.assertEqual(self._query("SELECT COUNT(*) FROM resource_transaction")[0][0], 0)
        self.assertEqual(len(self._purchaseRows()), 1)
        self.assertEqual(result.status.remaining_days, 7)

    def testUndoDoesNotTouchTradeLicenseTransaction(self):
        """常规「撤销上一笔」不会把月卡 500 当成可撤销录入。"""
        entry_service = ResourceEntryService()
        entry_service.record(
            "礼包", RESOURCE_DIRECTION_INCOME, 5, NOW, RESOURCE_TYPE_RED_GEM
        )
        self._service.renew(NOW)

        undoable = entry_service.getUndoableEntry(RESOURCE_TYPE_RED_GEM)

        self.assertIsNotNone(undoable)
        self.assertEqual(undoable.amount, 5)
        self.assertEqual(undoable.category, "礼包")


if __name__ == "__main__":
    unittest.main()
