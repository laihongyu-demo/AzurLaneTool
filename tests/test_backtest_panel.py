"""
「回测与校准」设置分组单元测试（#35 P3）。

覆盖：状态摘要、到期建议、待复核事件表、立即回测（成功/失败）、
标记已复核、状态读取异常降级。
"""

import os
import unittest
from datetime import datetime
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtWidgets import QApplication  # noqa: E402

from models.backtest_model import BacktestEventRecord  # noqa: E402
from services.backtest_service import BacktestRun, DueStatus  # noqa: E402
from utils.exceptions import DatabaseError  # noqa: E402
from views.widgets.settings_panel import (  # noqa: E402
    BacktestCalibrationSection, SettingsPanel,
)

APP = QApplication.instance() or QApplication([])


def _event(direction="up", start="2026-10-17", end="2026-10-26", days=10, peak=1.36,
           ongoing=False):
    """构造一条事件记录。"""
    return BacktestEventRecord(
        direction=direction,
        strength="normal",
        start_date=start,
        end_date=end,
        days=days,
        peak_ratio=peak,
        ongoing=ongoing,
    )


def _run(points=494):
    """构造一次回测结果。"""
    return BacktestRun(
        generated_at=datetime(2026, 10, 26, 21, 0),
        points=points,
        skipped=0,
        invalid=0,
        report="# report\n",
        summary={"slow": 11233},
        events=[],
        report_path="data/backtest/20261026_2100.md",
    )


class _StubBacktestService:
    """回测服务桩。"""

    def __init__(self, status=None, run_result=None, status_error=None, run_error=None):
        self._status = status or DueStatus(due=False)
        self._run_result = run_result or _run()
        self._status_error = status_error
        self._run_error = run_error
        self.status_calls = 0
        self.run_calls = 0
        self.handled = []

    def getDueStatus(self):
        self.status_calls += 1
        if self._status_error:
            raise self._status_error
        return self._status

    def run(self):
        self.run_calls += 1
        if self._run_error:
            raise self._run_error
        return self._run_result

    def markEventHandled(self, direction, start_date):
        self.handled.append((direction, start_date))
        return True


