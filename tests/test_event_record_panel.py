"""
活动记录页与常规录入活动选择单元测试。

覆盖：表格渲染、年份 / 类型 / 状态 / 关键词筛选、选中后启用操作按钮、
删除活动时解除关联、对话框默认值与保存，以及常规录入仅在
「支出 · 活动建造」时显示活动下拉并写入 event_id。
"""

import os
import shutil
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtWidgets import QApplication, QMessageBox  # noqa: E402

from models.event_model import EventOption, EventRecordModel  # noqa: E402
from services.event_record_service import EventRecordService  # noqa: E402
from services.resource_entry_service import (  # noqa: E402
    ResourceCategoryOption, ResourceEntryService,
)
from utils import time_source  # noqa: E402
from utils.constants import (  # noqa: E402
    EVENT_BUILD_CATEGORY,
    EVENT_STATUS_GRADUATED,
    EVENT_STATUS_MISSING,
    EVENT_STATUS_ONGOING,
    EVENT_STATUS_UNSET_LABEL,
    RESOURCE_DIRECTION_EXPENSE,
    RESOURCE_DIRECTION_INCOME,
    RESOURCE_TYPE_RED_GEM,
)
from utils.db_connection import DatabaseConnection  # noqa: E402
from utils.db_schema import ensureResourceStatisticsSchema  # noqa: E402
from views.dialogs.event_record_dialog import EventRecordDialog  # noqa: E402
from views.widgets.event_record_panel import EventRecordPanel  # noqa: E402
from views.widgets.regular_entry_panel import RegularEntryPanel  # noqa: E402

APP = QApplication.instance() or QApplication([])


class _TempEventPanelCase(unittest.TestCase):
    """带临时库的活动页测试基类。"""

    def setUp(self):
        self._original_db_path = DatabaseConnection.getDbPath()
        self._temp_dir = tempfile.mkdtemp(prefix="azurlane_event_panel_")
        self._db_path = os.path.join(self._temp_dir, "panel.db")
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

    def _date(self, days_ago: int = 0):
        """相对今天的历史日期。"""
        return time_source.today() - timedelta(days=days_ago)

    def _create(
        self,
        days_ago: int = 1,
        event_type: str = "大型海域",
        name: str = "飓风与雾霭回廊",
        status: str = EVENT_STATUS_ONGOING,
        status_note: str = "",
        build_cost: int = 2,
        use_ticket: int = 0,
        ticket_build_count=None,
        build_count=None,
        note: str = "",
    ) -> EventRecordModel:
        """新增一条活动记录并返回。"""
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
        return self._service.getRecord(result.record_id)

    def _record(self, event_id=None, amount: int = 60) -> int:
        """记一笔关联 / 不关联的活动建造支出。"""
        result = self._entry_service.record(
            category=EVENT_BUILD_CATEGORY,
            direction=RESOURCE_DIRECTION_EXPENSE,
            amount=amount,
            moment=datetime.now().replace(microsecond=0),
            event_id=event_id,
        )
        return result.transaction_id

    def _buildPanel(self) -> EventRecordPanel:
        """构建活动记录页并刷新。"""
        panel = EventRecordPanel(EventRecordService())
        panel.refreshData()
        return panel


