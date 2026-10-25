"""
指级效率算法单元测试（#16 v1 / #23 v2）。

口径见 docs/指级效率算法优化方案_20261018.md。用内存桩替换仓储，
覆盖：日窗口取点、同日去重、跨级换算、扩窗、降级与满级边界；
v2 追加：近期连续块、趋势档位、异常隔离、缺口、数据新鲜度与升级情景。
"""

import unittest
from datetime import datetime, timedelta
from unittest.mock import patch

from models.commander_model import CommanderLevelExpModel, CommanderSnapshotModel
from services.commander_service import (
    CommanderService, TREND_ACCELERATING, TREND_DECELERATING, TREND_STABLE,
)
from utils.exceptions import DatabaseError

# 合成基准：1～199 级每级 100 万经验，200 级为满级（NULL）。
# 取 100 万是为了让快照的本级经验（测试里到 75 万）不超过本级需求，
# 与真实库「本级经验 <= level_up_exp」的约束一致（#23 §4.1 异常校验）。
LEVEL_UP_EXP = 1_000_000
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

        self.assertEqual(service.getAbsoluteExp(5, 30), LEVEL_UP_EXP * 4 + 30)

    def testFullLevelStillComputable(self):
        """满级 200 只用到 cum(199)，不触碰 NULL 行。"""
        service = self._service([])

        self.assertEqual(service.getAbsoluteExp(200, 500), LEVEL_UP_EXP * 199 + 500)

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
            _snapshot(1, self._at(1), 3, 150),   # 2,000,000 + 150
            _snapshot(2, self._at(0), 4, 150),   # 3,000,000 + 150
        ]

        efficiency = self._service(snapshots).getExpEfficiency()

        self.assertEqual(efficiency.rate_per_day, LEVEL_UP_EXP)

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


class _MissingTableView:
    """模拟旧库缺表：读取快照时抛 DatabaseError。"""

    def findAll(self):
        raise DatabaseError("no such table: commander_info")

    def findLatest(self):
        raise DatabaseError("no such table: commander_info")

    def findLevelExp(self, level):
        return None


class TestRecentBlock(_EfficiencyCase):
    """近期连续块（fast）测试（#23 §5.2）。"""

    def testGapResetsRecentBlock(self):
        """T-13：-12 天与 -3 天之间缺口 9 天，fast 只用 -3 之后的点。"""
        snapshots = [
            _snapshot(1, self._at(20), 5, 0),
            _snapshot(2, self._at(12), 5, 100000),
            _snapshot(3, self._at(3), 5, 400000),
            _snapshot(4, self._at(1), 5, 500000),
        ]

        efficiency = self._service(snapshots).getExpEfficiency()

        self.assertEqual(efficiency.fast_rate_per_day, 50000)
        self.assertEqual(efficiency.fast_start_time, self._at(3).strftime("%Y-%m-%d %H:%M"))
        self.assertEqual(efficiency.fast_sample_count, 2)
        # 若错误地从 -12 天起算会得到 36,364/天
        self.assertNotEqual(efficiency.fast_rate_per_day, 36364)

    def testFastCapLimitsLookback(self):
        """T-15：每日快照连续 20 天，fast 跨度被 cap 在 14 天。"""
        snapshots = [
            _snapshot(index + 1, self._at(19 - index), 5, (index + 1) * 1000)
            for index in range(20)
        ]

        efficiency = self._service(snapshots).getExpEfficiency()

        self.assertAlmostEqual(efficiency.fast_span_days, 14.0)
        self.assertEqual(efficiency.fast_rate_per_day, 1000)
        self.assertEqual(efficiency.fast_sample_count, 15)

    def testGapOverSevenDaysLeavesSinglePoint(self):
        """只有两条、跨度 10 天时，缺口 >7 天 → fast 为空。"""
        snapshots = [
            _snapshot(1, self._at(10), 5, 0),
            _snapshot(2, self._at(0), 5, 100000),
        ]

        efficiency = self._service(snapshots).getExpEfficiency()

        self.assertIsNone(efficiency.fast_rate_per_day)
        self.assertIn("近期样本不足", self._service(snapshots).getExpEfficiencyTooltip())


