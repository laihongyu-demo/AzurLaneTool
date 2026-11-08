"""
统计卡片布局与角标位置回归测试（#38）。

设计口径（方案 A）：

- 资源卡的日环比角标贴在**标题行**，数值行只放数值，角标文案不再参与数值行宽度竞争；
- 卡片按内容宽度排布，两侧留白由 stretch 吸收，数值在不小于内容宽度时完整显示；
- 窗口窄于内容宽度时，数值退化为中间省略（并给全文 tooltip），而不是硬裁掉首位。

说明：offscreen 环境没有可用字体（本机 ``QFontDatabase().families()`` 为空，回退字体把
ASCII 也按全角宽度绘制），所以断言只用「内容宽度 vs 实际宽度」这类与字体无关的口径；
1024/1280 真实像素是否完整，由人工在真实字体下确认。
"""

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtGui import QFontMetrics  # noqa: E402
from PyQt5.QtWidgets import QApplication  # noqa: E402

from services.resource_service import ResourceCardView  # noqa: E402
from tests.test_commander_panel import (  # noqa: E402
    _StubCommanderService,
    _StubStatisticsService,
    _StubUserService,
)
from utils.constants import RESOURCE_TYPE_CUBE, RESOURCE_TYPE_RED_GEM  # noqa: E402
from utils.exceptions import DatabaseError  # noqa: E402
from views.widgets.stat_card import (  # noqa: E402
    BADGE_MAX_WIDTH,
    TITLE_BADGE_MAX_WIDTH,
    WIDGET_MAX_WIDTH,
    StatCard,
)
from views.widgets.statistics_panel import StatisticsPanel  # noqa: E402

APP = QApplication.instance() or QApplication([])

# 与真实数据同口径：三位数等级 + 当前经验/需求经验
COMMANDER_VALUE = "163（77,057/354,350）"
CARD_TEXTS = {RESOURCE_TYPE_CUBE: "4.1K", RESOURCE_TYPE_RED_GEM: "3.4K"}


class _StubBadgeResourceService:
    """资源服务桩：按资源类型返回固定角标，用于验证服务层 → 卡片角标的接线。"""

    def __init__(self, badges=None):
        self._badges = badges or {}

    def getCardView(self, resource_type):
        badge_text, badge_tone = self._badges.get(resource_type, ("", ""))
        return ResourceCardView(
            text=CARD_TEXTS.get(resource_type, "-"),
            tooltip=f"{resource_type} tip",
            badge_text=badge_text,
            badge_tone=badge_tone,
        )


class _FailingResourceService:
    """资源服务桩：模拟数据库异常，用于验证错误态清角标。"""

    def getCardView(self, resource_type):
        raise DatabaseError("simulated failure")


class _CardLayoutCase(unittest.TestCase):
    """构造带桩依赖的统计面板，并提供布局断言。"""

    def _buildPanel(self, resource_badges=None, commander_badge=("", ""), resource_service=None):
        """
        构造统计面板。

        Args:
            resource_badges: 资源类型 → (角标文案, 配色档位)。
            commander_badge: 指挥官标题角标 (文案, 配色档位)。
            resource_service: 自定义资源服务（默认用角标桩）。
        """
        badge_text, badge_tone = commander_badge
        panel = StatisticsPanel(
            statistics_service=_StubStatisticsService(),
            user_service=_StubUserService(),
            commander_service=_StubCommanderService(
                text=COMMANDER_VALUE,
                badge_text=badge_text,
                badge_tone=badge_tone,
            ),
            resource_service=resource_service or _StubBadgeResourceService(resource_badges),
        )
        self.addCleanup(panel.deleteLater)
        return panel

    def _layout(self, panel, width=None):
        """
        按指定宽度完成一次布局。

        Args:
            panel: 统计面板。
            width: 面板宽度；``None`` 表示按面板自身首选宽度（即内容宽度）布局。
        """
        panel.resize(width or panel.sizeHint().width(), 900)
        panel.show()
        APP.processEvents()
        return panel

    def _commanderRowCards(self, panel):
        """指挥官看板一行的五张卡。"""
        return [
            panel._commanderLevelCard,
            panel._dutyDaysCard,
            panel._expEfficiencyCard,
            panel._cubeCard,
            panel._redGemCard,
        ]

    def _assertNoHardClipping(self, panel, context):
        """任何可见文字都必须放得进标签可用宽度（放不下应已省略）。"""
        for card in panel.findChildren(StatCard):
            for attr in ("_titleLabel", "_badgeLabel", "_titleBadgeLabel", "_valueLabel"):
                label = getattr(card, attr)
                if not label.isVisible():
                    continue
                need = QFontMetrics(label.font()).horizontalAdvance(label.displayedText())
                self.assertLessEqual(
                    need,
                    label.contentsRect().width() + 1,
                    f"{context}：{card.title()} 的 {attr} 文字被硬裁",
                )


