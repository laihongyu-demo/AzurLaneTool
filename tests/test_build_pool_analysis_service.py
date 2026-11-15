"""
大建分析与毕业预测测试（#19）。

覆盖：只统计毕业池、分位插值、滚动中位数、经验生存曲线、样本范围过滤、
预算与进度对照（含超过样本最大值）。用桩服务喂数据，不依赖真实库。
"""

import os
import sqlite3
import tempfile
import unittest

from models.event_model import EventRecordModel
from services.build_pool_analysis_service import BuildPoolAnalysisService, percentile
from services.event_record_service import EventRecordService, EventRecordView
from utils.db_connection import DatabaseConnection
from utils.db_schema import ensureResourceStatisticsSchema


def _view(
    event_date: str,
    build_count,
    status: str = "毕业",
    event_type: str = "大型海域",
    build_cost: int = 2,
    derived: bool = False,
    name: str = "测试活动",
) -> EventRecordView:
    """构造一条活动记录展示行（测试夹具）。"""
    record = EventRecordModel(
        id=1,
        event_date=event_date,
        event_type=event_type,
        name=name,
        status=status,
        build_cost=build_cost,
    )
    return EventRecordView(record=record, build_count=build_count, derived=derived)


class _StubEventService:
    """只实现 listRecords 的活动服务桩。"""

    def __init__(self, views):
        self._views = list(views)

    def listRecords(self, *args, **kwargs):
        """返回预置记录。"""
        return list(self._views)


class TestPercentile(unittest.TestCase):
    """线性插值分位函数。"""

    def testInterpolatesBetweenNeighbours(self):
        """四个样本的 P50 落在中间两个值之间。"""
        self.assertEqual(percentile([10, 20, 30, 40], 0.5), 25.0)

    def testClampsFraction(self):
        """分位越界时截断到端点。"""
        self.assertEqual(percentile([10, 20], -1), 10.0)
        self.assertEqual(percentile([10, 20], 2), 20.0)

    def testEmptyReturnsZero(self):
        """空样本返回 0，调用方据此判断无数据。"""
        self.assertEqual(percentile([], 0.5), 0.0)

    def testSingleValue(self):
        """单样本任意分位都是该值。"""
        self.assertEqual(percentile([7], 0.9), 7.0)


