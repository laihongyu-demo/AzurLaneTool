"""
建造任务确认对话框模块。

日常任务「建造舰船 1 次」的完成动作不止一笔收入：还要按所选卡池记一笔建造支出，
使用建造券时不扣魔方但要把这次建造计入进行中活动的券抽次数。

本对话框只负责收集「卡池 + 是否用券」并把将要写入的明细预览给用户；真正的写入与
活动联动由 :class:`services.cube_task_service.CubeTaskService` 在同一事务内完成。
"""

from datetime import datetime
from typing import Dict

from PyQt5.QtWidgets import (
    QButtonGroup, QCheckBox, QDialog, QDialogButtonBox, QGroupBox, QLabel,
    QRadioButton, QVBoxLayout, QWidget,
)

from models.cube_task_model import CubeTaskModel
from services.cube_task_service import (
    BUILD_POOL_EVENT, DEFAULT_BUILD_POOL_KEY, BuildPool, BuildTaskPlan,
)
from utils.constants import RECORD_TIME_FORMAT, RESOURCE_DISPLAY_NAMES, RESOURCE_TYPE_CUBE


class BuildTaskDialog(QDialog):
    """
    建造任务完成确认框。

    默认选中轻型建造、不使用建造券；勾选建造券后卡池置灰（券不消耗魔方，
    这次建造按活动券抽计数）。
    """

    def __init__(
        self,
        plan: BuildTaskPlan,
        task: CubeTaskModel,
        moment: datetime,
        parent: QWidget = None,
    ):
        """
        初始化对话框。

        Args:
            plan: 卡池与进行中活动信息（由服务计算，活动池单耗已按活动替换）。
            task: 建造任务定义（用于展示奖励与名称）。
            moment: 本次记账时刻（补录时为所选日期 + 当前时分秒）。
            parent: 父控件。
        """
        super().__init__(parent)
        self._plan = plan
        self._task = task
        self._moment = moment
        self._radios: Dict[str, QRadioButton] = {}
        self._initUi()
        self._syncTicketState()

    # ------------------------------------------------------------------ UI

    def _initUi(self) -> None:
        """初始化用户界面。"""
        self.setWindowTitle("建造任务确认")
        self.setMinimumWidth(460)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(15, 15, 15, 15)
        layout.setSpacing(10)

        title = QLabel(f"完成「{self._task.name}」", self)
        title.setStyleSheet("font-weight: bold;")
        layout.addWidget(title)

        meta = QLabel(
            f"记账时刻 {self._moment.strftime(RECORD_TIME_FORMAT)}"
            f"｜任务奖励：{RESOURCE_DISPLAY_NAMES.get(RESOURCE_TYPE_CUBE, '魔方')}"
            f" +{self._task.reward}",
            self,
        )
        meta.setStyleSheet("color: #666; font-size: 12px;")
        layout.addWidget(meta)

        pool_group = QGroupBox("卡池", self)
        pool_layout = QVBoxLayout(pool_group)
        pool_layout.setContentsMargins(10, 14, 10, 10)
        pool_layout.setSpacing(6)

        self._radioGroup = QButtonGroup(self)
        for pool in self._plan.pools:
            radio = QRadioButton(f"{pool.label}（-{pool.cost} 魔方）", pool_group)
            radio.setToolTip(self._buildPoolTip(pool))
            self._radioGroup.addButton(radio)
            pool_layout.addWidget(radio)
            self._radios[pool.key] = radio

        default_radio = self._radios.get(DEFAULT_BUILD_POOL_KEY)
        if default_radio is not None:
            default_radio.setChecked(True)
        self._radioGroup.buttonToggled.connect(lambda *_: self._refreshPreview())
        layout.addWidget(pool_group)

        self._ticketCheck = QCheckBox("使用建造券（不扣魔方）", self)
        self._ticketCheck.setToolTip("券抽不消耗魔方；有进行中活动时计入该活动的券抽次数")
        self._ticketCheck.toggled.connect(self._onTicketToggled)
        layout.addWidget(self._ticketCheck)

        self._previewLabel = QLabel("", self)
        self._previewLabel.setWordWrap(True)
        self._previewLabel.setStyleSheet("color: #333; font-size: 12px;")
        layout.addWidget(self._previewLabel)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel, self)
        buttons.button(QDialogButtonBox.Ok).setText("确认记两笔")
        buttons.button(QDialogButtonBox.Cancel).setText("取消")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _buildPoolTip(self, pool: BuildPool) -> str:
        """
        生成卡池单选项的提示。

        Args:
            pool: 卡池。

        Returns:
            提示文本。
        """
        if pool.key == BUILD_POOL_EVENT and self._plan.ongoing_event is None:
            return "当前没有进行中活动：按默认单耗记支出，不关联活动"
        if pool.key == BUILD_POOL_EVENT:
            return f"关联进行中活动「{self._plan.ongoing_event.displayName}」并按单耗计入建造次数"
        return f"记一笔「支出 · {pool.category} {pool.cost}」"

    # --------------------------------------------------------------- 交互

    def _onTicketToggled(self, _checked: bool) -> None:
        """建造券勾选变化：置灰卡池并刷新预览。"""
        self._syncTicketState()

    def _syncTicketState(self) -> None:
        """按建造券状态启用 / 禁用卡池并刷新预览文案。"""
        use_ticket = self._ticketCheck.isChecked()
        for radio in self._radios.values():
            radio.setEnabled(not use_ticket)
        self._refreshPreview()

    def _refreshPreview(self) -> None:
        """刷新「将写入」预览。"""
        self._previewLabel.setText(self._buildPreviewText())

    def _buildPreviewText(self) -> str:
        """
        生成将要写入的明细说明。

        Returns:
            多行说明文本。
        """
        task = self._task
        event = self._plan.ongoing_event
        if self._ticketCheck.isChecked():
            lines = [f"将只写入 1 笔：收入 · {task.category} +{task.reward}，不扣魔方。"]
            if event is not None:
                lines.append(f"本次计入活动「{event.displayName}」的券抽次数（+1）。")
            else:
                lines.append("当前没有进行中活动，不产生活动计数。")
            return "\n".join(lines)

        pool = self.selectedPool()
        cost = pool.cost if pool is not None else 0
        category = pool.category if pool is not None else ""
        lines = [
            f"将写入 2 笔：支出 · {category} {cost}；收入 · {task.category} +{task.reward}。"
        ]
        if pool is not None and pool.key == BUILD_POOL_EVENT:
            if event is not None:
                lines.append(
                    f"关联活动「{event.displayName}」，按单耗 {cost} 魔方计入建造次数。"
                )
            else:
                lines.append(f"当前没有进行中活动：按 {cost} 魔方记支出，不关联活动。")
        return "\n".join(lines)

    # --------------------------------------------------------------- 结果

    def selectedPoolKey(self) -> str:
        """
        当前选中的卡池键。

        Returns:
            卡池键；没有任何选中时返回默认卡池。
        """
        for key, radio in self._radios.items():
            if radio.isChecked():
                return key
        return DEFAULT_BUILD_POOL_KEY

    def selectedPool(self):
        """
        当前选中的卡池对象。

        Returns:
            卡池；没有任何选中时返回 None。
        """
        key = self.selectedPoolKey()
        for pool in self._plan.pools:
            if pool.key == key:
                return pool
        return None

    def useTicket(self) -> bool:
        """
        是否使用建造券。

        Returns:
            勾选时返回 True。
        """
        return self._ticketCheck.isChecked()
