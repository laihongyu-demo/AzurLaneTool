"""
指挥官服务模块。

提供指挥官等级快照的录入、查询与看板展示文本。

命名沿用项目既有约定（View → Service → Repository），业务校验统一抛
:class:`ValidationError`，数据库异常统一转为 :class:`DatabaseError`。
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Optional

from models.commander_model import CommanderLevelExpModel, CommanderSnapshotModel
from repositories.commander_repository import CommanderRepository
from utils.constants import (
    COMMANDER_LEVEL_MAX, COMMANDER_LEVEL_MIN, COMMANDER_SNAPSHOT_RECENT_LIMIT,
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
        progress_rate: 本级进度百分比（0～100）；无基准时为 None。
        snapshot_date: 数据来源的记录时间。
    """

    level: int
    current_exp: int
    required_exp: Optional[int] = None
    cumulative_exp: Optional[int] = None
    progress_rate: Optional[float] = None
    snapshot_date: str = ""


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
        查询指定等级的升级经验基准。

        Args:
            level: 等级。

        Returns:
            基准模型实例；无该等级或表缺失时返回 None。
        """
        try:
            return self._commander_repository.findLevelExp(level)
        except DatabaseError as e:
            if isMissingTableError(e) or isMissingColumnError(e):
                return None
            raise

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

        return CommanderLevelOverview(
            level=level,
            current_exp=current_exp,
            required_exp=required,
            cumulative_exp=cumulative,
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

        Returns:
            提示文本，包含记录时间与累计经验。
        """
        latest = self.getLatestSnapshot()
        if latest is None:
            return "指挥官等级：暂无记录，请在「资源统计」页签录入快照"

        overview = self.getLevelOverview(latest.commander_level, latest.commander_exp)
        parts = [
            f"指挥官等级 {latest.commander_level}",
            f"当前经验 {formatExact(latest.commander_exp)}",
        ]
        if overview.required_exp is not None:
            parts.append(f"本级需求 {formatExact(overview.required_exp)}")
        if overview.progress_rate is not None:
            parts.append(f"进度 {overview.progress_rate:.1f}%")
        parts.append(f"记录于 {latest.statistics_date}")
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
        if parsed > datetime.now():
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