class TestTrend(_EfficiencyCase):
    """趋势档位测试（#23 §5.3）。"""

    def _accelerating(self):
        """slow=1,000、fast=1,300 的一组快照。"""
        return [
            _snapshot(1, self._at(30), 5, 0),
            _snapshot(2, self._at(10), 5, 17000),
            _snapshot(3, self._at(5), 5, 23500),
            _snapshot(4, self._at(0), 5, 30000),
        ]

    def testAccelerating(self):
        """T-16：fast/slow ≈ 1.3 → 加速。"""
        service = self._service(self._accelerating())
        efficiency = service.getExpEfficiency()

        self.assertEqual(efficiency.rate_per_day, 1000)
        self.assertEqual(efficiency.fast_rate_per_day, 1300)
        self.assertEqual(efficiency.trend, TREND_ACCELERATING)
        self.assertAlmostEqual(efficiency.trend_ratio, 1.3)
        self.assertIn("趋势 加速 +30%", service.getExpEfficiencyTooltip())

    def testDecelerating(self):
        """T-17：fast/slow ≈ 0.7 → 放缓，百分比带负号。"""
        snapshots = [
            _snapshot(1, self._at(30), 5, 0),
            _snapshot(2, self._at(10), 5, 23000),
            _snapshot(3, self._at(5), 5, 26500),
            _snapshot(4, self._at(0), 5, 30000),
        ]
        service = self._service(snapshots)

        self.assertEqual(service.getExpEfficiency().trend, TREND_DECELERATING)
        self.assertIn("趋势 放缓 -30%", service.getExpEfficiencyTooltip())

    def testStableIsNotShown(self):
        """T-18：fast/slow = 1.1 → 平稳，tooltip 不显示趋势文字。"""
        snapshots = [
            _snapshot(1, self._at(30), 5, 0),
            _snapshot(2, self._at(10), 5, 19000),
            _snapshot(3, self._at(5), 5, 24500),
            _snapshot(4, self._at(0), 5, 30000),
        ]
        service = self._service(snapshots)

        self.assertEqual(service.getExpEfficiency().trend, TREND_STABLE)
        tooltip = service.getExpEfficiencyTooltip()
        self.assertNotIn("趋势", tooltip)
        self.assertNotIn("加速", tooltip)
        self.assertNotIn("放缓", tooltip)

    def testTwoSamplesDoNotJudgeTrend(self):
        """T-14：fast 有值但只有 2 条 → 不判趋势，tooltip 说明样本少。"""
        snapshots = [
            _snapshot(1, self._at(30), 5, 0),
            _snapshot(2, self._at(5), 5, 250000),
            _snapshot(3, self._at(0), 5, 300000),
        ]
        service = self._service(snapshots)
        efficiency = service.getExpEfficiency()

        self.assertEqual(efficiency.fast_rate_per_day, 10000)
        self.assertIsNone(efficiency.trend)
        self.assertIn("样本较少，暂不判断趋势", service.getExpEfficiencyTooltip())

    def testSpanBelowThreeDaysDoesNotJudgeTrend(self):
        """T-19：3 条但跨度 2 天 <3 天 → 不判趋势。"""
        snapshots = [
            _snapshot(1, self._at(30), 5, 0),
            _snapshot(2, self._at(2), 5, 20000),
            _snapshot(3, self._at(1), 5, 21000),
            _snapshot(4, self._at(0), 5, 22000),
        ]
        service = self._service(snapshots)

        self.assertIsNone(service.getExpEfficiency().trend)
        self.assertIn("暂不判断趋势", service.getExpEfficiencyTooltip())


