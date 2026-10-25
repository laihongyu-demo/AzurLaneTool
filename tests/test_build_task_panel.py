"""
建造任务确认框与看板分流的 offscreen 测试。

覆盖：对话框默认值（轻型 / 不用券）、券勾选后卡池置灰与预览变化、进行中活动文案、
看板点击建造卡片走确认框后再写两笔、取消确认框时不写库、卡片 tooltip 展示收支。
"""

import os
import shutil
import sqlite3
import tempfile
import unittest
from datetime import datetime

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtWidgets import QApplication, QDialog  # noqa: E402

from models.event_model import EventRecordModel  # noqa: E402
from repositories.event_repository import EventRepository  # noqa: E402
from services.cube_task_service import BUILD_TASK_CODE, CubeTaskService  # noqa: E402
from utils.constants import EVENT_STATUS_ONGOING  # noqa: E402
from utils.db_connection import DatabaseConnection  # noqa: E402
from utils.db_schema import ensureResourceStatisticsSchema  # noqa: E402
from views.dialogs.build_task_dialog import BuildTaskDialog  # noqa: E402
from views.widgets.cube_task_board_panel import CubeTaskBoardPanel, CubeTaskCard  # noqa: E402

APP = QApplication.instance() or QApplication([])


class _StubBuildDialog:
    """替身对话框：直接返回预设选择，避免测试阻塞在模态窗口上。"""

    def __init__(self, pool_key: str = "light", use_ticket: bool = False, accept: bool = True):
        self._pool_key = pool_key
        self._use_ticket = use_ticket
        self._accept = accept
        self.calls = 0

    def exec_(self) -> int:
        """模拟 exec_，返回接受 / 拒绝。"""
        self.calls += 1
        return QDialog.Accepted if self._accept else QDialog.Rejected

    def selectedPoolKey(self) -> str:
        """预设卡池。"""
        return self._pool_key

    def useTicket(self) -> bool:
        """预设是否用券。"""
        return self._use_ticket


class _TempDatabaseCase(unittest.TestCase):
    """带任务看板表结构的临时库测试基类。"""

    def setUp(self):
        self._original_db_path = DatabaseConnection.getDbPath()
        self._temp_dir = tempfile.mkdtemp(prefix="azurlane_build_ui_")
        self._db_path = os.path.join(self._temp_dir, "build.db")
        DatabaseConnection.setDbPath(self._db_path)
        ensureResourceStatisticsSchema(self._db_path)

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

    def _addEvent(self, name: str = "测试活动", build_cost: int = 2) -> int:
        """插入一条进行中活动。"""
        return EventRepository().insert(
            EventRecordModel(
                event_date=datetime.now().strftime("%Y-%m-%d"),
                event_type="测试",
                name=name,
                status=EVENT_STATUS_ONGOING,
                build_cost=build_cost,
            )
        )


class TestBuildTaskDialog(_TempDatabaseCase):
    """确认框默认值与预览文案。"""

    def setUp(self):
        super().setUp()
        self._service = CubeTaskService()
        self._task = self._service._task_repository.findByCode(BUILD_TASK_CODE)
        self._dialogs = []

    def tearDown(self):
        for dialog in self._dialogs:
            dialog.deleteLater()
        super().tearDown()

    def _buildDialog(self) -> BuildTaskDialog:
        """按当前库构造确认框。"""
        dialog = BuildTaskDialog(
            self._service.getBuildPlan(), self._task, datetime.now().replace(microsecond=0)
        )
        self._dialogs.append(dialog)
        return dialog

    def testDefaultsToLightPoolWithoutTicket(self):
        """默认选轻型、不用券，预览写明两笔明细。"""
        dialog = self._buildDialog()

        self.assertEqual(dialog.selectedPoolKey(), "light")
        self.assertFalse(dialog.useTicket())
        self.assertIn("支出 · 轻型建造 1", dialog._previewLabel.text())
        self.assertIn("收入 · 日常任务 +1", dialog._previewLabel.text())

    def testTicketDisablesPoolAndSwitchesPreview(self):
        """勾选建造券：卡池置灰，预览只剩一笔收入。"""
        dialog = self._buildDialog()

        dialog._ticketCheck.setChecked(True)

        self.assertTrue(dialog.useTicket())
        for radio in dialog._radios.values():
            self.assertFalse(radio.isEnabled())
        preview = dialog._previewLabel.text()
        self.assertIn("将只写入 1 笔", preview)
        self.assertIn("不扣魔方", preview)
        self.assertIn("没有进行中活动", preview)

    def testTicketPreviewMentionsOngoingEvent(self):
        """有进行中活动时，券抽预览说明计入哪个活动。"""
        self._addEvent(name="正在进行")
        dialog = self._buildDialog()

        dialog._ticketCheck.setChecked(True)

        self.assertIn("正在进行", dialog._previewLabel.text())
        self.assertIn("券抽次数", dialog._previewLabel.text())

    def testEventPoolPreviewFollowsOngoingEvent(self):
        """活动池：预览写明关联活动与单耗。"""
        self._addEvent(name="风之活动", build_cost=1)
        dialog = self._buildDialog()

        dialog._radios["event"].setChecked(True)

        preview = dialog._previewLabel.text()
        self.assertIn("活动建造 1", preview)
        self.assertIn("风之活动", preview)

    def testEventPoolWithoutOngoingEventSaysUnlinked(self):
        """没有进行中活动：活动池预览写明不关联。"""
        dialog = self._buildDialog()

        dialog._radios["event"].setChecked(True)

        self.assertIn("不关联活动", dialog._previewLabel.text())


