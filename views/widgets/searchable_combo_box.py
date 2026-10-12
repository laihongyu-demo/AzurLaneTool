"""
可搜索下拉框组件模块。

提供支持模糊搜索的下拉框组件，使用弹出窗口避免布局偏移。
"""

from typing import List, Any, Optional
import time

from PyQt5.QtWidgets import (
    QWidget, QApplication, QVBoxLayout, QHBoxLayout, QLineEdit, QPushButton,
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

# 判断“弹窗是被本次点击收起”时，允许自动收起时刻略早于按下时刻的容差（秒）
AUTO_HIDE_PRESS_TOLERANCE_S = 0.2


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
        # 三角按钮开关的判定依据（详见 _togglePopup）
        self._auto_hidden_at = 0.0
        self._drop_press_started_at = 0.0
        self._popup_open_at_press = False
        self._hidingByCode = False

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

        self._popup = QFrame(
            self,
            Qt.Popup | Qt.FramelessWindowHint | Qt.WindowDoesNotAcceptFocus
        )
        self._popup.setAttribute(Qt.WA_TranslucentBackground, False)
        # 弹窗展示时不抢占窗口激活，避免主窗口的输入框失去键盘输入
        self._popup.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self._popup.setFocusPolicy(Qt.NoFocus)

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
        # 列表不参与焦点链：避免展开后键盘输入落到列表上，导致输入框表现为无法编辑
        self._listView.setFocusPolicy(Qt.NoFocus)

        self._model = QStringListModel(self)
        self._listView.setModel(self._model)

        popup_layout.addWidget(self._listView)

        self.setMinimumWidth(200)

    def _connectSignals(self) -> None:
        """连接信号与槽。"""
        self._lineEdit.textChanged.connect(self._onTextChanged)
        self._lineEdit.installEventFilter(self)
        self._popup.installEventFilter(self)
        self._listView.installEventFilter(self)
        self._dropBtn.pressed.connect(self._onDropButtonPressed)
        self._dropBtn.clicked.connect(self._togglePopup)
        self._listView.clicked.connect(self._onItemClicked)
        self._listView.activated.connect(self._onItemActivated)

    def _onDropButtonPressed(self) -> None:
        """
        三角按钮按下事件处理。

        记录按下时刻与“按下瞬间弹窗是否展开”，用于识别
        “本次点击已被 Qt 用于收起弹窗”的情况，避免松开时又把它展开。
        """
        self._drop_press_started_at = time.monotonic()
        self._popup_open_at_press = self._popup.isVisible() or self._popup_visible

    def eventFilter(self, watched, event) -> bool:
        """
        输入框事件过滤。

        - 用户点击输入框（鼠标按下）→ 展开下拉
        - 用户点击输入框导致的焦点变化（MouseFocusReason）→ 展开下拉
        - 输入框失焦 → 延迟收起下拉（容器自身为 NoFocus，无法承担该职责）；
          但焦点被下拉弹窗自身夺走（PopupFocusReason）时不得收起，
          否则会刚展开就被关掉、无法选择选项
        - 输入框随页面被隐藏（如切换页签）→ 收起下拉
        - 按下 Esc → 收起下拉

        程序化获得焦点（切换页签、窗口激活、setFocus）不会展开。

        Args:
            watched: 事件来源控件。
            event: 事件对象。

        Returns:
            是否拦截该事件（此处始终交由控件默认处理）。
        """
        if watched is self._popup or watched is self._listView:
            if event.type() == QEvent.KeyPress:
                # 弹窗模式下 Qt 会把按键投给弹窗控件，这里转回输入框，
                # 保证展开下拉后仍能继续输入、删除
                self._forwardKeyToLineEdit(event)
                return True
            if watched is self._popup and event.type() == QEvent.Hide:
                # Qt 也会因点击弹窗之外自行关闭弹窗，这里同步内部状态与按钮文案
                self._syncPopupHidden()
            return super().eventFilter(watched, event)

        if watched is self._lineEdit:
            if event.type() == QEvent.FocusIn:
                if event.reason() in USER_FOCUS_REASONS:
                    self._showPopup()
            elif event.type() == QEvent.MouseButtonPress:
                if event.button() == Qt.LeftButton:
                    self._showPopup()
            elif event.type() == QEvent.FocusOut:
                if event.reason() != Qt.PopupFocusReason:
                    QTimer.singleShot(HIDE_DELAY_MS, self._hidePopupIfFocusOutside)
            elif event.type() == QEvent.Hide:
                if not self.isVisible():
                    self._hidePopup()
            elif event.type() == QEvent.KeyPress and event.key() == Qt.Key_Escape:
                self._hidePopup()

        return super().eventFilter(watched, event)

    def _syncPopupHidden(self) -> None:
        """
        弹窗被隐藏时同步内部状态与按钮文案（不改变焦点）。

        若并非本控件代码主动收起，则记录时刻：这通常意味着 Qt 因
        “点击弹窗外部”把弹窗关掉了，而那次点击可能还会落到三角按钮上。
        """
        self._popup_visible = False
        self._dropBtn.setText("▼")

        if not self._hidingByCode:
            self._auto_hidden_at = time.monotonic()

    def _forwardKeyToLineEdit(self, event) -> None:
        """
        把弹窗/列表收到的按键转发给输入框。

        Qt 处于弹窗模式（Qt.Popup）时，键盘事件会被投递给弹窗控件；
        若不转发，展开下拉后输入框会表现为“无法继续输入或删除”。

        Args:
            event: 按键事件。
        """
        edit = self._lineEdit
        key = event.key()
        shift = bool(event.modifiers() & Qt.ShiftModifier)

        if key == Qt.Key_Escape:
            self._hidePopup()
        elif key == Qt.Key_Backspace:
            edit.backspace()
        elif key == Qt.Key_Delete:
            edit.del_()
        elif key == Qt.Key_Left:
            edit.cursorBackward(shift)
        elif key == Qt.Key_Right:
            edit.cursorForward(shift)
        elif key == Qt.Key_Home:
            edit.home(shift)
        elif key == Qt.Key_End:
            edit.end(shift)
        elif event.text() and not (event.modifiers() & (Qt.ControlModifier | Qt.AltModifier)):
            edit.insert(event.text())

    def _hidePopupIfFocusOutside(self) -> None:
        """
        延迟收起下拉，但焦点仍在本控件或下拉弹窗内部时保持展开。

        弹窗夺取焦点的事件已在 eventFilter 中按 PopupFocusReason 排除；
        此处再确认焦点确实落到了本控件之外，无法判定（focusWidget 为空）时保持展开，
        避免“刚展开就被收起、无法选择选项”。
        """
        focused = QApplication.focusWidget()
        if focused is None or self._containsWidget(focused):
            return

        self._hidePopup()

    def _containsWidget(self, widget) -> bool:
        """
        判断控件是否属于本控件或下拉弹窗（沿父子链向上查找）。

        Args:
            widget: 待判断的控件。

        Returns:
            属于本控件或下拉弹窗时返回 True。
        """
        current = widget
        while current is not None:
            if current is self or current is self._popup:
                return True
            current = current.parentWidget()

        return False

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
        """
        切换弹出窗口显示状态（三角按钮点击）。

        以弹窗的实际可见性为准；若本次点击已经把展开中的弹窗收起
        （Qt 会先因“点击弹窗外部”关掉弹窗，随后这次点击才到达按钮），
        则本次点击只负责收起，不再重新展开。
        """
        # 本次点击是否已经收起过弹窗：按下瞬间弹窗是展开的，或弹窗刚被自动收起
        closed_by_this_click = self._popup_open_at_press or (
            self._drop_press_started_at > 0.0
            and self._auto_hidden_at > 0.0
            and self._auto_hidden_at
            >= self._drop_press_started_at - AUTO_HIDE_PRESS_TOLERANCE_S
        )
        self._popup_open_at_press = False
        self._drop_press_started_at = 0.0

        if self._popup.isVisible():
            self._hidePopup()
            return

        if closed_by_this_click:
            self._auto_hidden_at = 0.0
            self._hidePopup()
            return

        self._showPopup()

    def _showPopup(self) -> None:
        """显示弹出窗口。"""
        if self._popup_visible:
            return

        self._filterItems(self._lineEdit.text())

        if self._model.rowCount() == 0:
            # 无匹配项时不展示，同时确保状态与按钮文案一致
            self._hidePopup()
            return

        self._updatePopupPosition()
        self._popup.show()
        self._popup_visible = True
        self._auto_hidden_at = 0.0
        self._dropBtn.setText("▲")
        # 弹窗不接收焦点，键盘输入始终留在输入框内
        self._lineEdit.setFocus()

    def _hidePopup(self) -> None:
        """
        隐藏弹出窗口，并把焦点交还输入框。

        弹窗在不同平台可能短暂持有焦点或键盘，收起后若不交还，
        输入框会表现为“无法编辑”（点选舰娘后再开关下拉时尤其明显）。
        """
        was_visible = self._popup.isVisible()
        self._hidingByCode = True
        self._popup.hide()
        self._hidingByCode = False
        self._popup_visible = False
        self._dropBtn.setText("▼")

        focused = QApplication.focusWidget()
        if was_visible and (focused is None or self._containsWidget(focused)):
            self._lineEdit.setFocus()

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