class TestDataQuality(_EfficiencyCase):
    """数据质量测试（#23 §4：异常隔离 / 缺口 / 新鲜度）。"""

    def testExpOverRequirementIsIsolated(self):
        """T-20：本级经验超过需求 → 该条隔离，其余照常计算。"""
        snapshots = [
            _snapshot(1, self._at(2), 5, 0),
            _snapshot(2, self._at(1), 5, LEVEL_UP_EXP + 1),
            _snapshot(3, self._at(0), 5, 10000),
        ]
        service = self._service(snapshots)
        efficiency = service.getExpEfficiency()

        self.assertEqual(efficiency.invalid_count, 1)
        self.assertEqual(efficiency.rate_per_day, 5000)
        self.assertIn("已隔离 1 条异常快照", service.getExpEfficiencyTooltip())

    def testRollbackSnapshotIsIsolated(self):
        """T-21a：绝对经验回退的那条被隔离，不参与计算。"""
        snapshots = [
            _snapshot(1, self._at(3), 5, 30000),
            _snapshot(2, self._at(1), 5, 10000),
            _snapshot(3, self._at(0), 5, 40000),
        ]
        service = self._service(snapshots)
        efficiency = service.getExpEfficiency()

        self.assertEqual(efficiency.invalid_count, 1)
        self.assertEqual(efficiency.rate_per_day, round(10000 / 3))
        self.assertIn("已隔离 1 条异常快照", service.getExpEfficiencyTooltip())

    def testLatestInvalidFallsBack(self):
        """T-21b：最新一条回退时回退到上一条有效快照，并在 tooltip 说明。"""
        snapshots = [
            _snapshot(1, self._at(3), 5, 0),
            _snapshot(2, self._at(1), 5, 20000),
            _snapshot(3, self._at(0), 5, 5000),
        ]
        service = self._service(snapshots)
        efficiency = service.getExpEfficiency()

        self.assertEqual(efficiency.end_time, self._at(1).strftime("%Y-%m-%d %H:%M"))
        self.assertEqual(efficiency.rate_per_day, 10000)
        self.assertIn("最新快照异常，已按上一条计算", service.getExpEfficiencyTooltip())

    def testStaleDataIsReported(self):
        """T-22：数据截止 10 天前 → stale_days=10，tooltip 提示未更新。"""
        snapshots = [
            _snapshot(1, self._at(15), 5, 0),
            _snapshot(2, self._at(10), 5, 50000),
        ]
        service = self._service(snapshots)

        with patch("utils.time_source.now", return_value=self.BASE):
            efficiency = service.getExpEfficiency()
            tooltip = service.getExpEfficiencyTooltip()

        self.assertEqual(efficiency.stale_days, 10)
        self.assertIn("数据已 10 天未更新", tooltip)

    def testStaleDaysAdvancesAfterMidnight(self):
        """跨天后缓存失效，stale_days 随"今天"推进，不需要重启应用。"""
        snapshots = [
            _snapshot(1, self._at(2), 5, 0),
            _snapshot(2, self._at(1), 5, 10000),
        ]
        service = self._service(snapshots)

        with patch("utils.time_source.now", return_value=self.BASE), \
                patch("utils.time_source.today", return_value=self.BASE.date()):
            first = service.getExpEfficiency()

        next_day = self.BASE + timedelta(days=1)
        with patch("utils.time_source.now", return_value=next_day), \
                patch("utils.time_source.today", return_value=next_day.date()):
            second = service.getExpEfficiency()

        self.assertEqual(first.stale_days, 1)
        self.assertEqual(second.stale_days, 2)

    def testGapIsReported(self):
        """T-23：窗口内 15 天缺口 → gap_days≈15，tooltip 提示。"""
        snapshots = [
            _snapshot(1, self._at(20), 5, 0),
            _snapshot(2, self._at(5), 5, 100000),
            _snapshot(3, self._at(0), 5, 200000),
        ]
        service = self._service(snapshots)

        with patch("utils.time_source.now", return_value=self.BASE):
            efficiency = service.getExpEfficiency()
            tooltip = service.getExpEfficiencyTooltip()

        self.assertAlmostEqual(efficiency.gap_days, 15.0)
        self.assertIn("窗口内最大缺口 15.0 天", tooltip)

    def testMissingTableDegradesQuietly(self):
        """T-26：旧库缺表 → 按无快照降级，不抛异常。"""
        service = CommanderService(_MissingTableView())

        self.assertIsNone(service.getExpEfficiency().rate_per_day)
        self.assertIn("暂无快照", service.getExpEfficiencyTooltip())

    def testSlowRateMatchesV1Formula(self):
        """T-25：v2 追加字段不影响主值，slow 仍与 v1 端点公式一致。"""
        snapshots = [
            _snapshot(1, self._at(31), 5, 10000),
            _snapshot(2, self._at(5), 5, 50000),
            _snapshot(3, self._at(0), 5, 60000),
        ]

        efficiency = self._service(snapshots).getExpEfficiency()

        self.assertEqual(efficiency.rate_per_day, round(50000 / 31))
        self.assertAlmostEqual(efficiency.span_days, 31.0)


class TestUpgradeScenario(_EfficiencyCase):
    """升级情景测试（#23 §6.3）。"""

    def testScenarioShowsBothSlowAndFast(self):
        """T-24：剩余 244,704、slow 11,374、fast 15,023 → 21.5 天 + 16.3 天，不写区间。"""
        snapshots = [
            _snapshot(1, self._at(30), 5, 414076),
            _snapshot(2, self._at(10), 5, 605066),
            _snapshot(3, self._at(7), 5, 650135),
            _snapshot(4, self._at(3), 5, 700000),
            _snapshot(5, self._at(0), 5, 755296),
        ]
        service = self._service(snapshots)

        badge = service.getCommanderLevelCardBadge()
        tooltip = service.getCommanderLevelCardTooltip()

        self.assertEqual(badge.text, "预计 21.5 天后升级")
        self.assertIn("若维持近期节奏 16.3 天后升级", tooltip)
        self.assertNotIn("～", tooltip)

    def testNoScenarioWhenTrendStable(self):
        """趋势平稳时不输出近期情景，避免制造两个口径。"""
        snapshots = [
            _snapshot(1, self._at(30), 5, 0),
            _snapshot(2, self._at(10), 5, 19000),
            _snapshot(3, self._at(5), 5, 24500),
            _snapshot(4, self._at(0), 5, 30000),
        ]
        service = self._service(snapshots)

        self.assertNotIn("若维持近期节奏", service.getCommanderLevelCardTooltip())


if __name__ == "__main__":
    unittest.main()
