"""
贸易许可证面板单元测试（offscreen）。

覆盖：初始状态、购买按钮写 500、期初登记、续约窗口按钮禁用、删除回滚。
"""

import os
import shutil
import sqlite3
import tempfile
import unittest
from datetime import date, datetime, timedelta
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtWidgets import QApplication, QDialog, QMessageBox  # noqa: E402

from services.trade_license_service import TradeLicenseService  # noqa: E402
from utils.db_connection import DatabaseConnection  # noqa: E402
from utils.db_schema import ensureResourceStatisticsSchema  # noqa: E402
from views.widgets.trade_license_panel import TradeLicensePanel  # noqa: E402

APP = QApplication.instance() or QApplication([])

TODAY = date(2026, 10, 24)
NOW = datetime(2026, 10, 24, 12, 0, 0)


class TestTradeLicensePanel(unittest.TestCase):
    """贸易许可证面板测试。"""

    def setUp(self):
        self._original_db_path = DatabaseConnection.getDbPath()
        self._temp_dir = tempfile.mkdtemp(prefix="azurlane_trade_panel_")
        self._db_path = os.path.join(self._temp_dir, "trade.db")
        DatabaseConnection.setDbPath(self._db_path)
        ensureResourceStatisticsSchema(self._db_path)
        self._service = TradeLicenseService()
        self._today_patch = patch("utils.time_source.today", return_value=TODAY)
        self._now_patch = patch("utils.time_source.now", return_value=NOW)
        self._today_patch.start()
        self._now_patch.start()
        self._panel = TradeLicensePanel(self._service)

    def tearDown(self):
        self._panel.deleteLater()
        self._today_patch.stop()
        self._now_patch.stop()
        DatabaseConnection.setDbPath(self._original_db_path)
        shutil.rmtree(self._temp_dir, ignore_errors=True)

    def _query(self, sql, params=()):
        """执行只读查询。"""
        conn = sqlite3.connect(self._db_path)
        try:
            return conn.execute(sql, params).fetchall()
        finally:
            conn.close()

    def testInitialState(self):
        """未购买时显示购买按钮与登记入口。"""
        self.assertIn("未购买", self._panel._statusLabel.text())
        self.assertTrue(self._panel._primaryBtn.isEnabled())
        self.assertIn("购买", self._panel._primaryBtn.text())
        self.assertFalse(self._panel._registerBtn.isHidden())
        self.assertTrue(self._panel._editBtn.isHidden())

    def testPurchaseWrites500AndUpdatesStatus(self):
        """点击购买并确认后写 500 红尖尖，按钮变为续约且禁用。"""
        original = QMessageBox.question
        QMessageBox.question = staticmethod(lambda *args, **kwargs: QMessageBox.Yes)
        try:
            self._panel._onPrimaryClicked()
        finally:
            QMessageBox.question = original

        self.assertEqual(self._query("SELECT amount FROM resource_transaction"), [(500,)])
        self.assertIn("剩余 30 天", self._panel._statusLabel.text())
        self.assertTrue(self._panel._primaryBtn.text().startswith("续约"))
        self.assertFalse(self._panel._primaryBtn.isEnabled())
        self.assertFalse(self._panel._editBtn.isHidden())

    def testRegisterInitialExpiry(self):
        """登记已有月卡不写 500 明细。"""
        with patch(
            "views.widgets.trade_license_panel._DateDialog.exec_",
            return_value=QDialog.Accepted,
        ), patch(
            "views.widgets.trade_license_panel._DateDialog.selectedDate",
            return_value=TODAY + timedelta(days=10),
        ):
            self._panel._onRegisterClicked()

        self.assertEqual(self._query("SELECT COUNT(*) FROM resource_transaction")[0][0], 0)
        self.assertIn("剩余 11 天", self._panel._statusLabel.text())

    def testRenewButtonDisabledBeforeWindow(self):
        """剩余 8 天以上时续约按钮禁用。"""
        self._service.registerInitialExpiry(TODAY + timedelta(days=20), NOW)
        self._panel.refreshState()

        self.assertFalse(self._panel._primaryBtn.isEnabled())
        self.assertIn("剩余 21 天", self._statusText())

    def _statusText(self) -> str:
        """状态文案。"""
        return self._panel._statusLabel.text()

    def testDeleteLatestRollsBackTransaction(self):
        """删除最近记录后回滚 500 并回到未购买。"""
        self._service.renew(NOW)
        self._panel.refreshState()

        original = QMessageBox.question
        QMessageBox.question = staticmethod(lambda *args, **kwargs: QMessageBox.Yes)
        try:
            self._panel._onDeleteClicked()
        finally:
            QMessageBox.question = original

        self.assertEqual(self._query("SELECT COUNT(*) FROM resource_transaction")[0][0], 0)
        self.assertIn("未购买", self._panel._statusLabel.text())


if __name__ == "__main__":
    unittest.main()