class TestBuildPoolAnalysis(unittest.TestCase):
    """毕业池统计与预测。"""

    def _service(self, views) -> BuildPoolAnalysisService:
        """构造注入桩活动的分析服务。"""
        return BuildPoolAnalysisService(_StubEventService(views))

    def testOnlyGraduatedPoolsCounted(self):
        """缺 / 进行中 / 未标记 / 次数为空的池都不计入，但计入「未计入」数量。"""
        service = self._service([
            _view("2024-01-01", 10),
            _view("2024-02-01", 20),
            _view("2024-03-01", None),
            _view("2024-04-01", 30, status="缺"),
            _view("2024-05-01", 40, status="进行中"),
            _view("2024-06-01", 50, status=""),
        ])

        analysis = service.getAnalysis()

        self.assertEqual(analysis.sample_size, 2)
        self.assertEqual(analysis.total, 30)
        self.assertEqual(analysis.excluded_count, 4)
        self.assertEqual([point.build_count for point in analysis.points], [10, 20])

    def testStatusIsStrippedButMustBeExact(self):
        """状态去空格后精确匹配「毕业」，自定义状态不计入。"""
        service = self._service([
            _view("2024-01-01", 10, status=" 毕业 "),
            _view("2024-02-01", 20, status="已毕业"),
        ])

        analysis = service.getAnalysis()

        self.assertEqual(analysis.sample_size, 1)
        self.assertEqual(analysis.points[0].build_count, 10)

    def testQuantilesAndAverages(self):
        """分位、中位数、均值、最大值。"""
        service = self._service([
            _view("2024-01-01", 10),
            _view("2024-02-01", 20),
            _view("2024-03-01", 30),
            _view("2024-04-01", 40),
        ])

        analysis = service.getAnalysis()

        self.assertEqual(analysis.median, 25.0)
        self.assertEqual(analysis.mean, 25.0)
        self.assertEqual(analysis.total, 100)
        self.assertEqual(analysis.max_count, 40)
        self.assertEqual(analysis.quantiles[0.5], 25.0)
        self.assertAlmostEqual(analysis.quantiles[0.9], 37.0)

    def testRollingMedianUsesTrailingWindow(self):
        """滚动中位数按尾随窗口计算，开头窗口不足时用已有样本。"""
        service = self._service([
            _view("2024-01-01", 10),
            _view("2024-02-01", 20),
            _view("2024-03-01", 30),
        ])

        analysis = service.getAnalysis()

        self.assertEqual(analysis.rolling_median, [10.0, 15.0, 20.0])

    def testSurvivalCurve(self):
        """生存曲线从 (0, 1.0) 开始，按不同次数给出剩余比例。"""
        service = self._service([
            _view("2024-01-01", 10),
            _view("2024-02-01", 20),
            _view("2024-03-01", 30),
        ])

        analysis = service.getAnalysis()

        self.assertEqual(analysis.survival[0], (0, 1.0))
        self.assertEqual([point[0] for point in analysis.survival], [0, 10, 20, 30])
        self.assertAlmostEqual(analysis.survival[1][1], 2 / 3)
        self.assertEqual(analysis.survival[-1], (30, 0.0))

    def testByYearAndTypeGroups(self):
        """年份升序、类型按 复刻→祈愿→其它 排列。"""
        service = self._service([
            _view("2024-01-01", 10, event_type="活动海域·轻量化复刻"),
            _view("2024-06-01", 20, event_type="大型海域·祈愿"),
            _view("2025-01-01", 30, event_type="大型海域"),
            _view("2025-06-01", 40, event_type="大型海域"),
        ])

        analysis = service.getAnalysis()

        self.assertEqual([group.name for group in analysis.by_year], ["2024", "2025"])
        self.assertEqual(analysis.by_year[0].sample_size, 2)
        self.assertEqual(
            [(group.name, group.sample_size) for group in analysis.by_type],
            [("复刻", 1), ("祈愿", 1), ("首次活动", 2)],
        )

    def testPointsSortedByDate(self):
        """输入是倒序（活动记录服务按日期倒序）时，输出仍按日期升序。"""
        service = self._service([
            _view("2024-03-01", 30),
            _view("2024-02-01", 20),
            _view("2024-01-01", 10),
        ])

        analysis = service.getAnalysis()

        self.assertEqual(
            [point.event_date for point in analysis.points],
            ["2024-01-01", "2024-02-01", "2024-03-01"],
        )
        self.assertEqual(analysis.rolling_median, [10.0, 15.0, 20.0])

    def testScopeFilters(self):
        """样本范围：全部 / 排除祈愿 / 仅复刻 / 仅祈愿。"""
        views = [
            _view("2024-01-01", 10, event_type="大型海域·轻量化复刻"),
            _view("2024-02-01", 20, event_type="大型海域·祈愿"),
            _view("2024-03-01", 30, event_type="大型海域"),
        ]
        service = self._service(views)

        self.assertEqual(service.getAnalysis("all").sample_size, 3)
        self.assertEqual(service.getAnalysis("exclude_wish").sample_size, 2)
        self.assertEqual(service.getAnalysis("copy").sample_size, 1)
        self.assertEqual(service.getAnalysis("wish").sample_size, 1)

    def testBudgetMultipliesBuildCost(self):
        """预算 = 分位次数 × 单耗（四舍五入）。"""
        service = self._service([
            _view("2024-01-01", 10),
            _view("2024-02-01", 20),
            _view("2024-03-01", 30),
            _view("2024-04-01", 40),
        ])
        analysis = service.getAnalysis()

        budget = service.buildBudget(analysis, 2)

        self.assertEqual([level.label for level in budget], ["中位", "偏高", "极端"])
        self.assertEqual([level.cube_cost for level in budget], [50, 65, 74])

    def testPredictionRankAndRemaining(self):
        """进度对照：分位排名、剩余中位数与 P75、折算魔方。"""
        service = self._service([
            _view("2024-01-01", 10),
            _view("2024-02-01", 20),
            _view("2024-03-01", 30),
            _view("2024-04-01", 40),
        ])
        analysis = service.getAnalysis()

        prediction = service.predictProgress(analysis, 20, 2)

        self.assertEqual(prediction.sample_size, 4)
        self.assertAlmostEqual(prediction.percentile_rank, 0.375)
        self.assertEqual(prediction.remaining_sample_size, 2)
        self.assertEqual(prediction.remaining_median, 15.0)
        self.assertEqual(prediction.remaining_p75, 17.5)
        self.assertEqual(prediction.cube_remaining_median, 30)
        self.assertEqual(prediction.cube_remaining_p75, 35)
        self.assertFalse(prediction.exceeded_max)

    def testPredictionExceededMax(self):
        """已抽次数达到样本最大值时不再给剩余估计。"""
        service = self._service([_view("2024-01-01", 10), _view("2024-02-01", 20)])
        analysis = service.getAnalysis()

        prediction = service.predictProgress(analysis, 30, 2)

        self.assertTrue(prediction.exceeded_max)
        self.assertIsNone(prediction.remaining_median)
        self.assertIsNone(prediction.cube_remaining_median)

    def testPredictionFromZeroUsesFullDistribution(self):
        """0 次时的剩余中位数等于整体中位数。"""
        service = self._service([_view("2024-01-01", 10), _view("2024-02-01", 30)])
        analysis = service.getAnalysis()

        prediction = service.predictProgress(analysis, 0, 1)

        self.assertEqual(prediction.percentile_rank, 0.0)
        self.assertEqual(prediction.remaining_median, 20.0)

    def testEmptySampleDegrades(self):
        """没有毕业池时各接口返回空结果。"""
        service = self._service([_view("2024-01-01", 10, status="缺")])

        analysis = service.getAnalysis()

        self.assertFalse(analysis.hasData)
        self.assertEqual(analysis.quantiles, {})
        self.assertEqual(service.buildBudget(analysis, 2), [])

        prediction = service.predictProgress(analysis, 50, 2)
        self.assertEqual(prediction.sample_size, 0)
        self.assertEqual(prediction.current_count, 50)


