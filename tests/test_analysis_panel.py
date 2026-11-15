"""
数据分析面板测试（offscreen，#19）。

覆盖：首次激活建图、切换控件重绘、毕业预测文案、空数据与缺表降级、
数据变更置脏。matplotlib 使用 Qt5Agg 画布，不画窗口。
"""

import os
import sqlite3
import tempfile
import unittest
from datetime import date
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtCore import pyqtSignal  # noqa: E402
from PyQt5.QtWidgets import QApplication, QWidget  # noqa: E402

from models.analysis_model import (  # noqa: E402
    BalancePoint,
    CategoryBreakdown,
    CategoryMonthly,
    CategoryShare,
    CommissionOverview,
    CommissionTotals,
    MonthlyPoint,
    TrendSeries,
)
from models.event_model import EventRecordModel  # noqa: E402
from services.build_pool_analysis_service import BuildPoolAnalysisService  # noqa: E402
from services.event_record_service import EventRecordView  # noqa: E402
from services.resource_analysis_service import ResourceAnalysisService  # noqa: E402
from utils.db_connection import DatabaseConnection  # noqa: E402
from utils.db_schema import ensureResourceStatisticsSchema  # noqa: E402
from views.widgets.analysis_panel import AnalysisPanel  # noqa: E402

APP = QApplication.instance() or QApplication([])


def _trend(months=None) -> TrendSeries:
    """构造一份有数据的趋势结果（按区间参数改文案）。"""
    label = "全部" if months is None else f"近 {months} 个月"
    return TrendSeries(
        resource_type="cube",
        display_name="魔方",
        balance_points=[
            BalancePoint("2024-01-01", 100, 10, 5, "summary_only", False),
            BalancePoint("2024-02-01", 120, 20, 10, "detail", True),
        ],
        monthly_points=[MonthlyPoint("2024-01", 10, 5), MonthlyPoint("2024-02", 20, 10)],
        total_income=30,
        total_expense=15,
        anchor_count=1,
        summary_days=1,
        detail_days=1,
        range_label=label,
        range_start="2024-01",
        range_end="2024-02",
    )


def _empty_trend(months=None) -> TrendSeries:
    """构造空趋势结果。"""
    label = "全部" if months is None else f"近 {months} 个月"
    return TrendSeries(resource_type="cube", display_name="魔方", range_label=label)


def _breakdown(direction: str) -> CategoryBreakdown:
    """构造一份类目占比结果（收入 / 支出各一套）。"""
    direction_name = "来源" if direction == "income" else "去向"
    if direction == "income":
        shares = [CategoryShare("军事委托", 60, 3, 0.6), CategoryShare("日常任务", 40, 2, 0.4)]
        categories = ["军事委托", "日常任务"]
        values = [[60], [40]]
    else:
        shares = [CategoryShare("活动建造", 30, 1, 0.75), CategoryShare("轻型建造", 10, 1, 0.25)]
        categories = ["活动建造", "轻型建造"]
        values = [[30], [10]]
    return CategoryBreakdown(
        resource_type="cube",
        direction=direction,
        display_name="魔方",
        direction_name=direction_name,
        shares=shares,
        monthly=CategoryMonthly(
            months=["2024-01"],
            categories=categories,
            values=values,
            month_totals=[100],
        ),
        detail_start="2024-01-01",
        detail_end="2024-01-31",
        detail_total=100,
        summary_days=2,
        summary_income=10,
        summary_expense=5,
        total_count=5,
    )


def _empty_breakdown() -> CategoryBreakdown:
    """构造空类目结果。"""
    return CategoryBreakdown("cube", "income", "魔方", "来源")


def _commission(months_param) -> CommissionOverview:
    """构造委托概览；区间文案随参数变化。"""
    label = "全部" if months_param is None else f"近 {months_param} 个月"
    return CommissionOverview(
        resource_type="cube",
        display_name="魔方",
        months=["2024-01", "2024-02"],
        amounts=[10, 20],
        counts=[1, 2],
        rolling_average=[None, 15.0],
        amount_distribution=[(10, 1), (20, 2)],
        totals=CommissionTotals(30, 3, 20, 2, 10.0, 15.0),
        range_label=label,
        range_start="2024-01",
        range_end="2024-02",
    )


def _empty_commission(months_param) -> CommissionOverview:
    """构造空委托概览。"""
    label = "全部" if months_param is None else f"近 {months_param} 个月"
    return CommissionOverview("cube", "魔方", range_label=label)


class _StubAnalysisService:
    """资源分析服务桩：按空 / 有数据两种模式返回，并记录最近一次查询参数。"""

    def __init__(self, with_data: bool = True):
        self._with_data = with_data
        self.last_direction = None
        self.last_months = "unset"
        self.last_trend_months = "unset"

    def getTrend(self, resource_type: str, months=None):
        """返回趋势，并记录区间参数。"""
        self.last_trend_months = months
        return _trend(months) if self._with_data else _empty_trend(months)

    def getCategoryBreakdown(self, resource_type: str, direction: str):
        """返回类目占比，并记录方向。"""
        self.last_direction = direction
        return _breakdown(direction) if self._with_data else _empty_breakdown()

    def getCommissionOverview(self, resource_type: str, months=None):
        """返回委托概览，并记录区间参数。"""
        self.last_months = months
        return _commission(months) if self._with_data else _empty_commission(months)


