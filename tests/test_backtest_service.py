"""
回测服务与运行记录单元测试（#35 P2）。

覆盖：到期判定（时间 / 样本增量）、事件检测（±25%×5 天、±50%×3 天、4 天不触发）、
同向冷却、事件复核标记、状态文件容错与原子写、回测无副作用、报告落盘。
"""

import os
import tempfile
import unittest
from datetime import datetime, timedelta
from unittest.mock import patch

from models.backtest_model import BacktestEventRecord
from models.commander_model import CommanderLevelExpModel, CommanderSnapshotModel
from repositories.backtest_state_repository import BacktestStateRepository
from services.backtest_service import BacktestService, TrendOrigin
from services.commander_service import CommanderService
from utils.exceptions import ValidationError

LEVEL_UP_EXP = 1_000_000
FULL_LEVEL = 200
BASE = datetime(2026, 10, 26, 18, 0)


def _buildRequirements(max_level: int = FULL_LEVEL):
    """构造等级基准：cum(L) = 100 万 × L，满级行 NULL。"""
    requirements = {}
    for level in range(1, max_level):
        requirements[level] = CommanderLevelExpModel(
            level=level, level_up_exp=LEVEL_UP_EXP, cumulative_exp=LEVEL_UP_EXP * level
        )
    requirements[max_level] = CommanderLevelExpModel(
        level=max_level, level_up_exp=None, cumulative_exp=None
    )
    return requirements


class _StubCommanderRepository:
    """指挥官数据访问桩（只读 + 写操作计数）。"""

    def __init__(self, snapshots=None, requirements=None):
        self.snapshots = list(snapshots or [])
        self.requirements = requirements if requirements is not None else _buildRequirements()
        self.write_calls = 0

    def findAll(self):
        return sorted(self.snapshots, key=lambda s: s.statistics_date, reverse=True)

    def findLatest(self):
        ordered = self.findAll()
        return ordered[0] if ordered else None

    def findLevelExp(self, level):
        return self.requirements.get(level)

    def insert(self, record):  # pragma: no cover - 只用于断言“没有被调用”
        self.write_calls += 1
        raise AssertionError("回测不应写数据库")

    def update(self, record):  # pragma: no cover
        self.write_calls += 1
        raise AssertionError("回测不应写数据库")

    def delete(self, record_id):  # pragma: no cover
        self.write_calls += 1
        raise AssertionError("回测不应写数据库")


def _snapshot(record_id: int, moment: datetime, level: int, exp: int) -> CommanderSnapshotModel:
    """构造快照模型。"""
    return CommanderSnapshotModel(
        id=record_id,
        statistics_date=moment.strftime("%Y-%m-%d %H:%M"),
        commander_level=level,
        commander_exp=exp,
    )


def _dailyPoints(days: int = 100, rate: int = 10000, start: datetime = None):
    """合成每日一条、恒定速率的数据点。"""
    origin = start or (BASE - timedelta(days=days))
    return [(origin + timedelta(days=index), rate * index) for index in range(days + 1)]


def _origin(day: int, ratio: float, slow: float = 10000.0) -> TrendOrigin:
    """构造一个 origin（用于事件检测单测）。"""
    base = datetime(2026, 1, 1)
    return TrendOrigin(
        moment=base + timedelta(days=day),
        slow=slow,
        fast=slow * ratio,
        ratio=ratio,
        sample_count=5,
        span_days=5.0,
    )


