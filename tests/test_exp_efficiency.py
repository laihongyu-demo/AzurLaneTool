"""
指级效率算法单元测试（#16）。

口径见 docs/指级效率算法方案_20261018.md。用内存桩替换仓储，
覆盖：日窗口取点、同日去重、跨级换算、扩窗、降级与满级边界。
"""

import unittest
from datetime import datetime, timedelta

from models.commander_model import CommanderLevelExpModel, CommanderSnapshotModel
from services.commander_service import CommanderService

# 合成基准：1～199 级每级 100 经验，200 级为满级（NULL）
LEVEL_UP_EXP = 100
FULL_LEVEL = 200


def _buildRequirements(max_level: int = FULL_LEVEL):
    """
    构造等级基准：`cumulative_exp(L) = 100 * L`，满级行留 NULL。

    Args:
        max_level: 最高等级。

    Returns:
        等级 → 基准模型的字典。
    """
    requirements = {}
    for level in range(1, max_level):
        requirements[level] = CommanderLevelExpModel(
            level=level,
            level_up_exp=LEVEL_UP_EXP,
            cumulative_exp=LEVEL_UP_EXP * level,
        )
    requirements[max_level] = CommanderLevelExpModel(
        level=max_level, level_up_exp=None, cumulative_exp=None
    )
    return requirements


class _StubCommanderRepository:
    """指挥官数据访问桩：内存快照 + 合成基准。"""

    def __init__(self, snapshots=None, requirements=None):
        self.snapshots = list(snapshots or [])
        self.requirements = requirements if requirements is not None else _buildRequirements()

    def findAll(self):
        return sorted(self.snapshots, key=lambda s: s.statistics_date, reverse=True)

    def findLatest(self):
        ordered = self.findAll()
        return ordered[0] if ordered else None

    def findLevelExp(self, level):
        return self.requirements.get(level)


def _snapshot(record_id: int, moment: datetime, level: int, exp: int) -> CommanderSnapshotModel:
    """构造快照模型。"""
    return CommanderSnapshotModel(
        id=record_id,
        statistics_date=moment.strftime("%Y-%m-%d %H:%M"),
        commander_level=level,
        commander_exp=exp,
    )


class _EfficiencyCase(unittest.TestCase):
    """构造服务的公共基类。"""

    BASE = datetime(2026, 10, 18, 12, 0)

    def _service(self, snapshots) -> CommanderService:
        """用给定快照构造服务。"""
        return CommanderService(_StubCommanderRepository(snapshots))

    def _at(self, days_ago: int, hour: int = 12) -> datetime:
        """相对基准日的时刻。"""
        return (self.BASE - timedelta(days=days_ago)).replace(hour=hour)


class TestAbsoluteExp(_EfficiencyCase):
    """绝对经验换算测试。"""

    def testLevelOneStartsAtZero(self):
        """1 级没有前序门槛，绝对值就是本级经验。"""
        service = self._service([])

        self.assertEqual(service.getAbsoluteExp(1, 42), 42)

    def testLevelUsesPreviousCumulative(self):
        """L 级 = cum(L-1) + 本级经验。"""
        service = self._service([])

        self.assertEqual(service.getAbsoluteExp(5, 30), 400 + 30)

    def testFullLevelStillComputable(self):
        """满级 200 只用到 cum(199)，不触碰 NULL 行。"""
        service = self._service([])

        self.assertEqual(service.getAbsoluteExp(200, 500), 100 * 199 + 500)

    def testOutOfRangeLevelsReturnNone(self):
        """越界等级无法换算。"""
        service = self._service([])

        self.assertIsNone(service.getAbsoluteExp(0, 10))
        self.assertIsNone(service.getAbsoluteExp(201, 10))

    def testMissingRequirementReturnsNone(self):
        """基准缺失时无法换算。"""
        repository = _StubCommanderRepository(
            requirements={1: CommanderLevelExpModel(level=1, level_up_exp=50, cumulative_exp=50)}
        )

        self.assertIsNone(CommanderService(repository).getAbsoluteExp(10, 0))