class TestEventPanelRendering(_TempEventPanelCase):
    """活动页表格与筛选测试。"""

    def setUp(self):
        super().setUp()
        self._graduated = self._create(
            days_ago=400,
            event_type="轻量化复刻·大型海域",
            name="复刻：愚者的天平",
            status=EVENT_STATUS_GRADUATED,
            status_note="20 券出",
            build_count=20,
        )
        self._missing = self._create(
            days_ago=2,
            event_type="大型海域",
            name="飓风与青春之泉",
            status=EVENT_STATUS_MISSING,
            status_note="缺圣马丁",
            build_count=None,
        )
        self._current = self._create(days_ago=1, build_count=30, note="新活动")
        self._record(event_id=self._current.id, amount=160)

    def testTableRendersRecordsAndLinkedStats(self):
        """表格按日期倒序渲染，建造次数按 160 ÷ 2 自动折算为 80。"""
        panel = self._buildPanel()

        self.assertEqual(panel._table.rowCount(), 3)
        self.assertEqual(panel._table.columnCount(), 10)
        self.assertEqual(panel._table.horizontalHeaderItem(5).text(), "建造次数")
        self.assertEqual(panel._table.item(0, 0).text(), self._current.event_date)
        self.assertEqual(panel._table.item(0, 2).text(), "飓风与雾霭回廊")
        self.assertEqual(panel._table.item(0, 3).text(), EVENT_STATUS_ONGOING)
        self.assertEqual(panel._table.item(0, 4).text(), "2 魔方")
        self.assertEqual(panel._table.item(0, 5).text(), "80")
        self.assertEqual(panel._table.item(0, 6).text(), "160")
        self.assertEqual(panel._table.item(0, 7).text(), "1")
        self.assertIn("共 3 条", panel._summaryLabel.text())
        self.assertIn("毕业 1", panel._summaryLabel.text())
        self.assertIn("缺 1", panel._summaryLabel.text())
        self.assertIn("建造次数合计 100", panel._summaryLabel.text())

    def testFilterByStatusAndKeyword(self):
        """状态下拉与关键词筛选只重查列表。"""
        panel = self._buildPanel()

        missing_index = panel._statusCombo.findData(EVENT_STATUS_MISSING)
        self.assertGreater(missing_index, 0)
        panel._statusCombo.setCurrentIndex(missing_index)
        self.assertEqual(panel._table.rowCount(), 1)
        self.assertEqual(panel._table.item(0, 2).text(), "飓风与青春之泉")

        unset_index = panel._statusCombo.findData("")
        self.assertGreater(unset_index, 0)
        panel._statusCombo.setCurrentIndex(unset_index)
        self.assertEqual(panel._table.rowCount(), 0)

        panel._statusCombo.setCurrentIndex(0)
        panel._searchEdit.setText("圣马丁")
        self.assertEqual(panel._table.rowCount(), 1)
        panel._searchEdit.setText("新活动")
        self.assertEqual(panel._table.rowCount(), 1)
        panel._searchEdit.setText("不存在的关键词")
        self.assertEqual(panel._table.rowCount(), 0)

    def testSelectionEnablesActions(self):
        """选中行后编辑 / 删除按钮可用。"""
        panel = self._buildPanel()
        self.assertFalse(panel._editBtn.isEnabled())
        self.assertFalse(panel._deleteBtn.isEnabled())

        panel._table.setCurrentCell(0, 0)
        self.assertTrue(panel._editBtn.isEnabled())
        self.assertTrue(panel._deleteBtn.isEnabled())

    def testStatusUnsetFilterLabel(self):
        """状态筛选含「未标记」项。"""
        panel = self._buildPanel()
        labels = [
            panel._statusCombo.itemText(index)
            for index in range(panel._statusCombo.count())
        ]
        self.assertIn(EVENT_STATUS_UNSET_LABEL, labels)


class TestEventPanelDelete(_TempEventPanelCase):
    """删除活动与解除关联测试。"""

    def testDeleteUnlinksAndKeepsTransaction(self):
        """确认删除后活动消失，明细保留但 event_id 置空。"""
        record = self._create()
        transaction_id = self._record(event_id=record.id)
        panel = self._buildPanel()
        panel._table.setCurrentCell(0, 0)

        results = []
        panel.resultReady.connect(results.append)

        with patch(
            "views.widgets.event_record_panel.QMessageBox.question",
            return_value=QMessageBox.Yes,
        ):
            panel._onDeleteClicked()

        self.assertEqual(panel._table.rowCount(), 0)
        self.assertEqual(self._service.countAll(), 0)
        self.assertEqual(
            self._query("SELECT event_id FROM resource_transaction WHERE id = ?", (transaction_id,)),
            [(None,)],
        )
        self.assertEqual(len(results), 1)
        self.assertIn("解除 1 笔", results[0].toStatusBarMessage())


