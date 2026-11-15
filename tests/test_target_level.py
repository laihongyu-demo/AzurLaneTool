"""
目标等级升级预测单元测试（#35 P0）。

覆盖：剩余经验公式、目标=当前+1 与「升级还需」一致、满级/越界/基准缺失/
速率缺失降级、里程碑、预计日期、90 天长期口径与「不输出区间」。
"""

import re
import unittest
from datetime import datetime, timedelta
from unittest.mock import patch

from models.commander_model import CommanderLevelExpModel, CommanderSnapshotModel
from services.commander_service import CommanderService
from utils.constants import COMMANDER_TARGET_LEVEL_MILESTONES
from utils.exceptions import ValidationError

# 合成基准：1～199 级每级 100 万累计经验，200 级为满级（NULL）
LEVEL_UP_EXP = 1_000_000
FULL_LEVEL = 200
# 第 5 级绝对经验 = cum(4) + 本级经验 = 4,000,000 + exp
LEVEL = 5


def _buildRequirements(max_level: int = FULL_LEVEL):
    """
    构造等级基准：`cumulative_exp(L) = 100 万 × L`，满级行留 NULL。

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
        self.latest_calls = 0

    def findAll(self):
        return sorted(self.snapshots, key=lambda s: s.statistics_date, reverse=True)

    def findLatest(self):
        self.latest_calls += 1
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


class _ProjectionCase(unittest.TestCase):
    """构造服务的公共基类。"""

    BASE = datetime(2026, 10, 18, 12, 0)

    def _service(self, snapshots, requirements=None) -> CommanderService:
        """用给定快照构造服务。"""
        return CommanderService(
            _StubCommanderRepository(snapshots=snapshots, requirements=requirements)
        )

    def _at(self, days_ago: int, hour: int = 12) -> datetime:
        """相对基准日的时刻。"""
        return (self.BASE - timedelta(days=days_ago)).replace(hour=hour)

    def _twoPoints(self, end_exp: int = 300000):
        """两条快照：30 天前 0 经验、现在 end_exp（slow = end_exp / 30）。"""
        return [
            _snapshot(1, self._at(30), LEVEL, 0),
            _snapshot(2, self._at(0), LEVEL, end_exp),
        ]


class TestRemainingExp(_ProjectionCase):
    """剩余经验口径测试。"""

    def testNextLevelMatchesOverview(self):
        """T-28：目标 = 当前+1 时，剩余经验与「升级还需」一致。"""
        service = self._service(self._twoPoints())
        projection = service.getTargetLevelProjection(LEVEL + 1)
        overview = service.getLevelOverview(LEVEL, 300000)

        self.assertEqual(projection.remaining_exp, overview.remaining_exp)
        self.assertEqual(projection.remaining_exp, 700000)
        self.assertEqual(projection.current_level, LEVEL)
        self.assertEqual(projection.current_absolute_exp, 4300000)

    def testTargetUsesCumulativeOfPreviousLevel(self):
        """T-29：目标 180 → cum(179) − 当前绝对经验。"""
        projection = self._service(self._twoPoints()).getTargetLevelProjection(180)

        self.assertEqual(projection.target_absolute_exp, LEVEL_UP_EXP * 179)
        self.assertEqual(projection.remaining_exp, LEVEL_UP_EXP * 179 - 4300000)

    def testFullLevelTargetUses199(self):
        """T-30：目标 200 用 cum(199)，不读 200 级 NULL 行。"""
        projection = self._service(self._twoPoints()).getTargetLevelProjection(200)

        self.assertEqual(projection.target_absolute_exp, LEVEL_UP_EXP * 199)
        self.assertEqual(projection.remaining_exp, LEVEL_UP_EXP * 199 - 4300000)
        self.assertIsNone(projection.degraded_reason)

    def testTargetBelowCurrent(self):
        """T-31a：目标低于当前等级 → 剩余 0 + 文案。"""
        projection = self._service(self._twoPoints()).getTargetLevelProjection(LEVEL - 1)

        self.assertEqual(projection.remaining_exp, 0)
        self.assertEqual(projection.degraded_reason, "目标低于当前等级")
        self.assertIsNone(projection.days_slow)

    def testTargetEqualsCurrent(self):
        """T-31b：目标等于当前等级 → 已在该等级。"""
        projection = self._service(self._twoPoints()).getTargetLevelProjection(LEVEL)

        self.assertEqual(projection.remaining_exp, 0)
        self.assertEqual(projection.degraded_reason, "已在该等级")

    def testMaxLevel(self):
        """T-31c：已满级 → 已满级，不再估算天数。"""
        service = self._service([_snapshot(1, self._at(0), FULL_LEVEL, 500)])
        projection = service.getTargetLevelProjection(FULL_LEVEL)

        self.assertEqual(projection.remaining_exp, 0)
        self.assertEqual(projection.degraded_reason, "已满级")
        self.assertIsNone(projection.estimated_date)

    def testInvalidTargetRaises(self):
        """T-31d：目标越界 → ValidationError。"""
        service = self._service(self._twoPoints())

        with self.assertRaises(ValidationError):
            service.getTargetLevelProjection(0)
        with self.assertRaises(ValidationError):
            service.getTargetLevelProjection(FULL_LEVEL + 1)


class TestProjectionDegradation(_ProjectionCase):
    """降级路径测试。"""

    def testNoSnapshot(self):
        """无快照 → 说明先录入等级。"""
        projection = self._service([]).getTargetLevelProjection(LEVEL + 1)

        self.assertIsNone(projection.remaining_exp)
        self.assertIn("暂无指挥官快照", projection.degraded_reason)

    def testMissingCurrentRequirement(self):
        """当前等级基准缺失 → 无法换算绝对经验。"""
        projection = self._service(self._twoPoints(), requirements={}).getTargetLevelProjection(
            LEVEL + 1
        )

        self.assertIsNone(projection.remaining_exp)
        self.assertEqual(projection.degraded_reason, "缺少当前等级的基准数据")

    def testMissingTargetRequirement(self):
        """目标等级基准缺失 → 只给说明，不算天数和日期。"""
        requirements = {4: CommanderLevelExpModel(level=4, level_up_exp=LEVEL_UP_EXP,
                                                  cumulative_exp=LEVEL_UP_EXP * 4)}
        projection = self._service(self._twoPoints(), requirements=requirements).getTargetLevelProjection(
            LEVEL + 1
        )

        self.assertIsNone(projection.target_absolute_exp)
        self.assertEqual(projection.degraded_reason, "缺少该等级的基准数据")

    def testRateMissing(self):
        """T-33：只有一条快照 → 经验可算，天数与日期为空并说明原因。"""
        service = self._service([_snapshot(1, self._at(0), LEVEL, 300000)])
        projection = service.getTargetLevelProjection(LEVEL + 1)

        self.assertEqual(projection.remaining_exp, 700000)
        self.assertIsNone(projection.days_slow)
        self.assertIsNone(projection.estimated_date)
        self.assertIn("暂无法估算", projection.degraded_reason)


class TestProjectionDurations(_ProjectionCase):
    """天数、日期与多口径测试。"""

    def testDaysAndEstimatedDate(self):
        """T-35：700,000 经验 ÷ 10,000/天 = 70 天，日期按 today 推算。"""
        service = self._service(self._twoPoints())

        with patch("utils.time_source.today", return_value=self.BASE.date()):
            projection = service.getTargetLevelProjection(LEVEL + 1)

        self.assertAlmostEqual(projection.days_slow, 70.0)
        self.assertEqual(
            projection.estimated_date,
            (self.BASE.date() + timedelta(days=70)).strftime("%Y-%m-%d"),
        )

    def testLongRateUses90Days(self):
        """T-36：90 天长期口径独立于 30 天主值。"""
        snapshots = [
            _snapshot(1, self._at(100), LEVEL, 0),
            _snapshot(2, self._at(40), LEVEL, 600000),
            _snapshot(3, self._at(0), LEVEL, 900000),
        ]
        service = self._service(snapshots)
        efficiency = service.getExpEfficiency()
        projection = service.getTargetLevelProjection(LEVEL + 1)

        self.assertEqual(efficiency.rate_per_day, 7500)
        self.assertEqual(efficiency.long_rate_per_day, 9000)
        self.assertAlmostEqual(projection.days_slow, 100000 / 7500)
        self.assertAlmostEqual(projection.days_long, 100000 / 9000)

    def testFastScenarioOnlyWhenTrending(self):
        """T-37a：加速时给近期情景；平稳时不给。"""
        accelerating = [
            _snapshot(1, self._at(30), LEVEL, 0),
            _snapshot(2, self._at(10), LEVEL, 17000),
            _snapshot(3, self._at(5), LEVEL, 23500),
            _snapshot(4, self._at(0), LEVEL, 30000),
        ]
        stable = [
            _snapshot(1, self._at(30), LEVEL, 0),
            _snapshot(2, self._at(10), LEVEL, 19000),
            _snapshot(3, self._at(5), LEVEL, 24500),
            _snapshot(4, self._at(0), LEVEL, 30000),
        ]

        trending = self._service(accelerating).getTargetLevelProjection(LEVEL + 1)
        flat = self._service(stable).getTargetLevelProjection(LEVEL + 1)

        self.assertAlmostEqual(trending.days_fast, 970000 / 1300)
        self.assertIsNone(flat.days_fast)

    def testMilestones(self):
        """T-34：默认里程碑 8 项、升序、全部可算。"""
        projections = self._service(self._twoPoints()).listTargetLevelProjections()

        self.assertEqual(
            [projection.target_level for projection in projections],
            list(COMMANDER_TARGET_LEVEL_MILESTONES),
        )
        self.assertTrue(all(projection.remaining_exp is not None for projection in projections))
        self.assertTrue(all(projection.days_slow is not None for projection in projections))

    def testMilestonesQueryLatestOnce(self):
        """里程碑批量计算只取一次最新快照，避免 N+1 查询。"""
        repository = _StubCommanderRepository(snapshots=self._twoPoints())
        CommanderService(repository).listTargetLevelProjections()

        self.assertEqual(repository.latest_calls, 1)

    def testNoRangeText(self):
        """T-37b：不输出伪区间，日期为 yyyy-MM-dd。"""
        service = self._service(self._twoPoints())

        with patch("utils.time_source.today", return_value=self.BASE.date()):
            projection = service.getTargetLevelProjection(180)

        self.assertNotIn("～", projection.degraded_reason or "")
        self.assertIsNotNone(
            re.match(r"^\d{4}-\d{2}-\d{2}$", projection.estimated_date)
        )


if __name__ == "__main__":
    unittest.main()