class TestRealRepositoryWiring(unittest.TestCase):
    """用临时库验证与 EventRecordService 的实际接线。"""

    def setUp(self):
        self._original_db_path = DatabaseConnection.getDbPath()
        self._temp_dir = tempfile.mkdtemp(prefix="azurlane_build_analysis_")
        self._db_path = os.path.join(self._temp_dir, "build.db")
        DatabaseConnection.setDbPath(self._db_path)
        ensureResourceStatisticsSchema(self._db_path)

        conn = sqlite3.connect(self._db_path)
        try:
            conn.execute(
                """
                INSERT INTO event_record
                    (event_date, event_type, name, status, build_cost, build_count)
                VALUES ('2024-01-01', '大型海域', '甲', '毕业', 2, 40)
                """
            )
            conn.execute(
                """
                INSERT INTO event_record
                    (event_date, event_type, name, status, build_cost, build_count)
                VALUES ('2024-02-01', '大型海域', '乙', '毕业', 2, 60)
                """
            )
            conn.execute(
                """
                INSERT INTO event_record
                    (event_date, event_type, name, status, build_cost, build_count)
                VALUES ('2024-03-01', '大型海域', '丙', '缺', 2, NULL)
                """
            )
            conn.commit()
        finally:
            conn.close()

    def tearDown(self):
        DatabaseConnection.setDbPath(self._original_db_path)

    def testReadsGraduatedPoolsFromDatabase(self):
        """真实库路径下只汇总毕业池。"""
        service = BuildPoolAnalysisService(EventRecordService())

        analysis = service.getAnalysis()

        self.assertEqual(analysis.sample_size, 2)
        self.assertEqual(analysis.total, 100)
        self.assertEqual(analysis.excluded_count, 1)


if __name__ == "__main__":
    unittest.main()
