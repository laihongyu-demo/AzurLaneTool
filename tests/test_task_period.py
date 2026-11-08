"""
任务周期与世界巡游档期测试。

覆盖：日 / 周 / 月 / 双月期键与区间、档期列表、档期键校验。
"""

import unittest
from datetime import date

from services.world_cruise_service import WorldCruiseService
from utils.exceptions import ValidationError
from utils.task_period import (
    buildPeriodInfo, buildPeriodKey, cruisePeriodEnd, cruisePeriodStart, periodRange,
)


class TestTaskPeriod(unittest.TestCase):
    """周期纯函数测试。"""

    def testPeriodKeys(self):
        """日 / 周 / 月 / 期键格式正确。"""
        self.assertEqual(buildPeriodKey("day", date(2026, 10, 17)), "2026-10-17")
        self.assertEqual(buildPeriodKey("week", date(2026, 10, 17)), "2026-W42")
        self.assertEqual(buildPeriodKey("month", date(2026, 10, 17)), "2026-10")
        self.assertEqual(buildPeriodKey("cruise", date(2026, 11, 30)), "2026-10")

    def testCruisePeriodRange(self):
        """巡游期为偶数月 1 日至次月最后一天。"""
        self.assertEqual(cruisePeriodStart(date(2026, 10, 17)), date(2026, 10, 1))
        self.assertEqual(cruisePeriodEnd(date(2026, 10, 17)), date(2026, 11, 30))
        self.assertEqual(
            periodRange("cruise", date(2026, 10, 17)),
            (date(2026, 10, 1), date(2026, 11, 30)),
        )

    def testBuildPeriodInfo(self):
        """周期信息包含键、标签与起止日。"""
        info = buildPeriodInfo("cruise", date(2026, 10, 17))

        self.assertEqual(info.period_key, "2026-10")
        self.assertEqual(info.label, "2026-10-01 ~ 2026-11-30")
        self.assertEqual(info.start, "2026-10-01")
        self.assertEqual(info.end, "2026-11-30")


class TestWorldCruiseService(unittest.TestCase):
    """世界巡游档期服务测试。"""

    def setUp(self):
        self._service = WorldCruiseService()

    def testGetPeriod(self):
        """按日期返回所属档期。"""
        period = self._service.getPeriod(date(2026, 10, 24))

        self.assertEqual(period.key, "2026-10")
        self.assertEqual(period.start, date(2026, 10, 1))
        self.assertEqual(period.end, date(2026, 11, 30))
        self.assertEqual(period.label, "2026-10-01 ~ 2026-11-30")

    def testGetPeriodByKey(self):
        """按档期键取回档期。"""
        period = self._service.getPeriodByKey("2026-10")

        self.assertEqual(period.start, date(2026, 10, 1))
        self.assertEqual(period.end, date(2026, 11, 30))

    def testInvalidPeriodKeyRejected(self):
        """非偶数月起始键被拒绝。"""
        with self.assertRaises(ValidationError):
            self._service.getPeriodByKey("2026-09")

    def testListPeriodsCurrentFirst(self):
        """列表当前期在前，按时间倒序包含历史期。"""
        periods = self._service.listPeriods(date(2026, 10, 24), past_count=2)

        self.assertEqual([period.key for period in periods], ["2026-10", "2026-08", "2026-06"])


if __name__ == "__main__":
    unittest.main()
