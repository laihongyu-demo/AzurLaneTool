"""
统计面板模块。

定义数据统计功能的独立界面组件，支持扩展。
"""

from typing import Optional, Dict, Any

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QGroupBox, QMessageBox
)
from PyQt5.QtCore import Qt, pyqtSignal

from services.statistics_service import StatisticsService
from services.user_service import UserService
from views.widgets.stat_card import StatCard
from utils.exceptions import DatabaseError


class StatisticsPanel(QWidget):
    """
    统计面板控件。

    提供数据统计功能的界面展示，支持扩展。
    """

    dataRefreshed = pyqtSignal()

    def __init__(
        self,
        statistics_service: Optional[StatisticsService] = None,
        user_service: Optional[UserService] = None,
        parent: QWidget = None
    ):
        """
        初始化统计面板。

        Args:
            statistics_service: 统计服务实例。
            user_service: 用户服务实例。
            parent: 父控件。
        """
        super().__init__(parent)
        self._statistics_service = statistics_service or StatisticsService()
        self._user_service = user_service or UserService()
        self._initUi()
        self._connectSignals()
        self.refreshData()

    def _initUi(self) -> None:
        """初始化用户界面。"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(15, 15, 15, 15)
        layout.setSpacing(20)

        commander_group = QGroupBox("指挥官看板")
        commander_layout = QVBoxLayout(commander_group)

        commander_stats_layout = QHBoxLayout()
        commander_stats_layout.setSpacing(15)

        self._commanderLevelCard = StatCard("指挥官等级", "-", clickable=True) # 格式："指挥官等级（当前经验/需求经验）"
        self._dutyDaysCard = StatCard("执勤天数", "-")
        self._expEfficiencyCard = StatCard("指级效率", "-") # ≥10000采用千进制显示且保留一位小数（示例：10000->10.0k）

        commander_stats_layout.addWidget(self._commanderLevelCard)
        commander_stats_layout.addWidget(self._dutyDaysCard)
        commander_stats_layout.addWidget(self._expEfficiencyCard)
        commander_stats_layout.addStretch()

        commander_layout.addLayout(commander_stats_layout)
        layout.addWidget(commander_group)

        unlock_group = QGroupBox("舰娘收藏看板")
        unlock_layout = QVBoxLayout(unlock_group)

        unlock_stats_layout = QHBoxLayout()
        unlock_stats_layout.setSpacing(15)

        self._totalCard = StatCard("舰娘总数", "0")
        self._unlockedCard = StatCard("已解锁", "0")
        self._lockedCard = StatCard("未解锁", "0")
        self._rateCard = StatCard("收藏率", "0%")

        unlock_stats_layout.addWidget(self._totalCard)
        unlock_stats_layout.addWidget(self._unlockedCard)
        unlock_stats_layout.addWidget(self._lockedCard)
        unlock_stats_layout.addWidget(self._rateCard)

        unlock_layout.addLayout(unlock_stats_layout)
        layout.addWidget(unlock_group)

        tp_group = QGroupBox("科技点看板")
        tp_layout = QVBoxLayout(tp_group)

        tp_stats_layout = QHBoxLayout()
        tp_stats_layout.setSpacing(15)

        self._totalTpCard = StatCard("科技点总值", "0")
        self._unlockedTpCard = StatCard("当前科技点", "0")
        self._tpRateCard = StatCard("科技点完成率", "0%")
        self._remainingLevelingCard = StatCard("剩余练级数量", "0")

        tp_stats_layout.addWidget(self._totalTpCard)
        tp_stats_layout.addWidget(self._unlockedTpCard)
        tp_stats_layout.addWidget(self._tpRateCard)
        tp_stats_layout.addWidget(self._remainingLevelingCard)

        tp_layout.addLayout(tp_stats_layout)
        layout.addWidget(tp_group)

        bulin_group = QGroupBox("杂项数据看板")
        bulin_layout = QVBoxLayout(bulin_group)

        bulin_stats_layout = QHBoxLayout()
        bulin_stats_layout.setSpacing(15)

        self._universalBulinCard = StatCard("泛用型布里", "0")
        self._trialBulinCard = StatCard("试作型布里MKII", "0")
        self._specializedBulinCard = StatCard("特装型布里MKIII", "0")
        self._cubeCard = StatCard("魔方", "-", clickable=True) # ≥10000采用千进制显示且保留一位小数（示例：10000->10.0k）
        self._redGemCard = StatCard("红尖尖", "-", clickable=True) # ≥10000采用千进制显示且保留一位小数（示例：10000->10.0k）

        bulin_stats_layout.addWidget(self._universalBulinCard)
        bulin_stats_layout.addWidget(self._trialBulinCard)
        bulin_stats_layout.addWidget(self._specializedBulinCard)
        bulin_stats_layout.addWidget(self._cubeCard)
        bulin_stats_layout.addWidget(self._redGemCard)

        bulin_layout.addLayout(bulin_stats_layout)
        layout.addWidget(bulin_group)

        button_layout = QHBoxLayout()
        button_layout.addStretch()
        self._refreshBtn = QPushButton("刷新统计")
        self._refreshBtn.setMinimumWidth(120)
        self._refreshBtn.setMinimumHeight(35)
        button_layout.addWidget(self._refreshBtn)
        layout.addLayout(button_layout)

        layout.addStretch()

    def _connectSignals(self) -> None:
        """连接信号与槽。"""
        self._refreshBtn.clicked.connect(self._onRefreshClicked)
        self._commanderLevelCard.clicked.connect(self._onCommanderLevelClicked)
        self._cubeCard.clicked.connect(self._onCubeClicked)
        self._redGemCard.clicked.connect(self._onRedGemClicked)

    def _onRefreshClicked(self) -> None:
        """刷新按钮点击事件处理。"""
        self.refreshData()
        self.dataRefreshed.emit()

    def _onCommanderLevelClicked(self) -> None:
        """
        指挥官等级卡片点击事件处理。

        TODO: 后续实现指挥官等级详细信息的业务逻辑
        """
        QMessageBox.information(
            self,
            "提示",
            "开发中",
            QMessageBox.Ok
        )

    def _onCubeClicked(self) -> None:
        """
        魔方卡片点击事件处理。

        TODO: 后续实现魔方详细信息的业务逻辑
        """
        QMessageBox.information(
            self,
            "提示",
            "开发中",
            QMessageBox.Ok
        )

    def _onRedGemClicked(self) -> None:
        """
        红尖尖卡片点击事件处理。

        TODO: 后续实现红尖尖详细信息的业务逻辑
        """
        QMessageBox.information(
            self,
            "提示",
            "开发中",
            QMessageBox.Ok
        )

    def refreshData(self) -> None:
        """刷新统计数据。"""
        try:
            duty_days_text = self._user_service.getDutyDaysText()
            self._dutyDaysCard.setValue(duty_days_text)

            stats = self._statistics_service.getAllStatistics()

            unlock_stats = stats.get("unlock", {})
            total_text = f"{unlock_stats.get('total_excluding_collab', 0)}（{unlock_stats.get('total', 0)}）"
            unlocked_text = f"{unlock_stats.get('unlocked_excluding_collab', 0)}（{unlock_stats.get('unlocked', 0)}）"
            locked_text = f"{unlock_stats.get('locked_excluding_collab', 0)}（{unlock_stats.get('locked', 0)}）"
            rate_text = f"{unlock_stats.get('unlock_rate', 0):.1f}%"

            self._totalCard.setValue(total_text)
            self._unlockedCard.setValue(unlocked_text)
            self._lockedCard.setValue(locked_text)
            self._rateCard.setValue(rate_text)

            tp_stats = stats.get("tp", {})
            total_tp = tp_stats.get("total_tp", 0)
            unlocked_tp = tp_stats.get("unlocked_tp", 0)
            completion_rate = tp_stats.get("completion_rate", 0)

            self._totalTpCard.setValue(str(total_tp))
            self._unlockedTpCard.setValue(str(unlocked_tp))
            self._tpRateCard.setValue(f"{completion_rate:.1f}%")

            bulin_stats = stats.get("bulin", {})
            self._universalBulinCard.setValue(str(bulin_stats.get("universal_bulin", 0)))
            self._trialBulinCard.setValue(str(bulin_stats.get("trial_bulin_mkii", 0)))
            self._specializedBulinCard.setValue(str(bulin_stats.get("specialized_bulin_mkiii", 0)))

            remaining_leveling = stats.get("remaining_leveling", 0)
            self._remainingLevelingCard.setValue(str(remaining_leveling))

        except DatabaseError as e:
            self._showError(f"数据库错误: {e}")
        except Exception as e:
            self._showError(f"刷新数据失败: {e}")

    def _showError(self, message: str) -> None:
        """显示错误信息。"""
        self._totalCard.setValue("错误")
        self._unlockedCard.setValue("错误")
        self._lockedCard.setValue("错误")
        self._rateCard.setValue("错误")
        self._totalTpCard.setValue("错误")
        self._unlockedTpCard.setValue("错误")
        self._tpRateCard.setValue("错误")
        self._remainingLevelingCard.setValue("错误")
        self._universalBulinCard.setValue("错误")
        self._trialBulinCard.setValue("错误")
        self._specializedBulinCard.setValue("错误")

    def updateUnlockStats(self, unlock_stats: Dict[str, Any]) -> None:
        """
        更新解锁统计显示。

        Args:
            unlock_stats: 解锁统计数据字典。
        """
        total_text = f"{unlock_stats.get('total_excluding_collab', 0)}（{unlock_stats.get('total', 0)}）"
        unlocked_text = f"{unlock_stats.get('unlocked_excluding_collab', 0)}（{unlock_stats.get('unlocked', 0)}）"
        locked_text = f"{unlock_stats.get('locked_excluding_collab', 0)}（{unlock_stats.get('locked', 0)}）"
        rate_text = f"{unlock_stats.get('unlock_rate', 0):.1f}%"

        self._totalCard.setValue(total_text)
        self._unlockedCard.setValue(unlocked_text)
        self._lockedCard.setValue(locked_text)
        self._rateCard.setValue(rate_text)

    def updateTpStats(self, tp_stats: Dict[str, Any]) -> None:
        """
        更新科技点统计显示。

        Args:
            tp_stats: 科技点统计数据字典。
        """
        total_tp = tp_stats.get("total_tp", 0)
        unlocked_tp = tp_stats.get("unlocked_tp", 0)
        completion_rate = tp_stats.get("completion_rate", 0)

        self._totalTpCard.setValue(str(total_tp))
        self._unlockedTpCard.setValue(str(unlocked_tp))
        self._tpRateCard.setValue(f"{completion_rate:.1f}%")

    def updateBulinStats(self, bulin_stats: Dict[str, Any]) -> None:
        """
        更新布里需求统计显示。

        Args:
            bulin_stats: 布里需求统计数据字典。
        """
        self._universalBulinCard.setValue(str(bulin_stats.get("universal_bulin", 0)))
        self._trialBulinCard.setValue(str(bulin_stats.get("trial_bulin_mkii", 0)))
        self._specializedBulinCard.setValue(str(bulin_stats.get("specialized_bulin_mkiii", 0)))