class TestBadgePlacement(unittest.TestCase):
    """角标位置：贴在标题行，不占数值行。"""

    def testResourceDeltaBadgeSitsInTitleRow(self):
        """魔方 / 红尖尖的日环比角标显示在标题行，数值行只有数值。"""
        card = StatCard("红尖尖", "3.4K")
        card.setBadge("↓30", "down")
        card.resize(400, 120)
        card.show()
        APP.processEvents()

        badge = card._badgeLabel
        value = card._valueLabel
        self.assertTrue(badge.isVisible())
        # 角标整体在数值标签上方：标题行在上、数值行在下
        self.assertLess(badge.geometry().bottom(), value.geometry().top())
        self.assertEqual(card.badgeText(), "↓30")
        self.assertEqual(card.badgeTone(), "down")
        card.close()

    def testBadgeDoesNotNarrowTheValue(self):
        """卡片按数值所需宽度给足时，角标文案再长也不省略数值。"""
        card = StatCard("红尖尖", "3.4K")
        card.show()
        APP.processEvents()
        width_for_value = card.sizeHint().width()

        for text in ("↓30", "未记录", "数据异常"):
            card.setBadge(text, "flat")
            card.resize(width_for_value, 120)
            APP.processEvents()
            self.assertFalse(card._valueLabel.isElided(), text)
            self.assertEqual(card.value(), "3.4K")
        card.close()

    def testValueLabelElidesMiddleOnlyWhenTooNarrow(self):
        """卡片窄于数值所需宽度时中间省略，首尾可辨，全文留在 tooltip。"""
        card = StatCard("指挥官等级", COMMANDER_VALUE)
        card.show()
        APP.processEvents()

        metrics = QFontMetrics(card._valueLabel.font())
        inner_width = 2 * metrics.horizontalAdvance("163") + metrics.horizontalAdvance("…") + 10
        card.resize(inner_width + 30, 120)  # 卡片左右各 15px 内边距
        APP.processEvents()

        label = card._valueLabel
        self.assertTrue(label.isElided())
        self.assertIn("…", label.displayedText())
        self.assertTrue(label.displayedText().startswith("163"))
        self.assertTrue(label.displayedText().endswith("）"))
        self.assertEqual(label.toolTip(), COMMANDER_VALUE)
        self.assertEqual(card.value(), COMMANDER_VALUE)
        card.close()

    def testWideCardShowsFullTextAndLeavesTooltipToCard(self):
        """空间足够时显示全文，且不拦截卡片自己的说明性 tooltip。"""
        card = StatCard("指挥官等级", COMMANDER_VALUE)
        card.setToolTip("指挥官等级说明")
        card.resize(800, 120)
        card.show()
        APP.processEvents()

        label = card._valueLabel
        self.assertFalse(label.isElided())
        self.assertEqual(label.displayedText(), COMMANDER_VALUE)
        self.assertEqual(label.toolTip(), "")
        self.assertEqual(card.toolTip(), "指挥官等级说明")
        card.close()


class TestBadgeWidthCap(unittest.TestCase):
    """角标宽度受上限约束，长文案只在自己格子里省略。"""

    def testLongValueBadgeIsCappedAndElided(self):
        """超长日环比角标宽度封顶，省略后全文可从 tooltip 查到。"""
        card = StatCard("红尖尖", "3.4K")
        card.setBadge("这一条角标文案特别长", "flat")
        card.resize(260, 120)
        card.show()
        APP.processEvents()

        badge = card._badgeLabel
        self.assertLessEqual(badge.maximumWidth(), BADGE_MAX_WIDTH)
        self.assertLessEqual(badge.width(), BADGE_MAX_WIDTH)
        self.assertTrue(badge.isElided())
        self.assertIn("…", badge.displayedText())
        self.assertEqual(badge.toolTip(), "这一条角标文案特别长")
        self.assertEqual(card.badgeText(), "这一条角标文案特别长")
        card.close()

    def testTitleBadgeIsCapped(self):
        """标题角标同样封顶，文案长度不再无上限撑宽。"""
        card = StatCard("指挥官等级", "163")
        card.setTitleBadge("预计 999.9 天后升级（经验不足）", "info")

        self.assertLessEqual(card._titleBadgeLabel.maximumWidth(), TITLE_BADGE_MAX_WIDTH)
        self.assertEqual(card.titleBadgeText(), "预计 999.9 天后升级（经验不足）")
        card.close()

    def testClearBadgeRestoresCardWidth(self):
        """清除角标后卡片首选宽度回到无角标状态，宽度上限与文本同步复位。"""
        card = StatCard("魔方", "4.1K")
        width_without_badge = card.sizeHint().width()

        card.setBadge("数据异常", "flat")
        card.clearBadge()

        self.assertEqual(card.badgeText(), "")
        self.assertEqual(card._badgeLabel.displayedText(), "")
        self.assertEqual(card._badgeLabel.toolTip(), "")
        self.assertEqual(card._badgeLabel.maximumWidth(), WIDGET_MAX_WIDTH)
        self.assertEqual(card.sizeHint().width(), width_without_badge)
        card.close()


