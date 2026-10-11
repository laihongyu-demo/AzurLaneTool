"""
认知觉醒 / 界限突破面板操作逻辑单元测试。

覆盖：
- 认知觉醒：选中舰娘后默认选中第一个可觉醒阶段，按钮可用
- 认知觉醒：觉醒成功后保留选中的舰娘，并默认选中下一阶段（便于连续觉醒）
- 认知觉醒：升到认知觉醒Ⅱ后该舰娘离开列表，选择自然清空
- 界限突破：单次突破成功后保留选中的舰娘与最新星级（便于连续升星）
- 界限突破：升到满星后该舰娘离开列表，选择自然清空
"""

import os
import shutil
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtWidgets import QApplication, QMessageBox  # noqa: E402

from utils.constants import DEFAULT_DB_PATH  # noqa: E402
from utils.db_connection import DatabaseConnection  # noqa: E402

CREATE_SQL = [
    """
    CREATE TABLE codex_group (
        codex_id TEXT NOT NULL PRIMARY KEY,
        ship_name TEXT,
        ship_level TEXT DEFAULT '未觉醒',
        ship_star INTEGER,
        ship_rarity TEXT,
        ship_typ TEXT,
        ship_group TEXT,
        ship_aid NUMERIC NOT NULL,
        ship_camp TEXT,
        ship_liking TEXT DEFAULT '陌生',
        oath_status TEXT DEFAULT 'N',
        codex_unlock TEXT DEFAULT 'N',
        date_edit NUMERIC
    )
    """,
    """
    CREATE TABLE codex_tp (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        codex_id TEXT NOT NULL,
        ship_name TEXT,
        ship_camp TEXT,
        ship_typ TEXT,
        tp_value INTEGER,
        unlock_cond TEXT,
        tp_unlock TEXT DEFAULT 'N',
        date_edit DATE
    )
    """,
    """
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
        buff_unlock TEXT DEFAULT 'N'
    )
    """,
]

# (codex_id, 名称, 等级, 星级, 稀有度, 分组, 实装日期, 解锁)
# ship_aid 越大的排在列表越前（findAwakenable / findLimitBreakable 均按 ship_aid 倒序）
FIXTURE = [
    ('9001', '测试未觉醒', '未觉醒', 3, 'SSR', '常规', '2026/01/05', 'Y'),
    ('9002', '测试五阶', '认知觉醒五阶', 6, 'SSR', '常规', '2026/01/04', 'Y'),
    ('9003', '测试满星', '认知觉醒五阶', 6, 'SSR', '常规', '2026/01/03', 'Y'),
    ('9004', '测试四星', '认知觉醒五阶', 4, 'SSR', '常规', '2026/01/02', 'Y'),
    ('9005', '测试已满级', '认知觉醒Ⅱ', 6, 'SSR', '常规', '2026/01/01', 'Y'),
    ('9006', '测试未解锁', '未觉醒', 3, 'SSR', '常规', '2025/12/31', 'N'),
    ('9007', '测试改造', 'null', 0, 'SSR', '改造', '2025/12/30', 'Y'),
]

APP = QApplication.instance() or QApplication([])


class ShipActionPanelTestCase(unittest.TestCase):
    """面板测试基类：每个用例使用独立临时数据库。"""

    def setUp(self):
        """测试初始化。"""
        self._test_db_dir = tempfile.mkdtemp()
        self._test_db_path = os.path.join(self._test_db_dir, "test_panels.db")
        DatabaseConnection.setDbPath(self._test_db_path)
        self._createTestDatabase()

    def tearDown(self):
        """测试清理。"""
        DatabaseConnection.setDbPath(DEFAULT_DB_PATH)
        if os.path.exists(self._test_db_dir):
            shutil.rmtree(self._test_db_dir)

    def _createTestDatabase(self):
        """创建测试数据库。"""
        conn = sqlite3.connect(self._test_db_path)
        cursor = conn.cursor()
        for sql in CREATE_SQL:
            cursor.execute(sql)

        for codex_id, name, level, star, rarity, group, aid, unlock in FIXTURE:
            cursor.execute(
                """
                INSERT INTO codex_group (codex_id, ship_name, ship_level, ship_star, ship_rarity,
                       ship_typ, ship_group, ship_aid, ship_camp, codex_unlock)
                VALUES (?, ?, ?, ?, ?, '驱逐舰', ?, ?, '白鹰联邦', ?)
                """,
                (codex_id, name, level, star, rarity, group, aid, unlock)
            )

        conn.commit()
        conn.close()

    def _shipRow(self, codex_id: str):
        """查询图鉴记录。"""
        conn = sqlite3.connect(self._test_db_path)
        conn.row_factory = sqlite3.Row
        try:
            return conn.execute(
                "SELECT * FROM codex_group WHERE codex_id = ?", (codex_id,)
            ).fetchone()
        finally:
            conn.close()

    def _indexOf(self, combo, codex_id: str) -> int:
        """在下拉项中按图鉴ID查找索引。"""
        target = str(codex_id)
        for index, (_, data) in enumerate(combo._items):
            if str(data) == target:
                return index
        return -1