class _BacktestCase(unittest.TestCase):
    """公共基类：临时状态目录 + 桩指挥官服务。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self._state_path = os.path.join(self._tmp.name, "efficiency_backtest.json")
        self._report_dir = os.path.join(self._tmp.name, "backtest")
        self._repository = BacktestStateRepository(
            file_path=self._state_path, report_dir=self._report_dir
        )

    def _service(self, snapshots=None):
        """构造指挥官服务 + 回测服务。"""
        self._commander_repository = _StubCommanderRepository(snapshots or [])
        commander_service = CommanderService(self._commander_repository)
        return BacktestService(
            commander_service=commander_service,
            state_repository=self._repository,
            db_path=os.path.join(self._tmp.name, "fake.db"),
        )

    def _writeState(self, **overrides):
        """写入一条运行记录。"""
        from models.backtest_model import BacktestState

        state = BacktestState(**overrides)
        self._repository.save(state)
        return state


class TestDueStatus(_BacktestCase):
    """到期判定测试（T-38 / T-39）。"""

    def testNeverRunIsDue(self):
        """从未回测 → 到期，原因含「尚未」。"""
        service = self._service()
        status = service.getDueStatus(points=_dailyPoints(40))

        self.assertTrue(status.due)
        self.assertIn("尚未运行过回测", status.reasons)
        self.assertEqual(status.new_points, 41)

    def testDueByInterval(self):
        """T-38：距上次 120 天 → 到期。"""
        service = self._service()
        state = self._writeState(
            last_run_at=(BASE - timedelta(days=120)).strftime("%Y-%m-%d %H:%M"),
            points_at_run=41,
        )
        with patch("utils.time_source.today", return_value=BASE.date()):
            status = service.getDueStatus(points=_dailyPoints(40))

        self.assertTrue(status.due)
        self.assertEqual(status.days_since, 120)
        self.assertTrue(any("距上次回测 120 天" in reason for reason in status.reasons))
        self.assertEqual(state.last_run_at, status.last_run_at)

    def testDueBySampleDelta(self):
        """T-39：新增 100 条快照 → 到期。"""
        service = self._service()
        points = _dailyPoints(120)
        self._writeState(
            last_run_at=(BASE - timedelta(days=5)).strftime("%Y-%m-%d %H:%M"),
            points_at_run=len(points) - 100,
        )
        with patch("utils.time_source.today", return_value=BASE.date()):
            status = service.getDueStatus(points=points)

        self.assertTrue(status.due)
        self.assertEqual(status.new_points, 100)
        self.assertTrue(any("新增 100 条有效快照" in reason for reason in status.reasons))

    def testNotDueWhenFreshAndSmallDelta(self):
        """刚回测过、样本增量小 → 不到期。"""
        service = self._service()
        points = _dailyPoints(40)
        self._writeState(
            last_run_at=(BASE - timedelta(days=3)).strftime("%Y-%m-%d %H:%M"),
            points_at_run=len(points),
        )
        with patch("utils.time_source.today", return_value=BASE.date()):
            status = service.getDueStatus(points=points)

        self.assertFalse(status.due)
        self.assertEqual(status.reasons, [])


class TestRegimeEvents(_BacktestCase):
    """事件检测测试（T-40 / T-41 / T-42）。"""

    def testNormalEventNeedsFiveDays(self):
        """T-40：1.3 连续 5 天 → 1 个 normal；4 天不触发。"""
        service = self._service()

        events = service.detectEventsFromSeries([_origin(day, 1.3) for day in range(5)])
        short = service.detectEventsFromSeries([_origin(day, 1.3) for day in range(4)])

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].direction, "up")
        self.assertEqual(events[0].strength, "normal")
        self.assertEqual(events[0].days, 5)
        self.assertEqual(short, [])

    def testStrongEventNeedsThreeDays(self):
        """T-41：1.6 连续 3 天 → 1 个 strong。"""
        service = self._service()

        events = service.detectEventsFromSeries([_origin(day, 1.6) for day in range(3)])

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].strength, "strong")

    def testDownEvent(self):
        """放缓事件：0.7 连续 5 天 → down。"""
        service = self._service()

        events = service.detectEventsFromSeries([_origin(day, 0.7) for day in range(5)])

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].direction, "down")

    def testCooldownDropsSecondEvent(self):
        """T-42：同向两次事件间隔 <30 天 → 只保留第一次。"""
        service = self._service()
        first = [_origin(day, 1.3) for day in range(5)]
        second = [_origin(day + 10, 1.3) for day in range(5)]

        merged = service.mergeEvents([], service.detectEventsFromSeries(first + second))

        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0].start_date, "2026-01-01")

    def testGapBreaksRun(self):
        """相邻 origin 间隔 >1 天视为断开，不拼成连续事件。"""
        service = self._service()
        series = [_origin(0, 1.3), _origin(1, 1.3), _origin(3, 1.3), _origin(4, 1.3)]

        self.assertEqual(service.detectEventsFromSeries(series), [])

    def testDetectFromPointsFindsEvent(self):
        """端到端：速率从 5,000 跳到 15,000 后应检测到加速事件。"""
        service = self._service()
        points = []
        value = 0
        start = BASE - timedelta(days=60)
        for day in range(61):
            if day > 0:
                value += 5000 if day < 40 else 15000
            points.append((start + timedelta(days=day), value))

        events = service.detectRegimeEvents(points)

        self.assertTrue(events)
        self.assertEqual(events[-1].direction, "up")


class TestStateRepository(_BacktestCase):
    """状态文件测试（T-43 / T-45）。"""

    def testMissingFileReturnsEmptyState(self):
        """文件不存在 → 空记录。"""
        state = self._repository.load()

        self.assertIsNone(state.last_run_at)
        self.assertEqual(state.events, [])

    def testCorruptFileReturnsEmptyState(self):
        """T-43：JSON 损坏 → 空记录，不抛异常。"""
        with open(self._state_path, "w", encoding="utf-8") as handle:
            handle.write("{not-json")

        state = self._repository.load()

        self.assertIsNone(state.last_run_at)
        self.assertEqual(state.points_at_run, 0)

    def testSaveAndLoadRoundtrip(self):
        """保存后能读回事件与摘要；临时文件不残留。"""
        from models.backtest_model import BacktestState

        state = BacktestState(
            last_run_at="2026-10-26 18:00",
            points_at_run=494,
            latest_snapshot_at="2026-10-26 18:09",
            summary={"slow": 11233.0},
            report_path="data/backtest/x.md",
            events=[BacktestEventRecord("up", "normal", "2026-10-20", "2026-10-24", days=5)],
        )
        self._repository.save(state)
        loaded = self._repository.load()

        self.assertEqual(loaded.last_run_at, "2026-10-26 18:00")
        self.assertEqual(len(loaded.events), 1)
        self.assertEqual(loaded.events[0].start_date, "2026-10-20")
        self.assertFalse(os.path.exists(self._state_path + ".tmp"))

    def testSaveReportWritesMarkdown(self):
        """T-45：报告写入指定目录，文件名含日期与时刻。"""
        path = self._repository.saveReport("# 报告\n", datetime(2026, 10, 26, 21, 5))

        self.assertTrue(os.path.exists(path))
        self.assertTrue(path.endswith("20261026_2105.md"))
        with open(path, "r", encoding="utf-8") as handle:
            self.assertEqual(handle.read(), "# 报告\n")


class TestRun(_BacktestCase):
    """运行回测测试（T-44 / T-45）。"""

    def testRunPersistsStateWithoutDbWrites(self):
        """T-44：运行后写状态/报告，但不写数据库、不改常量。"""
        service = self._service([
            _snapshot(1, BASE - timedelta(days=40), 5, 0),
            _snapshot(2, BASE - timedelta(days=20), 5, 200000),
            _snapshot(3, BASE, 5, 400000),
        ])

        with patch("utils.time_source.now", return_value=BASE), \
                patch("utils.time_source.today", return_value=BASE.date()):
            run = service.run()

        self.assertEqual(self._commander_repository.write_calls, 0)
        self.assertEqual(run.points, 3)
        self.assertIn("指级效率回测报告", run.report)
        self.assertTrue(os.path.exists(run.report_path))
        state = self._repository.load()
        self.assertEqual(state.points_at_run, 3)
        self.assertEqual(state.last_run_at, "2026-10-26 18:00")
        self.assertEqual(state.summary["slow"], run.summary["slow"])

    def testRunRejectsTooFewPoints(self):
        """有效快照不足两条 → ValidationError。"""
        service = self._service([_snapshot(1, BASE, 5, 1000)])

        with self.assertRaises(ValidationError):
            service.run()

    def testMarkEventHandled(self):
        """标记复核后，到期原因不再包含“待复核事件”。"""
        service = self._service(_snapshotsForEvent())
        with patch("utils.time_source.now", return_value=BASE), \
                patch("utils.time_source.today", return_value=BASE.date()):
            run = service.run()
        self.assertTrue(run.events)

        event = run.events[0]
        handled = service.markEventHandled(event.direction, event.start_date)

        self.assertTrue(handled)
        with patch("utils.time_source.today", return_value=BASE.date()):
            status = service.getDueStatus()
        self.assertFalse(any("待复核" in reason for reason in status.reasons))
        self.assertFalse(status.pending_events)

    def testEventHandledStatusPreservedOnRerun(self):
        """重新运行回测时，已复核标记不会被覆盖。"""
        service = self._service(_snapshotsForEvent())
        with patch("utils.time_source.now", return_value=BASE), \
                patch("utils.time_source.today", return_value=BASE.date()):
            first = service.run()
            service.markEventHandled(first.events[0].direction, first.events[0].start_date)
            second = service.run()

        self.assertTrue(second.events[0].handled_at)


def _snapshotsForEvent():
    """构造一段「最后 26 天明显加速」的快照（用于端到端事件测试）。"""
    snapshots = []
    value = 0
    start = BASE - timedelta(days=70)
    for day in range(71):
        if day > 0:
            value += 5000 if day < 45 else 20000
        snapshots.append(_snapshot(day + 1, start + timedelta(days=day), 5, value))
    return snapshots


if __name__ == "__main__":
    unittest.main()
