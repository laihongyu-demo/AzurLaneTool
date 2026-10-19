"""
指挥官服务模块。

提供指挥官等级快照的录入、查询与看板展示文本。

命名沿用项目既有约定（View → Service → Repository），业务校验统一抛
:class:`ValidationError`，数据库异常统一转为 :class:`DatabaseError`。
"""

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional, Tuple

from models.commander_model import CommanderLevelExpModel, CommanderSnapshotModel
from repositories.commander_repository import CommanderRepository
from utils import time_source
from utils.constants import (
    COMMANDER_LEVEL_MAX, COMMANDER_LEVEL_MIN, COMMANDER_SNAPSHOT_RECENT_LIMIT,
    EXP_EFFICIENCY_MIN_SAMPLES, EXP_EFFICIENCY_UNIT, EXP_EFFICIENCY_WINDOW_DAYS,
    STATISTICS_DATETIME_FORMAT,
)
from utils.db_schema import isMissingColumnError, isMissingTableError
from utils.exceptions import DatabaseError, ValidationError
from utils.unit_formatter import formatExact


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
class ExpEfficiency:
    """
    指级效率计算结果（#16）。

    口径：最近 `EXP_EFFICIENCY_WINDOW_DAYS` 天内的「绝对经验差 ÷ 实际跨度」。
    右端点取**最新快照**而非今天，避免"很久没记录"被当成"没肝"。

    Attributes:
        rate_per_day: 日均经验；降级时为 None。
        start_time: 区间起点快照时刻（``yyyy-MM-dd HH:mm``）。
        end_time: 区间终点（最新快照）时刻。
        span_days: 实际跨度（天，含小数）。
        sample_count: 区间内去重后的快照条数。
        cumulative_rate: 全程日均（首条到末条），供 tooltip 对照；样本不足时为 None。
        skipped: 因等级无法换算而被跳过的快照条数。
        degraded_reason: 降级原因；正常时为 None。
    """

    rate_per_day: Optional[int] = None
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    span_days: Optional[float] = None
    sample_count: int = 0
    cumulative_rate: Optional[int] = None
    skipped: int = 0
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
        # 指级效率的中间结果：一次刷新会取卡片文本、卡片提示与升级预估三次，
        # 快照写入（本服务内）后失效，避免重复扫描全部快照。
        self._efficiency_cache: Optional[ExpEfficiency] = None

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

    def getCommanderLevelCardTooltip(self) -> str:
        """
        生成「指挥官等级」看板卡片悬停提示。

        卡片本身已经展示「等级（当前经验/需求经验）」，所以提示里不再重复这三项，
        只补充升级还差多少、进度、按当前效率预计还要多少天，以及记录时间。

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
        estimate = self._formatUpgradeEstimate(overview.remaining_exp)
        if estimate:
            parts.append(estimate)
        parts.append(f"记录于 {latest.statistics_date}")
        return "｜".join(parts)

    def _formatUpgradeEstimate(self, remaining_exp: Optional[int]) -> Optional[str]:
        """
        按当前指级效率估算升级所需天数。

        效率取「近 30 天日均」（与指级效率卡同源）；数据不足以算效率时给出占位，
        而不是悄悄省略这一项。

        Args:
            remaining_exp: 本级还差多少经验；None 表示基准缺失。

        Returns:
            形如 ``预期升级 22.0 天`` 的片段；无法给出时返回占位或 None。
        """
        if remaining_exp is None:
            return None
        if remaining_exp <= 0:
            return "已满级"

        rate = self.getExpEfficiency().rate_per_day
        if not rate or rate <= 0:
            return "预期升级 —"
        return f"预期升级 {remaining_exp / rate:.1f} 天"

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

        一次刷新会取卡片文本、卡片提示与升级预估共三次，缓存后只扫描一遍快照；
        通过本服务写入快照时缓存失效。

        Returns:
            计算结果；数据不足或异常时 `rate_per_day` 为 None 并给出 `degraded_reason`。
        """
        if self._efficiency_cache is None:
            self._efficiency_cache = self._computeExpEfficiency()
        return self._efficiency_cache

    def _invalidateEfficiencyCache(self) -> None:
        """快照发生写入后丢弃指级效率缓存。"""
        self._efficiency_cache = None

    def _computeExpEfficiency(self) -> ExpEfficiency:
        """
        实际计算指级效率（不做缓存）。

        Returns:
            计算结果。
        """
        points, skipped = self._collectAbsolutePoints()

        if not points:
            return ExpEfficiency(
                skipped=skipped,
                degraded_reason="暂无快照，请先录入指挥官等级",
            )
        if len(points) < EXP_EFFICIENCY_MIN_SAMPLES:
            return ExpEfficiency(
                sample_count=len(points),
                skipped=skipped,
                degraded_reason=f"至少需要两条可换算的快照（当前 {len(points)} 条）",
            )

        end_time, end_absolute = points[-1]
        cutoff = end_time - timedelta(days=EXP_EFFICIENCY_WINDOW_DAYS)

        start: Optional[Tuple[datetime, int]] = None
        for moment, absolute in points:
            if moment <= cutoff:
                start = (moment, absolute)
            else:
                break

        if start is None:
            # 全部历史都在窗口内：用最早的一条，跨度自然小于窗口
            start = points[0]

        start_time, start_absolute = start
        span_days = (end_time - start_time).total_seconds() / 86400
        if span_days <= 0:
            return ExpEfficiency(
                start_time=start_time.strftime(STATISTICS_DATETIME_FORMAT),
                end_time=end_time.strftime(STATISTICS_DATETIME_FORMAT),
                span_days=span_days,
                sample_count=len(points),
                skipped=skipped,
                degraded_reason="区间跨度不足一天",
            )

        delta = end_absolute - start_absolute
        if delta < 0:
            return ExpEfficiency(
                start_time=start_time.strftime(STATISTICS_DATETIME_FORMAT),
                end_time=end_time.strftime(STATISTICS_DATETIME_FORMAT),
                span_days=span_days,
                sample_count=len(points),
                skipped=skipped,
                degraded_reason="最近快照的绝对经验低于区间起点，疑似录入错误",
            )

        sample_count = sum(1 for moment, _ in points if start_time <= moment <= end_time)
        return ExpEfficiency(
            rate_per_day=int(round(delta / span_days)),
            start_time=start_time.strftime(STATISTICS_DATETIME_FORMAT),
            end_time=end_time.strftime(STATISTICS_DATETIME_FORMAT),
            span_days=span_days,
            sample_count=sample_count,
            cumulative_rate=self._buildCumulativeRate(points[0], points[-1]),
            skipped=skipped,
        )

    def _collectAbsolutePoints(self) -> Tuple[List[Tuple[datetime, int]], int]:
        """
        读取全部快照、换算绝对经验并按天去重。

        Returns:
            (按时间升序且同日去重的 (时刻, 绝对经验) 列表, 被跳过的快照条数)。
        """
        points: List[Tuple[datetime, int]] = []
        skipped = 0
        try:
            snapshots = self._commander_repository.findAll()
        except DatabaseError as e:
            # 旧库 / 空库没有指挥官表：按"无快照"降级，不让整块看板报错
            if isMissingTableError(e) or isMissingColumnError(e):
                return [], 0
            raise

        for snapshot in reversed(snapshots):
            absolute = self.getAbsoluteExp(snapshot.commander_level, snapshot.commander_exp)
            if absolute is None:
                skipped += 1
                continue
            moment = datetime.strptime(snapshot.statistics_date, STATISTICS_DATETIME_FORMAT)
            points.append((moment, absolute))

        # 同一天只保留最后一条：最后一条的绝对经验已包含当天更早记录的全部增量
        by_day: Dict[date, Tuple[datetime, int]] = {}
        for moment, absolute in points:
            by_day[moment.date()] = (moment, absolute)
        return [by_day[day] for day in sorted(by_day)], skipped

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
        生成「指级效率」看板卡片悬停提示。

        Returns:
            正常时形如「近 30 天日均｜2026-09-16 18:42 → 2026-10-18 14:01（31.8 天，7 条快照）
            ｜累计日均 9,522/天」；降级时说明原因与口径。
        """
        efficiency = self.getExpEfficiency()
        window = f"近 {EXP_EFFICIENCY_WINDOW_DAYS} 天日均"
        if efficiency.rate_per_day is None:
            reason = efficiency.degraded_reason or "数据不足"
            return f"指级效率：{reason}｜口径：{window}（绝对经验差 ÷ 实际跨度）"

        parts = [
            window,
            f"{efficiency.start_time} → {efficiency.end_time}"
            f"（{efficiency.span_days:.1f} 天，{efficiency.sample_count} 条快照）",
        ]
        if efficiency.sample_count < 3:
            parts.append("样本较少，仅供参考")
        if efficiency.cumulative_rate is not None:
            parts.append(f"累计日均 {formatExact(efficiency.cumulative_rate)}{EXP_EFFICIENCY_UNIT}")
        return "｜".join(parts)

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
