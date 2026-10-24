"""
红尖尖世界巡游看板面板测试（offscreen）。

覆盖：只显示巡游分组、6 张卡片、档期下拉默认当前期、切换过去期后记账日期跟随。
"""

import os
import shutil
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtWidgets import QApplication  # noqa: E402

from services.cube_task_service import CubeTaskService  # noqa: E402
from services.world_cruise_service import WorldCruiseService  # noqa: E402
from utils.constants import RESOURCE_TYPE_RED_GEM, TASK_PERIOD_CRUISE  # noqa: E402
from utils.db_connection import DatabaseConnection  # noqa: E402
from utils.db_schema import ensureResourceStatisticsSchema  # noqa: E402
from views.widgets.cube_task_board_panel import CubeTaskBoardPanel  # noqa: E402

APP = QApplication.instance() or QApplication([])


class TestRedGemBoard(unittest.TestCase):
    """红尖尖世界巡游看板测试。"""

    def setUp(self):
        self._original_db_path = DatabaseConnection.getDbPath()
        self._temp_dir = tempfile.mkdtemp(prefix="azurlane_red_board_")
        self._db_path = os.path.join(self._temp_dir, "board.db")
        DatabaseConnection.setDbPath(self._db_path)
        ensureResourceStatisticsSchema(self._db_path)
        self._panel = CubeTaskBoardPanel(
            CubeTaskService(resource_type=RESOURCE_TYPE_RED_GEM),
            board_title="世界巡游",
            include_entry=False,
            period_types=(TASK_PERIOD_CRUISE,),
        )

    def tearDown(self):
        self._panel.deleteLater()
        DatabaseConnection.setDbPath(self._original_db_path)
        shutil.rmtree(self._temp_dir, ignore_errors=True)

    def testOnlyCruiseGroupAndSixCards(self):
        """只显示世界巡游一个分组，6 档合计 300。"""
        self.assertEqual(len(self._panel._groups), 1)
        self.assertEqual(self._panel._groups[0].total, 300)
        self.assertEqual(len(self._panel._state_by_code), 6)
        self.assertIsNone(self._panel._entry_panel)
        self.assertEqual(self._panel._current_columns, 1)

    def testPeriodComboDefaultsToCurrentAndSwitchesDate(self):
        """档期下拉默认当前期；切到过去期后记账日期落到该期末日。"""
        self.assertGreaterEqual(self._panel._periodCombo.count(), 2)
        current_key = self._panel._periodCombo.itemData(0)
        self.assertEqual(current_key, WorldCruiseService().getCurrentPeriod().key)

        last_index = self._panel._periodCombo.count() - 1
        last_key = self._panel._periodCombo.itemData(last_index)
        expected = WorldCruiseService().getPeriodByKey(last_key)

        self._panel._periodCombo.setCurrentIndex(last_index)

        self.assertEqual(self._panel._selectedDate(), expected.end)
        self.assertIn(expected.label, self._panel._periodLabel.text())


if __name__ == "__main__":
    unittest.main()
