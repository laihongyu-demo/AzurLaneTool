"""
可搜索下拉框展开/收起行为单元测试。

覆盖本次修复的缺陷：
- 程序化获得焦点（切换页签、窗口激活、setFocus）不得展开下拉
- 用户点击输入框（MouseFocusReason）才展开
- 输入框失焦后收起（原实现挂在 NoFocus 的容器上，属死代码）
- Esc 收起、点击列表项收起
- 程序化改文本（clear/setText）且输入框无焦点时不得展开
- 切换页签集成场景：切换前焦点在旧页面内，切换后下拉保持关闭
"""

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtCore import QEvent, Qt  # noqa: E402
from PyQt5.QtGui import QFocusEvent, QKeyEvent  # noqa: E402
from PyQt5.QtTest import QTest  # noqa: E402
from PyQt5.QtWidgets import (  # noqa: E402
    QApplication, QPushButton, QTabWidget, QVBoxLayout, QWidget
)

from views.widgets.searchable_combo_box import (  # noqa: E402
    HIDE_DELAY_MS, USER_FOCUS_REASONS, SearchableComboBox
)

APP = QApplication.instance() or QApplication([])

ITEMS = ["拉菲", "标枪", "企业", "独角兽", "Z23"]


class SearchableComboBoxTestCase(unittest.TestCase):
    """可搜索下拉框测试基类。"""

    def setUp(self):
        """测试初始化。"""
        self._combo = SearchableComboBox()
        self._combo.setMinimumWidth(220)
        for item in ITEMS:
            self._combo.addItem(item, item)
        self._combo.resize(220, 30)
        self._combo.show()
        APP.processEvents()

    def tearDown(self):
        """测试清理。"""
        self._combo._hidePopup()
        self._combo.hide()
        self._combo.deleteLater()
        APP.processEvents()

    def _sendFocusIn(self, reason) -> None:
        """通过事件分发投递 FocusIn，确保事件过滤器参与处理。"""
        QApplication.sendEvent(
            self._combo._lineEdit, QFocusEvent(QEvent.FocusIn, reason)
        )
        APP.processEvents()

    def _sendFocusOut(self) -> None:
        """通过事件分发投递 FocusOut。"""
        QApplication.sendEvent(self._combo._lineEdit, QFocusEvent(QEvent.FocusOut))
        APP.processEvents()

    def _sendKey(self, key) -> None:
        """通过事件分发投递按键事件。"""
        QApplication.sendEvent(
            self._combo._lineEdit, QKeyEvent(QEvent.KeyPress, key, Qt.NoModifier)
        )
        APP.processEvents()

    def _defocus(self) -> None:
        """让输入框失去焦点。"""
        self._combo._lineEdit.clearFocus()
        APP.processEvents()

    def _waitForHide(self) -> None:
        """等待延迟收起生效。"""
        QTest.qWait(HIDE_DELAY_MS + 80)


class TestFocusTrigger(SearchableComboBoxTestCase):
    """焦点触发相关测试。"""

    def testProgrammaticFocusDoesNotExpand(self):
        """程序化分派焦点（OtherFocusReason）不展开下拉。"""
        self._sendFocusIn(Qt.OtherFocusReason)

        self.assertFalse(self._combo._popup_visible)
        self.assertFalse(self._combo._popup.isVisible())

    def testActiveWindowFocusDoesNotExpand(self):
        """窗口激活导致的焦点（ActiveWindowFocusReason）不展开下拉。"""
        self._sendFocusIn(Qt.ActiveWindowFocusReason)

        self.assertFalse(self._combo._popup_visible)

    def testMouseFocusExpands(self):
        """用户点击输入框（MouseFocusReason）展开下拉。"""
        self._sendFocusIn(Qt.MouseFocusReason)

        self.assertTrue(self._combo._popup_visible)
        self.assertTrue(self._combo._popup.isVisible())
        self.assertEqual(self._combo._dropBtn.text(), '▲')

    def testOnlyMouseFocusReasonIsWhitelisted(self):
        """白名单只包含鼠标焦点来源。"""
        self.assertEqual(tuple(USER_FOCUS_REASONS), (Qt.MouseFocusReason,))

    def testFocusInEventIsNotPatched(self):
        """不再替换输入框的 focusInEvent（避免绕过默认焦点处理）。"""
        self.assertNotIn('focusInEvent', self._combo._lineEdit.__dict__)
        self.assertNotIn('focusOutEvent', self._combo._lineEdit.__dict__)


