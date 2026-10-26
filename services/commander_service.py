"""
指挥官服务模块。

提供指挥官等级快照的录入、查询与看板展示文本。

命名沿用项目既有约定（View → Service → Repository），业务校验统一抛
:class:`ValidationError`，数据库异常统一转为 :class:`DatabaseError`。
"""

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional, Sequence, Tuple

from models.commander_model import CommanderLevelExpModel, CommanderSnapshotModel
from repositories.commander_repository import CommanderRepository
from utils import time_source
from utils.constants import (
    COMMANDER_LEVEL_MAX, COMMANDER_LEVEL_MIN, COMMANDER_SNAPSHOT_RECENT_LIMIT,
    COMMANDER_TARGET_LEVEL_MILESTONES,
    EXP_EFFICIENCY_FAST_CAP_DAYS, EXP_EFFICIENCY_FAST_GAP_DAYS,
    EXP_EFFICIENCY_FAST_MIN_SAMPLES, EXP_EFFICIENCY_FAST_MIN_SPAN_DAYS,
    EXP_EFFICIENCY_GAP_HINT_DAYS, EXP_EFFICIENCY_LONG_WINDOW_DAYS,
    EXP_EFFICIENCY_MIN_SAMPLES, EXP_EFFICIENCY_STALE_DAYS,
    EXP_EFFICIENCY_TREND_DOWN_RATIO, EXP_EFFICIENCY_TREND_MIN_SAMPLES,
    EXP_EFFICIENCY_TREND_MIN_SPAN_DAYS, EXP_EFFICIENCY_TREND_UP_RATIO,
    EXP_EFFICIENCY_UNIT, EXP_EFFICIENCY_WINDOW_DAYS, RECORD_DATE_FORMAT,
    STATISTICS_DATETIME_FORMAT,
)
from utils.db_schema import isMissingColumnError, isMissingTableError
from utils.exceptions import DatabaseError, ValidationError
from utils.unit_formatter import formatExact

# 「指挥官等级」卡片标题角标的配色档位：
# 预计升级 / 可升级是信息型（蓝），已满级是完成态（绿）。
COMMANDER_BADGE_TONE_INFO = "info"
COMMANDER_BADGE_TONE_SUCCESS = "success"

# 趋势档位（#23）：fast/slow 偏离 30 天值 ±25% 才判定，其余记平稳。
TREND_ACCELERATING = "accelerating"
TREND_DECELERATING = "decelerating"
TREND_STABLE = "stable"


@dataclass
class CommanderWriteResult:
    """
    指挥官快照写操作结果。

    Attributes:
        success: 是否成功。
        snapshot_id: 受影响记录的 ID。
        message: 结果消息。
    """

    success: bool
    snapshot_id: Optional[int] = None
    message: str = ""

    def toStatusBarMessage(self) -> str:
        """
        生成状态栏显示消息。

        Returns:
            中文提示文本。
        """
        return self.message


@dataclass
class CommanderLevelOverview:
    """
    指挥官等级与经验展示数据。

    Attributes:
        level: 指挥官等级。
        current_exp: 当前等级内已累积经验。
        required_exp: 本级升级所需经验；基准表缺失时为 None。
        cumulative_exp: 从 1 级起的累计所需经验；基准表缺失时为 None。
        remaining_exp: 本级升级还差多少经验（需求 - 当前，不小于 0）；无基准时为 None。
        progress_rate: 本级进度百分比（0～100）；无基准时为 None。
        snapshot_date: 数据来源的记录时间。
    """

    level: int
    current_exp: int
    required_exp: Optional[int] = None
    cumulative_exp: Optional[int] = None
    remaining_exp: Optional[int] = None
    progress_rate: Optional[float] = None
    snapshot_date: str = ""


@dataclass
class CommanderLevelBadge:
    """
    「指挥官等级」卡片标题角标。

    Attributes:
        text: 角标文案；不展示时为空串。
        tone: 配色档位，``info``（预计 X 天后升级 / 可升级）/ ``success``（已满级）。
    """

    text: str = ""
    tone: str = ""


@dataclass
class ExpEfficiency:
    """
    指级效率计算结果（#16 v1，字段扩展见 #23 v2）。

    ``rate_per_day`` 是**主值**，口径与 v1 完全一致：最近
    `EXP_EFFICIENCY_WINDOW_DAYS` 天内的「绝对经验差 ÷ 实际跨度」，右端点取
    **最新有效快照**而非今天，避免"很久没记录"被当成"没肝"。

    v2 只追加信号层字段（近期节奏 / 趋势 / 缺口 / 新鲜度 / 异常隔离），
    不改变主值语义，也不参与主值计算。

    Attributes:
        rate_per_day: 慢窗口日均经验（主值）；降级时为 None。
        start_time: 慢窗口起点快照时刻（``yyyy-MM-dd HH:mm``）。
        end_time: 慢窗口终点（最新有效快照）时刻。
        span_days: 慢窗口实际跨度（天，含小数）。
        sample_count: 慢窗口内去重后的快照条数。
        cumulative_rate: 全程日均（首条到末条），供 tooltip 对照；样本不足时为 None。
        skipped: 因等级无法换算而被跳过的快照条数（v1 语义）。
        degraded_reason: 降级原因；正常时为 None。
        fast_rate_per_day: 近期连续块日均；块内不足两条或跨度不足时为 None。
        fast_start_time: 近期块起点时刻。
        fast_end_time: 近期块终点时刻。
        fast_span_days: 近期块跨度（天）。
        fast_sample_count: 近期块内快照条数。
        trend: ``accelerating`` / ``decelerating`` / ``stable``；样本不足时为 None。
        trend_ratio: ``fast / slow``；未判定趋势时为 None。
        gap_days: 慢窗口内相邻有效快照的最大间隔（天）；不足两条时为 None。
        stale_days: 数据截止（最新有效快照）距今天数（向下取整，最小 0）。
        invalid_count: 被隔离的异常快照条数（经验越界 / 绝对经验回退等）。
        long_rate_per_day: 90 天长期参考日均（#35）；仅用于目标等级预测，不参与主值与 tooltip。
    """

    rate_per_day: Optional[int] = None
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    span_days: Optional[float] = None
    sample_count: int = 0
    cumulative_rate: Optional[int] = None
    skipped: int = 0
    degraded_reason: Optional[str] = None

    fast_rate_per_day: Optional[int] = None
    fast_start_time: Optional[str] = None
    fast_end_time: Optional[str] = None
    fast_span_days: Optional[float] = None
    fast_sample_count: int = 0
    trend: Optional[str] = None
    trend_ratio: Optional[float] = None
    gap_days: Optional[float] = None
    stale_days: Optional[int] = None
    invalid_count: int = 0
    long_rate_per_day: Optional[int] = None