class TestAwakenPanel(ShipActionPanelTestCase):
    """认知觉醒面板测试类。"""

    def setUp(self):
        """测试初始化。"""
        super().setUp()
        from views.widgets.awaken_panel import AwakenPanel
        self._panel = AwakenPanel()

    def tearDown(self):
        """测试清理。"""
        self._panel.deleteLater()
        super().tearDown()

    def _select(self, codex_id: str) -> None:
        """选中指定舰娘。"""
        index = self._indexOf(self._panel._shipComboBox, codex_id)
        self.assertGreaterEqual(index, 0, f'{codex_id} 应出现在可觉醒列表中')
        self._panel._shipComboBox.setCurrentIndex(index)
        self._panel._onShipSelected(index)

    def testDefaultsToFirstAvailableLevel(self):
        """选中舰娘后默认选中第一个可觉醒阶段，且觉醒按钮可用。"""
        self._select('9001')

        self.assertEqual(self._panel._levelComboBox.currentIndex(), 0)
        self.assertEqual(self._panel._levelComboBox.currentText(), '认知觉醒一阶')
        self.assertTrue(self._panel._levelComboBox.isEnabled())
        self.assertTrue(self._panel._awakenBtn.isEnabled())

    def testDefaultsToNextStageForHigherLevelShip(self):
        """高阶段舰娘的默认阶段为其下一阶。"""
        self._select('9002')

        self.assertEqual(self._panel._levelComboBox.currentIndex(), 0)
        self.assertEqual(self._panel._levelComboBox.currentText(), '认知觉醒Ⅱ')

    def testKeepsSelectionAfterAwaken(self):
        """觉醒成功后保留选中的舰娘，并默认选中下一阶段。"""
        self._select('9001')
        level_index = self._panel._levelComboBox.currentIndex()

        with patch.object(QMessageBox, 'question', return_value=QMessageBox.Yes):
            self._panel._onAwakenClicked()

        row = self._shipRow('9001')
        self.assertEqual(row['ship_level'], '认知觉醒一阶')

        self.assertEqual(self._panel._shipComboBox.currentData(), '9001')
        self.assertEqual(self._panel._shipComboBox.currentIndex(),
                         self._indexOf(self._panel._shipComboBox, '9001'))
        self.assertEqual(self._panel._currentLevelLabel.text(), '认知觉醒一阶')
        self.assertEqual(self._panel._levelComboBox.currentIndex(), level_index)
        self.assertEqual(self._panel._levelComboBox.currentText(), '认知觉醒二阶')
        self.assertTrue(self._panel._awakenBtn.isEnabled())

    def testSelectionClearedAfterReachingMaxLevel(self):
        """升到认知觉醒Ⅱ后该舰娘离开列表，选择与按钮复位。"""
        self._select('9002')
        self.assertEqual(self._panel._levelComboBox.currentText(), '认知觉醒Ⅱ')

        with patch.object(QMessageBox, 'question', return_value=QMessageBox.Yes):
            self._panel._onAwakenClicked()

        row = self._shipRow('9002')
        self.assertEqual(row['ship_level'], '认知觉醒Ⅱ')

        self.assertEqual(self._indexOf(self._panel._shipComboBox, '9002'), -1)
        self.assertEqual(self._panel._shipComboBox.currentIndex(), -1)
        self.assertFalse(self._panel._awakenBtn.isEnabled())
        self.assertEqual(self._panel._currentLevelLabel.text(), '-')

    def testCancelledAwakenKeepsSelection(self):
        """取消确认时不改数据、不刷新列表。"""
        self._select('9001')

        with patch.object(QMessageBox, 'question', return_value=QMessageBox.No):
            self._panel._onAwakenClicked()

        self.assertEqual(self._shipRow('9001')['ship_level'], '未觉醒')
        self.assertEqual(self._panel._shipComboBox.currentData(), '9001')