class _SectionCase(unittest.TestCase):
    """构造分组的公共基类。"""

    def _section(self, service):
        self._service = service
        return BacktestCalibrationSection(service)

    def testStatusShowsLastRunAndNewPoints(self):
        """状态行含上次检查时刻、距今天数与新增记录数。"""
        section = self._section(_StubBacktestService(DueStatus(
            due=True,
            reasons=["1 段节奏变化等你确认"],
            last_run_at="2026-10-26 21:00",
            days_since=0,
            new_points=12,
            pending_events=[_event()],
            report_path="data/backtest/20261026_2100.md",
        )))

        self.assertIn("上次检查：2026-10-26 21:00", section._statusLabel.text())
        self.assertIn("之后新增 12 条记录", section._statusLabel.text())
        self.assertIn("建议检查", section._reasonsLabel.text())
        self.assertIn("1 段节奏变化等你确认", section._reasonsLabel.text())
        self.assertIn("20261026_2100.md", section._reportLabel.text())

    def testNeverRunShowsPlaceholder(self):
        """从未检查 → 明确提示。"""
        section = self._section(_StubBacktestService(DueStatus(
            due=True, reasons=["还没做过检查"],
        )))

        self.assertEqual(section._statusLabel.text(), "还没做过检查")

    def testNotDueShowsNoAction(self):
        """不到期 → 绿色「现在不需要检查」。"""
        section = self._section(_StubBacktestService(DueStatus(due=False)))

        self.assertEqual(section._reasonsLabel.text(), "现在不需要检查")

    def testEventsTableRendersPendingEvents(self):
        """事件表按服务层数据渲染，方向与幅度转成用户用语。"""
        section = self._section(_StubBacktestService(DueStatus(
            due=True,
            reasons=["1 段节奏变化等你确认"],
            pending_events=[_event(direction="down", start="2026-09-01", end="2026-09-08",
                                   days=8, peak=0.67)],
        )))

        table = section._eventsTable
        self.assertEqual(table.rowCount(), 1)
        self.assertEqual(table.item(0, 0).text(), "变慢")
        self.assertEqual(table.item(0, 1).text(), "2026-09-01 → 2026-09-08")
        self.assertEqual(table.item(0, 2).text(), "8 天")
        self.assertEqual(table.item(0, 3).text(), "慢 33%")
        self.assertFalse(section._handleBtn.isEnabled())

    def testRunButtonCallsServiceAndEmitsResult(self):
        """T-46：点击「立即检查」只调用一次服务，并转发结果。"""
        service = _StubBacktestService(DueStatus(due=True, reasons=["还没做过检查"]))
        section = self._section(service)
        results = []
        section.resultReady.connect(results.append)

        section._runBtn.click()

        self.assertEqual(service.run_calls, 1)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].points, 494)
        # 初始化一次 + 运行后刷新一次
        self.assertEqual(service.status_calls, 2)
        self.assertTrue(section._runBtn.isEnabled())

    def testRunFailureShowsMessage(self):
        """回测失败 → 弹窗提示，按钮恢复可用。"""
        service = _StubBacktestService(
            DueStatus(due=True), run_error=DatabaseError("写报告失败")
        )
        section = self._section(service)

        with patch("views.widgets.settings_panel.QMessageBox.critical") as critical:
            section._runBtn.click()

        self.assertTrue(critical.called)
        self.assertIn("写报告失败", critical.call_args[0][2])
        self.assertTrue(section._runBtn.isEnabled())

    def testMarkHandledCallsService(self):
        """T-47：选中事件后可确认已看过。"""
        service = _StubBacktestService(DueStatus(
            due=True, reasons=["1 段节奏变化等你确认"], pending_events=[_event()],
        ))
        section = self._section(service)
        section._eventsTable.selectRow(0)

        self.assertTrue(section._handleBtn.isEnabled())
        section._handleBtn.click()

        self.assertEqual(service.handled, [("up", "2026-10-17")])

    def testStatusErrorDegrades(self):
        """T-48：读取状态失败 → 显示原因，不抛异常。"""
        section = self._section(_StubBacktestService(
            status_error=DatabaseError("no such table"),
        ))

        self.assertEqual(section._statusLabel.text(), "-")
        self.assertIn("数据库错误", section._reasonsLabel.text())
        self.assertEqual(section._eventsTable.rowCount(), 0)


    def testOngoingEventShowsAsInProgress(self):
        """进行中的事件显示为「还在发生」，不计入到期。"""
        section = self._section(_StubBacktestService(DueStatus(
            due=False,
            ongoing_events=[_event(ongoing=True)],
        )))

        table = section._eventsTable
        self.assertEqual(table.rowCount(), 1)
        self.assertEqual(table.item(0, 4).text(), "还在发生")
        self.assertIn("还在发生", section._reasonsLabel.text())
        self.assertIn("现在不需要检查", section._reasonsLabel.text())

    def testPendingRowsComeBeforeOngoing(self):
        """待确认在前、进行中在后，状态列区分。"""
        section = self._section(_StubBacktestService(DueStatus(
            due=True,
            reasons=["1 段节奏变化等你确认"],
            pending_events=[_event(direction="down", start="2026-11-02", end="2026-11-07",
                                   peak=0.67)],
            ongoing_events=[_event(start="2026-10-17", end="2026-11-08", ongoing=True)],
        )))

        table = section._eventsTable
        self.assertEqual(table.rowCount(), 2)
        self.assertEqual(table.item(0, 4).text(), "等你确认")
        self.assertEqual(table.item(1, 4).text(), "还在发生")
        self.assertIn("等你确认", section._reasonsLabel.text())


class TestSettingsPanelWiring(unittest.TestCase):
    """设置页容器接线测试。"""

    def testPanelHostsBacktestSection(self):
        """设置页包含回测分组，刷新时两段都刷新。"""
        service = _StubBacktestService(DueStatus(due=False))
        panel = SettingsPanel(backtest_service=service)

        self.assertIsInstance(panel._backtestSection, BacktestCalibrationSection)
        before = service.status_calls
        panel.refreshData()

        self.assertEqual(service.status_calls, before + 1)


if __name__ == "__main__":
    unittest.main()
