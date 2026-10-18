"""
资源卡片日环比角标单元测试。

覆盖：上涨 / 下降 / 持平 / 断档 / 仅一天 / 锚点日 / 大额缩写 / 空数据，
以及角标文案、方向档位与 tooltip 说明。
"""

import unittest

from models.resource_model import ResourceDailyModel
from services.resource_service import (
    DELTA_TONE_DOWN,
    DELTA_TONE_FLAT,
    DELTA_TONE_UP,
    ResourceService,
)
from utils.constants import RESOURCE_DETAIL_MODE_DETAIL, RESOURCE_TYPE_CUBE


class _StubResourceRepository:
    """资源仓储桩：内存日汇总 + 明细汇总。"""

    def __init__(self, daily_rows=None, totals=None):
        self._daily_rows = list(daily_rows or [])
        self._totals = dict(totals or {})

    def findAllDaily(self, resource_type):
        return [row for row in self._daily_rows if row.resource_type == resource_type]

    def findTransactionTotals(self, resource_type):
        return self._totals


def _build(entries):
    """
    按 ``(日期, 收入, 支出, 锚点)`` 构造明细日与明细汇总。

    Args:
        entries: 四元组序列。

    Returns:
        ``(日汇总行列表, 明细汇总字典)``。
    """
    rows = []
    totals = {}
    for record_date, income, expense, override in entries:
        rows.append(
            ResourceDailyModel(
                resource_type=RESOURCE_TYPE_CUBE,
                record_date=record_date,
                detail_mode=RESOURCE_DETAIL_MODE_DETAIL,
                balance_override=override,
                last_record_time=f"{record_date} 12:00:00",
            )
        )
        totals[record_date] = {
            "income": income,
            "expense": expense,
            "count": 1,
            "last_time": f"{record_date} 12:00:00",
        }
    return rows, totals


def _service(entries) -> ResourceService:
    """用给定序列构造服务。"""
    rows, totals = _build(entries)
    return ResourceService(_StubResourceRepository(rows, totals))


class TestDeltaTone(unittest.TestCase):
    """上涨 / 下降 / 持平测试。"""

    def testRise(self):
        """昨日 4,076 → 今日 4,086，角标 ↑10（红）。"""
        view = _service([
            ("2026-10-17", 4076, 0, None),
            ("2026-10-18", 10, 0, None),
        ]).getCardView(RESOURCE_TYPE_CUBE)

        self.assertIsNotNone(view.delta)
        self.assertEqual(view.delta.delta, 10)
        self.assertEqual(view.delta.display_text, "↑10")
        self.assertEqual(view.delta.tone, DELTA_TONE_UP)
        self.assertIn("较昨日 +10", view.tooltip)
        self.assertIn("2026-10-17 4,076 → 2026-10-18 4,086", view.tooltip)

    def testFall(self):
        """结余下降时角标 ↓30（绿）。"""
        view = _service([
            ("2026-10-17", 4110, 0, None),
            ("2026-10-18", 0, 30, None),
        ]).getCardView(RESOURCE_TYPE_CUBE)

        self.assertEqual(view.delta.delta, -30)
        self.assertEqual(view.delta.display_text, "↓30")
        self.assertEqual(view.delta.tone, DELTA_TONE_DOWN)
        self.assertIn("较昨日 -30", view.tooltip)

    def testFlat(self):
        """无变化时角标为 —（灰），tooltip 说明持平。"""
        view = _service([
            ("2026-10-17", 4076, 0, None),
            ("2026-10-18", 0, 0, None),
        ]).getCardView(RESOURCE_TYPE_CUBE)

        self.assertEqual(view.delta.delta, 0)
        self.assertEqual(view.delta.display_text, "—")
        self.assertEqual(view.delta.tone, DELTA_TONE_FLAT)
        self.assertIn("与昨日持平", view.tooltip)

    def testLargeDeltaAbbreviated(self):
        """大额变化用缩写，与卡片刻度一致（阈值 10,000）。"""
        view = _service([
            ("2026-10-17", 0, 0, None),
            ("2026-10-18", 12345, 0, None),
        ]).getCardView(RESOURCE_TYPE_CUBE)

        self.assertEqual(view.delta.display_text, "↑12.3K")

    def testMediumDeltaKeepsThousandsSeparator(self):
        """未到缩写阈值时用千分符。"""
        view = _service([
            ("2026-10-17", 0, 0, None),
            ("2026-10-18", 6240, 0, None),
        ]).getCardView(RESOURCE_TYPE_CUBE)

        self.assertEqual(view.delta.display_text, "↑6,240")


class TestDeltaEdges(unittest.TestCase):
    """断档、仅一天、锚点与空数据测试。"""

    def testSingleDayHasNoBadge(self):
        """只有一天记录时不给角标。"""
        view = _service([("2026-10-18", 100, 0, None)]).getCardView(RESOURCE_TYPE_CUBE)

        self.assertIsNone(view.delta)
        self.assertIn("仅一天记录", view.tooltip)

    def testGapHasNoBadge(self):
        """昨日无记录时不给角标，也不拿更早的记录冒充昨天。"""
        view = _service([
            ("2026-10-16", 100, 0, None),
            ("2026-10-18", 50, 0, None),
        ]).getCardView(RESOURCE_TYPE_CUBE)

        self.assertIsNone(view.delta)
        self.assertIn("昨日（2026-10-17）无记录", view.tooltip)

    def testAnchorDayFlagged(self):
        """锚点日照常计算，tooltip 标注含手填结余。"""
        view = _service([
            ("2026-10-17", 100, 0, None),
            ("2026-10-18", 0, 0, 500),
        ]).getCardView(RESOURCE_TYPE_CUBE)

        self.assertEqual(view.delta.delta, 400)
        self.assertTrue(view.delta.has_anchor)
        self.assertIn("含手填结余", view.tooltip)

    def testEmptySeries(self):
        """无数据时卡片为 - 且无角标。"""
        view = ResourceService(_StubResourceRepository()).getCardView(RESOURCE_TYPE_CUBE)

        self.assertEqual(view.text, "-")
        self.assertIsNone(view.delta)
        self.assertIn("暂无记录", view.tooltip)

    def testLegacyAccessorsStillWork(self):
        """getCardText / getCardTooltip 仍可用（内部取同一视图）。"""
        service = _service([
            ("2026-10-17", 4076, 0, None),
            ("2026-10-18", 10, 0, None),
        ])

        self.assertEqual(service.getCardText(RESOURCE_TYPE_CUBE), "4.1K")
        self.assertIn("较昨日 +10", service.getCardTooltip(RESOURCE_TYPE_CUBE))


if __name__ == "__main__":
    unittest.main()
