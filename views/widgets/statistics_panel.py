"""
统计面板模块。

定义数据统计功能的独立界面组件，支持扩展。
"""

from typing import Optional, Dict, Any

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QGroupBox, QMessageBox, QCheckBox
)
from PyQt5.QtCore import Qt, pyqtSignal

from services.statistics_service import StatisticsService
from services.user_service import UserService
from services.commander_service import CommanderService
from services.resource_service import ResourceService
from services.mental_calculation_service import MentalCalculationService, MentalCalculationResult
from views.dialogs.commander_exp_dialog import CommanderExpDialog
from views.widgets.stat_card import StatCard
from utils.constants import RESOURCE_TYPE_CUBE, RESOURCE_TYPE_RED_GEM
from utils.exceptions import DatabaseError
from utils.unit_formatter import formatExact


class StatisticsPanel(QWidget):
    """
    统计面板控件。

    提供数据统计功能的界面展示，支持扩展。
    """

    dataRefreshed = pyqtSignal()
    commanderResult = pyqtSignal(object)

    def __init__(
        self,
        statistics_service: Optional[StatisticsService] = None,
        user_service: Optional[UserService] = None,
        mental_calculation_service: Optional[MentalCalculationService] = None,
        commander_service: Optional[CommanderService] = None,
        resource_service: Optional[ResourceService] = None,
        parent: QWidget = None
    ):
        """
        初始化统计面板。

        Args:
            statistics_service: 统计服务实例。
            user_service: 用户服务实例。
            mental_calculation_service: 心智计算服务实例。
            commander_service: 指挥官服务实例。
            resource_service: 资源统计服务实例（只读）。
            parent: 父控件。
        """
        super().__init__(parent)
        self._statistics_service = statistics_service or StatisticsService()
        self._user_service = user_service or UserService()
        self._mental_calculation_service = mental_calculation_service or MentalCalculationService()
        self._commander_service = commander_service or CommanderService()
        self._resource_service = resource_service or ResourceService()
        self._commanderDialog = None
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
        commander_layout.setContentsMargins(15, 20, 15, 20)
        commander_layout.setSpacing(10)

        commander_stats_layout = QHBoxLayout()
        commander_stats_layout.setSpacing(0)

        # 数值口径约定：精确数值固定加千分符；大概数值用 K/M/B/T 缩写（保留一位小数）。
        self._commanderLevelCard = StatCard("指挥官等级", "-", clickable=True) # 格式："指挥官等级（当前经验/需求经验）"
        self._dutyDaysCard = StatCard("执勤天数", "-") # 精确数值：固定千分符（示例：1169->1,169天）
        self._expEfficiencyCard = StatCard("指级效率", "-") # 精确数值：固定千分符，单位 /天（示例：11336->11,336/天）
        self._cubeCard = StatCard("魔方", "-") # 大概数值：≥10000用K/M/B/T缩写且保留一位小数（示例：10000->10.0K）
        self._redGemCard = StatCard("红尖尖", "-") # 大概数值：≥10000用K/M/B/T缩写且保留一位小数（示例：10000->10.0K）

        # 初始口径提示；每次刷新会被服务层返回的口径说明覆盖
        self._expEfficiencyCard.setToolTip("指级效率：近 30 天日均（绝对经验差 ÷ 实际跨度）")

        commander_stats_layout.addStretch()
        commander_stats_layout.addWidget(self._commanderLevelCard)
        commander_stats_layout.addStretch()
        commander_stats_layout.addWidget(self._dutyDaysCard)
        commander_stats_layout.addStretch()
        commander_stats_layout.addWidget(self._expEfficiencyCard)
        commander_stats_layout.addStretch()
        commander_stats_layout.addWidget(self._cubeCard)
        commander_stats_layout.addStretch()
        commander_stats_layout.addWidget(self._redGemCard)
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
        self._oathRateCard = StatCard("誓约率", "0%")

        unlock_stats_layout.addWidget(self._totalCard)
        unlock_stats_layout.addWidget(self._unlockedCard)
        unlock_stats_layout.addWidget(self._lockedCard)
        unlock_stats_layout.addWidget(self._rateCard)
        unlock_stats_layout.addWidget(self._oathRateCard)

        unlock_layout.addLayout(unlock_stats_layout)
        layout.addWidget(unlock_group)

        tp_group = QGroupBox("科技点看板")
        tp_layout = QVBoxLayout(tp_group)

        tp_stats_layout = QHBoxLayout()
        tp_stats_layout.setSpacing(15)

        self._totalTpCard = StatCard("科技点总值", "0")  # 精确数值：固定千分符
        self._unlockedTpCard = StatCard("当前科技点", "0")  # 精确数值：固定千分符
        self._tpRateCard = StatCard("科技点完成率", "0%")
        self._remainingLevelingCard = StatCard("剩余练级数量", "0")  # 格式："需消耗心智单元（还需练级）"
        self._remainingLevelingCard.setToolTip(
            "主值：未满 120 级、仍需消耗心智单元的舰娘数"
            "（认知觉醒四阶已不需材料，不计入）\n"
            "括弧：还需要练级的舰娘数"
            "（认知觉醒一阶经验已满足 120，不计入）"
        )

        tp_stats_layout.addWidget(self._totalTpCard)
        tp_stats_layout.addWidget(self._unlockedTpCard)
        tp_stats_layout.addWidget(self._tpRateCard)
        tp_stats_layout.addWidget(self._remainingLevelingCard)

        tp_layout.addLayout(tp_stats_layout)
        layout.addWidget(tp_group)

        requirement_group = QGroupBox("需求数据看板")
        requirement_layout = QVBoxLayout(requirement_group)

        requirement_stats_layout = QHBoxLayout()
        requirement_stats_layout.setSpacing(15)

        self._universalBulinCard = StatCard("泛用型布里", "0")
        self._trialBulinCard = StatCard("试作型布里MKII", "0")
        self._specializedBulinCard = StatCard("特装型布里MKIII", "0")
        self._mentalUnitCard = StatCard("心智单元", "-")  # 精确数值：固定千分符
        self._mentalUnitIICard = StatCard("心智单元Ⅱ", "-")  # 精确数值：固定千分符
        self._coinCard = StatCard("物资", "-")  # 精确数值：固定千分符

        requirement_stats_layout.addWidget(self._universalBulinCard)
        requirement_stats_layout.addWidget(self._trialBulinCard)
        requirement_stats_layout.addWidget(self._specializedBulinCard)
        requirement_stats_layout.addWidget(self._coinCard)
        requirement_stats_layout.addWidget(self._mentalUnitCard)
        requirement_stats_layout.addWidget(self._mentalUnitIICard)

        requirement_layout.addLayout(requirement_stats_layout)
        layout.addWidget(requirement_group)

        button_layout = QHBoxLayout()
        self._phaseIICheckBox = QCheckBox("认知觉醒II")
        self._phaseIICheckBox.setToolTip("勾选后计算至认知觉醒II阶段所需材料总量")
        self._mentalCalcBtn = QPushButton("心智计算")
        self._mentalCalcBtn.setMinimumWidth(100)
        self._mentalCalcBtn.setMinimumHeight(35)
        button_layout.addWidget(self._phaseIICheckBox)
        button_layout.addWidget(self._mentalCalcBtn)
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
        self._mentalCalcBtn.clicked.connect(self._onMentalCalcClicked)
        self._commanderLevelCard.clicked.connect(self._onCommanderLevelClicked)

    def _onRefreshClicked(self) -> None:
        """刷新按钮点击事件处理。"""
        self.refreshData()
        self.dataRefreshed.emit()

    def _onCommanderLevelClicked(self) -> None:
        """
        指挥官等级卡片点击事件处理：打开「指级经验」独立窗口。

        窗口非模态，打开期间仍可操作主界面；窗口内的增删改会即时刷新本卡片。
        """
        if self._commanderDialog is None:
            self._commanderDialog = CommanderExpDialog(self._commander_service, self)
            self._commanderDialog.dataRefreshed.connect(self._onCommanderDialogDataChanged)
            self._commanderDialog.snapshotResult.connect(self.commanderResult.emit)
            self._commanderDialog.finished.connect(self._onCommanderDialogFinished)

        self._commanderDialog.show()
        self._commanderDialog.raise_()
        self._commanderDialog.activateWindow()

    def _onCommanderDialogDataChanged(self) -> None:
        """指级经验窗口内数据变化：刷新卡片并通知外部。"""
        self.updateCommanderStats()
        self.dataRefreshed.emit()

    def _onCommanderDialogFinished(self, _result: int) -> None:
        """
        指级经验窗口关闭后刷新卡片。

        Args:
            _result: 对话框返回码（未使用）。
        """
        self.updateCommanderStats()

    def _onMentalCalcClicked(self) -> None:
        """
        心智计算按钮点击事件处理。

        根据复选框状态计算心智材料需求：
        - 未选中：计算至认知觉醒五阶(phase 4)
        - 选中：计算至认知觉醒II(phase 5)
        """
        try:
            include_phase_ii = self._phaseIICheckBox.isChecked()
            result = self._mental_calculation_service.calculate(include_phase_ii)

            if result.success:
                self._updateMentalCards(result)
            else:
                self._mentalUnitCard.setValue("错误")
                self._mentalUnitIICard.setValue("错误")
                self._coinCard.setValue("错误")
                QMessageBox.warning(self, "计算错误", result.message)
        except Exception as e:
            self._mentalUnitCard.setValue("错误")
            self._mentalUnitIICard.setValue("错误")
            self._coinCard.setValue("错误")
            QMessageBox.critical(self, "错误", f"心智计算异常: {e}")

    def _updateMentalCards(self, result: MentalCalculationResult) -> None:
        """
        根据计算结果更新心智相关标签卡。

        材料数量属于精确数值，统一固定加千分符（与状态栏消息口径一致），
        不做 K/M/B/T 缩写换算。

        Args:
            result: 心智计算结果对象。
        """
        self._mentalUnitCard.setValue(formatExact(result.expend_limit))
        self._mentalUnitIICard.setValue(formatExact(result.expend_limit2))
        self._coinCard.setValue(formatExact(result.expend_gc))

    def refreshData(self) -> None:
        """刷新统计数据。"""
        try:
            duty_days_text = self._user_service.getDutyDaysText()
            self._dutyDaysCard.setValue(duty_days_text)

            self.updateCommanderStats()
            self.updateResourceStats()

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

            oath_stats = stats.get("oath", {})
            oath_rate_text = f"{oath_stats.get('oath_rate', 0):.1f}%"
            self._oathRateCard.setValue(oath_rate_text)

            tp_stats = stats.get("tp", {})
            total_tp = tp_stats.get("total_tp", 0)
            unlocked_tp = tp_stats.get("unlocked_tp", 0)
            completion_rate = tp_stats.get("completion_rate", 0)

            self._totalTpCard.setValue(formatExact(total_tp))
            self._unlockedTpCard.setValue(formatExact(unlocked_tp))
            self._tpRateCard.setValue(f"{completion_rate:.1f}%")

            bulin_stats = stats.get("bulin", {})
            self._universalBulinCard.setValue(str(bulin_stats.get("universal_bulin", 0)))
            self._trialBulinCard.setValue(str(bulin_stats.get("trial_bulin_mkii", 0)))
            self._specializedBulinCard.setValue(str(bulin_stats.get("specialized_bulin_mkiii", 0)))

            material_pending = stats.get("material_pending", 0)
            leveling_required = stats.get("leveling_required", 0)
            self._remainingLevelingCard.setValue(f"{material_pending}（{leveling_required}）")

        except DatabaseError as e:
            self._showError(f"数据库错误: {e}")
        except Exception as e:
            self._showError(f"刷新数据失败: {e}")

    def _showError(self, message: str) -> None:
        """显示错误信息。"""
        self._commanderLevelCard.setValue("错误")
        self._expEfficiencyCard.setValue("错误")
        self._cubeCard.setValue("错误")
        self._redGemCard.setValue("错误")
        self._totalCard.setValue("错误")
        self._unlockedCard.setValue("错误")
        self._lockedCard.setValue("错误")
        self._rateCard.setValue("错误")
        self._oathRateCard.setValue("错误")
        self._totalTpCard.setValue("错误")
        self._unlockedTpCard.setValue("错误")
        self._tpRateCard.setValue("错误")
        self._remainingLevelingCard.setValue("错误")
        self._universalBulinCard.setValue("错误")
        self._trialBulinCard.setValue("错误")
        self._specializedBulinCard.setValue("错误")
        self._mentalUnitCard.setValue("错误")
        self._mentalUnitIICard.setValue("错误")
        self._coinCard.setValue("错误")

    def updateCommanderStats(self) -> None:
        """
        更新指挥官等级 / 指级效率卡片与悬停提示。

        精确数值口径：``等级（当前经验/需求经验）`` 与 ``日均经验/天``，固定加千分符；
        无快照时服务层返回 ``-``，不抛异常。
        """
        self._commanderLevelCard.setValue(self._commander_service.getCommanderLevelCardText())
        self._commanderLevelCard.setToolTip(self._commander_service.getCommanderLevelCardTooltip())
        self._expEfficiencyCard.setValue(self._commander_service.getExpEfficiencyText())
        self._expEfficiencyCard.setToolTip(self._commander_service.getExpEfficiencyTooltip())

    def updateResourceStats(self) -> None:
        """
        更新魔方 / 红尖尖卡片与悬停提示。

        大概数值口径：用 K/M/B/T 缩写并保留一位小数；悬停显示精确数值与数据截止日期。
        每张卡只扫一遍结余链（文本、提示与日环比角标共用同一次计算）。
        """
        for card, resource_type in (
            (self._cubeCard, RESOURCE_TYPE_CUBE),
            (self._redGemCard, RESOURCE_TYPE_RED_GEM),
        ):
            view = self._resource_service.getCardView(resource_type)
            card.setValue(view.text)
            card.setToolTip(view.tooltip)
            if view.delta is None:
                card.clearBadge()
            else:
                card.setBadge(view.delta.display_text, view.delta.tone)

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

        self._totalTpCard.setValue(formatExact(total_tp))
        self._unlockedTpCard.setValue(formatExact(unlocked_tp))
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
