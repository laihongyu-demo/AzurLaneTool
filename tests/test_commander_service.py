"""
指挥官服务单元测试。

使用内存桩替换 Repository，覆盖：卡片文本、需求经验、校验规则、
快照增删改、列表格式化与表缺失降级。
"""

import unittest
from datetime import datetime, timedelta

from models.commander_model import CommanderLevelExpModel, CommanderSnapshotModel
from services.commander_service import CommanderService
from utils.constants import STATISTICS_DATETIME_FORMAT
from utils.exceptions import DatabaseError, ValidationError


class _StubCommanderRepository:
    """指挥官数据访问桩：内存列表实现，可按需抛出"表不存在"。"""

    def __init__(self, snapshots=None, requirements=None, missing_table=False):
        self.snapshots = list(snapshots or [])
        self.requirements = dict(requirements or {})
        self.missing_table = missing_table
        self._next_id = max((s.id or 0) for s in self.snapshots) + 1 if self.snapshots else 1

    def _guard(self):
        if self.missing_table:
            raise DatabaseError("no such table: commander_info")

    def findAll(self):
        self._guard()
        return sorted(self.snapshots, key=lambda s: s.statistics_date, reverse=True)

    def findRecent(self, limit=30):
        return self.findAll()[:limit]

    def findByDateRange(self, start_date, end_date):
        self._guard()
        return [
            s for s in self.findAll()
            if start_date <= s.statistics_date[:10] <= end_date
        ]

    def findLatest(self):
        self._guard()
        ordered = self.findAll()
        return ordered[0] if ordered else None

    def findById(self, record_id):
        self._guard()
        for snapshot in self.snapshots:
            if snapshot.id == record_id:
                return snapshot
        return None

    def existsAt(self, statistics_date):
        self._guard()
        return any(s.statistics_date == statistics_date for s in self.snapshots)

    def insert(self, record):
        self._guard()
        record.id = self._next_id
        self._next_id += 1
        self.snapshots.append(record)
        return record.id

    def update(self, record):
        self._guard()
        for index, snapshot in enumerate(self.snapshots):
            if snapshot.id == record.id:
                self.snapshots[index] = record
                return True
        return False

    def delete(self, record_id):
        self._guard()
        before = len(self.snapshots)
        self.snapshots = [s for s in self.snapshots if s.id != record_id]
        return len(self.snapshots) < before

    def findLevelExp(self, level):
        if self.missing_table:
            raise DatabaseError("no such table: commander_level_exp")
        return self.requirements.get(level)


def _snapshot(record_id: int, date_text: str, level: int, exp: int) -> CommanderSnapshotModel:
    """构造快照模型。"""
    return CommanderSnapshotModel(
        id=record_id, statistics_date=date_text, commander_level=level, commander_exp=exp
    )


REQUIREMENTS = {
    162: CommanderLevelExpModel(level=162, level_up_exp=346200, cumulative_exp=11214610),
    163: CommanderLevelExpModel(level=163, level_up_exp=354350, cumulative_exp=11568960),
}