class TestEventDialog(_TempEventPanelCase):
    """新增 / 编辑对话框测试。"""

    def testNewDialogDefaults(self):
        """新增对话框默认今天、进行中、单耗 2，建造次数留空。"""
        dialog = EventRecordDialog(self._service)

        self.assertEqual(dialog.windowTitle(), "新增活动")
        self.assertEqual(dialog._dateEdit.date().toString("yyyy-MM-dd"),
                         time_source.today().strftime("%Y-%m-%d"))
        self.assertEqual(dialog._statusCombo.currentText(), EVENT_STATUS_ONGOING)
        self.assertEqual(dialog._buildCostCombo.currentData(), 2)
        self.assertEqual(dialog._buildCountEdit.text(), "")
        self.assertFalse(dialog._buildCountEdit.isReadOnly())
        self.assertFalse(dialog._useTicketCheck.isEnabled())

    def testEditDialogFillsRecordAndSaves(self):
        """编辑对话框回填字段，保存后写库。"""
        record = self._create(days_ago=1, build_count=30, status_note="缺吉尚", note="十连")
        dialog = EventRecordDialog(self._service, record)

        self.assertEqual(dialog.windowTitle(), "编辑活动")
        self.assertEqual(dialog._nameEdit.text(), "飓风与雾霭回廊")
        self.assertEqual(dialog._buildCountEdit.text(), "30")
        self.assertEqual(dialog._statusNoteEdit.text(), "缺吉尚")

        dialog._nameEdit.setText("改名后的活动")
        dialog._buildCountEdit.setText("42")
        saved = []
        dialog.saved.connect(saved.append)
        dialog._onSaveClicked()

        updated = self._service.getRecord(record.id)
        self.assertEqual(updated.name, "改名后的活动")
        self.assertEqual(updated.build_count, 42)
        self.assertEqual(len(saved), 1)

    def testLinkedDialogDerivesBuildCountAndTicket(self):
        """有明细时对话框按 160 ÷ 2 显示 80，勾选建造券后补加券抽次数。"""
        record = self._create(days_ago=1, build_cost=2)
        self._record(event_id=record.id, amount=160)
        dialog = EventRecordDialog(
            self._service, record, linked_count=1, linked_cube_expense=160
        )

        self.assertEqual(dialog._buildCountEdit.text(), "80")
        self.assertTrue(dialog._buildCountEdit.isReadOnly())
        self.assertTrue(dialog._useTicketCheck.isEnabled())

        dialog._useTicketCheck.setChecked(True)
        dialog._ticketCountEdit.setText("10")
        self.assertEqual(dialog._buildCountEdit.text(), "90")

        built = dialog._buildRecord()
        self.assertEqual(built.build_count, 90)
        self.assertEqual(built.use_ticket, 1)
        self.assertEqual(built.ticket_build_count, 10)


