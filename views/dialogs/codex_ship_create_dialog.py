"""
舰娘新增对话框模块。

定义新增舰娘的录入窗口：基础信息、科技点（固定三档）、科技属性（原始数据文本），
支持按分组自动生成图鉴ID、SQL预览，并在确认后通过服务层以单事务写入三张表。
"""

from typing import Dict, List, Optional

from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QLineEdit, QPushButton,
    QComboBox, QSpinBox, QTimeEdit, QGroupBox, QPlainTextEdit,
    QMessageBox, QTextEdit
)
from PyQt5.QtCore import QDate, QDateTime, QTime, pyqtSignal

from services.codex_ship_create_service import (
    CodexShipCreateService, ShipCreateDraft, ShipCreateResult
)
from utils import codex_options as options
from utils.exceptions import DatabaseError, ValidationError
from views.widgets.calendar_only_date_edit import CalendarOnlyDateEdit


class CodexShipCreateDialog(QDialog):
    """
    舰娘新增对话框控件。

    提供新增舰娘的界面交互，包含基础信息、科技点、科技属性三个区域。
    """

    shipCreated = pyqtSignal(object)

    def __init__(
        self,
        create_service: Optional[CodexShipCreateService] = None,
        parent: Optional[QDialog] = None
    ):
        """
        初始化新增对话框。

        Args:
            create_service: 舰娘新增服务实例。
            parent: 父控件。
        """
        super().__init__(parent)
        self._create_service = create_service or CodexShipCreateService()
        self._tpEdits: Dict[str, QLineEdit] = {}
        self._buffEdits: Dict[str, QPlainTextEdit] = {}
        self._initUi()
        self._connectSignals()
        self._applyGroupDefaults()

    def _initUi(self) -> None:
        """初始化用户界面。"""
        self.setWindowTitle("新增舰娘")
        self.setMinimumSize(820, 640)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(15, 15, 15, 15)
        layout.setSpacing(12)

        layout.addWidget(self._createBasicGroup())
        layout.addWidget(self._createTpGroup())
        layout.addWidget(self._createBuffGroup())
        layout.addStretch()
        layout.addLayout(self._createButtonLayout())

    # ---------- 基础信息 ----------

    def _createBasicGroup(self) -> QGroupBox:
        """创建基础信息区域。"""
        group = QGroupBox("基础信息")
        grid = QGridLayout(group)
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(8)

        self._groupCombo = QComboBox()
        self._groupCombo.addItems(options.SHIP_GROUPS)
        self._groupCombo.setMinimumWidth(180)

        self._idEdit = QLineEdit()
        self._idEdit.setMinimumWidth(150)
        self._regenerateBtn = QPushButton("重新生成")
        self._regenerateBtn.setMinimumWidth(90)

        id_layout = QHBoxLayout()
        id_layout.setContentsMargins(0, 0, 0, 0)
        id_layout.addWidget(self._idEdit)
        id_layout.addWidget(self._regenerateBtn)

        self._nameEdit = QLineEdit()
        self._nameEdit.setPlaceholderText("请输入舰娘名称")

        self._typCombo = QComboBox()
        self._typCombo.setEditable(True)
        self._typCombo.addItems(options.SHIP_TYPS)

        self._rarityCombo = QComboBox()
        self._rarityCombo.addItems(options.SHIP_RARITIES)

        self._starSpin = QSpinBox()
        self._starSpin.setRange(0, 6)

        self._campCombo = QComboBox()
        self._campCombo.setEditable(True)
        self._campCombo.addItems(options.SHIP_CAMPS)

        self._aidDateEdit = CalendarOnlyDateEdit()
        self._aidDateEdit.setDisplayFormat(options.SHIP_AID_FORMAT)
        self._aidDateEdit.setDate(QDate.currentDate())
        self._aidDateEdit.setMinimumWidth(120)

        self._levelCombo = QComboBox()
        self._levelCombo.setEditable(True)
        self._levelCombo.addItems(options.SHIP_LEVELS)

        self._likingCombo = QComboBox()
        self._likingCombo.setEditable(True)
        self._likingCombo.addItems(options.SHIP_LIKINGS)

        self._oathCombo = QComboBox()
        self._oathCombo.setEditable(True)
        self._oathCombo.addItems(options.OATH_STATUSES)

        self._editDateEdit = CalendarOnlyDateEdit()
        self._editDateEdit.setDisplayFormat(options.DATE_EDIT_DATE_FORMAT)
        self._editDateEdit.setDate(QDate.currentDate())
        self._editDateEdit.setMinimumWidth(120)

        self._editTimeEdit = QTimeEdit()
        self._editTimeEdit.setDisplayFormat(options.DATE_EDIT_TIME_FORMAT)
        self._editTimeEdit.setTime(QTime.currentTime())
        self._editTimeEdit.setMinimumWidth(88)
        self._editTimeEdit.setToolTip("可精确到秒：直接输入或使用上下箭头调整")

        self._nowBtn = QPushButton("现在")
        self._nowBtn.setMinimumWidth(56)
        self._nowBtn.setToolTip("将编辑日期与时间设为当前时间")

        edit_date_layout = QHBoxLayout()
        edit_date_layout.setContentsMargins(0, 0, 0, 0)
        edit_date_layout.setSpacing(6)
        edit_date_layout.addWidget(self._editDateEdit)
        edit_date_layout.addWidget(self._editTimeEdit)
        edit_date_layout.addWidget(self._nowBtn)

        grid.addWidget(QLabel("舰娘分组:"), 0, 0)
        grid.addWidget(self._groupCombo, 0, 1)
        grid.addWidget(QLabel("图鉴ID:"), 0, 2)
        grid.addLayout(id_layout, 0, 3)

        grid.addWidget(QLabel("舰娘名称:"), 1, 0)
        grid.addWidget(self._nameEdit, 1, 1)
        grid.addWidget(QLabel("舰船类型:"), 1, 2)
        grid.addWidget(self._typCombo, 1, 3)

        grid.addWidget(QLabel("稀有度:"), 2, 0)
        grid.addWidget(self._rarityCombo, 2, 1)
        grid.addWidget(QLabel("星级:"), 2, 2)
        grid.addWidget(self._starSpin, 2, 3)

        grid.addWidget(QLabel("阵营:"), 3, 0)
        grid.addWidget(self._campCombo, 3, 1)
        grid.addWidget(QLabel("实装日期:"), 3, 2)
        grid.addWidget(self._aidDateEdit, 3, 3)

        grid.addWidget(QLabel("等级:"), 4, 0)
        grid.addWidget(self._levelCombo, 4, 1)
        grid.addWidget(QLabel("好感度:"), 4, 2)
        grid.addWidget(self._likingCombo, 4, 3)

        grid.addWidget(QLabel("誓约状态:"), 5, 0)
        grid.addWidget(self._oathCombo, 5, 1)
        grid.addWidget(QLabel("编辑日期:"), 5, 2)
        grid.addLayout(edit_date_layout, 5, 3)

        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(3, 1)

        return group

    # ---------- 科技点 ----------

    def _createTpGroup(self) -> QGroupBox:
        """创建科技点区域（条件固定三档，只填数值）。"""
        group = QGroupBox("科技点 codex_tp")
        self._tpGroup = group
        grid = QGridLayout(group)
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(8)

        for column, unlock_cond in enumerate(options.TP_CONDS):
            edit = QLineEdit()
            edit.setPlaceholderText("数值")
            edit.setMinimumWidth(120)
            self._tpEdits[unlock_cond] = edit

            grid.addWidget(QLabel(f"{unlock_cond}:"), 0, column * 2)
            grid.addWidget(edit, 0, column * 2 + 1)
            grid.setColumnStretch(column * 2 + 1, 1)

        hint = QLabel("三项需同时填写；留空表示该舰娘没有科技点记录")
        hint.setStyleSheet("color: gray;")
        grid.addWidget(hint, 1, 0, 1, len(options.TP_CONDS) * 2)

        return group

    # ---------- 科技属性 ----------

    def _createBuffGroup(self) -> QGroupBox:
        """创建科技属性区域（原始数据文本录入）。"""
        group = QGroupBox("科技属性 codex_buff")
        self._buffGroup = group
        grid = QGridLayout(group)
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(8)

        for row, buff_cond in enumerate(options.BUFF_CONDS):
            edit = QPlainTextEdit()
            edit.setPlaceholderText(f"{options.BUFF_TEXT_EXAMPLE}    （每行一条，行内多个增益类型用 / 分隔）")
            edit.setMinimumHeight(88)
            edit.setTabChangesFocus(True)
            self._buffEdits[buff_cond] = edit

            grid.addWidget(QLabel(f"{buff_cond}:"), row, 0)
            grid.addWidget(edit, row, 1)

        grid.setColumnStretch(1, 1)

        self._buffHintLabel = QLabel("")
        grid.addWidget(self._buffHintLabel, len(options.BUFF_CONDS), 1)

        return group

    # ---------- 底部按钮 ----------

    def _createButtonLayout(self) -> QHBoxLayout:
        """创建底部按钮区域。"""
        button_layout = QHBoxLayout()

        self._previewBtn = QPushButton("预览SQL")
        self._previewBtn.setMinimumWidth(100)
        self._previewBtn.setMinimumHeight(35)
        button_layout.addWidget(self._previewBtn)

        button_layout.addStretch()

        self._confirmBtn = QPushButton("确认新增")
        self._confirmBtn.setMinimumWidth(100)
        self._confirmBtn.setMinimumHeight(35)
        button_layout.addWidget(self._confirmBtn)

        self._cancelBtn = QPushButton("取消")
        self._cancelBtn.setMinimumWidth(100)
        self._cancelBtn.setMinimumHeight(35)
        button_layout.addWidget(self._cancelBtn)

        return button_layout

    # ---------- 信号 ----------

    def _connectSignals(self) -> None:
        """连接信号与槽。"""
        self._groupCombo.currentIndexChanged.connect(self._onGroupChanged)
        self._rarityCombo.currentIndexChanged.connect(self._onRarityChanged)
        self._regenerateBtn.clicked.connect(self._onRegenerateIdClicked)
        self._nowBtn.clicked.connect(self._onNowClicked)
        self._previewBtn.clicked.connect(self._onPreviewClicked)
        self._confirmBtn.clicked.connect(self._onConfirmClicked)
        self._cancelBtn.clicked.connect(self.reject)

        for edit in self._buffEdits.values():
            edit.textChanged.connect(self._updateBuffHint)

        for edit in self._tpEdits.values():
            edit.textChanged.connect(self._updateBuffHint)

    def _onGroupChanged(self) -> None:
        """舰娘分组切换事件处理。"""
        self._applyGroupDefaults()

    def _onRarityChanged(self) -> None:
        """稀有度切换事件处理，仅在当前星级为默认值时同步更新。"""
        ship_group = self._groupCombo.currentText()
        default_values = set(options.DEFAULT_STAR_BY_RARITY.values()) | {options.DEFAULT_STAR_FOR_REFIT}
        if self._starSpin.value() not in default_values:
            return

        self._starSpin.setValue(
            self._create_service.getDefaultStar(ship_group, self._rarityCombo.currentText())
        )

    def _onRegenerateIdClicked(self) -> None:
        """重新生成图鉴ID事件处理。"""
        self._refreshCodexId()

    def _onNowClicked(self) -> None:
        """「现在」按钮事件处理：将编辑日期与时间设为当前时间。"""
        now = QDateTime.currentDateTime()
        self._editDateEdit.setDate(now.date())
        self._editTimeEdit.setTime(now.time())

    def _collectEditDate(self) -> str:
        """组合编辑日期与时间为 yyyy-MM-dd HH:mm:ss 文本。"""
        return (
            f"{self._editDateEdit.date().toString(options.DATE_EDIT_DATE_FORMAT)} "
            f"{self._editTimeEdit.time().toString(options.DATE_EDIT_TIME_FORMAT)}"
        )

    def _applyGroupDefaults(self) -> None:
        """应用分组默认形态、默认ID与明细区可用状态。"""
        ship_group = self._groupCombo.currentText()
        defaults = self._create_service.getGroupFieldDefaults(ship_group)

        self._levelCombo.setCurrentText(defaults["ship_level"])
        self._likingCombo.setCurrentText(defaults["ship_liking"])
        self._oathCombo.setCurrentText(defaults["oath_status"])

        self._starSpin.setValue(
            self._create_service.getDefaultStar(ship_group, self._rarityCombo.currentText())
        )

        self._refreshCodexId()
        self._applyTpBuffAvailability(ship_group)

    def _refreshCodexId(self) -> None:
        """按当前分组刷新图鉴ID。"""
        try:
            self._idEdit.setText(self._create_service.getNextCodexId(self._groupCombo.currentText()))
        except DatabaseError as e:
            QMessageBox.warning(self, "数据库错误", f"生成图鉴ID失败: {e}")

    def _applyTpBuffAvailability(self, ship_group: str) -> None:
        """根据分组启用或禁用科技点、科技属性区域。"""
        no_tp_buff = self._create_service.isNoTpBuffGroup(ship_group)

        self._tpGroup.setEnabled(not no_tp_buff)
        self._buffGroup.setEnabled(not no_tp_buff)

        if no_tp_buff:
            for edit in self._tpEdits.values():
                edit.clear()
            for edit in self._buffEdits.values():
                edit.clear()
            self._tpGroup.setTitle(f"科技点 codex_tp（{ship_group}类型无科技点记录）")
            self._buffGroup.setTitle(f"科技属性 codex_buff（{ship_group}类型无科技属性记录）")
        else:
            self._tpGroup.setTitle("科技点 codex_tp")
            self._buffGroup.setTitle("科技属性 codex_buff")

        self._updateBuffHint()

    def _updateBuffHint(self) -> None:
        """实时提示科技属性将写入的记录数。"""
        buff_text = self._collectBuffText()

        if not self._buffGroup.isEnabled():
            self._buffHintLabel.setText("该分组不写入科技点与科技属性记录")
            self._buffHintLabel.setStyleSheet("color: gray;")
            return

        try:
            rows = self._create_service.parseBuffRows(buff_text)
        except ValidationError as e:
            self._buffHintLabel.setText(str(e))
            self._buffHintLabel.setStyleSheet("color: #c0392b;")
            return

        tp_count = len(self._collectTpRows())
        if rows:
            self._buffHintLabel.setText(
                f"将写入 codex_tp {tp_count} 条、codex_buff {len(rows)} 条"
            )
        else:
            self._buffHintLabel.setText(
                f"将写入 codex_tp {tp_count} 条、codex_buff 0 条（请按原始数据录入科技属性）"
            )
        self._buffHintLabel.setStyleSheet("color: gray;")

    # ---------- 数据采集 ----------

    def _collectTpValues(self) -> Dict[str, str]:
        """采集科技点输入值。"""
        return {cond: edit.text().strip() for cond, edit in self._tpEdits.items()}

    def _collectBuffText(self) -> Dict[str, str]:
        """采集科技属性原始数据文本。"""
        return {cond: edit.toPlainText() for cond, edit in self._buffEdits.items()}

    def _collectTpRows(self) -> List[Dict]:
        """按当前输入估算科技点行数（仅用于界面提示）。"""
        return [
            {"unlock_cond": cond, "tp_value": value}
            for cond, value in self._collectTpValues().items() if value
        ]

    def _buildDraft(self) -> ShipCreateDraft:
        """根据界面内容构建新增草稿。"""
        return ShipCreateDraft(
            codex_id=self._idEdit.text(),
            ship_name=self._nameEdit.text(),
            ship_group=self._groupCombo.currentText(),
            ship_typ=self._typCombo.currentText().strip(),
            ship_rarity=self._rarityCombo.currentText(),
            ship_star=self._starSpin.value(),
            ship_camp=self._campCombo.currentText().strip(),
            ship_aid=self._aidDateEdit.date().toString(options.SHIP_AID_FORMAT),
            ship_level=self._levelCombo.currentText().strip(),
            ship_liking=self._likingCombo.currentText().strip(),
            oath_status=self._oathCombo.currentText().strip(),
            date_edit=self._collectEditDate(),
            tp_values=self._collectTpValues(),
            buff_text=self._collectBuffText()
        )

    # ---------- 预览与提交 ----------

    def _onPreviewClicked(self) -> None:
        """预览SQL事件处理。"""
        draft = self._buildDraft()

        try:
            self._create_service.validateDraft(draft)
            sql = self._create_service.buildPreviewSql(draft)
        except ValidationError as e:
            QMessageBox.warning(self, "校验失败", str(e))
            return
        except DatabaseError as e:
            QMessageBox.critical(self, "数据库错误", str(e))
            return

        self._showPreviewDialog(sql)

    def _showPreviewDialog(self, sql: str) -> None:
        """显示SQL预览窗口。"""
        dialog = QDialog(self)
        dialog.setWindowTitle("SQL预览")
        dialog.setMinimumSize(760, 560)

        layout = QVBoxLayout(dialog)
        text_edit = QTextEdit()
        text_edit.setReadOnly(True)
        text_edit.setPlainText(sql)
        layout.addWidget(text_edit)

        button_layout = QHBoxLayout()
        button_layout.addStretch()
        close_btn = QPushButton("关闭")
        close_btn.setMinimumWidth(100)
        close_btn.setMinimumHeight(35)
        close_btn.clicked.connect(dialog.accept)
        button_layout.addWidget(close_btn)
        layout.addLayout(button_layout)

        dialog.exec_()

    def _onConfirmClicked(self) -> None:
        """确认新增事件处理。"""
        draft = self._buildDraft()

        try:
            normalized = self._create_service.normalizeDraft(draft)
        except ValidationError as e:
            QMessageBox.warning(self, "校验失败", str(e))
            return
        except DatabaseError as e:
            QMessageBox.critical(self, "数据库错误", str(e))
            return

        if not self._confirmDuplicate(draft):
            return

        if not self._confirmSummary(draft, normalized):
            return

        try:
            result = self._create_service.createShip(draft)
        except ValidationError as e:
            QMessageBox.warning(self, "校验失败", str(e))
            return
        except DatabaseError as e:
            QMessageBox.critical(self, "数据库错误", f"新增失败，事务已回滚: {e}")
            return
        except Exception as e:
            QMessageBox.critical(self, "错误", f"新增操作发生异常: {e}")
            return

        self.shipCreated.emit(result)
        self._showSuccess(result)
        self.accept()

    def _confirmDuplicate(self, draft: ShipCreateDraft) -> bool:
        """同分组同名舰娘二次确认。"""
        try:
            duplicates = self._create_service.findDuplicateShips(draft.ship_name, draft.ship_group)
        except DatabaseError as e:
            QMessageBox.critical(self, "数据库错误", str(e))
            return False

        if not duplicates:
            return True

        existing = "、".join(f"{ship.codex_id}" for ship in duplicates)
        reply = QMessageBox.question(
            self,
            "同名提示",
            f"分组 '{draft.ship_group}' 下已存在同名舰娘（图鉴ID: {existing}），仍要继续新增吗？",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )

        return reply == QMessageBox.Yes

    def _confirmSummary(self, draft: ShipCreateDraft, normalized: Dict) -> bool:
        """写入前的落库确认。"""
        summary = (
            f"即将写入数据库：\n\n"
            f"· codex_group：1 条\n"
            f"· codex_tp：{len(normalized['tp_rows'])} 条\n"
            f"· codex_buff：{len(normalized['buff_rows'])} 条\n\n"
            f"图鉴ID：{draft.codex_id}\n"
            f"舰娘名称：{draft.ship_name}\n"
            f"舰娘分组：{draft.ship_group}\n\n"
            f"新增后舰娘保持未解锁状态，请再走解锁流程。"
        )

        reply = QMessageBox.question(
            self,
            "确认新增",
            summary,
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )

        return reply == QMessageBox.Yes

    def _showSuccess(self, result: ShipCreateResult) -> None:
        """显示新增成功提示。"""
        QMessageBox.information(
            self,
            "新增成功",
            f"舰娘 '{result.ship_name}' 新增成功\n\n"
            f"图鉴ID：{result.codex_id}\n"
            f"科技点：{result.tp_count} 条\n"
            f"科技属性：{result.buff_count} 条"
        )