class TestBuildTaskPanelDispatch(_TempDatabaseCase):
    """看板点击建造卡片的择流与写库。"""

    def setUp(self):
        super().setUp()
        self._service = CubeTaskService()
        self._panel = CubeTaskBoardPanel(self._service)

    def tearDown(self):
        self._panel.deleteLater()
        super().tearDown()

    def _useStub(self, stub: _StubBuildDialog) -> _StubBuildDialog:
        """替换确认框工厂。"""
        self._panel._createBuildDialog = lambda plan, task, moment: stub
        return stub

    def _buildCard(self) -> CubeTaskCard:
        """当前看板上的建造卡片。"""
        for card in self._panel.findChildren(CubeTaskCard):
            if card._state.task.code == BUILD_TASK_CODE:
                return card
        raise AssertionError("看板上没有建造卡片")

    def testAcceptedDialogWritesTwoRecords(self):
        """确认后写两笔，并刷新卡片 tooltip。"""
        stub = self._useStub(_StubBuildDialog(pool_key="light"))

        self._panel._onCompleteRequested(BUILD_TASK_CODE)

        self.assertEqual(stub.calls, 1)
        self.assertEqual(
            self._query("SELECT direction, category, amount FROM resource_transaction"
                        " ORDER BY record_time, id"),
            [("expense", "轻型建造", 1), ("income", "日常任务", 1)],
        )
        self.assertIn("支出 · 轻型建造 1", self._buildCard().toolTip())

    def testRejectedDialogWritesNothing(self):
        """取消确认框不写库。"""
        stub = self._useStub(_StubBuildDialog(accept=False))

        self._panel._onCompleteRequested(BUILD_TASK_CODE)

        self.assertEqual(stub.calls, 1)
        self.assertEqual(self._query("SELECT id FROM resource_transaction"), [])

    def testTicketSelectionWritesIncomeOnly(self):
        """勾选建造券：只写收入，并把券抽计入进行中活动。"""
        event_id = self._addEvent()
        self._useStub(_StubBuildDialog(pool_key="light", use_ticket=True))

        self._panel._onCompleteRequested(BUILD_TASK_CODE)

        self.assertEqual(
            self._query("SELECT direction, amount FROM resource_transaction"),
            [("income", 1)],
        )
        self.assertEqual(
            self._query(
                "SELECT use_ticket, ticket_build_count FROM event_record WHERE id = ?",
                (event_id,),
            ),
            [(1, 1)],
        )
        self.assertIn("建造券", self._buildCard().toolTip())

    def testNonBuildTaskStillCompletesDirectly(self):
        """其它任务仍走原路径，不弹确认框。"""
        self._useStub(_StubBuildDialog())

        self._panel._onCompleteRequested("daily_battle_win")

        self.assertEqual(
            self._query("SELECT category, amount FROM resource_transaction"),
            [("日常任务", 2)],
        )


if __name__ == "__main__":
    unittest.main()
