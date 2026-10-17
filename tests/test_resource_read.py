"""
资源统计只读服务单元测试。

覆盖：结余链与手填锚点、明细日折算、卡片文本口径、日期范围过滤、
表缺失降级，以及"本阶段不提供写接口"的约定。
"""

import unittest

from models.resource_model import ResourceCategoryModel, ResourceDailyModel
from repositories.resource_repository import ResourceRepository
from services.resource_service import ResourceService
from utils.constants import (
    RESOURCE_DETAIL_MODE_DETAIL, RESOURCE_DETAIL_MODE_SUMMARY_ONLY, RESOURCE_TYPE_CUBE,
    RESOURCE_TYPE_RED_GEM,
)
from utils.exceptions import DatabaseError


class _StubResourceRepository:
    """资源数据访问桩：返回预设的日汇总、明细汇总与字典。"""

    def __init__(self, daily=None, totals=None, categories=None, missing_table=False):
        self.daily = list(daily or [])
        self.totals = dict(totals or {})
        self.categories = list(categories or [])
        self.missing_table = missing_table

    def _guard(self):
        if self.missing_table:
            raise DatabaseError("no such table: resource_daily")

    def findAllDaily(self, resource_type):
        self._guard()
        return [row for row in self.daily if row.resource_type == resource_type]

    def findTransactionTotals(self, resource_type):
        self._guard()
        return dict(self.totals)

    def findCategories(self, resource_type, direction):
        self._guard()
        return [
            item for item in self.categories
            if item.resource_type == resource_type and item.direction == direction
        ]


def _summary_day(record_date: str, income: int, expense: int, override=None) -> ResourceDailyModel:
    """构造汇总日（无明细）。"""
    return ResourceDailyModel(
        resource_type=RESOURCE_TYPE_CUBE,
        record_date=record_date,
        detail_mode=RESOURCE_DETAIL_MODE_SUMMARY_ONLY,
        income=income,
        expense=expense,
        balance_override=override,
    )


def _detail_day(record_date: str, override=None) -> ResourceDailyModel:
    """构造明细日（收支由明细聚合）。"""
    return ResourceDailyModel(
        resource_type=RESOURCE_TYPE_CUBE,
        record_date=record_date,
        detail_mode=RESOURCE_DETAIL_MODE_DETAIL,
        balance_override=override,
    )


class TestBalanceChain(unittest.TestCase):
    """结余链与锚点测试。"""

    def _service(self) -> ResourceService:
        daily = [
            _summary_day("2023-08-03", 7, 1, override=3),
            _detail_day("2023-08-04"),
            _detail_day("2023-08-05"),
            _summary_day("2023-08-06", 0, 0, override=100),
            _summary_day("2023-08-07", 4, 1),
        ]
        totals = {
            "2023-08-04": {"income": 20, "expense": 0, "count": 3},
            "2023-08-05": {"income": 0, "expense": 5, "count": 1},
        }
        return ResourceService(_StubResourceRepository(daily=daily, totals=totals))

    def testBalanceUsesAnchorsAndDetailTotals(self):
        """锚点重设结余，明细日按 Σ明细 累计。"""
        series = self._service().getBalanceSeries(RESOURCE_TYPE_CUBE)

        self.assertEqual([item["balance"] for item in series], [3, 23, 18, 100, 103])
        self.assertEqual([item["income"] for item in series], [7, 20, 0, 0, 4])
        self.assertEqual([item["expense"] for item in series], [1, 0, 5, 0, 1])
        self.assertEqual([item["transaction_count"] for item in series], [0, 3, 1, 0, 0])

    def testCurrentBalanceAndLatestDate(self):
        """当前结余与末次记录日期取最后一行。"""
        service = self._service()

        self.assertEqual(service.getBalance(RESOURCE_TYPE_CUBE), 103)
        self.assertEqual(service.getLatestRecordDate(RESOURCE_TYPE_CUBE), "2023-08-07")

    def testListDailyFiltersByDate(self):
        """日期范围过滤包含边界。"""
        service = self._service()

        rows = service.listDaily(RESOURCE_TYPE_CUBE, "2023-08-04", "2023-08-06")

        self.assertEqual([row["record_date"] for row in rows], ["2023-08-04", "2023-08-05", "2023-08-06"])

    def testBalanceOverrideIsReported(self):
        """锚点日在结果中带出 balance_override 原值。"""
        series = self._service().getBalanceSeries(RESOURCE_TYPE_CUBE)

        self.assertEqual(series[0]["balance_override"], 3)
        self.assertIsNone(series[1]["balance_override"])