class _StubEventService:
    """活动服务桩：两个毕业池 + 一个缺。"""

    def listRecords(self, *args, **kwargs):
        """返回预置活动记录。"""
        views = []
        for index, (day, count, status) in enumerate(
            [("2024-01-01", 40, "毕业"), ("2024-02-01", 60, "毕业"), ("2024-03-01", None, "缺")]
        ):
            record = EventRecordModel(
                id=index + 1,
                event_date=day,
                event_type="大型海域",
                name=f"活动{index + 1}",
                status=status,
                build_cost=2,
            )
            views.append(EventRecordView(record=record, build_count=count))
        return views


class TestAnalysisPanel(unittest.TestCase):
    """面板行为。"""

    def setUp(self):
        self._analysis_stub = _StubAnalysisService()
        self._panel = AnalysisPanel(
            analysis_service=self._analysis_stub,
            build_service=BuildPoolAnalysisService(_StubEventService()),
        )
        self._panel.resize(1000, 900)

    def tearDown(self):
        self._panel.deleteLater()

    def testFirstActivationBuildsAllCanvases(self):
        """首次激活才建图，并渲染四个区块。"""
        self.assertFalse(self._panel._built)
        self.assertIsNone(self._panel._trendBalanceCanvas)

        self._panel.onActivated()

        self.assertTrue(self._panel._built)
        self.assertIsNotNone(self._panel._trendBalanceCanvas)
        self.assertIsNotNone(self._panel._categoryCanvas)
        self.assertIsNotNone(self._panel._commissionCanvas)
        self.assertIsNotNone(self._panel._buildTrendCanvas)
        self.assertIn("当前结余 120", self._panel._trendCards.text())

    def testCategoryToggleRerendersNote(self):
        """方向切换后按新方向重新取数。"""
        self._panel.onActivated()
        self.assertIn("汇总日 2 天未拆分", self._panel._categoryNote.text())
        self.assertEqual(self._analysis_stub.last_direction, "income")

        self._panel._categoryDirectionCombo.setCurrentIndex(1)

        self.assertEqual(self._analysis_stub.last_direction, "expense")

    def testTrendRangeSwitch(self):
        """趋势范围切到近 12 个月时，参数与卡片前缀跟随。"""
        self._panel.onActivated()
        self.assertIsNone(self._analysis_stub.last_trend_months)
        self.assertNotIn("近 12 个月", self._panel._trendCards.text())

        self._panel._trendRangeCombo.setCurrentIndex(1)

        self.assertEqual(self._analysis_stub.last_trend_months, 12)
        self.assertIn("近 12 个月", self._panel._trendCards.text())
        self.assertIn("2024-01 ~ 2024-02", self._panel._trendNote.text())

    def testCommissionRangeSwitch(self):
        """范围切到近 12 个月时参数与卡片文案跟随。"""
        self._panel.onActivated()
        self.assertIn("（全部）", self._panel._commissionCards.text())
        self.assertIsNone(self._analysis_stub.last_months)

        self._panel._commissionRangeCombo.setCurrentIndex(1)

        self.assertEqual(self._analysis_stub.last_months, 12)
        self.assertIn("（近 12 个月）", self._panel._commissionCards.text())

    def testBuildPredictionFollowsSpinBox(self):
        """已抽次数变化后预测文案更新。"""
        self._panel.onActivated()
        self.assertIn("新池预算", self._panel._buildPrediction.text())

        self._panel._buildCountSpin.setValue(40)

        text = self._panel._buildPrediction.text()
        self.assertIn("超过 25%", text)
        self.assertIn("还需中位", text)

    def testBuildCardsExcludeNonGraduated(self):
        """卡片只统计毕业池，并说明未计入数量。"""
        self._panel.onActivated()

        self.assertIn("毕业池 2", self._panel._buildCards.text())
        self.assertIn("未计入 1 池", self._panel._buildNote.text())

    def testRefreshBeforeBuildOnlyMarksDirty(self):
        """未建图时刷新只置脏，不触发查询。"""
        self._panel.refreshData()

        self.assertFalse(self._panel._built)
        self.assertTrue(self._panel._dirty)

    @patch("utils.time_source.today", return_value=date(2024, 1, 2))
    def testCrossDaySyncMarksDirty(self, today_mock):
        """跨天后同步时间上下文会置脏，下次激活重建。"""
        self._panel.onActivated()
        self.assertFalse(self._panel._dirty)

        today_mock.return_value = date(2024, 1, 3)
        self._panel.syncTimeContext()

        self.assertTrue(self._panel._dirty)


