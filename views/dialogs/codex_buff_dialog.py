"""
科技属性看板对话框模块。

点击「数据看板 → 剩余练级数量」卡片时弹出，按 Buff 属性类型（buff_typ）
汇总 buff_value。窗口只读，不写数据库。
"""

from typing import Optional

from PyQt5.QtCore import Qt
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

from services.statistics_service import CodexBuffValueSummary, StatisticsService
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
        self.setMinimumSize(760, 520)
        self.resize(900, 620)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(15, 15, 15, 15)
        layout.setSpacing(10)

        intro = QLabel(
            "按 Buff 属性类型（buff_typ）汇总 buff_value；主值为已解锁记录的汇总值，"
            "总汇总值为该属性全部记录之和。数据来源：codex_buff（只读）。"
        )
        intro.setWordWrap(True)
        intro.setStyleSheet("color: #666;")
        layout.addWidget(intro)

        self._table = QTableWidget(0, 4, self)
        self._table.setHorizontalHeaderLabels([
            "Buff 属性",
            "已获得汇总值",
            "总汇总值",
            "完成率",
        ])
        self._table.verticalHeader().setVisible(False)
        self._table.verticalHeader().setDefaultSectionSize(30)
        self._table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SingleSelection)
        self._table.setAlternatingRowColors(True)
        self._table.setWordWrap(False)

        header = self._table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.Stretch)
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        layout.addWidget(self._table, 1)

        self._statusLabel = QLabel("")
        self._statusLabel.setStyleSheet("color: #666; font-size: 12px;")
        layout.addWidget(self._statusLabel)

        buttons = QDialogButtonBox(QDialogButtonBox.Close, self)
        buttons.button(QDialogButtonBox.Close).setText("关闭")
        buttons.rejected.connect(self.close)
        layout.addWidget(buttons, 0, Qt.AlignRight)

    def refreshData(self) -> None:
        """重新读取并渲染 9 个 buff_typ 的汇总值。"""
        try:
            summaries = self._statistics_service.getBuffStatisticsByBuffTyp()
        except DatabaseError as e:
            self._renderError(f"数据库错误：{e}")
            return
        except Exception as e:
            self._renderError(f"读取科技属性数据失败：{e}")
            return

        self._table.setRowCount(len(summaries))
        for row_index, summary in enumerate(summaries):
            values = [
                summary.buff_typ,
                formatExact(summary.unlocked_value),
                formatExact(summary.total_value),
                f"{summary.completion_rate:.1f}%",
            ]
            tooltip = self._buildTooltip(summary)
            for column, text in enumerate(values):
                item = QTableWidgetItem(text)
                item.setTextAlignment(Qt.AlignCenter)
                item.setToolTip(tooltip)
                self._table.setItem(row_index, column, item)

        self._statusLabel.setText(
            f"共 {len(summaries)} 个 Buff 属性；悬停单元格可查看口径说明。"
        )

    def _renderError(self, message: str) -> None:
        """渲染读取失败状态，不弹模态错误框。"""
        self._table.setRowCount(0)
        self._statusLabel.setText(message)

    def _buildTooltip(self, summary: CodexBuffValueSummary) -> str:
        """
        生成单行口径提示。

        Args:
            summary: 单个 buff_typ 的汇总值。

        Returns:
            悬停说明文本。
        """
        return (
            f"{summary.buff_typ}：已获得汇总值 {summary.unlocked_value}"
            f" / 总汇总值 {summary.total_value}"
            f"（{summary.completion_rate:.1f}%）；"
            "按 buff_value 求和，已获得仅统计 buff_unlock='Y' 的记录。"
        )

    def showEvent(self, event) -> None:
        """窗口显示时重新读取数据，保证打开期间的数据变化可见。"""
        super().showEvent(event)
        self.refreshData()
