"""
「升级预测」面板接线单元测试（#35 P1）。

覆盖：默认目标=当前+1、剩余经验/天数/日期文案、里程碑表、
切换目标只重算不写库、满级与速率缺失降级、不输出伪区间。
"""

import os
import unittest
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtWidgets import QApplication  # noqa: E402

from services.commander_service import TargetLevelProjection  # noqa: E402
from utils.constants import COMMANDER_TARGET_LEVEL_MILESTONES  # noqa: E402
from views.widgets.commander_exp_panel import CommanderExpPanel  # noqa: E402

APP = QApplication.instance() or QApplication([])

CURRENT_LEVEL = 163
CURRENT_EXP = 215507


def _projection(
    target: int,
    remaining=501393,
    days_slow=44.6,
    days_long=45.3,
    days_fast=35.5,
    estimated_date="2026-12-10",
    reason=None,
) -> TargetLevelProjection:
    """构造一条预测结果。"""
    return TargetLevelProjection(
        target_level=target,
        current_level=CURRENT_LEVEL,
        current_exp=CURRENT_EXP,
        current_absolute_exp=11430117,
        target_absolute_exp=11430117 + (remaining or 0),
        remaining_exp=remaining,
        days_slow=days_slow,
        days_long=days_long,
        days_fast=days_fast,
        estimated_date=estimated_date,
        degraded_reason=reason,
    )


def _default_projections():
    """为默认目标与 8 个里程碑各构造一条结果。"""
    projections = {
        164: _projection(164, remaining=138843, days_slow=12.4, days_long=12.5,
                         days_fast=9.8, estimated_date="2026-11-07"),
    }
    for index, target in enumerate(COMMANDER_TARGET_LEVEL_MILESTONES):
        projections[target] = _projection(
            target,
            remaining=(index + 1) * 1000000,
            days_slow=(index + 1) * 10.0,
            days_long=(index + 1) * 10.1,
            days_fast=None,
            estimated_date=f"2027-01-{index + 1:02d}",
        )
    projections[180] = _projection(
        180, remaining=7035793, days_slow=626.4, days_long=635.4, days_fast=498.1,
        estimated_date="2028-07-13",
    )
    return projections


class _StubCommanderService:
    """指挥官服务桩：只实现面板用到的只读方法。"""

    def __init__(self, projections=None):
        self._projections = projections or _default_projections()
        self.requested_targets = []
        self.milestone_calls = 0

    def listSnapshotRows(self, limit=None, start_date=None, end_date=None):
        return []

    def getLevelOverview(self, level, current_exp):
        return SimpleNamespace(
            required_exp=354350,
            cumulative_exp=10530310,
            remaining_exp=max(0, 354350 - current_exp),
            progress_rate=60.0,
        )

    def listTargetLevelProjections(self, targets=None):
        self.milestone_calls += 1
        return [self._projections[target] for target in COMMANDER_TARGET_LEVEL_MILESTONES]

    def getTargetLevelProjection(self, target):
        self.requested_targets.append(target)
        return self._projections[target]


class _PredictionPanelCase(unittest.TestCase):
    """构造面板的公共基类。"""

    def _panel(self, projections=None):
        self._service = _StubCommanderService(projections)
        return CommanderExpPanel(self._service)

    def testDefaultTargetIsNextLevel(self):
        """首次刷新把目标设为当前等级+1。"""
        panel = self._panel()

        self.assertEqual(panel._targetSpin.value(), CURRENT_LEVEL + 1)
        self.assertEqual(self._service.requested_targets, [CURRENT_LEVEL + 1])

    def testSummaryShowsRemainingExp(self):
        """摘要行显示剩余经验（千分符）。"""
        panel = self._panel()

        self.assertIn("138,843", panel._targetSummaryLabel.text())
        self.assertIn("还需", panel._targetSummaryLabel.text())

    def testDetailShowsDaysLongAndScenario(self):
        """T-46：换算行含 30 天口径、日期、90 天参考与近期情景。"""
        panel = self._panel()
        panel._targetSpin.setValue(180)

        detail = panel._targetDetailLabel.text()
        self.assertIn("626.4 天", detail)
        self.assertIn("2028-07-13", detail)
        self.assertIn("近 90 天节奏 635.4 天", detail)
        self.assertIn("若维持近期节奏 498.1 天", detail)
        self.assertIn("长期估算", detail)

    def testChangingTargetOnlyRecomputes(self):
        """T-47：切换目标只调用服务重算，不触发写入。"""
        panel = self._panel()
        panel._targetSpin.setValue(170)

        self.assertEqual(self._service.requested_targets[-1], 170)
        self.assertIn("还需 2,000,000 经验", panel._targetSummaryLabel.text())

    def testMilestoneTable(self):
        """里程碑表 8 行，取值来自服务层。"""
        panel = self._panel()
        table = panel._predictionTable

        self.assertEqual(table.rowCount(), len(COMMANDER_TARGET_LEVEL_MILESTONES))
        self.assertEqual(table.item(0, 0).text(), "165 级")
        self.assertEqual(table.item(0, 1).text(), "1,000,000")
        self.assertEqual(table.item(0, 2).text(), "10.0 天")
        self.assertEqual(table.item(0, 4).text(), "2027-01-01")

    def testFullLevelShowsText(self):
        """满级时摘要显示「已满级」，不显示天数。"""
        projections = _default_projections()
        projections[200] = _projection(200, remaining=0, days_slow=None, days_long=None,
                                       days_fast=None, estimated_date=None, reason="已满级")
        panel = self._panel(projections)
        panel._targetSpin.setValue(200)

        self.assertEqual(panel._targetSummaryLabel.text(), "已满级")
        self.assertEqual(panel._targetDetailLabel.text(), "")

    def testRateMissingShowsReason(self):
        """T-48：速率不足时经验照常显示，天数说明原因。"""
        projections = _default_projections()
        projections[165] = _projection(
            165, remaining=501393, days_slow=None, days_long=None, days_fast=None,
            estimated_date=None, reason="指级效率数据不足，暂无法估算天数",
        )
        panel = self._panel(projections)
        panel._targetSpin.setValue(165)

        self.assertIn("还需 501,393 经验", panel._targetSummaryLabel.text())
        self.assertIn("暂无法估算", panel._targetDetailLabel.text())
        self.assertEqual(panel._predictionTable.item(0, 2).text(), "-")

    def testRefreshKeepsUserTarget(self):
        """数据刷新后保留用户选择的目标，不会重置为当前+1。"""
        panel = self._panel()
        panel._targetSpin.setValue(180)
        panel.refreshData()

        self.assertEqual(panel._targetSpin.value(), 180)
        self.assertEqual(self._service.requested_targets[-1], 180)

    def testMilestonesQueriedOncePerRefresh(self):
        """每次刷新只批量取一次里程碑，避免 N+1。"""
        panel = self._panel()
        before = self._service.milestone_calls
        panel.refreshData()

        self.assertEqual(self._service.milestone_calls, before + 1)

    def testNoPseudoRangeText(self):
        """所有文案与表格都不出现「～」「最快」「最慢」。"""
        panel = self._panel()
        panel._targetSpin.setValue(180)

        texts = [
            panel._targetSummaryLabel.text(),
            panel._targetDetailLabel.text(),
        ]
        table = panel._predictionTable
        for row in range(table.rowCount()):
            for column in range(table.columnCount()):
                texts.append(table.item(row, column).text())

        for text in texts:
            for banned in ("～", "最快", "最慢"):
                self.assertNotIn(banned, text)


if __name__ == "__main__":
    unittest.main()