class TestAnalysisPanelEmptyData(unittest.TestCase):
    """空数据与缺表降级。"""

    def testEmptyDataRendersWithoutCrash(self):
        """空数据时建图不抛异常，说明文案为空。"""
        panel = AnalysisPanel(
            analysis_service=_StubAnalysisService(with_data=False),
            build_service=BuildPoolAnalysisService(_StubEventService()),
        )
        try:
            panel.onActivated()

            self.assertTrue(panel._built)
            self.assertEqual(panel._trendCards.text(), "")
            self.assertEqual(panel._commissionCards.text(), "")
            self.assertIn("无军事委托记录", panel._commissionNote.text())
        finally:
            panel.deleteLater()

    def testMissingTablesDegrade(self):
        """临时空库（无建表）下真实服务返回空结果，面板照常构建。"""
        original_path = DatabaseConnection.getDbPath()
        temp_dir = tempfile.mkdtemp(prefix="azurlane_panel_empty_")
        db_path = os.path.join(temp_dir, "empty.db")
        sqlite3.connect(db_path).close()
        DatabaseConnection.setDbPath(db_path)

        panel = AnalysisPanel(
            analysis_service=ResourceAnalysisService(),
            build_service=BuildPoolAnalysisService(),
        )
        try:
            panel.onActivated()

            self.assertTrue(panel._built)
            self.assertEqual(panel._trendCards.text(), "")
        finally:
            panel.deleteLater()
            DatabaseConnection.setDbPath(original_path)


class TestAnalysisPanelWithSchema(unittest.TestCase):
    """建表后但无数据：面板显示空状态而不是异常。"""

    def testEmptySchemaPanel(self):
        """空库（已建表）下四个区块都显示空状态。"""
        original_path = DatabaseConnection.getDbPath()
        temp_dir = tempfile.mkdtemp(prefix="azurlane_panel_schema_")
        db_path = os.path.join(temp_dir, "schema.db")
        DatabaseConnection.setDbPath(db_path)
        ensureResourceStatisticsSchema(db_path)

        panel = AnalysisPanel(
            analysis_service=ResourceAnalysisService(),
            build_service=BuildPoolAnalysisService(),
        )
        try:
            panel.onActivated()

            self.assertTrue(panel._built)
            self.assertEqual(panel._trendCards.text(), "")
            self.assertEqual(panel._buildCards.text(), "暂无毕业池样本")
        finally:
            panel.deleteLater()
            DatabaseConnection.setDbPath(original_path)


class _StubShipPanel(QWidget):
    """舰娘管理面板桩：占位屏环境下该面板无法创建窗口级控件，只验证页签接线。"""

    dataRefreshed = pyqtSignal()
    unlockResult = pyqtSignal(object)
    shipCreateResult = pyqtSignal(object)
    awakenResult = pyqtSignal(object)
    limitBreakResult = pyqtSignal(object)
    oathResult = pyqtSignal(object)

    def __init__(self, *args, **kwargs):
        """忽略构造参数（服务注入）。"""
        super().__init__()

    def refreshData(self) -> None:
        """空实现。"""

    def syncTimeContext(self) -> None:
        """空实现。"""


class _FakeWriteResult:
    """写操作结果桩：只提供状态栏文案。"""

    def toStatusBarMessage(self) -> str:
        """返回固定文案。"""
        return "测试写操作完成"


class TestMainWindowIntegration(unittest.TestCase):
    """主窗口接线：第 6 个页签是数据分析，激活后建图，写操作会置脏。"""

    def testSixthTabIsAnalysis(self):
        """页签数量、标题、激活建图与写操作置脏。"""
        original_path = DatabaseConnection.getDbPath()
        temp_dir = tempfile.mkdtemp(prefix="azurlane_window_")
        db_path = os.path.join(temp_dir, "window.db")
        DatabaseConnection.setDbPath(db_path)
        ensureResourceStatisticsSchema(db_path)
        window = None
        try:
            with patch("views.main_window.ShipManagementPanel", _StubShipPanel):
                from views.main_window import MainWindow

                window = MainWindow()
                self.assertEqual(window._tabWidget.count(), 6)
                self.assertEqual(
                    [window._tabWidget.tabText(index) for index in range(6)],
                    ["数据看板", "舰娘管理", "资源统计", "活动记录", "数据分析", "设置"],
                )

                window._tabWidget.setCurrentIndex(4)
                self.assertTrue(window._analysisPanel._built)
                self.assertFalse(window._analysisPanel._dirty)

                # 其它页签写入后，分析页签应置脏（不可见时等下次激活重建）
                window._onCubeTaskResult(_FakeWriteResult())
                self.assertTrue(window._analysisPanel._dirty)

                window.refreshData()
                self.assertTrue(window._analysisPanel._dirty)
        finally:
            if window is not None:
                window.deleteLater()
            DatabaseConnection.setDbPath(original_path)


if __name__ == "__main__":
    unittest.main()
