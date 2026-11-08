"""
资源看板头部档期控件的布局测试（offscreen）。

口径：魔方看板的「档期」下拉右边缘必须等于左列分组（「任务」）的右边缘；红尖尖看板
沿用同一尺寸（同样的最小 / 最大宽度与高度），右边缘贴住自身分组。窄屏单列时头部
退回两行，但右边缘仍对齐单个分组的右边缘。
"""

import os
import shutil
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtWidgets import QApplication  # noqa: E402

from services.cube_task_service import CubeTaskService  # noqa: E402
from utils.db_connection import DatabaseConnection  # noqa: E402
from utils.db_schema import ensureResourceStatisticsSchema  # noqa: E402
from views.widgets.cube_task_board_panel import (  # noqa: E402
    PERIOD_COMBO_HEIGHT, PERIOD_COMBO_MAX_WIDTH, PERIOD_COMBO_MIN_WIDTH, CubeTaskBoardPanel,
)
from views.widgets.resource_management_panel import ResourceManagementPanel  # noqa: E402

APP = QApplication.instance() or QApplication([])


class TestBoardHeaderAlignment(unittest.TestCase):
    """档期下拉与分组右边缘的对齐。"""

    def setUp(self):
        self._original_db_path = DatabaseConnection.getDbPath()
        self._temp_dir = tempfile.mkdtemp(prefix="azurlane_layout_")
        self._db_path = os.path.join(self._temp_dir, "layout.db")
        DatabaseConnection.setDbPath(self._db_path)
        ensureResourceStatisticsSchema(self._db_path)
        self._panel = ResourceManagementPanel()
        self._panel.resize(1010, 1400)
        self._panel.show()
        self._settle()

    def tearDown(self):
        self._panel.deleteLater()
        DatabaseConnection.setDbPath(self._original_db_path)
        shutil.rmtree(self._temp_dir, ignore_errors=True)

    def _settle(self) -> None:
        """跑两轮事件循环，让布局与滚动区宽度都刷新。"""
        APP.processEvents()
        APP.processEvents()

    def _right(self, widget) -> int:
        """控件右边缘在面板坐标系下的 x。"""
        return widget.mapTo(self._panel, widget.rect().topRight()).x()

    def _firstGroupRight(self, board) -> int:
        """看板第一个分组的右边缘。"""
        group = board._boardLayout.itemAt(0).widget()
        self.assertIsNotNone(group)
        return self._right(group)

    def testCubePeriodComboAlignsWithTaskGroup(self):
        """魔方：档期下拉右边缘等于「任务」分组右边缘。"""
        board = self._panel._taskBoardPanel

        self.assertEqual(board._headerColumns, 2)
        self.assertLessEqual(abs(self._right(board._periodCombo) - self._firstGroupRight(board)), 1)

    def testRedGemPeriodComboMatchesCubeSize(self):
        """红尖尖：档期下拉与魔方同尺寸，右边缘贴住自身分组。"""
        cube_combo = self._panel._taskBoardPanel._periodCombo
        red_board = self._panel._redGemCruisePanel
        red_combo = red_board._periodCombo

        for combo in (cube_combo, red_combo):
            self.assertEqual(combo.minimumWidth(), PERIOD_COMBO_MIN_WIDTH)
            self.assertEqual(combo.maximumWidth(), PERIOD_COMBO_MAX_WIDTH)
            self.assertEqual(combo.height(), PERIOD_COMBO_HEIGHT)

        self.assertLessEqual(abs(self._right(red_combo) - self._firstGroupRight(red_board)), 1)

        # 宽屏下左列足够宽，两个下拉都能取到自然宽度，尺寸一致
        self._panel.resize(1400, 1400)
        self._settle()
        self.assertEqual(cube_combo.width(), red_combo.width())

    def testRedGemHeaderHidesEmptyRightSegment(self):
        """红尖尖看板只有一个分组：紧凑头部右侧没有内容，不额外占一行。"""
        self.assertEqual(self._panel._redGemCruisePanel._headerColumns, 1)
        self.assertFalse(self._panel._redGemCruisePanel._headerRight.isVisible())

    def testNarrowBoardFallsBackToTwoRowHeader(self):
        """窄屏看板：头部退回两行，档期下拉仍对齐（此时唯一的）分组右边缘。"""
        board = CubeTaskBoardPanel(CubeTaskService())
        board.resize(900, 1200)
        board.show()
        self.addCleanup(board.deleteLater)
        self._settle()

        self.assertEqual(board._headerColumns, 1)
        self.assertTrue(board._headerRight.isVisible())
        combo = board._periodCombo
        group = board._boardLayout.itemAt(0).widget()
        combo_right = combo.mapTo(board, combo.rect().topRight()).x()
        group_right = group.mapTo(board, group.rect().topRight()).x()
        self.assertLessEqual(abs(combo_right - group_right), 1)
        self.assertLessEqual(combo_right, board.width())


if __name__ == "__main__":
    unittest.main()