class TestResourceCardText(unittest.TestCase):
    """看板卡片与提示文本测试。"""

    def testCardTextUsesAbbreviation(self):
        """结余 10,000 按大概数值口径显示为 10.0K。"""
        repository = _StubResourceRepository(
            daily=[_summary_day("2026-10-17", 10000, 0)]
        )
        service = ResourceService(repository)

        self.assertEqual(service.getCardText(RESOURCE_TYPE_CUBE), "10.0K")
        self.assertIn("10,000", service.getCardTooltip(RESOURCE_TYPE_CUBE))

    def testCardTextBelowThousandHasNoSuffix(self):
        """千位以下不带单位。"""
        repository = _StubResourceRepository(
            daily=[_summary_day("2026-10-17", 103, 0)]
        )

        self.assertEqual(ResourceService(repository).getCardText(RESOURCE_TYPE_CUBE), "103")

    def testCardTextWithoutData(self):
        """无数据时卡片显示 -，提示说明暂无记录。"""
        service = ResourceService(_StubResourceRepository())

        self.assertEqual(service.getCardText(RESOURCE_TYPE_RED_GEM), "-")
        self.assertIn("暂无记录", service.getCardTooltip(RESOURCE_TYPE_RED_GEM))
        self.assertIsNone(service.getBalance(RESOURCE_TYPE_RED_GEM))

    def testMissingTableDegrades(self):
        """表缺失时读取降级为空，不抛异常。"""
        service = ResourceService(_StubResourceRepository(missing_table=True))

        self.assertEqual(service.getBalanceSeries(RESOURCE_TYPE_CUBE), [])
        self.assertIsNone(service.getBalance(RESOURCE_TYPE_CUBE))
        self.assertEqual(service.getCardText(RESOURCE_TYPE_CUBE), "-")
        self.assertEqual(service.getCategories(RESOURCE_TYPE_CUBE, "income"), [])

    def testCategoriesAreOrderedByRepository(self):
        """字典按仓库返回顺序透出名称。"""
        repository = _StubResourceRepository(categories=[
            ResourceCategoryModel(resource_type=RESOURCE_TYPE_CUBE, direction="income", name="日常任务"),
            ResourceCategoryModel(resource_type=RESOURCE_TYPE_CUBE, direction="income", name="军事委托"),
            ResourceCategoryModel(resource_type=RESOURCE_TYPE_CUBE, direction="expense", name="轻型建造"),
        ])
        service = ResourceService(repository)

        self.assertEqual(service.getCategories(RESOURCE_TYPE_CUBE, "income"), ["日常任务", "军事委托"])
        self.assertEqual(service.getCategories(RESOURCE_TYPE_CUBE, "expense"), ["轻型建造"])


class TestWriteInterfaceClosed(unittest.TestCase):
    """本阶段必须不提供写入接口（需求文档 AC-09）。"""

    def testRepositoryWriteMethodsRaise(self):
        """Repository 的增删改一律拒绝，提示指向 #17。"""
        repository = ResourceRepository()

        for method_name in ("insert", "update", "delete"):
            with self.assertRaises(NotImplementedError) as ctx:
                getattr(repository, method_name)(None)
            self.assertIn("#17", str(ctx.exception))

    def testServiceHasNoWriteMethods(self):
        """服务层不暴露任何写方法。"""
        forbidden = [name for name in dir(ResourceService) if name.startswith(
            ("add", "update", "delete", "set", "insert")
        )]

        self.assertEqual(forbidden, [])


if __name__ == "__main__":
    unittest.main()
