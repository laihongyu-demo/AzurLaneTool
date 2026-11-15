"""
资源分析服务测试（#19）。

覆盖：结余链与月度收支、类目占比分母（汇总日不计入）、Top N 合并、
军事委托月度 / 全部与近一年区间、缺口不补 0、缺表降级。

夹具说明：每个「明细日」都配了对应的明细记录，避免出现「有明细、无日汇总」的孤儿数据——
真实库当前不存在这种数据，夹具也保持一致。
"""

import os
import sqlite3
import tempfile
import unittest
from datetime import date
from unittest.mock import patch

from services.resource_analysis_service import ResourceAnalysisService
from utils.db_connection import DatabaseConnection
from utils.db_schema import ensureResourceStatisticsSchema


def _insertDaily(
    conn: sqlite3.Connection,
    resource_type: str,
    record_date: str,
    detail_mode: str = "detail",
    income=None,
    expense=None,
    override=None,
) -> None:
    """写入一条日汇总行（测试夹具）。"""
    conn.execute(
        """
        INSERT INTO resource_daily
            (resource_type, record_date, detail_mode, income, expense, balance_override, note)
        VALUES (?, ?, ?, ?, ?, ?, '')
        """,
        (resource_type, record_date, detail_mode, income, expense, override),
    )


def _insertTransaction(
    conn: sqlite3.Connection,
    resource_type: str,
    direction: str,
    record_time: str,
    category: str,
    amount: int,
) -> None:
    """写入一条明细（测试夹具）。"""
    conn.execute(
        """
        INSERT INTO resource_transaction
            (resource_type, direction, record_time, category, amount, note)
        VALUES (?, ?, ?, ?, ?, '')
        """,
        (resource_type, direction, record_time, category, amount),
    )


