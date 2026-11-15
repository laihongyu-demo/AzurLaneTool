"""
业务逻辑层模块单元测试。
"""

import unittest
from datetime import date, timedelta

from models.ship_model import ShipModel
from models.user_model import UserModel
from services.calc_service import CalcService
from services.user_service import UserService


class TestCalcService(unittest.TestCase):
    """计算服务测试类。"""

    def setUp(self):
        """测试初始化。"""
        self._calc_service = CalcService()

    def testComputeStatisticsEmpty(self):
        """测试空数据统计。"""
        result = self._calc_service.computeStatistics([])
        self.assertEqual(result["count"], 0)
        self.assertEqual(result["total_capacity"], 0)
        self.assertEqual(result["mean_capacity"], 0)

    def testComputeStatistics(self):
        """测试数据统计计算。"""
        ships = [
            ShipModel(id=1, name="Ship 1", capacity=1000),
            ShipModel(id=2, name="Ship 2", capacity=2000),
            ShipModel(id=3, name="Ship 3", capacity=3000),
        ]
        result = self._calc_service.computeStatistics(ships)
        self.assertEqual(result["count"], 3)
        self.assertEqual(result["total_capacity"], 6000)
        self.assertEqual(result["mean_capacity"], 2000)
        self.assertEqual(result["max_capacity"], 3000)
        self.assertEqual(result["min_capacity"], 1000)

    def testGroupByStatus(self):
        """测试按状态分组。"""
        ships = [
            ShipModel(id=1, name="Ship 1", capacity=1000, status="active"),
            ShipModel(id=2, name="Ship 2", capacity=2000, status="inactive"),
            ShipModel(id=3, name="Ship 3", capacity=3000, status="active"),
        ]
        result = self._calc_service.groupByStatus(ships)
        self.assertEqual(len(result["active"]), 2)
        self.assertEqual(len(result["inactive"]), 1)

    def testCalculateCapacityDistribution(self):
        """测试载容量分布计算。"""
        ships = [
            ShipModel(id=1, name="Ship 1", capacity=100),
            ShipModel(id=2, name="Ship 2", capacity=200),
            ShipModel(id=3, name="Ship 3", capacity=300),
        ]
        result = self._calc_service.calculateCapacityDistribution(ships, bins=3)
        self.assertIsInstance(result, dict)
        self.assertEqual(sum(result.values()), 3)


class _StubUserRepository:
    """用户数据访问桩：返回指定起始日期的用户。"""

    def __init__(self, start_date: str = ""):
        self._user = (
            UserModel(username="tester", start_date=start_date)
            if start_date else None
        )

    def loadUser(self):
        """返回预设用户模型。"""
        return self._user


class TestUserService(unittest.TestCase):
    """用户服务测试类。"""

    def _serviceWithDaysAgo(self, days_ago: int) -> UserService:
        """构造一个起始日期在 days_ago 天前的用户服务。"""
        start = date.today() - timedelta(days=days_ago)
        return UserService(_StubUserRepository(start.strftime("%Y-%m-%d")))

    def testDutyDaysTextUsesThousandSeparator(self):
        """执勤天数为精确数值，过千时固定加千分符。"""
        service = self._serviceWithDaysAgo(1169)

        self.assertEqual(service.getDutyDays(), 1169)
        self.assertEqual(service.getDutyDaysText(), '1,169天')

    def testDutyDaysTextBelowThousand(self):
        """千位以下不加分隔符。"""
        self.assertEqual(self._serviceWithDaysAgo(999).getDutyDaysText(), '999天')

    def testDutyDaysTextWithoutUser(self):
        """无用户数据时执勤天数为 0。"""
        self.assertEqual(UserService(_StubUserRepository()).getDutyDaysText(), '0天')


if __name__ == "__main__":
    unittest.main()
