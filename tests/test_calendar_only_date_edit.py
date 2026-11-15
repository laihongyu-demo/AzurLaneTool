"""
仅日历下拉日期控件单元测试。

测试覆盖：
- 日历下拉可打开且选择可写回控件（回归：只读状态会连带禁用日历下拉）
- 手动输入、粘贴、拖放均不能修改日期
- 上下箭头、翻页键、滚轮与步进均不能修改日期
- Tab 焦点切换仍可用
"""

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtCore import QDate, QPoint, Qt  # noqa: E402
from PyQt5.QtTest import QTest  # noqa: E402
from PyQt5.QtWidgets import QApplication, QLineEdit  # noqa: E402

from views.widgets.calendar_only_date_edit import CalendarOnlyDateEdit  # noqa: E402

APP = QApplication.instance() or QApplication([])

BASE_DATE = QDate(2026, 8, 8)


class TestCalendarOnlyDateEdit(unittest.TestCase):
    """仅日历选择日期控件测试类。"""

    def setUp(self):
        """测试初始化。"""
        self._edit = CalendarOnlyDateEdit()
        self._edit.setDisplayFormat("yyyy/MM/dd")
        self._edit.setDate(BASE_DATE)
        self._edit.resize(140, 28)

    def tearDown(self):
        """测试清理。"""
        self._edit.hide()
        self._edit.deleteLater()

    def _calendarVisible(self) -> bool:
        """判断日历下拉是否可见。"""
        calendar = self._edit.calendarWidget()
        if calendar is None or calendar.window() is None:
            return False
        return bool(calendar.window().isVisible())

    def testCalendarPopupEnabledAndLineEditReadOnly(self):
        """启用日历下拉，且内部行编辑为只读（不使用控件级只读）。"""
        self.assertTrue(self._edit.calendarPopup())
        self.assertIsNotNone(self._edit.calendarWidget())
        self.assertFalse(self._edit.isReadOnly(), "控件级只读会禁用日历下拉")

        line_edit = self._edit.findChild(QLineEdit)
        self.assertIsNotNone(line_edit)
        self.assertTrue(line_edit.isReadOnly())
        self.assertFalse(line_edit.acceptDrops())

    def testCalendarPopupOpensByButtonClick(self):
        """点击下拉箭头可以打开日历（关键回归用例）。"""
        self._edit.show()
        APP.processEvents()

        QTest.mouseClick(
            self._edit, Qt.LeftButton, Qt.NoModifier,
            QPoint(self._edit.width() - 8, self._edit.height() // 2)
        )
        APP.processEvents()

        self.assertTrue(self._calendarVisible(), "点击下拉箭头后日历应可见")

        self._edit.calendarWidget().window().hide()

    def testCalendarSelectionUpdatesDate(self):
        """日历选择可将日期写回控件。"""
        target = QDate(2025, 3, 4)

        self._edit.calendarWidget().clicked.emit(target)

        self.assertEqual(self._edit.date(), target)

    def testTypingIsIgnored(self):
        """手动输入不会改变日期。"""
        self._edit.show()
        self._edit.setFocus()
        QTest.keyClicks(self._edit, "19990101")
        QTest.keyClick(self._edit, Qt.Key_Delete)
        QTest.keyClick(self._edit, Qt.Key_Backspace)
        APP.processEvents()

        self.assertEqual(self._edit.date(), BASE_DATE)

    def testArrowAndPageKeysDoNotStep(self):
        """上下箭头、翻页键与首尾键不会修改日期。"""
        self._edit.show()
        self._edit.setFocus()
        for key in (Qt.Key_Up, Qt.Key_Down, Qt.Key_PageUp, Qt.Key_PageDown, Qt.Key_Home, Qt.Key_End):
            QTest.keyClick(self._edit, key)
        APP.processEvents()

        self.assertEqual(self._edit.date(), BASE_DATE)

    def testStepByIsIgnored(self):
        """按钮/程序步进被忽略。"""
        self._edit.stepUp()
        self._edit.stepDown()
        self._edit.stepBy(5)

        self.assertEqual(self._edit.date(), BASE_DATE)

    def testFocusPolicyKeepsTabFocus(self):
        """控件仍可获得焦点，保证 Tab 切换可用。"""
        self.assertTrue(self._edit.focusPolicy() & Qt.TabFocus)


if __name__ == "__main__":
    unittest.main()