class TestResourceAnalysisService(unittest.TestCase):
    """资源分析服务口径。"""

    def setUp(self):
        self._original_db_path = DatabaseConnection.getDbPath()
        self._temp_dir = tempfile.mkdtemp(prefix="azurlane_analysis_")
        self._db_path = os.path.join(self._temp_dir, "analysis.db")
        DatabaseConnection.setDbPath(self._db_path)
        ensureResourceStatisticsSchema(self._db_path)
        self._service = ResourceAnalysisService()

        conn = sqlite3.connect(self._db_path)
        try:
            # 魔方：2023-12、2024-01、2024-02、2024-04 明细日；2024-01、2024-03 汇总日
            _insertDaily(conn, "cube", "2023-12-10", "detail")
            _insertDaily(conn, "cube", "2024-01-01", "summary_only", income=10, expense=4)
            _insertDaily(conn, "cube", "2024-01-02", "detail")
            _insertDaily(conn, "cube", "2024-02-05", "detail")
            _insertDaily(conn, "cube", "2024-02-20", "detail")
            _insertDaily(conn, "cube", "2024-03-01", "summary_only", income=0, expense=0, override=100)
            _insertDaily(conn, "cube", "2024-04-10", "detail")

            _insertTransaction(conn, "cube", "income", "2023-12-10 08:00:00", "军事委托", 1)
            _insertTransaction(conn, "cube", "income", "2024-01-02 08:00:00", "军事委托", 3)
            _insertTransaction(conn, "cube", "income", "2024-01-02 09:00:00", "日常任务", 2)
            _insertTransaction(conn, "cube", "expense", "2024-01-02 10:00:00", "活动建造", 4)
            _insertTransaction(conn, "cube", "income", "2024-02-05 08:00:00", "军事委托", 5)
            _insertTransaction(conn, "cube", "expense", "2024-02-05 09:00:00", "轻型建造", 1)
            _insertTransaction(conn, "cube", "income", "2024-02-20 08:00:00", "字典外类目", 7)
            _insertTransaction(conn, "cube", "income", "2024-04-10 08:00:00", "军事委托", 2)

            # 红尖尖：只有 1 月有明细
            _insertDaily(conn, "red_gem", "2025-01-01", "summary_only", income=0, expense=0, override=500)
            _insertDaily(conn, "red_gem", "2025-01-05", "detail")
            _insertTransaction(conn, "red_gem", "income", "2025-01-05 08:00:00", "军事委托", 10)
            _insertTransaction(conn, "red_gem", "expense", "2025-01-05 09:00:00", "皮肤", 200)
            conn.commit()
        finally:
            conn.close()

    def tearDown(self):
        DatabaseConnection.setDbPath(self._original_db_path)

    # ------------------------------------------------------------- 趋势

    def testTrendSumsSummaryAndDetailDays(self):
        """月度收支与累计同时覆盖汇总日与明细日。"""
        series = self._service.getTrend("cube")

        self.assertEqual(len(series.balance_points), 7)
        self.assertEqual(series.total_income, 30)  # 汇总 10 + 明细 20
        self.assertEqual(series.total_expense, 9)  # 汇总 4 + 明细 5
        self.assertEqual(series.netGrowth, 21)
        self.assertEqual(series.summary_days, 2)
        self.assertEqual(series.detail_days, 5)

        months = [point.month for point in series.monthly_points]
        self.assertEqual(months, ["2023-12", "2024-01", "2024-02", "2024-03", "2024-04"])
        january = series.monthly_points[1]
        self.assertEqual((january.income, january.expense, january.net), (15, 8, 7))

    def testTrendMarksAnchorAndResetsBalance(self):
        """手填结余日重设累计值并标记为锚点。"""
        series = self._service.getTrend("cube")

        self.assertEqual(series.latestBalance, 102)
        self.assertEqual(series.anchor_count, 1)
        self.assertEqual(
            [point.balance for point in series.balance_points], [1, 7, 8, 12, 19, 100, 102]
        )
        anchors = [point.record_date for point in series.balance_points if point.is_anchor]
        self.assertEqual(anchors, ["2024-03-01"])

    def testTrendRedGemBalance(self):
        """红尖尖只有两条日记录：手填结余后按明细日继续累加。"""
        series = self._service.getTrend("red_gem")

        self.assertEqual(len(series.balance_points), 2)
        self.assertEqual(series.latestBalance, 310)  # 500 + 10 - 200

    # ------------------------------------------------------------- 类目占比

    def testCategorySharesExcludeSummaryDays(self):
        """占比分母只含明细期，汇总日金额单列。"""
        breakdown = self._service.getCategoryBreakdown("cube", "income")

        self.assertEqual(breakdown.detail_total, 20)  # 1+3+2+5+7+2
        self.assertEqual(breakdown.total_count, 6)
        self.assertEqual(breakdown.summary_days, 2)
        self.assertEqual(breakdown.summary_income, 10)
        self.assertEqual(breakdown.summary_expense, 4)
        self.assertEqual(breakdown.detail_start, "2023-12-10")
        self.assertEqual(breakdown.detail_end, "2024-04-10")
        self.assertAlmostEqual(sum(item.share for item in breakdown.shares), 1.0)

    def testCategorySharesSortedAndUnmappedReported(self):
        """类目按金额降序；字典外类目照常统计并单独报告。"""
        breakdown = self._service.getCategoryBreakdown("cube", "income")

        self.assertEqual(
            [(item.name, item.amount, item.count) for item in breakdown.shares],
            [("军事委托", 11, 4), ("字典外类目", 7, 1), ("日常任务", 2, 1)],
        )
        # 新库种子没有「日常任务」，历史库要等任务看板 / 迁移补字典项；两者都应被报告
        self.assertEqual(breakdown.unmapped_names, ["字典外类目", "日常任务"])
        self.assertNotIn("军事委托", breakdown.unmapped_names)

    def testCategoryMonthlyMatrix(self):
        """月度矩阵按类目 × 月份对齐，只含有明细的月份。"""
        breakdown = self._service.getCategoryBreakdown("cube", "income")
        monthly = breakdown.monthly

        self.assertEqual(monthly.months, ["2023-12", "2024-01", "2024-02", "2024-04"])
        self.assertEqual(monthly.categories, ["军事委托", "字典外类目", "日常任务"])
        self.assertEqual(monthly.month_totals, [1, 5, 12, 2])
        self.assertEqual(monthly.values[0], [1, 3, 5, 2])
        self.assertEqual(monthly.values[1], [0, 0, 7, 0])
        self.assertEqual(monthly.values[2], [0, 2, 0, 0])

    def testCategoryTopNIsMerged(self):
        """类目超过 Top N 时，尾部合并为「其他」。"""
        conn = sqlite3.connect(self._db_path)
        try:
            _insertDaily(conn, "cube", "2024-05-01", "detail")
            for index in range(10):
                _insertTransaction(
                    conn,
                    "cube",
                    "income",
                    f"2024-05-01 0{index}:00:00",
                    f"凑数类目{index}",
                    100 + index,
                )
            conn.commit()
        finally:
            conn.close()

        breakdown = self._service.getCategoryBreakdown("cube", "income")
        monthly = breakdown.monthly

        self.assertEqual(len(monthly.categories), 9)  # Top 8 + 其他
        self.assertEqual(monthly.categories[-1], "其他")
        self.assertEqual(monthly.months, ["2023-12", "2024-01", "2024-02", "2024-04", "2024-05"])

    def testCategoryExpenseDirection(self):
        """方向切换只统计对应方向。"""
        breakdown = self._service.getCategoryBreakdown("cube", "expense")

        self.assertEqual(breakdown.detail_total, 5)
        self.assertEqual(
            [item.name for item in breakdown.shares], ["活动建造", "轻型建造"]
        )

    # ------------------------------------------------------------- 军事委托

    def testCommissionAllRangeKeepsGaps(self):
        """全部范围按连续月份输出，缺口月份为 None 而不是 0。"""
        overview = self._service.getCommissionOverview("cube")

        self.assertEqual(overview.months, ["2023-12", "2024-01", "2024-02", "2024-03", "2024-04"])
        self.assertEqual(overview.amounts, [1, 3, 5, None, 2])
        self.assertEqual(overview.totals.amount, 11)
        self.assertEqual(overview.totals.count, 4)
        self.assertEqual(overview.totals.max_amount, 5)
        self.assertEqual(overview.totals.active_days, 4)
        self.assertAlmostEqual(overview.totals.mean, 2.75)
        self.assertAlmostEqual(overview.totals.daily_mean, 2.75)
        self.assertEqual(overview.amount_distribution, [(1, 1), (2, 1), (3, 1), (5, 1)])
        self.assertEqual(overview.range_label, "全部")

    @patch("utils.time_source.today", return_value=date(2024, 6, 15))
    def testCommissionRecentRangeStartsFromToday(self, _today):
        """近一年以今天所在月为末月，起点不早于数据起点。"""
        overview = self._service.getCommissionOverview("cube", 12)

        self.assertEqual(overview.range_start, "2023-12")
        self.assertEqual(overview.range_end, "2024-06")
        self.assertEqual(len(overview.months), 7)
        self.assertEqual(overview.amounts, [1, 3, 5, None, 2, None, None])
        self.assertEqual(overview.totals.amount, 11)
        self.assertEqual(overview.range_label, "近 12 个月")

    @patch("utils.time_source.today", return_value=date(2024, 6, 15))
    def testCommissionRollingAverageNeedsSamples(self, _today):
        """移动平均在样本不足时为 None，当前月无记录时也为 None。"""
        overview = self._service.getCommissionOverview("cube", 12)

        self.assertEqual(overview.rolling_average[:2], [None, None])
        self.assertEqual(overview.rolling_average[2], 3.0)
        self.assertIsNone(overview.rolling_average[3])
        self.assertEqual(overview.rolling_average[4], 2.75)

    def testCommissionEmptyResource(self):
        """没有委托记录时返回空概览。"""
        conn = sqlite3.connect(self._db_path)
        try:
            conn.execute(
                "DELETE FROM resource_transaction WHERE resource_type = 'red_gem' AND category = '军事委托'"
            )
            conn.commit()
        finally:
            conn.close()

        overview = self._service.getCommissionOverview("red_gem")

        self.assertFalse(overview.hasData)
        self.assertEqual(overview.months, [])
        self.assertEqual(overview.totals.count, 0)
        self.assertEqual(overview.range_label, "全部")


class TestMissingSchemaDegrades(unittest.TestCase):
    """旧库缺表时降级为空结果。"""

    def setUp(self):
        self._original_db_path = DatabaseConnection.getDbPath()
        self._temp_dir = tempfile.mkdtemp(prefix="azurlane_analysis_empty_")
        self._db_path = os.path.join(self._temp_dir, "empty.db")
        DatabaseConnection.setDbPath(self._db_path)
        sqlite3.connect(self._db_path).close()

    def tearDown(self):
        DatabaseConnection.setDbPath(self._original_db_path)

    def testMissingTablesReturnEmptyResults(self):
        """建表脚本未执行时，三个聚合都返回空结果而不是抛异常。"""
        service = ResourceAnalysisService()

        trend = service.getTrend("cube")
        self.assertEqual(trend.balance_points, [])
        self.assertEqual(trend.latestBalance, 0)

        breakdown = service.getCategoryBreakdown("cube", "income")
        self.assertFalse(breakdown.hasData)
        self.assertEqual(breakdown.monthly.months, [])

        overview = service.getCommissionOverview("cube")
        self.assertFalse(overview.hasData)


if __name__ == "__main__":
    unittest.main()