@dataclass
class TargetLevelProjection:
    """
    目标等级升级预测结果（#35）。

    口径：`remaining(T) = cum(T-1) − (cum(L-1) + exp)`，`T = L+1` 时与看板
    「升级还需」完全一致；`T = 200` 使用 `cum(199)`，不读满级 NULL 行。

    Attributes:
        target_level: 目标等级。
        current_level: 当前等级（最新快照）；无快照时为 0。
        current_exp: 当前等级内已累积经验。
        current_absolute_exp: 当前绝对经验；无法换算时为 None。
        target_absolute_exp: 到达目标等级的绝对经验（`cum(T-1)`）；缺失时为 None。
        remaining_exp: 还需经验；无法计算时为 None，已达目标时为 0。
        days_slow: 按 30 天主值估算的天数。
        days_long: 按 90 天长期参考估算的天数。
        days_fast: 按近期节奏估算的天数；仅在趋势明确（加速/放缓）时给值。
        estimated_date: 预计日期（`today + round(days_slow)`，``yyyy-MM-dd``）。
        degraded_reason: 不可算或已达成时的说明；正常时为 None。
    """

    target_level: int
    current_level: int = 0
    current_exp: int = 0
    current_absolute_exp: Optional[int] = None
    target_absolute_exp: Optional[int] = None
    remaining_exp: Optional[int] = None
    days_slow: Optional[float] = None
    days_long: Optional[float] = None
    days_fast: Optional[float] = None
    estimated_date: Optional[str] = None
    degraded_reason: Optional[str] = None