class TestLimitBreakPanel(ShipActionPanelTestCase):
    """界限突破面板测试类。"""

    def setUp(self):
        """测试初始化。"""
        super().setUp()
        from views.widgets.limit_break_panel import LimitBreakPanel
        self._panel = LimitBreakPanel()

    def tearDown(self):
        """测试清理。"""
        self._panel.deleteLater()
        super().tearDown()

    def _select(self, codex_id: str) -> None:
        """选中指定舰娘。"""
        index = self._indexOf(self._panel._shipComboBox, codex_id)
        self.assertGreaterEqual(index, 0, f'{codex_id} 应出现在可突破列表中')
        self._panel._shipComboBox.setCurrentIndex(index)
        self._panel._onShipSelected(index)

    def testKeepsSelectionAfterLimitBreak(self):
        """单次突破成功后保留选中的舰娘，并显示最新星级。"""
        self._select('9001')
        self.assertEqual(self._panel._currentStarLabel.text(), '3')

        with patch.object(QMessageBox, 'question', return_value=QMessageBox.Yes):
            self._panel._onLimitBreakClicked()

        row = self._shipRow('9001')
        self.assertEqual(row['ship_star'], 4)

        self.assertEqual(self._panel._shipComboBox.currentData(), '9001')
        self.assertEqual(self._panel._shipComboBox.currentIndex(),
                         self._indexOf(self._panel._shipComboBox, '9001'))
        self.assertEqual(self._panel._currentStarLabel.text(), '4')
        self.assertTrue(self._panel._limitBreakBtn.isEnabled())
        self.assertTrue(self._panel._limitBreakMaxBtn.isEnabled())

    def testConsecutiveLimitBreakOnSameShip(self):
        """连续点击突破可持续升星；升到满星后该舰娘离开列表、选择复位。"""
        self._select('9004')   # 4 星 SSR，满星为 6

        with patch.object(QMessageBox, 'question', return_value=QMessageBox.Yes):
            self._panel._onLimitBreakClicked()          # 4 星 -> 5 星
            self.assertEqual(self._panel._currentStarLabel.text(), '5')
            self.assertEqual(self._panel._shipComboBox.currentData(), '9004')
            self.assertTrue(self._panel._limitBreakBtn.isEnabled())

            self._panel._onLimitBreakClicked()          # 5 星 -> 6 星（满星）

        self.assertEqual(self._shipRow('9004')['ship_star'], 6)
        self.assertEqual(self._indexOf(self._panel._shipComboBox, '9004'), -1)
        self.assertFalse(self._panel._limitBreakBtn.isEnabled())
        self.assertEqual(self._panel._currentStarLabel.text(), '-')

    def testSelectionClearedAfterReachingMaxStar(self):
        """突破至满星后该舰娘离开列表，选择与按钮复位。"""
        self._select('9004')
        self._panel._limitBreakMaxBtn.isEnabled()

        with patch.object(QMessageBox, 'question', return_value=QMessageBox.Yes):
            self._panel._onLimitBreakMaxClicked()

        self.assertEqual(self._shipRow('9004')['ship_star'], 6)
        self.assertEqual(self._indexOf(self._panel._shipComboBox, '9004'), -1)
        self.assertEqual(self._panel._shipComboBox.currentIndex(), -1)
        self.assertFalse(self._panel._limitBreakBtn.isEnabled())
        self.assertFalse(self._panel._limitBreakMaxBtn.isEnabled())
        self.assertEqual(self._panel._currentStarLabel.text(), '-')

    def testManualRefreshClearsSelection(self):
        """手动刷新（未指定保留项）仍会清空选择。"""
        self._select('9001')

        self._panel.refreshData()

        self.assertEqual(self._panel._shipComboBox.currentIndex(), -1)
        self.assertFalse(self._panel._limitBreakBtn.isEnabled())


if __name__ == "__main__":
    unittest.main()