class TestBoardLayout(_CardLayoutCase):
    """面板级：按内容宽度排布，角标变化不压缩其他卡。"""

    def _buildBusyPanel(self):
        """构造角标全开的面板，复现断档当天状态。"""
        return self._buildPanel(
            resource_badges={
                RESOURCE_TYPE_CUBE: ("数据异常", "flat"),
                RESOURCE_TYPE_RED_GEM: ("数据异常", "flat"),
            },
            commander_badge=("预计 27.7 天后升级", "info"),
        )

    def testValuesAreFullyVisibleAtContentWidth(self):
        """给足内容宽度时，五张卡的数值都完整显示、卡片互不重叠。"""
        panel = self._layout(self._buildBusyPanel())
        cards = self._commanderRowCards(panel)

        for card in cards:
            self.assertGreaterEqual(card.width() + 1, card.sizeHint().width(), card.title())
            self.assertFalse(card._valueLabel.isElided(), card.title())
        for left, right in zip(cards, cards[1:]):
            self.assertLess(left.geometry().right(), right.geometry().left(), f"{left.title()} 与 {right.title()} 重叠")

    def testBadgeTextChangeOnlyTouchesItsOwnCard(self):
        """红尖尖角标在 ↓30 / 未记录 / 数据异常 间切换时，其他四张卡宽度不变。"""
        panel = self._layout(self._buildBusyPanel())
        others = [card for card in self._commanderRowCards(panel) if card is not panel._redGemCard]
        baseline = [card.width() for card in others]

        for text in ("↓30", "未记录", "数据异常"):
            panel._redGemCard.setBadge(text, "flat")
            APP.processEvents()
            self.assertEqual([card.width() for card in others], baseline, text)
            self.assertEqual(panel._redGemCard.badgeText(), text)

    def testTitleBadgeChangeOnlyTouchesCommanderCard(self):
        """指挥官标题角标预计升级 / 已满级切换时，其余四张卡宽度不变。"""
        panel = self._layout(self._buildBusyPanel())
        others = [card for card in self._commanderRowCards(panel) if card is not panel._commanderLevelCard]
        baseline = [card.width() for card in others]

        panel._commanderLevelCard.setTitleBadge("已满级", "success")
        APP.processEvents()
        self.assertEqual([card.width() for card in others], baseline)
        self.assertEqual(panel._commanderLevelCard.titleBadgeText(), "已满级")

    def testNarrowPanelElidesInsteadOfClipping(self):
        """窗口窄于内容宽度时，文字退化为省略号，不出现硬裁与重叠。"""
        panel = self._layout(self._buildBusyPanel(), 800)
        cards = self._commanderRowCards(panel)

        self._assertNoHardClipping(panel, "800 宽")
        for left, right in zip(cards, cards[1:]):
            self.assertLess(left.geometry().right(), right.geometry().left(), f"{left.title()} 与 {right.title()} 重叠")

    def testErrorStateClearsResourceBadges(self):
        """资源刷新失败时清掉日环比角标，避免「错误」旁边残留旧状态。"""
        panel = self._layout(self._buildPanel(resource_service=_FailingResourceService()))

        self.assertEqual(panel._cubeCard.value(), "错误")
        self.assertEqual(panel._cubeCard.badgeText(), "")
        self.assertEqual(panel._redGemCard.value(), "错误")
        self.assertEqual(panel._redGemCard.badgeText(), "")


if __name__ == "__main__":
    unittest.main()