class TestCommanderCardText(unittest.TestCase):
    """看板卡片文本口径测试。"""

    def testCardTextUsesExactFormat(self):
        """卡片文本为「等级（当前经验/需求经验）」，且加千分符。"""
        repository = _StubCommanderRepository(
            snapshots=[_snapshot(1, "2026-10-16 22:53", 163, 77057)],
            requirements=REQUIREMENTS,
        )
        service = CommanderService(repository)

        self.assertEqual(service.getCommanderLevelCardText(), "163（77,057/354,350）")

    def testCardTextWithoutSnapshot(self):
        """无快照时卡片显示 -，不抛异常。"""
        service = CommanderService(_StubCommanderRepository())

        self.assertEqual(service.getCommanderLevelCardText(), "-")
        self.assertIn("暂无记录", service.getCommanderLevelCardTooltip())

    def testCardTextWithoutRequirementTable(self):
        """基准表缺失时需求经验退化为 -，等级与经验仍显示。"""
        repository = _StubCommanderRepository(
            snapshots=[_snapshot(1, "2026-10-16 22:53", 163, 77057)],
            missing_table=True,
        )
        service = CommanderService(repository)

        self.assertEqual(service.getCommanderLevelCardText(), "-")
        repository.missing_table = False
        self.assertEqual(service.getCommanderLevelCardText(), "163（77,057/-）")

    def testCardTextUsesLatestSnapshot(self):
        """取最新一条快照，而不是最早一条。"""
        repository = _StubCommanderRepository(
            snapshots=[
                _snapshot(1, "2026-10-11 10:31", 162, 344987),
                _snapshot(2, "2026-10-16 22:53", 163, 77057),
            ],
            requirements=REQUIREMENTS,
        )
        service = CommanderService(repository)

        self.assertTrue(service.getCommanderLevelCardText().startswith("163（"))

    def testTooltipShowsRemainingExpOnly(self):
        """悬停提示只补充升级还需经验与进度，不重复卡片已有数值。"""
        repository = _StubCommanderRepository(
            snapshots=[
                _snapshot(1, "2026-10-17 22:53", 163, 67057),
                _snapshot(2, "2026-10-18 22:53", 163, 77057),
            ],
            requirements=REQUIREMENTS,
        )
        tooltip = CommanderService(repository).getCommanderLevelCardTooltip()

        # 354,350 - 77,057 = 277,293
        self.assertIn("升级还需 277,293 经验", tooltip)
        self.assertIn("进度 21.7%", tooltip)
        self.assertIn("2026-10-18 22:53", tooltip)
        # 卡片已展示的三项不再重复
        self.assertNotIn("77,057", tooltip)
        self.assertNotIn("354,350", tooltip)
        self.assertNotIn("本级需求", tooltip)

    def testTooltipShowsUpgradeEstimateAfterProgress(self):
        """预期升级时间排在进度之后、记录时间之前。"""
        repository = _StubCommanderRepository(
            snapshots=[
                _snapshot(1, "2026-10-17 22:53", 163, 67057),
                _snapshot(2, "2026-10-18 22:53", 163, 77057),
            ],
            requirements=REQUIREMENTS,
        )
        tooltip = CommanderService(repository).getCommanderLevelCardTooltip()

        # 两条快照相差 10,000 经验 / 1 天 → 10,000 每天；277,293 ÷ 10,000 = 27.7 天
        self.assertIn("进度 21.7%｜预期升级 27.7 天｜记录于", tooltip)

    def testUpgradeEstimatePlaceholderWithoutEfficiency(self):
        """只有一条快照、算不出效率时给出占位而不是省略。"""
        repository = _StubCommanderRepository(
            snapshots=[_snapshot(1, "2026-10-18 22:53", 163, 77057)],
            requirements=REQUIREMENTS,
        )

        self.assertIn("预期升级 —", CommanderService(repository).getCommanderLevelCardTooltip())


