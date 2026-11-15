"""
数据分析面板（#19）。

页签级结构（自上而下，整体放在滚动区）：

1. 整体趋势：日结余折线 + 月度收支柱；
2. 来源 / 去向占比：总计条形 + 月度堆叠；
3. 军事委托产出：月度产出 + 单笔分布；
4. 大建详情：毕业次数趋势 / 分布 / 类型对照 / 生存曲线 + 毕业预测。

matplotlib 在**首次激活页签时**才导入并建图：启动时只建控件骨架，
不影响 5 个既有页签的启动速度。数据变更由主窗口 ``refreshData()`` 置脏，
下次激活或当前可见时重建。
"""

import threading
from typing import Optional

from PyQt5.QtCore import QEvent, Qt, QTimer
from PyQt5.QtWidgets import (
    QApplication,
    QComboBox,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from models.analysis_model import BuildPoolAnalysis
from services.build_pool_analysis_service import BuildPoolAnalysisService
from services.resource_analysis_service import ResourceAnalysisService
from utils import time_source
from utils.constants import (
    ANALYSIS_RECENT_MONTHS,
    ANALYSIS_TOP_CATEGORY_COUNT,
    BUILD_SCOPES,
    BUILD_SCOPE_TITLES,
    EVENT_BUILD_COST_OPTIONS,
    EVENT_DEFAULT_BUILD_COST,
    RESOURCE_DIRECTION_EXPENSE,
    RESOURCE_DIRECTION_INCOME,
    RESOURCE_DIRECTION_NAMES,
    RESOURCE_DISPLAY_NAMES,
    RESOURCE_TYPE_CUBE,
    RESOURCE_TYPE_RED_GEM,
)
from utils.exceptions import DatabaseError
from utils.unit_formatter import formatExact

# 图表资源下拉的展示顺序：魔方在前
RESOURCE_ORDER = (RESOURCE_TYPE_CUBE, RESOURCE_TYPE_RED_GEM)

# 说明文字的统一样式（与资源统计页保持一致）
HINT_STYLE = "color: #888; font-size: 12px;"

# 月度视图切换：绝对值 / 占比
_MONTHLY_MODE_ABSOLUTE = "absolute"
_MONTHLY_MODE_RATIO = "ratio"


class AnalysisPanel(QWidget):
    """
    数据分析面板。

    所有数据都来自只读分析服务；本控件不写库、不拼 SQL。
    """

    def __init__(
        self,
        analysis_service: Optional[ResourceAnalysisService] = None,
        build_service: Optional[BuildPoolAnalysisService] = None,
        parent: Optional[QWidget] = None,
    ):
        """
        初始化数据分析面板。

        Args:
            analysis_service: 资源分析服务实例。
            build_service: 大建分析服务实例。
            parent: 父控件。
        """
        super().__init__(parent)
        self._analysis_service = analysis_service or ResourceAnalysisService()
        self._build_service = build_service or BuildPoolAnalysisService()

        self._built = False
        self._dirty = True
        self._today = time_source.today()
        self._build_analysis: Optional[BuildPoolAnalysis] = None

        # 延迟创建：matplotlib 的导入与画布构造都放到首次激活
        self._trendBalanceCanvas = None
        self._trendMonthlyCanvas = None
        self._categoryCanvas = None
        self._commissionCanvas = None
        self._buildTrendCanvas = None
        self._buildCompareCanvas = None

        # 预热：主窗口显示后后台导入 matplotlib，避免首次切页时现付 ~0.7 s
        self._warmup_thread = None
        self._warmup_done = threading.Event()

        self._content = None
        self._scroll = None
        self._renderScheduled = False
        self._initUi()
        self._connectSignals()

    # ------------------------------------------------------------------ UI

    def _initUi(self) -> None:
        """初始化界面骨架（不建图、不查库）。"""
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, 15, 0, 0)
        layout.setSpacing(12)

        layout.addWidget(self._buildTrendGroup())
        layout.addWidget(self._buildCategoryGroup())
        layout.addWidget(self._buildCommissionGroup())
        layout.addWidget(self._buildPoolGroup())
        layout.addStretch()

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        scroll.setWidget(content)
        outer.addWidget(scroll)
        self._content = content
        self._scroll = scroll

    def _buildTrendGroup(self) -> QGroupBox:
        """
        构建「整体趋势」分组。

        Returns:
            分组控件。
        """
        group = QGroupBox("整体趋势")
        layout = QVBoxLayout(group)
        layout.setContentsMargins(10, 14, 10, 10)
        layout.setSpacing(6)

        toolbar = QHBoxLayout()
        toolbar.addWidget(QLabel("资源："))
        self._trendResourceCombo = self._buildResourceCombo()
        toolbar.addWidget(self._trendResourceCombo)
        toolbar.addSpacing(12)
        toolbar.addWidget(QLabel("范围："))
        self._trendRangeCombo = QComboBox()
        self._trendRangeCombo.addItem("全部", None)
        self._trendRangeCombo.addItem(
            f"近 {ANALYSIS_RECENT_MONTHS} 个月", ANALYSIS_RECENT_MONTHS
        )
        toolbar.addWidget(self._trendRangeCombo)
        toolbar.addStretch()
        layout.addLayout(toolbar)

        self._trendSlot = QVBoxLayout()
        self._trendSlot.setSpacing(4)
        layout.addLayout(self._trendSlot)

        self._trendCards = self._buildInfoLabel("")
        layout.addWidget(self._trendCards)
        self._trendNote = self._buildHintLabel("")
        layout.addWidget(self._trendNote)
        return group

    def _buildCategoryGroup(self) -> QGroupBox:
        """
        构建「来源 / 去向占比」分组。

        Returns:
            分组控件。
        """
        group = QGroupBox("来源 / 去向占比")
        layout = QVBoxLayout(group)
        layout.setContentsMargins(10, 14, 10, 10)
        layout.setSpacing(6)

        toolbar = QHBoxLayout()
        toolbar.addWidget(QLabel("资源："))
        self._categoryResourceCombo = self._buildResourceCombo()
        toolbar.addWidget(self._categoryResourceCombo)
        toolbar.addSpacing(12)
        toolbar.addWidget(QLabel("方向："))
        self._categoryDirectionCombo = QComboBox()
        for direction in (RESOURCE_DIRECTION_INCOME, RESOURCE_DIRECTION_EXPENSE):
            self._categoryDirectionCombo.addItem(
                RESOURCE_DIRECTION_NAMES.get(direction, direction), direction
            )
        toolbar.addWidget(self._categoryDirectionCombo)
        toolbar.addSpacing(12)
        toolbar.addWidget(QLabel("月度视图："))
        self._categoryModeCombo = QComboBox()
        self._categoryModeCombo.addItem("绝对值", _MONTHLY_MODE_ABSOLUTE)
        self._categoryModeCombo.addItem("占比", _MONTHLY_MODE_RATIO)
        toolbar.addWidget(self._categoryModeCombo)
        toolbar.addStretch()
        layout.addLayout(toolbar)

        self._categorySlot = QVBoxLayout()
        layout.addLayout(self._categorySlot)

        self._categoryNote = self._buildHintLabel("")
        layout.addWidget(self._categoryNote)
        return group

    def _buildCommissionGroup(self) -> QGroupBox:
        """
        构建「军事委托产出」分组。

        Returns:
            分组控件。
        """
        group = QGroupBox("军事委托产出")
        layout = QVBoxLayout(group)
        layout.setContentsMargins(10, 14, 10, 10)
        layout.setSpacing(6)

        toolbar = QHBoxLayout()
        toolbar.addWidget(QLabel("资源："))
        self._commissionResourceCombo = self._buildResourceCombo()
        toolbar.addWidget(self._commissionResourceCombo)
        toolbar.addSpacing(12)
        toolbar.addWidget(QLabel("范围："))
        self._commissionRangeCombo = QComboBox()
        self._commissionRangeCombo.addItem("全部", None)
        self._commissionRangeCombo.addItem(f"近 {ANALYSIS_RECENT_MONTHS} 个月", ANALYSIS_RECENT_MONTHS)
        toolbar.addWidget(self._commissionRangeCombo)
        toolbar.addStretch()
        layout.addLayout(toolbar)

        self._commissionSlot = QVBoxLayout()
        layout.addLayout(self._commissionSlot)

        self._commissionCards = self._buildInfoLabel("")
        layout.addWidget(self._commissionCards)
        self._commissionNote = self._buildHintLabel("")
        layout.addWidget(self._commissionNote)
        return group

    def _buildPoolGroup(self) -> QGroupBox:
        """
        构建「大建详情」分组。

        Returns:
            分组控件。
        """
        group = QGroupBox("大建详情（仅毕业池）")
        layout = QVBoxLayout(group)
        layout.setContentsMargins(10, 14, 10, 10)
        layout.setSpacing(6)

        toolbar = QHBoxLayout()
        toolbar.addWidget(QLabel("样本范围："))
        self._buildScopeCombo = QComboBox()
        for scope in BUILD_SCOPES:
            self._buildScopeCombo.addItem(BUILD_SCOPE_TITLES.get(scope, scope), scope)
        toolbar.addWidget(self._buildScopeCombo)
        toolbar.addSpacing(12)
        toolbar.addWidget(QLabel("单耗："))
        self._buildCostCombo = QComboBox()
        for cost in EVENT_BUILD_COST_OPTIONS:
            self._buildCostCombo.addItem(f"{cost} 魔方/次", cost)
        self._buildCostCombo.setCurrentIndex(
            max(0, list(EVENT_BUILD_COST_OPTIONS).index(EVENT_DEFAULT_BUILD_COST))
        )
        toolbar.addWidget(self._buildCostCombo)
        toolbar.addSpacing(12)
        toolbar.addWidget(QLabel("已抽次数："))
        self._buildCountSpin = QSpinBox()
        self._buildCountSpin.setRange(0, 100000)
        self._buildCountSpin.setSingleStep(10)
        self._buildCountSpin.setValue(0)
        self._buildCountSpin.setFixedWidth(90)
        toolbar.addWidget(self._buildCountSpin)
        toolbar.addStretch()
        layout.addLayout(toolbar)

        self._buildSlot = QVBoxLayout()
        layout.addLayout(self._buildSlot)

        self._buildCards = self._buildInfoLabel("")
        layout.addWidget(self._buildCards)
        self._buildPrediction = self._buildInfoLabel("")
        layout.addWidget(self._buildPrediction)
        self._buildNote = self._buildHintLabel("")
        layout.addWidget(self._buildNote)
        return group

    def _buildResourceCombo(self) -> QComboBox:
        """
        构建资源下拉（默认魔方）。

        Returns:
            资源下拉控件。
        """
        combo = QComboBox()
        for resource_type in RESOURCE_ORDER:
            combo.addItem(RESOURCE_DISPLAY_NAMES.get(resource_type, resource_type), resource_type)
        return combo

    @staticmethod
    def _buildInfoLabel(text: str) -> QLabel:
        """
        构建数值说明标签。

        Args:
            text: 初始文本。

        Returns:
            标签控件。
        """
        label = QLabel(text)
        label.setWordWrap(True)
        label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        return label

    @staticmethod
    def _buildHintLabel(text: str) -> QLabel:
        """
        构建灰色提示标签。

        Args:
            text: 初始文本。

        Returns:
            标签控件。
        """
        label = QLabel(text)
        label.setWordWrap(True)
        label.setStyleSheet(HINT_STYLE)
        return label

    # ------------------------------------------------------------------ 信号

    def _connectSignals(self) -> None:
        """连接切换控件的信号。"""
        self._trendResourceCombo.currentIndexChanged.connect(self._onTrendChanged)
        self._trendRangeCombo.currentIndexChanged.connect(self._onTrendChanged)
        self._categoryResourceCombo.currentIndexChanged.connect(self._onCategoryChanged)
        self._categoryDirectionCombo.currentIndexChanged.connect(self._onCategoryChanged)
        self._categoryModeCombo.currentIndexChanged.connect(self._onCategoryChanged)
        self._commissionResourceCombo.currentIndexChanged.connect(self._onCommissionChanged)
        self._commissionRangeCombo.currentIndexChanged.connect(self._onCommissionChanged)
        self._buildScopeCombo.currentIndexChanged.connect(self._onBuildScopeChanged)
        self._buildCostCombo.currentIndexChanged.connect(self._updatePrediction)
        self._buildCountSpin.valueChanged.connect(self._updatePrediction)

    def _onTrendChanged(self) -> None:
        """趋势资源切换。"""
        if self._built:
            self._renderTrend()

    def _onCategoryChanged(self) -> None:
        """类目资源 / 方向 / 月度视图切换。"""
        if self._built:
            self._renderCategory()

    def _onCommissionChanged(self) -> None:
        """委托资源 / 范围切换。"""
        if self._built:
            self._renderCommission()

    def _onBuildScopeChanged(self) -> None:
        """大建样本范围切换：重算分析并刷新预测。"""
        if self._built:
            self._renderBuild()

    # ------------------------------------------------------------------ 生命周期

    def onActivated(self) -> None:
        """页签激活：首次构建图表；跨天或数据已脏时重建。"""
        today = time_source.today()
        if today != self._today:
            self._today = today
            self._dirty = True
        if not self._built or self._dirty:
            self._rebuildAll()

    def syncTimeContext(self) -> None:
        """只同步时间上下文（不查库），供全局刷新在重渲染前调用。"""
        today = time_source.today()
        if today != self._today:
            self._today = today
            self._dirty = True

    def refreshData(self) -> None:
        """数据变更通知：置脏；当前可见时立即重建。"""
        self._dirty = True
        if self._built and self.isVisible():
            self._rebuildAll()

    # ------------------------------------------------------------------ 构建与渲染

    def _ensureCanvases(self) -> bool:
        """
        首次建图：导入 matplotlib 并实例化 6 个画布。

        Returns:
            True 表示画布已就绪；False 表示缺少 matplotlib（降级为提示，不让整页崩掉）。
        """
        if self._trendBalanceCanvas is not None:
            return True

        # 预热还在跑就等它（最多 3 s）：避免主线程与后台线程同时初始化 matplotlib
        if self._warmup_thread is not None and not self._warmup_done.is_set():
            self._warmup_done.wait(timeout=3.0)

        # 局部导入：matplotlib 体积大、导入约 1 s，只有真正打开本页签时才付这个成本
        try:
            from utils.chart_style import applyChartStyle
            from views.widgets.charts.build_pool_canvas import (
                BuildPoolCompareCanvas,
                BuildPoolTrendCanvas,
            )
            from views.widgets.charts.category_canvas import CategoryCanvas
            from views.widgets.charts.commission_canvas import CommissionCanvas
            from views.widgets.charts.trend_canvas import (
                TrendBalanceCanvas,
                TrendMonthlyCanvas,
            )
        except ImportError as e:
            self._trendNote.setText(f"缺少图表依赖（matplotlib）：{e}")
            return False

        applyChartStyle()
        self._trendBalanceCanvas = TrendBalanceCanvas(self)
        self._trendMonthlyCanvas = TrendMonthlyCanvas(self)
        self._trendSlot.addWidget(self._trendBalanceCanvas)
        self._trendSlot.addWidget(self._trendMonthlyCanvas)

        self._categoryCanvas = CategoryCanvas(self)
        self._categorySlot.addWidget(self._categoryCanvas)

        self._commissionCanvas = CommissionCanvas(self)
        self._commissionSlot.addWidget(self._commissionCanvas)

        self._buildTrendCanvas = BuildPoolTrendCanvas(self)
        self._buildCompareCanvas = BuildPoolCompareCanvas(self)
        self._buildSlot.addWidget(self._buildTrendCanvas)
        self._buildSlot.addWidget(self._buildCompareCanvas)
        self._settleLayout()
        return True

    def _rebuildAll(self) -> None:
        """重建全部区块（可见时把绘制推迟到布局稳定后的下一帧）。"""
        if not self._ensureCanvases():
            self._built = True
            self._dirty = False
            return
        # 先置为已构建：各区块的渲染与预测文案会互相调用，避免被「未构建」守卫拦住
        self._built = True
        self._dirty = False
        if self.isVisible():
            # 画布是刚塞进布局的：同一帧里 Qt 还没重算内容高度，直接绘制会按被压扁的
            # 尺寸裁切（右侧色块）。让事件循环先完成布局，再绘制。
            self._scheduleRender()
        else:
            self._renderSections()

    def _scheduleRender(self) -> None:
        """把首帧绘制排到下一帧（合并重复请求）。"""
        if self._renderScheduled:
            return
        self._renderScheduled = True
        QTimer.singleShot(0, self._renderSections)

    def _renderSections(self) -> None:
        """渲染「整体趋势」并结算布局；其余区块再排一帧，先让首屏出内容。"""
        self._renderScheduled = False
        self._renderTrend()
        self._settleLayout()
        if self.isVisible():
            QTimer.singleShot(0, self._renderRestSections)
        else:
            self._renderRestSections()

    def _renderRestSections(self) -> None:
        """渲染剩余三个区块（占比 / 委托 / 大建）并再次结算布局。"""
        self._renderCategory()
        self._renderCommission()
        self._renderBuild()
        self._settleLayout()

    def _settleLayout(self) -> None:
        """
        立即结算滚动区布局。

        画布是在 ``__init__`` 之后才塞进分组的：``QScrollArea`` 在 ``widgetResizable``
        模式下只会按视口高度设置内容控件，不会主动把内容撑到布局的最小高度，首帧就会
        把分组压扁（图表被裁切、右侧出现色块），拉伸窗口才恢复。这里激活布局并把内容
        的最小高度固定为布局最小高度，让首帧就是最终尺寸。
        """
        if self._content is None or self._scroll is None:
            return
        layout = self._content.layout()
        if layout is None:
            return
        layout.activate()
        self._content.setMinimumHeight(layout.minimumSize().height())
        QApplication.sendPostedEvents(self._content, QEvent.LayoutRequest)
        QApplication.sendPostedEvents(self._scroll, QEvent.LayoutRequest)

    def resizeEvent(self, event) -> None:
        """
        面板尺寸变化时重算内容最小高度（换行标签会随宽度变高）。

        Args:
            event: Qt 尺寸事件。
        """
        super().resizeEvent(event)
        if self._built and self._content is not None:
            self._settleLayout()

    # ------------------------------------------------------------------ 预热

    def warmUpAsync(self) -> None:
        """
        后台预热 matplotlib（只导入模块，不创建任何 Qt 控件）。

        首次切到本页签时若现导入 matplotlib 要付约 0.7 s（含 Qt 后端），
        放在窗口显示后的空闲时间做，用户点进来时只剩查询与绘制。
        """
        if self._warmup_thread is not None:
            return
        self._warmup_thread = threading.Thread(
            target=self._warmUp, name="analysis-warmup", daemon=True
        )
        self._warmup_thread.start()

    def _warmUp(self) -> None:
        """预热线程体：导入图表依赖并应用样式；失败时退回首次激活再导入。"""
        try:
            import importlib

            for module_name in (
                "matplotlib",
                "matplotlib.backends.backend_qt5agg",
                "views.widgets.charts.base_canvas",
                "views.widgets.charts.trend_canvas",
                "views.widgets.charts.category_canvas",
                "views.widgets.charts.commission_canvas",
                "views.widgets.charts.build_pool_canvas",
            ):
                importlib.import_module(module_name)

            from utils.chart_style import applyChartStyle

            applyChartStyle()
        except Exception:
            # 预热只是优化：失败就不预热，首次激活照常导入，不向用户抛错
            pass
        finally:
            self._warmup_done.set()

    def _renderTrend(self) -> None:
        """刷新整体趋势区块。"""
        resource_type = self._trendResourceCombo.currentData()
        months = self._trendRangeCombo.currentData()
        display_name = RESOURCE_DISPLAY_NAMES.get(resource_type, resource_type)
        try:
            series = self._analysis_service.getTrend(resource_type, months)
        except DatabaseError as e:
            self._trendBalanceCanvas.showHint(f"{display_name}：读取失败")
            self._trendMonthlyCanvas.showHint("数据读取失败，请点刷新重试")
            self._trendCards.setText("")
            self._trendNote.setText(f"读取失败：{e}")
            return

        self._trendBalanceCanvas.render(series)
        self._trendMonthlyCanvas.render(series)
        if not series.balance_points:
            self._trendCards.setText("")
            self._trendNote.setText(f"{display_name}：{series.range_label}暂无记录")
            return
        self._trendCards.setText(self._formatTrendCards(series))
        parts = ["结余与收支同源（日汇总 + 明细合计）"]
        if series.range_label != "全部":
            parts.append(
                f"{series.range_label}：{series.range_start} ~ {series.range_end}，"
                "收入 / 支出按区间重算，结余仍为历史累计值"
            )
        if series.anchor_count:
            parts.append("▲ 为手填结余，曲线在此处跳变属正常")
        self._trendNote.setText("；".join(parts) + "。")

    def _renderCategory(self) -> None:
        """刷新来源 / 去向占比区块。"""
        resource_type = self._categoryResourceCombo.currentData()
        direction = self._categoryDirectionCombo.currentData()
        ratio_mode = self._categoryModeCombo.currentData() == _MONTHLY_MODE_RATIO
        try:
            breakdown = self._analysis_service.getCategoryBreakdown(resource_type, direction)
        except DatabaseError as e:
            self._categoryCanvas.showHint("数据读取失败")
            self._categoryNote.setText(f"读取失败：{e}")
            return

        self._categoryCanvas.render(breakdown, ratio_mode)
        self._categoryNote.setText(self._formatCategoryNote(breakdown))

    def _renderCommission(self) -> None:
        """刷新军事委托产出区块。"""
        resource_type = self._commissionResourceCombo.currentData()
        months = self._commissionRangeCombo.currentData()
        try:
            overview = self._analysis_service.getCommissionOverview(resource_type, months)
        except DatabaseError as e:
            self._commissionCanvas.showHint("数据读取失败")
            self._commissionCards.setText("")
            self._commissionNote.setText(f"读取失败：{e}")
            return

        self._commissionCanvas.render(overview, showAverage=months is None)
        self._commissionCards.setText(self._formatCommissionCards(overview))
        self._commissionNote.setText(self._formatCommissionNote(overview))

    def _renderBuild(self) -> None:
        """刷新大建详情区块。"""
        scope = self._buildScopeCombo.currentData()
        try:
            analysis = self._build_service.getAnalysis(scope)
        except DatabaseError as e:
            self._build_analysis = None
            self._buildTrendCanvas.showHint("数据读取失败")
            self._buildCompareCanvas.showHint("数据读取失败")
            self._buildCards.setText("")
            self._buildPrediction.setText("")
            self._buildNote.setText(f"读取失败：{e}")
            return

        self._build_analysis = analysis
        self._buildCards.setText(self._formatBuildCards(analysis))
        self._buildNote.setText(
            "仅统计状态=毕业的池；次数=关联魔方÷单耗+券抽（无明细时用手填值）；"
            f"样本 {analysis.sample_size} 池，未计入 {analysis.excluded_count} 池；"
            "分位为线性插值，预测仅作经验参考。"
        )
        self._updatePrediction()
        self._buildTrendCanvas.render(analysis)

    # ------------------------------------------------------------------ 文案

    @staticmethod
    def _formatTrendCards(series) -> str:
        """
        趋势卡片文案。

        Args:
            series: 趋势数据。

        Returns:
            单行文案。
        """
        prefix = "" if series.range_label == "全部" else f"{series.range_label}·"
        return (
            f"{prefix}当前结余 {formatExact(series.latestBalance)}｜"
            f"累计收入 {formatExact(series.total_income)}｜"
            f"累计支出 {formatExact(series.total_expense)}｜"
            f"净增长 {series.netGrowth:+d}｜"
            f"记录 {len(series.balance_points)} 天"
            f"（明细日 {series.detail_days}、汇总日 {series.summary_days}）｜"
            f"手填结余 {series.anchor_count} 处"
        )

    @staticmethod
    def _formatCategoryNote(breakdown) -> str:
        """
        类目覆盖说明。

        Args:
            breakdown: 类目占比结果。

        Returns:
            说明文案。
        """
        if not breakdown.detail_start:
            return "明细期：无明细数据（不足一笔明细时无法做类目占比）"

        parts = [
            f"类目占比仅含明细期 {breakdown.detail_start} ~ {breakdown.detail_end}"
            f"（合计 {formatExact(breakdown.detail_total)} / {breakdown.total_count} 笔）"
        ]
        if len(breakdown.shares) > ANALYSIS_TOP_CATEGORY_COUNT:
            parts.append(
                f"月度图只展开金额前 {ANALYSIS_TOP_CATEGORY_COUNT} 的类目，其余合并为「其他」"
            )
        if breakdown.summary_days:
            parts.append(
                f"汇总日 {breakdown.summary_days} 天未拆分："
                f"收 {formatExact(breakdown.summary_income)} / "
                f"支 {formatExact(breakdown.summary_expense)}，未计入占比"
            )
        if breakdown.unmapped_names:
            parts.append("字典外类目：" + "、".join(breakdown.unmapped_names))
        return "；".join(parts)

    @staticmethod
    def _formatCommissionCards(overview) -> str:
        """
        委托卡片文案。

        Args:
            overview: 委托概览结果。

        Returns:
            单行文案。
        """
        totals = overview.totals
        if not overview.hasData:
            return ""
        return (
            f"{overview.range_start} ~ {overview.range_end}（{overview.range_label}）｜"
            f"累计 {formatExact(totals.amount)}｜{totals.count} 笔｜"
            f"单笔均值 {totals.mean:.2f}｜"
            f"有记录日 {totals.active_days} 天、日均 {totals.daily_mean:.2f}｜"
            f"最高单笔 {totals.max_amount}"
        )

    @staticmethod
    def _formatCommissionNote(overview) -> str:
        """
        委托说明文案。

        Args:
            overview: 委托概览结果。

        Returns:
            说明文案。
        """
        if not overview.hasData:
            return f"{overview.range_label}：无军事委托记录"
        return "无记录月份留空（不补 0）；明细未记录委托类型，暂不能按委托等级拆分。"

    @staticmethod
    def _formatBuildCards(analysis) -> str:
        """
        大建卡片文案。

        Args:
            analysis: 大建分析结果。

        Returns:
            单行文案。
        """
        if not analysis.hasData:
            return "暂无毕业池样本"
        return (
            f"毕业池 {analysis.sample_size}｜"
            f"次数合计 {formatExact(analysis.total)}｜"
            f"中位 {analysis.median:g}｜均值 {analysis.mean:.1f}｜"
            f"P75 {analysis.quantiles.get(0.75, 0):g}｜"
            f"P90 {analysis.quantiles.get(0.90, 0):g}｜"
            f"最高 {analysis.max_count}"
        )

    def _currentBuildCount(self) -> int:
        """
        当前输入的大建次数。

        Returns:
            已抽次数。
        """
        return int(self._buildCountSpin.value())

    def _currentBuildCost(self) -> int:
        """
        当前选择的单耗。

        Returns:
            每次消耗的魔方数。
        """
        return int(self._buildCostCombo.currentData() or EVENT_DEFAULT_BUILD_COST)

    def _updatePrediction(self) -> None:
        """刷新毕业预算与进度对照文案。"""
        analysis = self._build_analysis
        if analysis is None or not analysis.hasData:
            self._buildPrediction.setText("")
            if self._buildCompareCanvas is not None:
                self._buildCompareCanvas.render(analysis or BuildPoolAnalysis())
            return

        cost = self._currentBuildCost()
        budget = self._build_service.buildBudget(analysis, cost)
        budget_text = " / ".join(
            f"{level.label} {level.build_count:g} 次→{level.cube_cost} 魔方"
            for level in budget
        )

        prediction = self._build_service.predictProgress(
            analysis, self._currentBuildCount(), cost
        )
        if prediction.exceeded_max:
            progress_text = "已抽次数已达到或超过历史最高，样本无法估计剩余"
        else:
            progress_text = (
                f"还需中位 {prediction.remaining_median:g} 次"
                f"（{prediction.cube_remaining_median} 魔方）"
                f" / P75 {prediction.remaining_p75:g} 次"
                f"（{prediction.cube_remaining_p75} 魔方）"
            )

        self._buildPrediction.setText(
            f"新池预算（单耗 {cost}）：{budget_text}｜"
            f"当前 {prediction.current_count} 次超过 "
            f"{prediction.percentile_rank:.0%} 的历史毕业池｜"
            f"{progress_text}"
        )
        if self._buildCompareCanvas is not None:
            self._buildCompareCanvas.render(analysis, prediction.current_count)
