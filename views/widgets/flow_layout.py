"""
流式布局模块。

按「一行放得下就并排，放不下就换行」的方式排列子项。任务看板的分组（任务 /
签到 / 世界巡游 / 常规录入）宽度按内容收紧，窗口宽裕时自然并排，窄时自动换行。

实现参考 Qt 官方的 FlowLayout 示例，支持 ``heightForWidth``，因此放进滚动区后
高度能随宽度正确变化。
"""

from typing import List, Optional

from PyQt5.QtCore import QPoint, QRect, QSize, Qt
from PyQt5.QtWidgets import QLayout, QLayoutItem, QWidget


class FlowLayout(QLayout):
    """
    流式布局。

    与 QHBoxLayout 的区别：子项不会被拉伸到整行宽度，也不会因为总宽超出而压扁，
    而是按各自 ``sizeHint`` 排列，超出容器宽度就换到下一行。
    """

    def __init__(
        self,
        parent: Optional[QWidget] = None,
        margin: int = 0,
        h_spacing: int = 10,
        v_spacing: int = 10
    ):
        """
        初始化流式布局。

        Args:
            parent: 父控件。
            margin: 四周留白。
            h_spacing: 水平间距。
            v_spacing: 垂直间距。
        """
        super().__init__(parent)
        self._items: List[QLayoutItem] = []
        self._h_spacing = h_spacing
        self._v_spacing = v_spacing
        self.setContentsMargins(margin, margin, margin, margin)

    def addItem(self, item: QLayoutItem) -> None:
        """追加一个布局项。"""
        self._items.append(item)

    def count(self) -> int:
        """布局项数量。"""
        return len(self._items)

    def itemAt(self, index: int) -> Optional[QLayoutItem]:
        """按索引取布局项。"""
        if 0 <= index < len(self._items):
            return self._items[index]
        return None

    def takeAt(self, index: int) -> Optional[QLayoutItem]:
        """移除并返回指定位置的布局项。"""
        if 0 <= index < len(self._items):
            return self._items.pop(index)
        return None

    def expandingDirections(self) -> Qt.Orientations:
        """流式布局本身不吸收额外空间。"""
        return Qt.Orientations(Qt.Orientation(0))

    def hasHeightForWidth(self) -> bool:
        """高度依赖宽度。"""
        return True

    def heightForWidth(self, width: int) -> int:
        """按给定宽度计算布局所需高度。"""
        return self._doLayout(QRect(0, 0, width, 0), True)

    def setGeometry(self, rect: QRect) -> None:
        """按给定矩形重新排列子项。"""
        super().setGeometry(rect)
        self._doLayout(rect, False)

    def sizeHint(self) -> QSize:
        """推荐尺寸。"""
        return self.minimumSize()

    def minimumSize(self) -> QSize:
        """最小尺寸：取所有子项最小尺寸的外接矩形。"""
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        margins = self.contentsMargins()
        return size + QSize(
            margins.left() + margins.right(), margins.top() + margins.bottom()
        )

    def _doLayout(self, rect: QRect, test_only: bool) -> int:
        """
        排列子项并返回占用高度。

        Args:
            rect: 可用矩形。
            test_only: 为 True 时只计算不移动。

        Returns:
            排列后占用的高度。
        """
        margins = self.contentsMargins()
        effective = rect.adjusted(
            margins.left(), margins.top(), -margins.right(), -margins.bottom()
        )
        x = effective.x()
        y = effective.y()
        line_height = 0

        for item in self._items:
            hint = item.sizeHint()
            next_x = x + hint.width() + self._h_spacing
            if next_x - self._h_spacing > effective.right() and line_height > 0:
                x = effective.x()
                y = y + line_height + self._v_spacing
                next_x = x + hint.width() + self._h_spacing
                line_height = 0

            if not test_only:
                item.setGeometry(QRect(QPoint(x, y), hint))

            x = next_x
            line_height = max(line_height, hint.height())

        return y + line_height - rect.y() + margins.bottom()
