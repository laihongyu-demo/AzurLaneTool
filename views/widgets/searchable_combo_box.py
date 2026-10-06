"""
可搜索下拉框组件模块。

提供支持模糊搜索的下拉框组件，使用弹出窗口避免布局偏移。
"""

from typing import List, Any, Optional

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLineEdit, QPushButton,
    QFrame, QAbstractItemView, QListView
)
from PyQt5.QtCore import (
    Qt, pyqtSignal, QStringListModel, QModelIndex, QEvent, QTimer
)

# 仅这些焦点来源视为“用户主动交互”，才展开下拉列表；
# 程序化分派焦点（切换页签、窗口激活、setFocus 等）为 OtherFocusReason，不展开。
USER_FOCUS_REASONS = (Qt.MouseFocusReason,)

# 输入框失焦后延迟收起下拉列表的毫秒数（留出点击列表项的处理时间）
HIDE_DELAY_MS = 100


class SearchableComboBox(QWidget):
    """
    可搜索下拉框控件。

    使用弹出窗口显示下拉列表，避免影响页面布局。
    支持模糊搜索、实时过滤。

    展开时机仅限用户主动交互：点击输入框、在输入框内输入、点击下拉箭头；
    程序化获得焦点不会展开。
    """

    currentIndexChanged = pyqtSignal(int)

    def __init__(self, parent: QWidget = None):
        """
        初始化可搜索下拉框。

        Args:
            parent: 父控件。
        """
        super().__init__(parent)
        self._items: List[tuple] = []
        self._filtered_texts: List[str] = []
        self._current_index = -1
        self._popup_visible = False

        self._initUi()
        self._connectSignals()

    def _initUi(self) -> None:
        """初始化用户界面。"""
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._lineEdit = QLineEdit()
        self._lineEdit.setPlaceholderText("请选择或输入搜索...")
        self._lineEdit.setMinimumHeight(30)

        self._dropBtn = QPushButton("▼")
        self._dropBtn.setFixedWidth(30)
        self._dropBtn.setFixedHeight(30)
        self._dropBtn.setFocusPolicy(Qt.NoFocus)

        layout.addWidget(self._lineEdit)
        layout.addWidget(self._dropBtn)

        self._popup = QFrame(self, Qt.Popup | Qt.FramelessWindowHint)
        self._popup.setAttribute(Qt.WA_TranslucentBackground, False)

        popup_layout = QVBoxLayout(self._popup)
        popup_layout.setContentsMargins(0, 0, 0, 0)
        popup_layout.setSpacing(0)

        self._listView = QListView(self._popup)
        self._listView.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._listView.setSelectionMode(QAbstractItemView.SingleSelection)
        self._listView.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._listView.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self._listView.setMinimumHeight(0)
        self._listView.setMaximumHeight(200)

        self._model = QStringListModel(self)
        self._listView.setModel(self._model)

        popup_layout.addWidget(self._listView)

        self.setMinimumWidth(200)

    def _connectSignals(self) -> None:
        """连接信号与槽。"""
        self._lineEdit.textChanged.connect(self._onTextChanged)
        self._lineEdit.installEventFilter(self)
        self._dropBtn.clicked.connect(self._togglePopup)
        self._listView.clicked.connect(self._onItemClicked)
        self._listView.activated.connect(self._onItemActivated)

    def eventFilter(self, watched, event) -> bool:
        """
        输入框事件过滤。

        - 用户点击输入框（鼠标按下）→ 展开下拉
        - 用户点击输入框导致的焦点变化（MouseFocusReason）→ 展开下拉
        - 输入框失焦 → 延迟收起下拉（容器自身为 NoFocus，无法承担该职责）
        - 输入框被隐藏（如切换页签）→ 立即收起下拉
        - 按下 Esc → 收起下拉

        程序化获得焦点（切换页签、窗口激活、setFocus）不会展开。

        Args:
            watched: 事件来源控件。
            event: 事件对象。

        Returns:
            是否拦截该事件（此处始终交由控件默认处理）。
        """
        if watched is self._lineEdit:
            if event.type() == QEvent.FocusIn:
                if event.reason() in USER_FOCUS_REASONS:
                    self._showPopup()
            elif event.type() == QEvent.MouseButtonPress:
                if event.button() == Qt.LeftButton:
                    self._showPopup()
            elif event.type() == QEvent.FocusOut:
                QTimer.singleShot(HIDE_DELAY_MS, self._hidePopup)
            elif event.type() == QEvent.Hide:
                self._hidePopup()
            elif event.type() == QEvent.KeyPress and event.key() == Qt.Key_Escape:
                self._hidePopup()

        return super().eventFilter(watched, event)

    def _onTextChanged(self, text: str) -> None:
        """
        文本变化事件处理。

        仅在输入框持有焦点（用户正在输入）时展开下拉，
        避免程序化的 clear()/setText() 误触发弹窗。
        """
        self._filterItems(text)
        if self._lineEdit.hasFocus():
            self._showPopup()
        self._updatePopupSize()

    def _togglePopup(self) -> None:
        """切换弹出窗口显示状态。"""
        if self._popup_visible:
            self._hidePopup()
        else:
            self._showPopup()

    def _showPopup(self) -> None:
        """显示弹出窗口。"""
        if self._popup_visible:
            return

        self._filterItems(self._lineEdit.text())

        if self._model.rowCount() == 0:
            return

        self._updatePopupPosition()
        self._popup.show()
        self._popup_visible = True
        self._dropBtn.setText("▲")

    def _hidePopup(self) -> None:
        """隐藏弹出窗口。"""
        if self._popup_visible:
            self._popup.hide()
            self._popup_visible = False
            self._dropBtn.setText("▼")

    def _updatePopupPosition(self) -> None:
        """更新弹出窗口位置。"""
        global_pos = self._lineEdit.mapToGlobal(self._lineEdit.rect().bottomLeft())
        self._popup.move(global_pos)
        self._updatePopupSize()

    def _updatePopupSize(self) -> None:
        """更新弹出窗口大小。"""
        width = max(self._lineEdit.width() + self._dropBtn.width(), 200)
        height = min(self._listView.sizeHintForRow(0) * self._model.rowCount() + 4, 200)
        height = max(height, 50)
        self._popup.setFixedWidth(width)
        self._popup.setFixedHeight(height)

    def _filterItems(self, text: str) -> None:
        """过滤列表项。"""
        search_text = text.lower().strip()
        self._filtered_texts = []

        for item_text, item_data in self._items:
            if not search_text or search_text in item_text.lower():
                self._filtered_texts.append(item_text)

        self._model.setStringList(self._filtered_texts)

    def _onItemClicked(self, index: QModelIndex) -> None:
        """列表项点击事件处理。"""
        self._selectItem(index.row())

    def _onItemActivated(self, index: QModelIndex) -> None:
        """列表项激活事件处理。"""
        self._selectItem(index.row())

    def _selectItem(self, filtered_index: int) -> None:
        """选择列表项。"""
        if 0 <= filtered_index < len(self._filtered_texts):
            selected_text = self._filtered_texts[filtered_index]

            for i, (item_text, item_data) in enumerate(self._items):
                if item_text == selected_text:
                    self._lineEdit.blockSignals(True)
                    self._lineEdit.setText(item_text)
                    self._lineEdit.blockSignals(False)

                    if self._current_index != i:
                        self._current_index = i
                        self.currentIndexChanged.emit(i)

                    break

            self._hidePopup()

    def addItem(self, text: str, data: Any = None) -> None:
        """
        添加列表项。

        Args:
            text: 显示文本。
            data: 关联数据。
        """
        self._items.append((text, data))
        self._filterItems(self._lineEdit.text())

    def addItems(self, texts: List[str], data_list: List[Any] = None) -> None:
        """
        批量添加列表项。

        Args:
            texts: 显示文本列表。
            data_list: 关联数据列表。
        """
        if data_list is None:
            data_list = [None] * len(texts)

        for text, data in zip(texts, data_list):
            self._items.append((text, data))

        self._filterItems(self._lineEdit.text())

    def clear(self) -> None:
        """清空所有列表项。"""
        self._items.clear()
        self._filtered_texts.clear()
        self._model.setStringList([])
        self._lineEdit.clear()
        self._current_index = -1
        self._hidePopup()

    def currentIndex(self) -> int:
        """
        获取当前选中索引。

        Returns:
            当前选中项的索引，未选中返回-1。
        """
        return self._current_index

    def setCurrentIndex(self, index: int) -> None:
        """
        设置当前选中索引。

        Args:
            index: 要选中的索引。
        """
        if -1 <= index < len(self._items):
            self._current_index = index
            if index >= 0:
                item_text, _ = self._items[index]
                self._lineEdit.blockSignals(True)
                self._lineEdit.setText(item_text)
                self._lineEdit.blockSignals(False)

    def currentData(self) -> Any:
        """
        获取当前选中项的数据。

        Returns:
            当前选中项的数据，未选中返回None。
        """
        if 0 <= self._current_index < len(self._items):
            return self._items[self._current_index][1]
        return None

    def setPlaceholderText(self, text: str) -> None:
        """
        设置占位文本。

        Args:
            text: 占位文本。
        """
        self._lineEdit.setPlaceholderText(text)

    def setMinimumWidth(self, width: int) -> None:
        """
        设置最小宽度。

        Args:
            width: 最小宽度。
        """
        super().setMinimumWidth(width)
        self._lineEdit.setMinimumWidth(width - 30)