class TestCommanderSnapshotWrite(unittest.TestCase):
    """快照写入与校验测试。"""

    def setUp(self):
        self._repository = _StubCommanderRepository(requirements=REQUIREMENTS)
        self._service = CommanderService(self._repository)

    def _now_text(self) -> str:
        """当前时间（到分）。"""
        return datetime.now().strftime(STATISTICS_DATETIME_FORMAT)

    def testAddSnapshotAppendsAndNormalizes(self):
        """新增快照追加一行，并规范化为补零格式。"""
        result = self._service.addSnapshot(
            CommanderSnapshotModel(statistics_date="2026-10-17 08:05", commander_level=163, commander_exp=100)
        )

        self.assertTrue(result.success)
        self.assertEqual(len(self._repository.snapshots), 1)
        self.assertEqual(self._repository.snapshots[0].statistics_date, "2026-10-17 08:05")
        self.assertIn("163", result.toStatusBarMessage())

    def testAddSnapshotRejectsFutureTime(self):
        """未来时间被拒绝。"""
        future = (datetime.now() + timedelta(days=1)).strftime(STATISTICS_DATETIME_FORMAT)

        with self.assertRaises(ValidationError):
            self._service.addSnapshot(
                CommanderSnapshotModel(statistics_date=future, commander_level=163, commander_exp=0)
            )

    def testAddSnapshotRejectsExpAboveRequirement(self):
        """当前经验超过本级需求时被拒绝。"""
        with self.assertRaises(ValidationError) as ctx:
            self._service.addSnapshot(
                CommanderSnapshotModel(
                    statistics_date=self._now_text(), commander_level=163, commander_exp=354351
                )
            )

        self.assertIn("354,350", str(ctx.exception))

    def testAddSnapshotRejectsDuplicateTime(self):
        """同一时间点重复录入被拒绝。"""
        snapshot = CommanderSnapshotModel(
            statistics_date=self._now_text(), commander_level=163, commander_exp=100
        )
        self._service.addSnapshot(snapshot)

        with self.assertRaises(ValidationError) as ctx:
            self._service.addSnapshot(
                CommanderSnapshotModel(
                    statistics_date=self._now_text(), commander_level=163, commander_exp=200
                )
            )
        self.assertIn("已存在", str(ctx.exception))

    def testAddSnapshotRejectsInvalidLevel(self):
        """等级越界被拒绝。"""
        with self.assertRaises(ValidationError):
            self._service.addSnapshot(
                CommanderSnapshotModel(statistics_date="2026-10-17 08:05", commander_level=201, commander_exp=0)
            )

    def testAddSnapshotRejectsMalformedTime(self):
        """时间格式不合法时给出明确提示。"""
        with self.assertRaises(ValidationError) as ctx:
            self._service.addSnapshot(
                CommanderSnapshotModel(statistics_date="2026/10/17 08:05", commander_level=163, commander_exp=0)
            )

        self.assertIn("yyyy-MM-dd HH:mm", str(ctx.exception))

    def testUpdateSnapshotRewritesRow(self):
        """更新快照按 ID 覆盖同一行，不新增。"""
        self._service.addSnapshot(
            CommanderSnapshotModel(statistics_date="2026-10-17 08:05", commander_level=162, commander_exp=100)
        )
        target = self._repository.snapshots[0]

        result = self._service.updateSnapshot(
            CommanderSnapshotModel(
                id=target.id, statistics_date="2026-10-17 08:06", commander_level=163, commander_exp=200
            )
        )

        self.assertTrue(result.success)
        self.assertEqual(len(self._repository.snapshots), 1)
        self.assertEqual(self._repository.snapshots[0].statistics_date, "2026-10-17 08:06")
        self.assertEqual(self._repository.snapshots[0].commander_level, 163)

    def testUpdateSnapshotRequiresExistingRecord(self):
        """更新不存在的记录时报错。"""
        with self.assertRaises(ValidationError):
            self._service.updateSnapshot(
                CommanderSnapshotModel(id=999, statistics_date="2026-10-17 08:05", commander_level=163, commander_exp=1)
            )

    def testDeleteSnapshotRemovesRow(self):
        """删除快照后列表减少一条。"""
        self._service.addSnapshot(
            CommanderSnapshotModel(statistics_date="2026-10-17 08:05", commander_level=163, commander_exp=1)
        )
        target = self._repository.snapshots[0]

        result = self._service.deleteSnapshot(target.id)

        self.assertTrue(result.success)
        self.assertEqual(self._repository.snapshots, [])

    def testDeleteSnapshotRequiresExistingRecord(self):
        """删除不存在的记录时报错。"""
        with self.assertRaises(ValidationError):
            self._service.deleteSnapshot(12345)


class TestCommanderSnapshotList(unittest.TestCase):
    """列表与降级测试。"""

    def testListSnapshotRowsFormatsFields(self):
        """列表行包含千分符文本与进度百分比。"""
        repository = _StubCommanderRepository(
            snapshots=[_snapshot(1, "2026-10-16 22:53", 163, 77057)],
            requirements=REQUIREMENTS,
        )
        rows = CommanderService(repository).listSnapshotRows(limit=10)

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["exp_text"], "77,057")
        self.assertEqual(rows[0]["required_text"], "354,350")
        self.assertEqual(rows[0]["progress_text"], "21.7%")

    def testListSnapshotRowsWithoutRequirement(self):
        """基准缺失时需求与进度显示 -。"""
        repository = _StubCommanderRepository(
            snapshots=[_snapshot(1, "2026-10-16 22:53", 163, 77057)],
        )
        rows = CommanderService(repository).listSnapshotRows(limit=10)

        self.assertEqual(rows[0]["required_text"], "-")
        self.assertEqual(rows[0]["progress_text"], "-")

    def testMissingTableDegradesToEmpty(self):
        """表缺失时读取降级为空结果，不抛异常。"""
        service = CommanderService(_StubCommanderRepository(missing_table=True))

        self.assertIsNone(service.getLatestSnapshot())
        self.assertEqual(service.listSnapshots(limit=10), [])
        self.assertEqual(service.listSnapshotRows(limit=10), [])


if __name__ == "__main__":
    unittest.main()
