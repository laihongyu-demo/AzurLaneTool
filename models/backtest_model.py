"""
回测运行记录的数据模型（#35 P2）。

只描述持久化结构，不含 IO 与业务判断；JSON 读写由
:class:`repositories.backtest_state_repository.BacktestStateRepository` 负责。
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class BacktestEventRecord:
    """
    一次「经验获取大幅偏离」事件记录。

    事件只用于提示复核，不参与主值、不自动改常量。

    Attributes:
        direction: ``up``（加速）/ ``down``（放缓）。
        strength: ``normal``（±25% 持续 5 天）/ ``strong``（±50% 持续 3 天）。
        start_date: 事件首日（``yyyy-MM-dd``）。
        end_date: 事件末日。
        days: 持续的自然日数。
        peak_ratio: 事件期间最大 |fast/slow| 偏离比值。
        slow_start: 事件首日的 30 天日均。
        slow_end: 事件末日（复核时）的 30 天日均。
        sample_count: 事件期间的快照条数。
        handled_at: 人工标记复核的时间；None 表示待复核。
    """

    direction: str
    strength: str
    start_date: str
    end_date: str
    days: int = 0
    peak_ratio: float = 1.0
    slow_start: int = 0
    slow_end: int = 0
    sample_count: int = 0
    handled_at: Optional[str] = None

    def toDict(self) -> Dict[str, Any]:
        """
        转换为可 JSON 序列化的字典。

        Returns:
            字段字典。
        """
        return {
            "direction": self.direction,
            "strength": self.strength,
            "start_date": self.start_date,
            "end_date": self.end_date,
            "days": self.days,
            "peak_ratio": self.peak_ratio,
            "slow_start": self.slow_start,
            "slow_end": self.slow_end,
            "sample_count": self.sample_count,
            "handled_at": self.handled_at,
        }

    @classmethod
    def fromDict(cls, data: Dict[str, Any]) -> "BacktestEventRecord":
        """
        从字典恢复事件记录；缺失字段用默认值兜底。

        Args:
            data: 字段字典。

        Returns:
            事件记录。
        """
        return cls(
            direction=str(data.get("direction", "")),
            strength=str(data.get("strength", "normal")),
            start_date=str(data.get("start_date", "")),
            end_date=str(data.get("end_date", "")),
            days=int(data.get("days", 0) or 0),
            peak_ratio=float(data.get("peak_ratio", 1.0) or 1.0),
            slow_start=int(data.get("slow_start", 0) or 0),
            slow_end=int(data.get("slow_end", 0) or 0),
            sample_count=int(data.get("sample_count", 0) or 0),
            handled_at=data.get("handled_at") or None,
        )


@dataclass
class BacktestState:
    """
    上次回测的运行记录（本地 JSON）。

    Attributes:
        last_run_at: 上次运行时刻（``yyyy-MM-dd HH:mm``）。
        points_at_run: 运行时的有效快照条数。
        latest_snapshot_at: 运行时最新快照时刻。
        constants: 运行时的关键常量快照，便于回溯“当时用的哪套口径”。
        summary: 运行时摘要（slow / fast / MAPE 等）。
        report_path: 报告文件路径（本机 ``data/backtest/``）。
        events: 近期事件（含已复核标记）。
    """

    last_run_at: Optional[str] = None
    points_at_run: int = 0
    latest_snapshot_at: Optional[str] = None
    constants: Dict[str, float] = field(default_factory=dict)
    summary: Dict[str, float] = field(default_factory=dict)
    report_path: Optional[str] = None
    events: List[BacktestEventRecord] = field(default_factory=list)

    def toDict(self) -> Dict[str, Any]:
        """
        转换为可 JSON 序列化的字典。

        Returns:
            字段字典。
        """
        return {
            "last_run_at": self.last_run_at,
            "points_at_run": self.points_at_run,
            "latest_snapshot_at": self.latest_snapshot_at,
            "constants": dict(self.constants),
            "summary": dict(self.summary),
            "report_path": self.report_path,
            "events": [event.toDict() for event in self.events],
        }

    @classmethod
    def fromDict(cls, data: Dict[str, Any]) -> "BacktestState":
        """
        从字典恢复运行记录；结构损坏时按空记录处理。

        Args:
            data: 字段字典。

        Returns:
            运行记录。
        """
        if not isinstance(data, dict):
            return cls()
        events = [
            BacktestEventRecord.fromDict(item)
            for item in data.get("events", [])
            if isinstance(item, dict)
        ]
        return cls(
            last_run_at=data.get("last_run_at") or None,
            points_at_run=int(data.get("points_at_run", 0) or 0),
            latest_snapshot_at=data.get("latest_snapshot_at") or None,
            constants=dict(data.get("constants") or {}),
            summary=dict(data.get("summary") or {}),
            report_path=data.get("report_path") or None,
            events=events,
        )