class TestRegularEntryEventSelector(_TempEventPanelCase):
    """常规录入的活动下拉测试。"""

    def _selectCategory(self, panel: RegularEntryPanel, name: str, direction: str) -> None:
        """按名称 + 方向选中类型。"""
        for index in range(panel._typeCombo.count()):
            option = panel._typeCombo.itemData(index)
            if (
                isinstance(option, ResourceCategoryOption)
                and option.name == name
                and option.direction == direction
            ):
                panel._typeCombo.setCurrentIndex(index)
                return
        raise AssertionError(f"没有类型：{name}（{direction}）")

    def testEventRowOnlyVisibleForActivityBuild(self):
        """只有「支出 · 活动建造」显示活动下拉。"""
        self._create(days_ago=1)
        panel = RegularEntryPanel(ResourceEntryService())

        self.assertTrue(panel._eventCombo.isHidden())
        self._selectCategory(panel, "轻型建造", RESOURCE_DIRECTION_EXPENSE)
        self.assertTrue(panel._eventCombo.isHidden())
        self._selectCategory(panel, EVENT_BUILD_CATEGORY, RESOURCE_DIRECTION_EXPENSE)
        self.assertFalse(panel._eventCombo.isHidden())
        self.assertIsNotNone(panel._selectedEventId())
        self._selectCategory(panel, "军事委托", RESOURCE_DIRECTION_INCOME)
        self.assertTrue(panel._eventCombo.isHidden())

    def testActivityBuildRecordsSelectedEvent(self):
        """记录活动建造时把默认进行中活动写入 event_id。"""
        record = self._create(days_ago=1)
        panel = RegularEntryPanel(ResourceEntryService())
        self._selectCategory(panel, EVENT_BUILD_CATEGORY, RESOURCE_DIRECTION_EXPENSE)

        self.assertEqual(panel._selectedEventId(), record.id)
        panel._amountSpin.setValue(60)
        panel._onRecordClicked()

        rows = self._query("SELECT category, amount, event_id FROM resource_transaction")
        self.assertEqual(rows, [(EVENT_BUILD_CATEGORY, 60, record.id)])

    def testDefaultSelectsOngoingEvent(self):
        """默认关联「进行中」活动，而不是最近一条历史活动。"""
        self._create(days_ago=10, name="已毕业活动", status=EVENT_STATUS_GRADUATED)
        ongoing = self._create(days_ago=1, name="进行中活动", status=EVENT_STATUS_ONGOING)
        panel = RegularEntryPanel(ResourceEntryService())
        self._selectCategory(panel, EVENT_BUILD_CATEGORY, RESOURCE_DIRECTION_EXPENSE)

        self.assertEqual(panel._selectedEventId(), ongoing.id)
        self.assertEqual(panel._eventLabel.text(), "活动")

    def testMultipleOngoingDefaultsToMostRecentAndWarns(self):
        """多个进行中活动时默认最近一个，并在标签上提示确认。"""
        self._create(days_ago=2, name="进行中 A", status=EVENT_STATUS_ONGOING)
        newer = self._create(days_ago=1, name="进行中 B", status=EVENT_STATUS_ONGOING)
        panel = RegularEntryPanel(ResourceEntryService())
        self._selectCategory(panel, EVENT_BUILD_CATEGORY, RESOURCE_DIRECTION_EXPENSE)

        self.assertEqual(panel._selectedEventId(), newer.id)
        self.assertEqual(panel._eventLabel.text(), "活动（请选择）")

    def testNoOngoingDefaultsToUnlinked(self):
        """没有进行中活动时默认「不关联」，不拿历史活动顶替。"""
        self._create(days_ago=1, name="已毕业活动", status=EVENT_STATUS_GRADUATED)
        panel = RegularEntryPanel(ResourceEntryService())
        self._selectCategory(panel, EVENT_BUILD_CATEGORY, RESOURCE_DIRECTION_EXPENSE)

        self.assertIsNone(panel._selectedEventId())
        self.assertEqual(panel._eventLabel.text(), "活动")

    def testManualChoicePreservedOnRefresh(self):
        """用户手动选过活动后，刷新不回到默认进行中活动。"""
        self._create(days_ago=1, name="进行中活动", status=EVENT_STATUS_ONGOING)
        old = self._create(days_ago=10, name="历史活动", status=EVENT_STATUS_GRADUATED)
        panel = RegularEntryPanel(ResourceEntryService())
        self._selectCategory(panel, EVENT_BUILD_CATEGORY, RESOURCE_DIRECTION_EXPENSE)

        for index in range(panel._eventCombo.count()):
            option = panel._eventCombo.itemData(index)
            if isinstance(option, EventOption) and option.id == old.id:
                panel._eventCombo.setCurrentIndex(index)
                break
        self.assertEqual(panel._selectedEventId(), old.id)

        panel.refreshEventOptions()
        self.assertEqual(panel._selectedEventId(), old.id)
        self.assertEqual(panel._eventLabel.text(), "活动")

    def testRedGemHasNoEventSelector(self):
        """红尖尖没有「活动建造」，活动下拉始终隐藏。"""
        panel = RegularEntryPanel(ResourceEntryService(), resource_type=RESOURCE_TYPE_RED_GEM)
        for index in range(panel._typeCombo.count()):
            panel._typeCombo.setCurrentIndex(index)
            self.assertTrue(panel._eventCombo.isHidden())


if __name__ == "__main__":
    unittest.main()