class CommanderService:
    """
    指挥官服务类。

    封装等级快照的业务校验、需求经验查询与看板文本生成。
    快照为历史语义：新增追加一行，修改与删除按 ID 操作。
    """

    def __init__(self, commander_repository: Optional[CommanderRepository] = None):
        """
        初始化指挥官服务。

        Args:
            commander_repository: 指挥官数据访问实例。
        """
        self._commander_repository = commander_repository or CommanderRepository()
        # 等级基准是只读配置表；逐条快照换算绝对经验时会按等级反复查询，
        # 而每次查询都会新建 SQLite 连接（约 1ms），500+ 条快照就是半秒级开销。
        self._level_exp_cache: Dict[int, Optional[CommanderLevelExpModel]] = {}
        # 指级效率的中间结果：一次刷新会取卡片文本、卡片提示与升级情景三次，
        # 快照写入（本服务内）后失效；stale_days 依赖"今天"，因此跨天也要失效。
        self._efficiency_cache: Optional[ExpEfficiency] = None
        self._efficiency_cache_date: Optional[date] = None

    def getLatestSnapshot(self) -> Optional[CommanderSnapshotModel]:
        """
        获取最新一条指挥官快照。

        Returns:
            快照模型实例；无数据或表缺失时返回 None。
        """
        try:
            return self._commander_repository.findLatest()
        except DatabaseError as e:
            if isMissingTableError(e) or isMissingColumnError(e):
                return None
            raise

    def getLevelRequirement(self, level: int) -> Optional[CommanderLevelExpModel]:
        """
        查询指定等级的升级经验基准（按等级缓存）。

        基准表由迁移脚本固定、运行期只读，因此可以安全缓存；命中缓存后
        绝对经验换算不再为每条快照打开一次数据库连接。

        Args:
            level: 等级。

        Returns:
            基准模型实例；无该等级或表缺失时返回 None。
        """
        if level in self._level_exp_cache:
            return self._level_exp_cache[level]

        try:
            requirement = self._commander_repository.findLevelExp(level)
        except DatabaseError as e:
            if isMissingTableError(e) or isMissingColumnError(e):
                self._level_exp_cache[level] = None
                return None
            raise

        self._level_exp_cache[level] = requirement
        return requirement

    def listSnapshots(
        self,
        limit: Optional[int] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> List[CommanderSnapshotModel]:
        """
        查询快照列表。

        Args:
            limit: 可选条数上限（仅在不指定日期范围时生效）。
            start_date: 可选起始日期 ``yyyy-MM-dd``。
            end_date: 可选结束日期 ``yyyy-MM-dd``。

        Returns:
            快照模型列表，按时间倒序；表缺失时返回空列表。
        """
        try:
            if start_date or end_date:
                return self._commander_repository.findByDateRange(
                    start_date or "0000-01-01", end_date or "9999-12-31"
                )
            if limit is not None:
                return self._commander_repository.findRecent(limit)
            return self._commander_repository.findAll()
        except DatabaseError as e:
            if isMissingTableError(e) or isMissingColumnError(e):
                return []
            raise

    def listSnapshotRows(
        self,
        limit: Optional[int] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> List[Dict]:
        """
        查询快照并附带已格式化的展示字段，供列表直接渲染。

        等级经验基准按等级缓存，避免同一等级重复查库。

        Args:
            limit: 可选条数上限（仅在不指定日期范围时生效）。
            start_date: 可选起始日期 ``yyyy-MM-dd``。
            end_date: 可选结束日期 ``yyyy-MM-dd``。

        Returns:
            字典列表，字段：``id``、``statistics_date``、``commander_level``、
            ``commander_exp``、``exp_text``、``required_text``、``progress_text``。
        """
        snapshots = self.listSnapshots(limit=limit, start_date=start_date, end_date=end_date)
        requirement_cache: Dict[int, Optional[CommanderLevelExpModel]] = {}
        rows: List[Dict] = []

        for snapshot in snapshots:
            level = snapshot.commander_level
            if level not in requirement_cache:
                requirement_cache[level] = self.getLevelRequirement(level)
            requirement = requirement_cache[level]

            required = requirement.level_up_exp if requirement else None
            progress_text = "-"
            if required and required > 0:
                progress_text = f"{snapshot.commander_exp / required * 100:.1f}%"

            rows.append({
                "id": snapshot.id,
                "statistics_date": snapshot.statistics_date,
                "commander_level": level,
                "commander_exp": snapshot.commander_exp,
                "exp_text": formatExact(snapshot.commander_exp),
                "required_text": formatExact(required) if required is not None else "-",
                "progress_text": progress_text,
            })
        return rows

    def addSnapshot(self, snapshot: CommanderSnapshotModel) -> CommanderWriteResult:
        """
        新增一条指挥官快照。

        Args:
            snapshot: 快照模型实例（ID 会被忽略）。

        Returns:
            写操作结果。

        Raises:
            ValidationError: 当时间格式、等级、经验或重复时间不合法时抛出。
            DatabaseError: 当数据库写入失败时抛出。
        """
        self._validateSnapshot(snapshot)
        normalized = self._normalize(snapshot)
        if self._commander_repository.existsAt(normalized.statistics_date):
            raise ValidationError(
                f"该时间点已存在记录：{normalized.statistics_date}，请调整分钟数"
            )

        normalized.id = None
        new_id = self._commander_repository.insert(normalized)
        self._invalidateEfficiencyCache()
        return CommanderWriteResult(
            success=True,
            snapshot_id=new_id,
            message=(
                f"已记录指挥官 {normalized.commander_level} 级快照"
                f"（{normalized.statistics_date}，当前经验 {formatExact(normalized.commander_exp)}）"
            ),
        )

    def updateSnapshot(self, snapshot: CommanderSnapshotModel) -> CommanderWriteResult:
        """
        更新一条指挥官快照。

        Args:
            snapshot: 快照模型实例，必须带有效 ID。

        Returns:
            写操作结果。

        Raises:
            ValidationError: 当缺少 ID 或字段不合法时抛出。
            DatabaseError: 当数据库写入失败时抛出。
        """
        if snapshot.id is None:
            raise ValidationError("更新快照需要指定记录")

        self._validateSnapshot(snapshot)
        normalized = self._normalize(snapshot)

        existing = self._commander_repository.findById(snapshot.id)
        if existing is None:
            raise ValidationError("待更新的快照已不存在，请刷新列表")

        if (existing.statistics_date != normalized.statistics_date
                and self._commander_repository.existsAt(normalized.statistics_date)):
            raise ValidationError(
                f"该时间点已存在记录：{normalized.statistics_date}，请调整分钟数"
            )

        updated = self._commander_repository.update(normalized)
        if not updated:
            raise ValidationError("更新失败，请刷新列表后重试")

        self._invalidateEfficiencyCache()
        return CommanderWriteResult(
            success=True,
            snapshot_id=normalized.id,
            message=f"已更新指挥官 {normalized.commander_level} 级快照（{normalized.statistics_date}）",
        )

    def deleteSnapshot(self, snapshot_id: int) -> CommanderWriteResult:
        """
        删除一条指挥官快照。

        Args:
            snapshot_id: 快照 ID。

        Returns:
            写操作结果。

        Raises:
            ValidationError: 当记录不存在时抛出。
            DatabaseError: 当数据库写入失败时抛出。
        """
        if snapshot_id is None:
            raise ValidationError("删除快照需要指定记录")

        existing = self._commander_repository.findById(snapshot_id)
        if existing is None:
            raise ValidationError("待删除的快照已不存在，请刷新列表")

        self._commander_repository.delete(snapshot_id)
        self._invalidateEfficiencyCache()
        return CommanderWriteResult(
            success=True,
            snapshot_id=snapshot_id,
            message=f"已删除 {existing.statistics_date} 的指挥官快照",
        )

    def getLevelOverview(self, level: int, current_exp: int) -> CommanderLevelOverview:
        """
        汇总某等级的经验需求与进度，供面板与卡片复用。

        Args:
            level: 等级。
            current_exp: 当前等级内已累积经验。

        Returns:
            展示数据对象。
        """
        requirement = self.getLevelRequirement(level)
        required = requirement.level_up_exp if requirement else None
        cumulative = requirement.cumulative_exp if requirement else None

        progress = None
        if required and required > 0:
            progress = min(100.0, max(0.0, current_exp / required * 100))

        remaining = max(0, required - current_exp) if required is not None else None

        return CommanderLevelOverview(
            level=level,
            current_exp=current_exp,
            required_exp=required,
            cumulative_exp=cumulative,
            remaining_exp=remaining,
            progress_rate=progress,
        )

    def getCommanderLevelCardText(self) -> str:
        """
        生成「指挥官等级」看板卡片文本。

        精确数值口径：``等级（当前经验/需求经验）``，固定加千分符。

        Returns:
            卡片文本；无快照时为 ``-``。
        """
        latest = self.getLatestSnapshot()
        if latest is None:
            return "-"

        overview = self.getLevelOverview(latest.commander_level, latest.commander_exp)
        required_text = formatExact(overview.required_exp) if overview.required_exp is not None else "-"
        return (
            f"{latest.commander_level}"
            f"（{formatExact(latest.commander_exp)}/{required_text}）"
        )

    def getCommanderLevelCardBadge(self) -> CommanderLevelBadge:
        """
        生成「指挥官等级」卡片标题角标（预计 X 天后升级）。

        预计升级按当前指级效率（近 30 天日均）估算；该信息已从 tooltip 迁到
        卡片标题行，避免本就很长的「等级（当前经验/需求经验）」再被撑宽。
        无快照、未满级但缺基准、或效率不足时返回空角标，由面板隐藏。

        Returns:
            角标文案与配色档位。
        """
        latest = self.getLatestSnapshot()
        if latest is None:
            return CommanderLevelBadge()

        overview = self.getLevelOverview(latest.commander_level, latest.commander_exp)
        return self._buildUpgradeBadge(latest.commander_level, overview.remaining_exp)

    def getCommanderLevelCardTooltip(self) -> str:
        """
        生成「指挥官等级」看板卡片悬停提示。

        卡片本身已经展示「等级（当前经验/需求经验）」，标题角标展示「预计 X 天后升级」，
        所以提示里不再重复这些内容，只补充升级还差多少、进度、效率不足时的说明、
        「若维持近期节奏」情景（#23），以及记录时间。

        Returns:
            提示文本。
        """
        latest = self.getLatestSnapshot()
        if latest is None:
            return "指挥官等级：暂无记录，请在「资源统计」页签录入快照"

        overview = self.getLevelOverview(latest.commander_level, latest.commander_exp)
        parts = []
        if overview.remaining_exp is not None:
            parts.append(f"升级还需 {formatExact(overview.remaining_exp)} 经验")
        else:
            parts.append("升级所需经验未知（缺少该等级的基准数据）")
        if overview.progress_rate is not None:
            parts.append(f"进度 {overview.progress_rate:.1f}%")
        scenario = self.getUpgradeScenario(overview.remaining_exp)
        if scenario:
            parts.append(scenario)
        badge = self._buildUpgradeBadge(latest.commander_level, overview.remaining_exp)
        if (
            not badge.text
            and latest.commander_level < COMMANDER_LEVEL_MAX
            and overview.remaining_exp is not None
            and overview.remaining_exp > 0
        ):
            # 角标给不出天数时，tooltip 保留原因，避免信息静默消失
            parts.append("暂无法预估升级天数（指级效率数据不足）")
        parts.append(f"记录于 {latest.statistics_date}")
        return "｜".join(parts)

    def _buildUpgradeBadge(
        self, level: int, remaining_exp: Optional[int]
    ) -> CommanderLevelBadge:
        """
        根据等级与剩余经验生成升级角标。

        满级判断优先于「剩余 0」：只有达到最高等级才显示「已满级」；未满级但
        经验已满时显示「可升级」，避免把“可以升级”误报成满级。

        Args:
            level: 指挥官等级。
            remaining_exp: 本级还差多少经验；None 表示基准缺失。

        Returns:
            角标；无法估算时 ``text`` 为空串。
        """
        if level >= COMMANDER_LEVEL_MAX:
            return CommanderLevelBadge("已满级", COMMANDER_BADGE_TONE_SUCCESS)
        if remaining_exp is None:
            return CommanderLevelBadge()
        if remaining_exp <= 0:
            return CommanderLevelBadge("可升级", COMMANDER_BADGE_TONE_INFO)

        rate = self.getExpEfficiency().rate_per_day
        if not rate or rate <= 0:
            return CommanderLevelBadge()
        return CommanderLevelBadge(
            f"预计 {remaining_exp / rate:.1f} 天后升级",
            COMMANDER_BADGE_TONE_INFO,
        )

    def getUpgradeScenario(self, remaining_exp: Optional[int]) -> str:
        """
        生成「若维持近期节奏」的升级情景文案（#23 §6.3）。

        只在趋势明确（加速 / 放缓）时给出：近期节奏有偏，只作方向与情景参考，
        不写成区间、不参与角标主值。升级天数主值仍由标题角标承载。

        Args:
            remaining_exp: 本级还差多少经验；None 或 <=0 时不输出情景。

        Returns:
            形如「若维持近期节奏 16.3 天后升级」；不适用时返回空串。
        """
        if not remaining_exp or remaining_exp <= 0:
            return ""
        efficiency = self.getExpEfficiency()
        if efficiency.trend not in (TREND_ACCELERATING, TREND_DECELERATING):
            return ""
        fast = efficiency.fast_rate_per_day
        if not fast or fast <= 0:
            return ""
        return f"若维持近期节奏 {remaining_exp / fast:.1f} 天后升级"

    # ----------------------------------------------------- 指级效率（#16）

    def getAbsoluteExp(self, level: int, current_exp: int) -> Optional[int]:
        """
        把「等级 + 本级已累积经验」换算为从 1 级起的绝对经验。

        公式：`absolute(1) = exp`，`absolute(L) = cumulative_exp(L-1) + exp`。
        满级（`COMMANDER_LEVEL_MAX`）只用到 `cumulative_exp(L-1)`，不会触碰基准表里
        200 级的 NULL 行；等级越界或基准缺失时返回 None（该快照不参与计算）。

        Args:
            level: 指挥官等级。
            current_exp: 本级已累积经验。

        Returns:
            绝对经验；无法换算时返回 None。
        """
        if level < COMMANDER_LEVEL_MIN or level > COMMANDER_LEVEL_MAX:
            return None
        if level == COMMANDER_LEVEL_MIN:
            return current_exp

        requirement = self.getLevelRequirement(level - 1)
        if requirement is None or requirement.cumulative_exp is None:
            return None
        return int(requirement.cumulative_exp) + current_exp

    def getExpEfficiency(self) -> ExpEfficiency:
        """
        计算指级效率（近 30 天日均，结果按服务实例缓存）。

        口径见 `docs/指级效率算法方案_20261018.md`：
        窗口右端点取最新快照（不是今天），起点取窗口边界之前最近的一条快照；
        若全部历史都落在窗口内，则直接使用最早的一条（跨度会小于窗口）。

        同一次刷新里卡片文本、卡片提示、升级角标与升级情景都会调用本方法，
        缓存后只扫描一遍快照；通过本服务写入快照时缓存失效；
        ``stale_days`` 依赖当天日期，跨天后同样失效。

        Returns:
            计算结果；数据不足或异常时 `rate_per_day` 为 None 并给出 `degraded_reason`。
        """
        today = time_source.today()
        if self._efficiency_cache is None or self._efficiency_cache_date != today:
            self._efficiency_cache = self._computeExpEfficiency()
            self._efficiency_cache_date = today
        return self._efficiency_cache

    def _invalidateEfficiencyCache(self) -> None:
        """快照发生写入后丢弃指级效率缓存。"""
        self._efficiency_cache = None
        self._efficiency_cache_date = None

    def _computeExpEfficiency(self) -> ExpEfficiency:
        """
        实际计算指级效率（不做缓存）。

        主值（slow）沿用 v1 公式；v2 在同一份 points 上追加近期节奏（fast）、
        趋势（trend）、窗口内最大缺口（gap_days）与数据新鲜度（stale_days），
        不新增 SQL、不改变主值语义。

        Returns:
            计算结果。
        """
        points, skipped, invalid = self.collectAbsolutePoints()

        if not points:
            if invalid:
                reason = f"快照异常且没有可回退的有效记录（已隔离 {invalid} 条）"
            else:
                reason = "暂无快照，请先录入指挥官等级"
            return ExpEfficiency(
                skipped=skipped, invalid_count=invalid, degraded_reason=reason
            )
        if len(points) < EXP_EFFICIENCY_MIN_SAMPLES:
            suffix = f"；已隔离 {invalid} 条异常，疑似录入错误" if invalid else ""
            return ExpEfficiency(
                sample_count=len(points),
                skipped=skipped,
                invalid_count=invalid,
                degraded_reason=f"至少需要两条可换算的快照（当前 {len(points)} 条{suffix}）",
            )

        end_time, end_absolute = points[-1]
        start_time, start_absolute = self._findWindowStart(points, end_time)
        span_days = (end_time - start_time).total_seconds() / 86400
        stale_days = self._computeStaleDays(end_time)

        if span_days <= 0:
            return ExpEfficiency(
                start_time=self._formatMoment(start_time),
                end_time=self._formatMoment(end_time),
                span_days=span_days,
                sample_count=len(points),
                skipped=skipped,
                stale_days=stale_days,
                invalid_count=invalid,
                degraded_reason="区间跨度不足一天",
            )

        delta = end_absolute - start_absolute
        if delta < 0:
            return ExpEfficiency(
                start_time=self._formatMoment(start_time),
                end_time=self._formatMoment(end_time),
                span_days=span_days,
                sample_count=len(points),
                skipped=skipped,
                stale_days=stale_days,
                invalid_count=invalid,
                degraded_reason="最近快照的绝对经验低于区间起点，疑似录入错误",
            )

        slow_rate = int(round(delta / span_days))
        sample_count = sum(1 for moment, _ in points if start_time <= moment <= end_time)
        block = self._currentBlock(points)
        fast_rate, fast_span = self._computeBlockRate(block)
        trend, trend_ratio = self._classifyTrend(slow_rate, block, fast_rate, fast_span)
        return ExpEfficiency(
            rate_per_day=slow_rate,
            start_time=self._formatMoment(start_time),
            end_time=self._formatMoment(end_time),
            span_days=span_days,
            sample_count=sample_count,
            cumulative_rate=self._buildCumulativeRate(points[0], points[-1]),
            skipped=skipped,
            fast_rate_per_day=fast_rate,
            fast_start_time=self._formatMoment(block[0][0]),
            fast_end_time=self._formatMoment(block[-1][0]),
            fast_span_days=fast_span,
            fast_sample_count=len(block),
            trend=trend,
            trend_ratio=trend_ratio,
            gap_days=self._computeMaxGap(points, start_time, end_time),
            stale_days=stale_days,
            invalid_count=invalid,
            long_rate_per_day=self._computeWindowRate(
                points, end_time, EXP_EFFICIENCY_LONG_WINDOW_DAYS
            ),
        )

    def _computeWindowRate(
        self,
        points: List[Tuple[datetime, int]],
        end_time: datetime,
        window_days: int,
    ) -> Optional[int]:
        """
        用指定窗口的端点差计算日均（不改主值，仅作参考口径）。

        Args:
            points: 按时间升序的有效快照点（至少 2 条）。
            end_time: 右端点（最新有效快照）。
            window_days: 窗口天数。

        Returns:
            日均经验；跨度不足一天时返回 None。
        """
        start_time, start_absolute = self._findWindowStart(points, end_time, window_days)
        span_days = (end_time - start_time).total_seconds() / 86400
        if span_days <= 0:
            return None
        return int(round((points[-1][1] - start_absolute) / span_days))

    @staticmethod
    def _findWindowStart(
        points: List[Tuple[datetime, int]],
        end_time: datetime,
        window_days: int = EXP_EFFICIENCY_WINDOW_DAYS,
    ) -> Tuple[datetime, int]:
        """
        取指定窗口的起点：窗口边界之前最近的一条有效快照。

        Args:
            points: 按时间升序的有效快照点。
            end_time: 右端点（最新有效快照）。
            window_days: 窗口天数，默认慢窗口。

        Returns:
            起点 (时刻, 绝对经验)；全部历史都在窗口内时返回最早一条。
        """
        cutoff = end_time - timedelta(days=window_days)
        start: Optional[Tuple[datetime, int]] = None
        for moment, absolute in points:
            if moment <= cutoff:
                start = (moment, absolute)
            else:
                break
        return start if start is not None else points[0]

    @staticmethod
    def _currentBlock(points: List[Tuple[datetime, int]]) -> List[Tuple[datetime, int]]:
        """
        截取"近期连续记录块"：从最新点往回走，遇到超过 fast 缺口上限即停，
        最多回看 fast 回看上限（两个阈值见 `utils.constants`）。

        严格 cap：不为了凑够两条而回退到 14 天以外，宁可让 fast 为空。

        Args:
            points: 按时间升序的有效快照点（至少 2 条）。

        Returns:
            块内点（升序，至少包含最新一条）。
        """
        cap_cutoff = points[-1][0] - timedelta(days=EXP_EFFICIENCY_FAST_CAP_DAYS)
        block: List[Tuple[datetime, int]] = [points[-1]]
        for moment, absolute in reversed(points[:-1]):
            if moment < cap_cutoff:
                break
            gap_days = (block[0][0] - moment).total_seconds() / 86400
            if gap_days > EXP_EFFICIENCY_FAST_GAP_DAYS:
                break
            block.insert(0, (moment, absolute))
        return block

    @staticmethod
    def _computeBlockRate(
        block: List[Tuple[datetime, int]]
    ) -> Tuple[Optional[int], Optional[float]]:
        """
        用端点差计算近期块日均，避免段速率被"记录频率"加权。

        Args:
            block: 近期连续块（升序）。

        Returns:
            (日均经验, 块跨度天数)；不足 2 条或跨度 <1 天时返回 (None, 跨度/None)。
        """
        if len(block) < 2:
            return None, None
        span_days = (block[-1][0] - block[0][0]).total_seconds() / 86400
        if len(block) < EXP_EFFICIENCY_FAST_MIN_SAMPLES:
            return None, span_days
        if span_days < EXP_EFFICIENCY_FAST_MIN_SPAN_DAYS:
            return None, span_days
        delta = block[-1][1] - block[0][1]
        return int(round(delta / span_days)), span_days

    @staticmethod
    def _classifyTrend(
        slow_rate: int,
        block: List[Tuple[datetime, int]],
        fast_rate: Optional[int],
        fast_span: Optional[float],
    ) -> Tuple[Optional[str], Optional[float]]:
        """
        按 fast / slow 判定趋势档位。

        Args:
            slow_rate: 主值（30 天日均）。
            block: 近期连续块。
            fast_rate: 近期日均；None 表示样本不足。
            fast_span: 近期块跨度。

        Returns:
            (trend 档位, fast/slow 比值)；未判定趋势时返回 (None, None)。
        """
        if fast_rate is None or fast_span is None or slow_rate <= 0:
            return None, None
        if (
            len(block) < EXP_EFFICIENCY_TREND_MIN_SAMPLES
            or fast_span < EXP_EFFICIENCY_TREND_MIN_SPAN_DAYS
        ):
            return None, None

        ratio = fast_rate / slow_rate
        if ratio >= EXP_EFFICIENCY_TREND_UP_RATIO:
            return TREND_ACCELERATING, ratio
        if ratio <= EXP_EFFICIENCY_TREND_DOWN_RATIO:
            return TREND_DECELERATING, ratio
        return TREND_STABLE, ratio

    @staticmethod
    def _computeMaxGap(
        points: List[Tuple[datetime, int]], start_time: datetime, end_time: datetime
    ) -> Optional[float]:
        """
        计算慢窗口内相邻有效快照的最大间隔。

        Args:
            points: 按时间升序的有效快照点。
            start_time: 窗口起点。
            end_time: 窗口终点。

        Returns:
            最大间隔（天）；窗口内不足两条时为 None。
        """
        window = [moment for moment, _ in points if start_time <= moment <= end_time]
        if len(window) < 2:
            return None
        return max(
            (window[index] - window[index - 1]).total_seconds() / 86400
            for index in range(1, len(window))
        )

    @staticmethod
    def _computeStaleDays(end_time: datetime) -> int:
        """
        计算数据新鲜度：最新有效快照距今天数（向下取整，最小 0）。

        Args:
            end_time: 最新有效快照时刻。

        Returns:
            距今天数。
        """
        seconds = (time_source.now() - end_time).total_seconds()
        return max(0, int(seconds // 86400))

    @staticmethod
    def _formatMoment(moment: datetime) -> str:
        """
        把时刻格式化为数据库口径 ``yyyy-MM-dd HH:mm``。

        Args:
            moment: 时刻。

        Returns:
            格式化文本。
        """
        return moment.strftime(STATISTICS_DATETIME_FORMAT)

    @staticmethod
    def _formatTooltipMoment(value: Optional[str]) -> str:
        """
        把快照时刻格式化为 tooltip 口径：同年省略年份，跨年保留完整日期。

        Args:
            value: ``yyyy-MM-dd HH:mm`` 文本。

        Returns:
            ``MM-dd HH:mm`` 或完整日期；空值返回 ``-``。
        """
        if not value:
            return "-"
        moment = datetime.strptime(value, STATISTICS_DATETIME_FORMAT)
        if moment.year == time_source.now().year:
            return moment.strftime("%m-%d %H:%M")
        return moment.strftime(STATISTICS_DATETIME_FORMAT)

    def collectAbsolutePoints(self) -> Tuple[List[Tuple[datetime, int]], int, int]:
        """
        读取全部快照、逐条校验、换算绝对经验并按天去重。

        校验顺序（#23 §4.1）：先判断能否换算（等级越界 / 基准缺失）→ 再判断
        「可换算但异常」（经验为负、超过本级需求、绝对经验回退）→ 最后按天去重，
        同一天只保留最后一条**有效**快照。校验逻辑与写入时的 ``_validateSnapshot``
        一致，额外覆盖旧库、迁移数据与外部写库。

        Returns:
            (按时间升序且同日去重的 (时刻, 绝对经验) 列表,
             无法换算条数, 异常隔离条数)。
        """
        points: List[Tuple[datetime, int]] = []
        skipped = 0
        invalid = 0
        last_absolute: Optional[int] = None
        try:
            snapshots = self._commander_repository.findAll()
        except DatabaseError as e:
            # 旧库 / 空库没有指挥官表：按"无快照"降级，不让整块看板报错
            if isMissingTableError(e) or isMissingColumnError(e):
                return [], 0, 0
            raise

        for snapshot in reversed(snapshots):
            absolute = self.getAbsoluteExp(snapshot.commander_level, snapshot.commander_exp)
            if absolute is None:
                skipped += 1
                continue
            if self._isInvalidSnapshot(snapshot):
                invalid += 1
                continue
            if last_absolute is not None and absolute < last_absolute:
                # 绝对经验必须单调不减；回退多半是录入错误，隔离该条而不是整块降级
                invalid += 1
                continue
            moment = datetime.strptime(snapshot.statistics_date, STATISTICS_DATETIME_FORMAT)
            points.append((moment, absolute))
            last_absolute = absolute

        # 同一天只保留最后一条有效快照：它已包含当天更早记录的全部增量
        by_day: Dict[date, Tuple[datetime, int]] = {}
        for moment, absolute in points:
            by_day[moment.date()] = (moment, absolute)
        return [by_day[day] for day in sorted(by_day)], skipped, invalid

    def _isInvalidSnapshot(self, snapshot: CommanderSnapshotModel) -> bool:
        """
        判断一条可换算快照是否属于"可换算但异常"。

        规则：本级经验为负，或超过本级升级需求（满级 200 无本级需求，不判越界）。

        Args:
            snapshot: 快照模型。

        Returns:
            是否异常。
        """
        level = snapshot.commander_level
        exp = snapshot.commander_exp
        if exp < 0:
            return True
        if level >= COMMANDER_LEVEL_MAX:
            return False
        requirement = self.getLevelRequirement(level)
        if requirement is None or requirement.level_up_exp is None:
            return False
        return exp > requirement.level_up_exp

    @staticmethod
    def _buildCumulativeRate(
        first: Tuple[datetime, int], last: Tuple[datetime, int]
    ) -> Optional[int]:
        """
        计算全程日均（首条 → 末条），作为 tooltip 对照项。

        Args:
            first: 首条 (时刻, 绝对经验)。
            last: 末条 (时刻, 绝对经验)。

        Returns:
            全程日均；跨度为 0 时返回 None。
        """
        span_days = (last[0] - first[0]).total_seconds() / 86400
        if span_days <= 0:
            return None
        return int(round((last[1] - first[1]) / span_days))

    def getExpEfficiencyText(self) -> str:
        """
        生成「指级效率」看板卡片文本。

        Returns:
            ``11,336/天`` 形式；数据不足时返回 ``-``。
        """
        efficiency = self.getExpEfficiency()
        if efficiency.rate_per_day is None:
            return "-"
        return f"{formatExact(efficiency.rate_per_day)}{EXP_EFFICIENCY_UNIT}"

    def getExpEfficiencyTooltip(self) -> str:
        """
        生成「指级效率」看板卡片悬停提示（#23 三段式）。

        第 1 段慢窗口（主值 + 区间 + 样本数），第 2 段近期节奏与趋势，
        第 3 段窗口内最大缺口 / 数据截止 / 累计日均与异常隔离说明。
        缺数据时说明降级原因与口径。

        Returns:
            最多三行的提示文本。
        """
        efficiency = self.getExpEfficiency()
        window = f"近 {EXP_EFFICIENCY_WINDOW_DAYS} 天日均"
        if efficiency.rate_per_day is None:
            reason = efficiency.degraded_reason or "数据不足"
            return f"指级效率：{reason}｜口径：{window}（绝对经验差 ÷ 实际跨度）"

        slow_parts = [
            f"{window} {formatExact(efficiency.rate_per_day)}{EXP_EFFICIENCY_UNIT}",
            f"{self._formatTooltipMoment(efficiency.start_time)} → "
            f"{self._formatTooltipMoment(efficiency.end_time)}"
            f"（{efficiency.span_days:.1f} 天，{efficiency.sample_count} 条快照）",
        ]
        if efficiency.sample_count < 3:
            slow_parts.append("样本较少，仅供参考")

        return "\n".join([
            "｜".join(slow_parts),
            self._buildFastTooltipPart(efficiency),
            self._buildQualityTooltipPart(efficiency),
        ])

    def _buildFastTooltipPart(self, efficiency: ExpEfficiency) -> str:
        """
        生成 tooltip 第 2 段：近期节奏与趋势。

        Args:
            efficiency: 指级效率结果。

        Returns:
            单行提示；近期样本不足时说明原因。
        """
        if efficiency.fast_rate_per_day is None:
            return "近期样本不足"

        parts = [
            f"近期节奏 {formatExact(efficiency.fast_rate_per_day)}{EXP_EFFICIENCY_UNIT}",
            f"{self._formatTooltipMoment(efficiency.fast_start_time)} → "
            f"{self._formatTooltipMoment(efficiency.fast_end_time)}"
            f"（{efficiency.fast_span_days:.1f} 天，{efficiency.fast_sample_count} 条快照）",
        ]
        if efficiency.trend == TREND_ACCELERATING:
            parts.append(f"趋势 加速 +{self._trendPercent(efficiency.trend_ratio)}%")
        elif efficiency.trend == TREND_DECELERATING:
            parts.append(f"趋势 放缓 {self._trendPercent(efficiency.trend_ratio)}%")
        elif efficiency.trend is None:
            parts.append("样本较少，暂不判断趋势")
        # stable 不显示：趋势平稳时多一行文字只会稀释重点
        return "｜".join(parts)

    @staticmethod
    def _trendPercent(ratio: Optional[float]) -> int:
        """
        把 fast/slow 比值换算成相对 30 天值的百分比变化（四舍五入取整）。

        Args:
            ratio: fast/slow 比值；None 视为 0。

        Returns:
            百分比整数，例如 1.32 → 32，0.82 → -18。
        """
        if ratio is None:
            return 0
        return int(round((ratio - 1) * 100))

    def _buildQualityTooltipPart(self, efficiency: ExpEfficiency) -> str:
        """
        生成 tooltip 第 3 段：缺口、数据新鲜度、累计对照与异常隔离。

        Args:
            efficiency: 指级效率结果。

        Returns:
            单行提示。
        """
        parts = []
        if (
            efficiency.gap_days is not None
            and efficiency.gap_days >= EXP_EFFICIENCY_GAP_HINT_DAYS
        ):
            parts.append(f"窗口内最大缺口 {efficiency.gap_days:.1f} 天")
        parts.append(f"数据截止 {self._formatTooltipMoment(efficiency.end_time)}")
        if (
            efficiency.stale_days is not None
            and efficiency.stale_days >= EXP_EFFICIENCY_STALE_DAYS
        ):
            parts.append(f"数据已 {efficiency.stale_days} 天未更新")
        if efficiency.cumulative_rate is not None:
            parts.append(f"累计日均 {formatExact(efficiency.cumulative_rate)}{EXP_EFFICIENCY_UNIT}")
        if efficiency.invalid_count:
            if self._latestSnapshotIsolated(efficiency):
                parts.append("最新快照异常，已按上一条计算")
            else:
                parts.append(f"已隔离 {efficiency.invalid_count} 条异常快照")
        return "｜".join(parts)

    def _latestSnapshotIsolated(self, efficiency: ExpEfficiency) -> bool:
        """
        判断被隔离的异常里是否包含"最新一条"快照。

        Args:
            efficiency: 指级效率结果。

        Returns:
            最新快照是否晚于已采用的右端点。
        """
        if not efficiency.invalid_count or not efficiency.end_time:
            return False
        latest = self.getLatestSnapshot()
        if latest is None:
            return False
        latest_moment = datetime.strptime(latest.statistics_date, STATISTICS_DATETIME_FORMAT)
        end_moment = datetime.strptime(efficiency.end_time, STATISTICS_DATETIME_FORMAT)
        return latest_moment > end_moment

    # ----------------------------------------------------- 目标等级预测（#35）

    def getTargetLevelProjection(self, target_level: int) -> TargetLevelProjection:
        """
        计算到达指定目标等级还需的经验与预计时间（#35）。

        口径：`remaining(T) = cum(T-1) − absolute(当前)`；主值仍用 30 天日均，
        另给 90 天长期参考；趋势明确时追加近期情景。不输出区间、不写库。

        Args:
            target_level: 目标等级（1～200）。

        Returns:
            预测结果；已达成 / 基准缺失 / 速率缺失时在 `degraded_reason` 说明。

        Raises:
            ValidationError: 目标等级越界时抛出。
        """
        self._validateTargetLevel(target_level)
        return self._buildProjection(self.getLatestSnapshot(), target_level)

    def listTargetLevelProjections(
        self, targets: Optional[Sequence[int]] = None
    ) -> List[TargetLevelProjection]:
        """
        批量计算里程碑目标等级（默认 `COMMANDER_TARGET_LEVEL_MILESTONES`）。

        最新快照只取一次，避免 8 个里程碑各查一遍库。

        Args:
            targets: 目标等级序列；None 时取默认里程碑。

        Returns:
            与输入顺序一致的预测结果列表。

        Raises:
            ValidationError: 任一目标等级越界时抛出。
        """
        if targets is None:
            targets = COMMANDER_TARGET_LEVEL_MILESTONES
        latest = self.getLatestSnapshot()
        projections: List[TargetLevelProjection] = []
        for target in targets:
            self._validateTargetLevel(target)
            projections.append(self._buildProjection(latest, target))
        return projections

    @staticmethod
    def _validateTargetLevel(target_level: int) -> None:
        """
        校验目标等级范围。

        Args:
            target_level: 目标等级。

        Raises:
            ValidationError: 越界时抛出。
        """
        if target_level < COMMANDER_LEVEL_MIN or target_level > COMMANDER_LEVEL_MAX:
            raise ValidationError(
                f"目标等级必须在 {COMMANDER_LEVEL_MIN}～{COMMANDER_LEVEL_MAX} 之间"
            )

    def _buildProjection(
        self,
        latest: Optional[CommanderSnapshotModel],
        target_level: int,
    ) -> TargetLevelProjection:
        """
        基于已取到的最新快照构造预测（不查快照表）。

        Args:
            latest: 最新快照；None 表示无数据。
            target_level: 已校验的目标等级。

        Returns:
            预测结果。
        """
        if latest is None:
            return TargetLevelProjection(
                target_level=target_level,
                degraded_reason="暂无指挥官快照，请先录入等级",
            )

        level = latest.commander_level
        absolute = self.getAbsoluteExp(level, latest.commander_exp)
        projection = TargetLevelProjection(
            target_level=target_level,
            current_level=level,
            current_exp=latest.commander_exp,
            current_absolute_exp=absolute,
        )

        if level >= COMMANDER_LEVEL_MAX:
            projection.remaining_exp = 0
            projection.degraded_reason = "已满级"
            return projection
        if target_level < level:
            projection.remaining_exp = 0
            projection.degraded_reason = "目标低于当前等级"
            return projection
        if target_level == level:
            projection.remaining_exp = 0
            projection.degraded_reason = "已在该等级"
            return projection
        if absolute is None:
            projection.degraded_reason = "缺少当前等级的基准数据"
            return projection

        requirement = self.getLevelRequirement(target_level - 1)
        if requirement is None or requirement.cumulative_exp is None:
            projection.degraded_reason = "缺少该等级的基准数据"
            return projection

        projection.target_absolute_exp = int(requirement.cumulative_exp)
        projection.remaining_exp = max(0, projection.target_absolute_exp - absolute)
        self._fillProjectionDurations(projection)
        return projection

    def _fillProjectionDurations(self, projection: TargetLevelProjection) -> None:
        """
        填充预测结果的天数与预计日期（就地修改）。

        仅在 `remaining_exp` 已算出的前提下调用；速率不足时只写降级原因，
        不伪造天数或日期。

        Args:
            projection: 待填充的预测结果。
        """
        if projection.remaining_exp is None:
            return

        efficiency = self.getExpEfficiency()
        rate = efficiency.rate_per_day
        if not rate or rate <= 0:
            projection.degraded_reason = "指级效率数据不足，暂无法估算天数"
            return

        projection.days_slow = projection.remaining_exp / rate
        projection.estimated_date = (
            time_source.today() + timedelta(days=round(projection.days_slow))
        ).strftime(RECORD_DATE_FORMAT)

        long_rate = efficiency.long_rate_per_day
        if long_rate and long_rate > 0:
            projection.days_long = projection.remaining_exp / long_rate

        if efficiency.trend in (TREND_ACCELERATING, TREND_DECELERATING):
            fast = efficiency.fast_rate_per_day
            if fast and fast > 0:
                projection.days_fast = projection.remaining_exp / fast

    def _normalize(self, snapshot: CommanderSnapshotModel) -> CommanderSnapshotModel:
        """
        校验并规范化快照字段（时间补齐为 ``yyyy-MM-dd HH:mm``）。

        Args:
            snapshot: 原始快照模型。

        Returns:
            规范化后的快照模型。

        Raises:
            ValidationError: 当时间格式不合法时抛出。
        """
        parsed = self._parseStatisticsDate(snapshot.statistics_date)
        normalized = CommanderSnapshotModel(
            id=snapshot.id,
            statistics_date=parsed.strftime(STATISTICS_DATETIME_FORMAT),
            commander_level=int(snapshot.commander_level),
            commander_exp=int(snapshot.commander_exp),
        )
        return normalized

    def _validateSnapshot(self, snapshot: CommanderSnapshotModel) -> None:
        """
        校验快照字段。

        Args:
            snapshot: 待校验快照。

        Raises:
            ValidationError: 任一规则不满足时抛出。
        """
        parsed = self._parseStatisticsDate(snapshot.statistics_date)
        if parsed > time_source.now():
            raise ValidationError("不能录入未来时间的快照")

        level = int(snapshot.commander_level)
        if level < COMMANDER_LEVEL_MIN or level > COMMANDER_LEVEL_MAX:
            raise ValidationError(
                f"指挥官等级必须在 {COMMANDER_LEVEL_MIN}～{COMMANDER_LEVEL_MAX} 之间"
            )

        exp = int(snapshot.commander_exp)
        if exp < 0:
            raise ValidationError("当前等级经验不能为负数")

        requirement = self.getLevelRequirement(level)
        if requirement is not None and requirement.level_up_exp is not None:
            if exp > requirement.level_up_exp:
                raise ValidationError(
                    f"{level} 级本级需求经验为 {formatExact(requirement.level_up_exp)}，"
                    f"当前经验不能超过该值（建议先升级）"
                )

    def _parseStatisticsDate(self, value: str) -> datetime:
        """
        解析快照时间。

        Args:
            value: 时间字符串，格式 ``yyyy-MM-dd HH:mm``。

        Returns:
            datetime 对象。

        Raises:
            ValidationError: 当格式不匹配时抛出。
        """
        if not value or not str(value).strip():
            raise ValidationError("记录时间不能为空")

        text = str(value).strip()
        try:
            return datetime.strptime(text, STATISTICS_DATETIME_FORMAT)
        except ValueError:
            raise ValidationError(f"记录时间格式应为 yyyy-MM-dd HH:mm，实际为：{text}")
