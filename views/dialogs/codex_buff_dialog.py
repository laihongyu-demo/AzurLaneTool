"""
科技属性看板对话框模块。

点击「数据看板 → 剩余练级数量」卡片时弹出，按增益目标舰种（boost_typ）
× Buff 属性类型（buff_typ）汇总 buff_value。窗口只读，不写数据库。
"""

from typing import Optional

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QBrush, QColor
from PyQt5.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QHeaderView,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from services.statistics_service import (
    CodexBuffMatrix,
    CodexBuffMatrixCell,
    CodexBuffValueSummary,
    StatisticsService,
)
from utils.exceptions import DatabaseError
from utils.unit_formatter import formatExact


class CodexBuffDialog(QDialog):
    """
    科技属性看板对话框。

    非模态窗口：打开期间仍可操作主界面；每次显示时重新读取聚合结果。
    """

    def __init__(
        self,
        statistics_service: Optional[StatisticsService] = None,
        parent: QWidget = None
    ):
        """
        初始化科技属性看板对话框。

        Args:
            statistics_service: 统计服务实例。
            parent: 父控件。
        """
        super().__init__(parent)
        self._statistics_service = statistics_service or StatisticsService()
        self._initUi()
        self.refreshData()

    def _initUi(self) -> None:
        """初始化用户界面。"""
        self.setWindowTitle("科技属性看板")
        self.setModal(False)
        self.setMinimumSize(900, 560)
        self.resize(1000, 720)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(15, 15, 15, 15)
        layout.setSpacing(10)

        intro = QLabel(
            "按舰种（boost_typ）× Buff 属性（buff_typ）汇总 buff_value；"
            "单元格 = 已获得 / 总（省略千分符，悬停查看精确值）；"
            "— = 无记录；绿色 = 已完成（已获得 = 总）。"
            "数据来源：codex_buff（只读）。"
        )
        intro.setWordWrap(True)
        intro.setStyleSheet("color: #666;")
        layout.addWidget(intro)

        self._table = QTableWidget(0, 0, self)
        self._table.verticalHeader().setVisible(False)
        self._table.verticalHeader().setDefaultSectionSize(28)
        self._table.horizontalHeader().setMinimumSectionSize(70)
        self._table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._table.setSelectionBehavior(QAbstractItemView.SelectItems)
        self._table.setSelectionMode(QAbstractItemView.SingleSelection)
        self._table.setAlternatingRowColors(True)
        self._table.setWordWrap(False)
        layout.addWidget(self._table, 1)

        self._statusLabel = QLabel("")
        self._statusLabel.setStyleSheet("color: #666; font-size: 12px;")
        layout.addWidget(self._statusLabel)

        buttons = QDialogButtonBox(QDialogButtonBox.Close, self)
        buttons.button(QDialogButtonBox.Close).setText("关闭")
        buttons.rejected.connect(self.close)
        layout.addWidget(buttons, 0, Qt.AlignRight)

    def refreshData(self) -> None:
        """重新读取并渲染舰种 × Buff 属性矩阵。"""
        try:
            matrix = self._statistics_service.getBuffMatrix()
        except DatabaseError as e:
            self._renderError(f"数据库错误：{e}")
            return
        except Exception as e:
            self._renderError(f"读取科技属性数据失败：{e}")
            return

        self._renderMatrix(matrix)

    def _renderMatrix(self, matrix: CodexBuffMatrix) -> None:
        """
        渲染矩阵与底部合计行。

        Args:
            matrix: Service 产出的 15×9 矩阵。
        """
        boost_typs = matrix.boost_typs
        buff_typs = matrix.buff_typs

        self._table.clear()
        self._table.setColumnCount(len(buff_typs) + 1)
        self._table.setRowCount(len(boost_typs) + 1)
        self._table.setHorizontalHeaderLabels(["舰种"] + buff_typs)

        header = self._table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeToContents)

        for row_index, boost_typ in enumerate(boost_typs):
            self._table.setItem(
                row_index,
                0,
                self._makeItem(boost_typ, f"{boost_typ}：增益目标舰种", bold=True),
            )
            for column_index, buff_typ in enumerate(buff_typs, start=1):
                cell = matrix.getCell(boost_typ, buff_typ)
                self._table.setItem(
                    row_index,
                    column_index,
                    self._makeCellItem(cell),
                )

        total_row = len(boost_typs)
        self._table.setItem(
            total_row,
            0,
            self._makeItem("合计", "按 buff_typ 汇总全部舰种", bold=True, filled=True),
        )
        for column_index, summary in enumerate(matrix.column_totals, start=1):
            item = self._makeItem(
                f"{summary.unlocked_value}/{summary.total_value}",
                self._buildTotalTooltip(summary.buff_typ, summary),
                bold=True,
                filled=True,
            )
            self._table.setItem(total_row, column_index, item)

        nonempty_count = sum(1 for cell in matrix.cells.values() if cell.has_records)
        self._statusLabel.setText(
            f"{len(boost_typs)} 舰种 × {len(buff_typs)} 属性；"
            f"{nonempty_count} 个组合有记录；— 表示无记录。"
        )

    def _makeCellItem(self, cell: CodexBuffMatrixCell) -> QTableWidgetItem:
        """
        生成单个矩阵单元格。

        Args:
            cell: 舰种 × 属性单元格。

        Returns:
            表格项；无记录时显示灰色 ``—``。
        """
        if not cell.has_records:
            return self._makeItem(
                "—",
                f"{cell.boost_typ} × {cell.buff_typ}：暂无记录",
                muted=True,
            )

        text = f"{cell.unlocked_value}/{cell.total_value}"
        return self._makeItem(text, self._buildCellTooltip(cell), completed=cell.is_completed)

    def _makeItem(
        self,
        text: str,
        tooltip: str,
        bold: bool = False,
        muted: bool = False,
        filled: bool = False,
        completed: bool = False,
    ) -> QTableWidgetItem:
        """
        构造统一样式的表格项。

        Args:
            text: 显示文本。
            tooltip: 悬停提示。
            bold: 是否加粗。
            muted: 是否使用灰色（无记录）。
            filled: 是否使用浅灰底色（合计行）。
            completed: 是否使用浅绿底 + 深绿字（已完成单元格）。

        Returns:
            表格项。
        """
        item = QTableWidgetItem(text)
        item.setTextAlignment(Qt.AlignCenter)
        item.setToolTip(tooltip)
        if bold:
            font = item.font()
            font.setBold(True)
            item.setFont(font)
        if muted:
            item.setForeground(QBrush(QColor("#9e9e9e")))
        if completed:
            item.setBackground(QBrush(QColor("#e8f5e9")))
            item.setForeground(QBrush(QColor("#1b5e20")))
        elif filled:
            item.setBackground(QBrush(QColor("#f5f5f5")))
        return item

    def _buildCellTooltip(self, cell: CodexBuffMatrixCell) -> str:
        """
        生成单元格口径提示。

        Args:
            cell: 舰种 × 属性单元格。

        Returns:
            悬停说明文本。
        """
        base = (
            f"{cell.boost_typ} × {cell.buff_typ}："
            f"已获得 {formatExact(cell.unlocked_value)} / "
            f"总 {formatExact(cell.total_value)}"
            f"（{cell.completion_rate:.1f}%）；"
            f"{cell.record_count} 条记录"
        )
        if cell.is_completed:
            base += "，已完成"
        elif cell.unlocked_value == 0:
            base += "，均未解锁"
        return base + "。"

    def _buildTotalTooltip(self, buff_typ: str, summary: CodexBuffValueSummary) -> str:
        """
        生成合计行口径提示。

        Args:
            buff_typ: Buff 属性类型。
            summary: 该属性的列合计。

        Returns:
            悬停说明文本。
        """
        return (
            f"全部舰种 × {buff_typ}："
            f"已获得 {formatExact(summary.unlocked_value)} / "
            f"总 {formatExact(summary.total_value)}"
            f"（{summary.completion_rate:.1f}%）。"
        )

    def _renderError(self, message: str) -> None:
        """渲染读取失败状态，不弹模态错误框。"""
        self._table.clear()
        self._table.setRowCount(0)
        self._table.setColumnCount(0)
        self._statusLabel.setText(message)

    def showEvent(self, event) -> None:
        """窗口显示时重新读取数据，保证打开期间的数据变化可见。"""
        super().showEvent(event)
        self.refreshData()