class TestTextTrigger(SearchableComboBoxTestCase):
    """文本触发相关测试。"""

    def testProgrammaticTextChangeDoesNotExpand(self):
        """输入框无焦点时程序化改文本不展开下拉。"""
        self._sendFocusIn(Qt.MouseFocusReason)
        self._combo._hidePopup()
        self._defocus()

        self._combo._lineEdit.setText("拉")
        APP.processEvents()
        self.assertFalse(self._combo._popup_visible)

        self._combo._lineEdit.clear()
        APP.processEvents()
        self.assertFalse(self._combo._popup_visible)

    def testTypingWithFocusExpands(self):
        """输入框持有焦点时输入内容会展开下拉并完成过滤。"""
        self._combo._lineEdit.setFocus()
        APP.processEvents()
        self.assertTrue(self._combo._lineEdit.hasFocus(), "无头环境下应能授予焦点")

        self._combo._hidePopup()
        APP.processEvents()

        # 使用 ASCII 按键，避免 QTest 对非 ASCII 字符的键盘映射限制
        QTest.keyClicks(self._combo._lineEdit, "Z")
        APP.processEvents()

        self.assertEqual(self._combo._lineEdit.text(), "Z")
        self.assertTrue(self._combo._popup_visible)
        self.assertEqual(self._combo._model.rowCount(), 1)

    def testDropButtonTogglesPopup(self):
        """点击下拉箭头可展开再收起。"""
        self._combo._togglePopup()
        self.assertTrue(self._combo._popup_visible)

        self._combo._togglePopup()
        self.assertFalse(self._combo._popup_visible)

    def testMouseClickExpandsEvenWhenAlreadyFocused(self):
        """焦点已在输入框内时再次点击，仍会展开下拉（此时没有 FocusIn 事件）。"""
        self._combo._lineEdit.setFocus()
        APP.processEvents()
        self.assertTrue(self._combo._lineEdit.hasFocus())

        self._combo._hidePopup()
        APP.processEvents()
        self.assertFalse(self._combo._popup_visible)

        QTest.mouseClick(self._combo._lineEdit, Qt.LeftButton)
        APP.processEvents()

        self.assertTrue(self._combo._popup_visible)


class TestHideTrigger(SearchableComboBoxTestCase):
    """收起触发相关测试。"""

    def testFocusOutHidesPopup(self):
        """输入框失焦后延迟收起。"""
        self._sendFocusIn(Qt.MouseFocusReason)
        self.assertTrue(self._combo._popup_visible)

        self._sendFocusOut()
        self._waitForHide()

        self.assertFalse(self._combo._popup_visible)
        self.assertEqual(self._combo._dropBtn.text(), '▼')

    def testEscapeHidesPopup(self):
        """按下 Esc 收起下拉。"""
        self._sendFocusIn(Qt.MouseFocusReason)
        self.assertTrue(self._combo._popup_visible)

        self._sendKey(Qt.Key_Escape)

        self.assertFalse(self._combo._popup_visible)

    def testContainerHasNoFocusSoOldHookWasDead(self):
        """容器自身为 NoFocus，说明旧实现挂在容器上的收起逻辑永远不会触发。"""
        self.assertEqual(self._combo.focusPolicy(), Qt.NoFocus)
        self.assertTrue(self._combo._lineEdit.focusPolicy() & Qt.TabFocus)

    def testItemSelectionHidesPopup(self):
        """选择列表项后收起并回填选中值。"""
        self._sendFocusIn(Qt.MouseFocusReason)
        self._combo._selectItem(0)
        APP.processEvents()

        self.assertFalse(self._combo._popup_visible)
        self.assertEqual(self._combo._lineEdit.text(), ITEMS[0])
        self.assertEqual(self._combo.currentIndex(), 0)

    def testHidingWidgetHidesPopup(self):
        """控件被隐藏（如切换页签）时收起下拉，避免弹窗残留。"""
        self._sendFocusIn(Qt.MouseFocusReason)
        self.assertTrue(self._combo._popup_visible)

        self._combo.hide()
        APP.processEvents()

        self.assertFalse(self._combo._popup_visible)
        self.assertFalse(self._combo._popup.isVisible())


class TestTabSwitchScenario(unittest.TestCase):
    """切换页签场景回归测试（本次 bug 的直接复现场景）。"""

    @classmethod
    def setUpClass(cls):
        """构造两个页签：页 0 放一个按钮，页 1 放可搜索下拉框。"""
        cls._tabs = QTabWidget()

        cls._page0 = QWidget()
        page0_layout = QVBoxLayout(cls._page0)
        cls._button = QPushButton("占位按钮")
        page0_layout.addWidget(cls._button)
        cls._tabs.addTab(cls._page0, "数据看板")

        cls._combo = SearchableComboBox()
        for item in ITEMS:
            cls._combo.addItem(item, item)
        cls._tabs.addTab(cls._combo, "舰娘管理")

        cls._tabs.resize(600, 300)
        cls._tabs.show()
        APP.processEvents()

    @classmethod
    def tearDownClass(cls):
        """测试清理。"""
        cls._combo._hidePopup()
        cls._tabs.hide()
        cls._tabs.deleteLater()
        APP.processEvents()

    def testTabSwitchWithFocusInPreviousPageKeepsPopupClosed(self):
        """切换前焦点在旧页面内时，切换后下拉保持关闭。"""
        self._tabs.setCurrentIndex(0)
        APP.processEvents()
        self._button.setFocus()
        APP.processEvents()
        self.assertIs(APP.focusWidget(), self._button)

        self._combo._hidePopup()
        APP.processEvents()

        self._tabs.setCurrentIndex(1)
        APP.processEvents()

        # 前置条件：Qt 把焦点交给了新页面里第一个可聚焦控件（即本控件的输入框）
        self.assertIs(APP.focusWidget(), self._combo._lineEdit)
        self.assertFalse(self._combo._popup_visible)
        self.assertFalse(self._combo._popup.isVisible())


if __name__ == "__main__":
    unittest.main()