class TestWindowSelection(_EfficiencyCase):
    """窗口取点与扩窗测试。"""

    def testTwoConsecutiveDays(self):
        """相邻两天各 +1,000 经验 → 1,000/天。"""
        snapshots = [
            _snapshot(1, self._at(1), 5, 1000),
            _snapshot(2, self._at(0), 5, 2000),
        ]

        efficiency = self._service(snapshots).getExpEfficiency()

        self.assertEqual(efficiency.rate_per_day, 1000)
        self.assertEqual(efficiency.span_days, 1.0)
        self.assertEqual(efficiency.sample_count, 2)

    def testCrossLevelKeepsContinuous(self):
        """跨级时绝对经验连续，不出现负增量。"""
        snapshots = [
            _snapshot(1, self._at(1), 3, 150),   # 200 + 150 = 350
            _snapshot(2, self._at(0), 4, 150),   # 300 + 150 = 450
        ]

        efficiency = self._service(snapshots).getExpEfficiency()

        self.assertEqual(efficiency.rate_per_day, 100)

    def testSameDayKeepsLastSnapshot(self):
        """同日多条只保留最后一条，样本数按天计。"""
        snapshots = [
            _snapshot(1, self._at(1, hour=8), 5, 1000),
            _snapshot(2, self._at(1, hour=20), 5, 2000),
            _snapshot(3, self._at(0), 5, 2000),
        ]

        efficiency = self._service(snapshots).getExpEfficiency()

        self.assertEqual(efficiency.sample_count, 2)
        self.assertEqual(efficiency.rate_per_day, 0)
        self.assertIn("2026-10-17 20:00", efficiency.start_time)

    def testStartIsLastSnapshotBeforeCutoff(self):
        """起点取窗口边界之前最近的一条快照（跨度可大于窗口）。"""
        snapshots = [
            _snapshot(1, self._at(60), 5, 0),
            _snapshot(2, self._at(20), 5, 1000),
            _snapshot(3, self._at(0), 5, 2000),
        ]

        efficiency = self._service(snapshots).getExpEfficiency()

        self.assertEqual(efficiency.start_time, self._at(60).strftime("%Y-%m-%d %H:%M"))
        self.assertEqual(efficiency.span_days, 60.0)
        self.assertEqual(efficiency.rate_per_day, round(2000 / 60))

    def testAllWithinWindowUsesEarliest(self):
        """全部历史都在窗口内时，直接用最早一条（跨度小于窗口）。"""
        snapshots = [
            _snapshot(1, self._at(10), 5, 1000),
            _snapshot(2, self._at(0), 5, 3000),
        ]

        efficiency = self._service(snapshots).getExpEfficiency()

        self.assertEqual(efficiency.span_days, 10.0)
        self.assertEqual(efficiency.rate_per_day, 200)
        self.assertEqual(efficiency.start_time, self._at(10).strftime("%Y-%m-%d %H:%M"))
        self.assertIn("样本较少", self._service(snapshots).getExpEfficiencyTooltip())

    def testCumulativeRateUsesWholeHistory(self):
        """累计日均按首条到末条计算。"""
        snapshots = [
            _snapshot(1, self._at(100), 5, 0),
            _snapshot(2, self._at(0), 5, 5000),
        ]

        efficiency = self._service(snapshots).getExpEfficiency()

        self.assertEqual(efficiency.cumulative_rate, 50)


class TestDegradation(_EfficiencyCase):
    """降级路径测试。"""

    def testNoSnapshot(self):
        """无快照 → '-' 且提示录入。"""
        service = self._service([])

        self.assertEqual(service.getExpEfficiencyText(), "-")
        self.assertIn("暂无快照", service.getExpEfficiencyTooltip())

    def testSingleSnapshot(self):
        """仅一条快照无法构成区间。"""
        service = self._service([_snapshot(1, self._at(0), 5, 1000)])

        self.assertEqual(service.getExpEfficiencyText(), "-")
        self.assertIn("至少需要两条", service.getExpEfficiencyTooltip())

    def testRollbackDetected(self):
        """绝对经验回退视为录入错误并降级。"""
        snapshots = [
            _snapshot(1, self._at(5), 5, 5000),
            _snapshot(2, self._at(0), 5, 100),
        ]

        service = self._service(snapshots)

        self.assertEqual(service.getExpEfficiencyText(), "-")
        self.assertIn("录入错误", service.getExpEfficiencyTooltip())

    def testUnconvertibleSnapshotsAreSkipped(self):
        """越界等级被跳过；剩余两条仍可计算。"""
        snapshots = [
            _snapshot(1, self._at(2), 0, 100),
            _snapshot(2, self._at(1), 5, 1000),
            _snapshot(3, self._at(0), 5, 2000),
        ]

        efficiency = self._service(snapshots).getExpEfficiency()

        self.assertEqual(efficiency.rate_per_day, 1000)
        self.assertEqual(efficiency.skipped, 1)

    def testAllSnapshotsUnconvertible(self):
        """全部无法换算时按无数据处理。"""
        service = self._service([
            _snapshot(1, self._at(1), 201, 100),
            _snapshot(2, self._at(0), 201, 200),
        ])

        self.assertEqual(service.getExpEfficiencyText(), "-")


class TestCardText(_EfficiencyCase):
    """卡片文本格式测试。"""

    def testTextUsesThousandSeparatorAndUnit(self):
        """精确值 + 千分符 + /天。"""
        snapshots = [
            _snapshot(1, self._at(1), 5, 1000),
            _snapshot(2, self._at(0), 5, 123456),
        ]

        text = self._service(snapshots).getExpEfficiencyText()

        self.assertTrue(text.endswith("/天"))
        self.assertIn(",", text)
        self.assertNotIn(" ", text)

    def testTooltipContainsWindowAndSamples(self):
        """tooltip 交代窗口、区间、样本数与累计对照。"""
        snapshots = [
            _snapshot(1, self._at(1), 5, 1000),
            _snapshot(2, self._at(0), 5, 2000),
        ]

        tooltip = self._service(snapshots).getExpEfficiencyTooltip()

        self.assertIn("近 30 天日均", tooltip)
        self.assertIn("2 条快照", tooltip)
        self.assertIn("累计日均", tooltip)


if __name__ == "__main__":
    unittest.main()
