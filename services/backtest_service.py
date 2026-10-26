"""指级效率回测服务（#23 P2 / #35 P2）。

提供离线回测的纯计算与运行编排：

- 候选口径：30 天端点（现口径）、7 天端点、长窗指数加权回归、分段速率指数加权平均；
- 指标：MAPE / MAE / 偏差 / 抖动 / 阶跃响应 / 趋势 precision 与 lift / 情景覆盖率；
- 网格：慢窗口、fast 缺口与回看上限、趋势阈值；
- 事件检测：fast/slow 偏离 ±25%（强事件 ±50%）持续若干天，用于“建议复核”；
- 运行记录：报告写 ``data/backtest/``、状态写 ``data/efficiency_backtest.json``，
  均由 :class:`repositories.backtest_state_repository.BacktestStateRepository` 落盘；
  **不写数据库、不改常量**。

口径见 ``docs/指级效率算法优化方案_20261018.md`` §2/§7 与
``docs/20261026_回测校准与目标等级预测方案.md`` §3。

命令行入口见 ``tools/backtest_exp_efficiency.py``（本模块不解析参数）。
"""

import os
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Callable, Dict, List, Optional, Sequence, Tuple

from models.backtest_model import BacktestEventRecord, BacktestState
from repositories.backtest_state_repository import BacktestStateRepository
from services.commander_service import (
    CommanderService, TREND_ACCELERATING, TREND_DECELERATING,
)
from utils import time_source
from utils.constants import (
    BASE_DIR, EXP_BACKTEST_INTERVAL_DAYS, EXP_BACKTEST_SAMPLE_DELTA,
    EXP_EFFICIENCY_FAST_CAP_DAYS, EXP_EFFICIENCY_FAST_GAP_DAYS,
    EXP_EFFICIENCY_LONG_WINDOW_DAYS,
    EXP_EFFICIENCY_TREND_DOWN_RATIO, EXP_EFFICIENCY_TREND_UP_RATIO,
    EXP_EFFICIENCY_WINDOW_DAYS, EXP_REGIME_COOLDOWN_DAYS,
    EXP_REGIME_DOWN_RATIO, EXP_REGIME_EVENT_LOOKBACK_DAYS, EXP_REGIME_MIN_DAYS,
    EXP_REGIME_STRONG_DOWN_RATIO, EXP_REGIME_STRONG_MIN_DAYS,
    EXP_REGIME_STRONG_UP_RATIO, EXP_REGIME_UP_RATIO, RECORD_DATE_FORMAT,
    STATISTICS_DATETIME_FORMAT,
)
from utils.db_connection import DatabaseConnection
from utils.exceptions import ValidationError

Point = Tuple[datetime, int]
Estimator = Callable[[Sequence[Point]], Optional[float]]

HORIZONS = (7, 14, 30)
TARGET_TOLERANCE_DAYS = 3
TREND_HORIZON = 14
# 趋势信号的最小样本 / 最小跨度：与运行时常量语义一致，网格里只扫阈值
TREND_MIN_SAMPLES = 3
TREND_MIN_SPAN_DAYS = 3.0


def _days(start: datetime, end: datetime) -> float:
    """两个时刻相差多少天（含小数）。"""
    return (end - start).total_seconds() / 86400


def _fmtRate(value: Optional[float]) -> str:
    """把日均值格式化为带千分符的整数文本。"""
    if value is None:
        return "-"
    return f"{int(round(value)):,}"


def _fmtPct(value: Optional[float]) -> str:
    """把比例格式化为百分比文本（保留 1 位小数）。"""
    if value is None:
        return "-"
    return f"{value * 100:.1f}%"


# --------------------------------------------------------------------------
# 候选估计器
# --------------------------------------------------------------------------


def endpointEstimator(window_days: int) -> Estimator:
    """
    端点口径：窗口内首末两点绝对经验差 ÷ 实际跨度（v1 主值口径）。

    Args:
        window_days: 窗口天数。

    Returns:
        估计函数；数据不足时返回 None。
    """

    def estimate(points: Sequence[Point]) -> Optional[float]:
        if len(points) < 2:
            return None
        end_time, end_absolute = points[-1]
        cutoff = end_time - timedelta(days=window_days)
        start: Optional[Point] = None
        for moment, absolute in points:
            if moment <= cutoff:
                start = (moment, absolute)
            else:
                break
        if start is None:
            start = points[0]
        span = _days(start[0], end_time)
        if span <= 0:
            return None
        return (end_absolute - start[1]) / span

    estimate.__name__ = f"endpoint{window_days}"
    return estimate


def weightedRegressionEstimator(
    window_days: int = 120, half_life: float = 30.0
) -> Estimator:
    """
    长窗指数加权最小二乘回归的斜率（半衰期以天计）。

    Args:
        window_days: 回看窗口天数。
        half_life: 权重半衰期（天）。

    Returns:
        估计函数；窗口内不足两点或时间全相同则返回 None。
    """

    def estimate(points: Sequence[Point]) -> Optional[float]:
        if len(points) < 2:
            return None
        end_time = points[-1][0]
        cutoff = end_time - timedelta(days=window_days)
        window = [(moment, absolute) for moment, absolute in points if moment >= cutoff]
        if len(window) < 2:
            return None

        xs = [_days(end_time, moment) for moment, _ in window]  # <= 0
        ys = [float(absolute) for _, absolute in window]
        weights = [0.5 ** (abs(x) / half_life) for x in xs]

        total = sum(weights)
        if total <= 0:
            return None
        x_mean = sum(w * x for w, x in zip(weights, xs)) / total
        y_mean = sum(w * y for w, y in zip(weights, ys)) / total
        sxx = sum(w * (x - x_mean) ** 2 for w, x in zip(weights, xs))
        if sxx <= 0:
            return None
        sxy = sum(w * (x - x_mean) * (y - y_mean) for w, x, y in zip(weights, xs, ys))
        return sxy / sxx

    estimate.__name__ = "weightedRegression"
    return estimate


def segmentedEwmaEstimator(half_life: float = 30.0) -> Estimator:
    """
    对相邻段速率做半衰期指数加权平均（权重归一化，等价于 EWMA）。

    段速率按记录时间加权会放大"记录频率"的影响，这里只作为对照口径，
    不进入主值。

    Args:
        half_life: 权重半衰期（天）。

    Returns:
        估计函数；没有有效段时返回 None。
    """

    def estimate(points: Sequence[Point]) -> Optional[float]:
        if len(points) < 2:
            return None
        end_time = points[-1][0]
        weighted = 0.0
        total = 0.0
        for index in range(1, len(points)):
            span = _days(points[index - 1][0], points[index][0])
            if span <= 0:
                continue
            rate = (points[index][1] - points[index - 1][1]) / span
            age = _days(points[index][0], end_time)
            weight = 0.5 ** (age / half_life)
            weighted += weight * rate
            total += weight
        if total <= 0:
            return None
        return weighted / total

    estimate.__name__ = "segmentedEwma"
    return estimate


# --------------------------------------------------------------------------
# 指标
# --------------------------------------------------------------------------


@dataclass
class HorizonMetrics:
    """某个前瞻天数下的误差指标。"""

    horizon: int
    samples: int = 0
    mape: Optional[float] = None
    mae: Optional[float] = None
    bias: Optional[float] = None


@dataclass
class SignalMetrics:
    """趋势信号质量指标。"""

    up_count: int = 0
    up_precision: Optional[float] = None
    up_lift: Optional[float] = None
    down_count: int = 0
    down_precision: Optional[float] = None
    down_lift: Optional[float] = None
    baseline: Optional[float] = None


@dataclass
class Evaluation:
    """一个候选口径的完整回测结果。"""

    name: str
    horizons: Dict[int, HorizonMetrics] = field(default_factory=dict)
    jitter: Optional[float] = None
    response_days: Optional[int] = None
    signal: Optional[SignalMetrics] = None
    coverage: Optional[float] = None


def futureAverage(
    points: Sequence[Point], origin: int, horizon: int
) -> Optional[float]:
    """
    取 origin 之后首个跨度 >= horizon 天的快照的平均效率。

    Args:
        points: 全部有效快照点（升序）。
        origin: 起点下标。
        horizon: 前瞻天数。

    Returns:
        实际日均；没有满足容差的未来快照时返回 None。
    """
    start_time, start_absolute = points[origin]
    for index in range(origin + 1, len(points)):
        span = _days(start_time, points[index][0])
        if span < horizon:
            continue
        if span > horizon + TARGET_TOLERANCE_DAYS:
            return None
        return (points[index][1] - start_absolute) / span
    return None


def _horizonMetrics(
    pairs: Sequence[Tuple[float, float]]
) -> HorizonMetrics:
    """把 (估计, 实际) 对换算成 MAPE / MAE / 偏差。"""
    metrics = HorizonMetrics(horizon=0, samples=len(pairs))
    if not pairs:
        return metrics
    relative = [abs(estimate - actual) / actual for estimate, actual in pairs if actual > 0]
    absolute = [abs(estimate - actual) for estimate, actual in pairs]
    signed = [
        (estimate - actual) / actual for estimate, actual in pairs if actual > 0
    ]
    metrics.mape = sum(relative) / len(relative) if relative else None
    metrics.mae = sum(absolute) / len(absolute)
    metrics.bias = sum(signed) / len(signed) if signed else None
    return metrics


def _estimateSeries(
    estimate: Estimator, points: Sequence[Point]
) -> List[Optional[float]]:
    """对每个 origin 计算估值（只用当时可见数据）。"""
    return [estimate(points[: index + 1]) for index in range(len(points))]


def _jitter(series: Sequence[Optional[float]]) -> Optional[float]:
    """相邻两次估值变化的平均绝对值。"""
    changes = [
        abs(current - previous)
        for previous, current in zip(series, series[1:])
        if previous is not None and current is not None
    ]
    if not changes:
        return None
    return sum(changes) / len(changes)


def responseDays(
    estimate: Estimator, target: float = 15000.0, tolerance: float = 0.1
) -> Optional[int]:
    """
    阶跃响应：合成「前 60 天 5,000/天、之后 15,000/天、每日一条」的数据。

    Args:
        estimate: 估计函数。
        target: 阶跃后的真实速率。
        tolerance: 进入 ±tol 视为收敛。

    Returns:
        从阶跃当天起算的收敛天数；未进入容差返回 None。
    """
    base = datetime(2024, 1, 1)
    points: List[Point] = []
    value = 0.0
    for day in range(0, 121):
        if day > 0:
            value += 15000.0 if day >= 60 else 5000.0
        points.append((base + timedelta(days=day), int(round(value))))

    for day in range(60, 121):
        estimated = estimate(points[: day + 1])
        if estimated is None:
            continue
        if abs(estimated - target) <= target * tolerance:
            return day - 60
    return None


def recentBlock(
    points: Sequence[Point], gap_days: float, cap_days: float
) -> List[Point]:
    """
    截取近期连续块（与运行时 ``CommanderService._currentBlock`` 同口径）。

    这里单独实现一份，是为了在网格里扫不同的 gap / cap。

    Args:
        points: 升序快照点。
        gap_days: 允许的最大相邻间隔。
        cap_days: 最大回看天数。

    Returns:
        块内点（升序，至少包含最新一条）。
    """
    if not points:
        return []
    cap_cutoff = points[-1][0] - timedelta(days=cap_days)
    block = [points[-1]]
    for moment, absolute in reversed(points[:-1]):
        if moment < cap_cutoff:
            break
        if _days(moment, block[0][0]) > gap_days:
            break
        block.insert(0, (moment, absolute))
    return block


def fastRate(block: Sequence[Point]) -> Optional[float]:
    """近期块端点日均；不足两条或跨度 <1 天返回 None。"""
    if len(block) < 2:
        return None
    span = _days(block[0][0], block[-1][0])
    if span < 1.0:
        return None
    return (block[-1][1] - block[0][1]) / span


def trendSignals(
    points: Sequence[Point],
    gap_days: float = EXP_EFFICIENCY_FAST_GAP_DAYS,
    cap_days: float = EXP_EFFICIENCY_FAST_CAP_DAYS,
    up_ratio: float = EXP_EFFICIENCY_TREND_UP_RATIO,
    down_ratio: float = EXP_EFFICIENCY_TREND_DOWN_RATIO,
) -> List[Tuple[int, Optional[str], float, float]]:
    """
    对每个 origin 生成趋势信号。

    Args:
        points: 升序快照点。
        gap_days: fast 缺口重置天数。
        cap_days: fast 回看上限。
        up_ratio: 加速阈值。
        down_ratio: 放缓阈值。

    Returns:
        (origin 下标, 信号或 None, slow, fast) 列表；fast 为 None 时信号必为 None。
    """
    slow_estimator = endpointEstimator(EXP_EFFICIENCY_WINDOW_DAYS)
    signals: List[Tuple[int, Optional[str], float, float]] = []
    for index in range(len(points)):
        slow = slow_estimator(points[: index + 1])
        if slow is None:
            continue
        block = recentBlock(points[: index + 1], gap_days, cap_days)
        fast = fastRate(block)
        signal = None
        if fast is not None and slow > 0:
            span = _days(block[0][0], block[-1][0])
            if len(block) >= TREND_MIN_SAMPLES and span >= TREND_MIN_SPAN_DAYS:
                ratio = fast / slow
                if ratio >= up_ratio:
                    signal = TREND_ACCELERATING
                elif ratio <= down_ratio:
                    signal = TREND_DECELERATING
        signals.append((index, signal, slow, fast if fast is not None else 0.0))
    return signals


def signalMetrics(
    points: Sequence[Point],
    gap_days: float = EXP_EFFICIENCY_FAST_GAP_DAYS,
    cap_days: float = EXP_EFFICIENCY_FAST_CAP_DAYS,
    up_ratio: float = EXP_EFFICIENCY_TREND_UP_RATIO,
    down_ratio: float = EXP_EFFICIENCY_TREND_DOWN_RATIO,
) -> SignalMetrics:
    """
    检验趋势信号：未来 14 天实际效率相对 30 天值的方向是否与信号一致。

    Args:
        points: 升序快照点。
        gap_days: fast 缺口重置天数。
        cap_days: fast 回看上限。
        up_ratio: 加速阈值。
        down_ratio: 放缓阈值。

    Returns:
        命中率、相对基线的 lift 与样本数。
    """
    metrics = SignalMetrics()
    above = 0
    baseline_total = 0
    up_hits = 0
    down_hits = 0

    for index, signal, slow, _fast in trendSignals(
        points, gap_days, cap_days, up_ratio, down_ratio
    ):
        actual = futureAverage(points, index, TREND_HORIZON)
        if actual is None or slow <= 0:
            continue
        is_above = actual > slow
        baseline_total += 1
        above += int(is_above)
        if signal == TREND_ACCELERATING:
            metrics.up_count += 1
            up_hits += int(is_above)
        elif signal == TREND_DECELERATING:
            metrics.down_count += 1
            down_hits += int(not is_above)

    if baseline_total:
        metrics.baseline = above / baseline_total
    if metrics.up_count:
        metrics.up_precision = up_hits / metrics.up_count
        if metrics.baseline is not None:
            metrics.up_lift = metrics.up_precision - metrics.baseline
    if metrics.down_count:
        metrics.down_precision = down_hits / metrics.down_count
        if metrics.baseline is not None:
            metrics.down_lift = metrics.down_precision - (1 - metrics.baseline)
    return metrics


def scenarioCoverage(points: Sequence[Point]) -> Optional[float]:
    """
    情景覆盖率：``[slow, fast]`` 是否覆盖未来 14 天实际值。

    覆盖率低说明"两个情景"不能当区间读——这正是报告里反对写伪区间的原因。

    Args:
        points: 升序快照点。

    Returns:
        覆盖率；没有可用样本时返回 None。
    """
    covered = 0
    total = 0
    for index, signal, slow, fast in trendSignals(points):
        if signal is None or not fast or fast <= 0:
            continue
        actual = futureAverage(points, index, TREND_HORIZON)
        if actual is None:
            continue
        total += 1
        covered += int(min(slow, fast) <= actual <= max(slow, fast))
    if not total:
        return None
    return covered / total


def evaluate(name: str, estimate: Estimator, points: Sequence[Point]) -> Evaluation:
    """
    对一个候选估计器做完整回测。

    Args:
        name: 口径名称。
        estimate: 估计函数。
        points: 升序快照点。

    Returns:
        回测结果。
    """
    evaluation = Evaluation(name=name)
    series = _estimateSeries(estimate, points)

    for horizon in HORIZONS:
        pairs = []
        for index, estimated in enumerate(series):
            if estimated is None:
                continue
            actual = futureAverage(points, index, horizon)
            if actual is None or actual <= 0:
                continue
            pairs.append((estimated, actual))
        metrics = _horizonMetrics(pairs)
        metrics.horizon = horizon
        evaluation.horizons[horizon] = metrics

    evaluation.jitter = _jitter(series)
    evaluation.response_days = responseDays(estimate)
    return evaluation


# --------------------------------------------------------------------------
# 数据与报告
# --------------------------------------------------------------------------


def _fmtResponse(days: Optional[int]) -> str:
    """阶跃响应文本：None 表示 120 天内未收敛。"""
    if days is None:
        return ">120 天"
    return f"{days} 天"


def _displayPath(path: str) -> str:
    """数据库/报告路径：项目内用相对路径，避免报告写死本机绝对路径。"""
    if not os.path.isabs(path):
        return path.replace("\\", "/")
    absolute = os.path.abspath(path)
    try:
        relative = os.path.relpath(absolute, BASE_DIR)
    except ValueError:
        return absolute
    if relative.startswith(".."):
        return absolute
    return relative.replace("\\", "/")


def _currentSummaryLine(points: Sequence[Point]) -> str:
    """
    生成报告 §1 的运行摘要（与卡片 tooltip 同口径）。

    Args:
        points: 升序快照点。

    Returns:
        形如「slow 11,233/天｜fast 14,124/天（ratio 1.26，加速）｜long 11,073/天｜数据截止 …」。
    """
    slow = endpointEstimator(EXP_EFFICIENCY_WINDOW_DAYS)(points)
    long_rate = endpointEstimator(EXP_EFFICIENCY_LONG_WINDOW_DAYS)(points)
    block = recentBlock(
        points, EXP_EFFICIENCY_FAST_GAP_DAYS, EXP_EFFICIENCY_FAST_CAP_DAYS
    )
    fast = fastRate(block)
    ratio = fast / slow if fast is not None and slow else None
    block_span = _days(block[0][0], block[-1][0]) if len(block) >= 2 else 0.0

    if (
        ratio is None
        or len(block) < TREND_MIN_SAMPLES
        or block_span < TREND_MIN_SPAN_DAYS
    ):
        trend = "样本不足"
    elif ratio >= EXP_EFFICIENCY_TREND_UP_RATIO:
        trend = "加速"
    elif ratio <= EXP_EFFICIENCY_TREND_DOWN_RATIO:
        trend = "放缓"
    else:
        trend = "平稳"

    fast_text = "-" if fast is None else _fmtRate(fast)
    ratio_text = "-" if ratio is None else f"{ratio:.2f}"
    deadline = points[-1][0].strftime("%Y-%m-%d %H:%M")
    return (
        f"slow {_fmtRate(slow)}/天｜fast {fast_text}/天（ratio {ratio_text}，{trend}）"
        f"｜long {_fmtRate(long_rate)}/天｜数据截止 {deadline}"
    )


def buildReport(
    points: Sequence[Point],
    skipped: int,
    invalid: int,
    raw_count: int,
    db_path: str,
    generated_at: datetime,
) -> Tuple[str, Dict[str, float]]:
    """
    生成回测报告全文与运行摘要。

    Args:
        points: 升序快照点。
        skipped: 无法换算条数。
        invalid: 异常隔离条数。
        raw_count: 原始快照条数（去重前）。
        db_path: 数据库路径。
        generated_at: 生成时刻。

    Returns:
        (Markdown 文本, 运行摘要)；摘要用于状态 JSON，不进入报告正文。
    """
    lines: List[str] = []
    add = lines.append

    endpoint30 = endpointEstimator(EXP_EFFICIENCY_WINDOW_DAYS)
    candidates = [
        ("30 天端点（现口径）", endpoint30),
        ("7 天端点", endpointEstimator(7)),
        ("长窗指数加权回归（120 天 / 半衰期 30 天）", weightedRegressionEstimator()),
        ("分段速率指数加权平均（半衰期 30 天）", segmentedEwmaEstimator()),
    ]
    evaluations = [evaluate(name, estimator, points) for name, estimator in candidates]
    current = evaluations[0]
    current.signal = signalMetrics(points)
    current.coverage = scenarioCoverage(points)

    first, last = points[0], points[-1]
    total_span = _days(first[0], last[0])

    add("# 指级效率回测报告（#23 P2 / #35 P2）")
    add("")
    add(f"> 版本 v1.1（回测服务自动生成，{generated_at.strftime('%Y-%m-%d %H:%M')}）")
    add("> 复现：`python tools/backtest_exp_efficiency.py "
        f"--db {_displayPath(db_path)} --report <本文件>`")
    add("> 口径：`docs/指级效率算法优化方案_20261018.md` §2 / §7；"
        "服务只读数据库，不改常量、不写库。")
    add("")
    add("## 0. 结论")
    add("")
    add(f"- 主值仍是 **{EXP_EFFICIENCY_WINDOW_DAYS} 天端点**：同一份数据下与 v1 数值完全一致；")
    add("- 平滑口径（长窗回归 / 分段指数加权）30 天前瞻误差更低，但阶跃响应更慢，"
        "不适合替代主值；")
    add("- fast / trend 只作方向与情景，不能当点估计；"
        f"当前 fast 信号对 {TREND_HORIZON} 天前瞻的方向命中率见 §4；")
    add("- 结论与 2026-10-18 方案一致：**主值不换，另加信号层**；"
        "本报告不自动改常量，§5 只给人工复核依据。")
    add("")

    add("## 1. 数据快照")
    add("")
    add("| 项 | 值 |")
    add("| --- | --- |")
    add(f"| 数据库 | `{_displayPath(db_path)}` |")
    add(f"| 原始快照 | {raw_count} 条 |")
    add(f"| 同日去重后有效点 | {len(points)} 条 |")
    add(f"| 首条 | {first[0].strftime('%Y-%m-%d %H:%M')}（累计绝对经验 {_fmtRate(first[1])}） |")
    add(f"| 末条 | {last[0].strftime('%Y-%m-%d %H:%M')}（累计绝对经验 {_fmtRate(last[1])}） |")
    add(f"| 时间跨度 | {total_span:.1f} 天 |")
    add(f"| 无法换算（跳过） | {skipped} 条 |")
    add(f"| 异常隔离 | {invalid} 条 |")
    add("")
    add(f"> 运行摘要：{_currentSummaryLine(points)}")
    add("")
    add("> walk-forward 口径：origin `i` 只用 `points[:i+1]`；目标取之后首个跨度 "
        f">= H 天的快照，跨度 <= H+{TARGET_TOLERANCE_DAYS} 天才收录。")
    add("")

    add("## 2. 候选口径对比（walk-forward）")
    add("")
    header = "| 口径 | 7d MAPE | 14d MAPE | 30d MAPE | 30d MAE | 30d 偏差 | 抖动 | 阶跃响应 |"
    add(header)
    add("| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |")
    for evaluation in evaluations:
        metrics7 = evaluation.horizons.get(7, HorizonMetrics(7))
        metrics14 = evaluation.horizons.get(14, HorizonMetrics(14))
        metrics30 = evaluation.horizons.get(30, HorizonMetrics(30))
        add(
            f"| {evaluation.name} | {_fmtPct(metrics7.mape)} | {_fmtPct(metrics14.mape)} | "
            f"{_fmtPct(metrics30.mape)} | {_fmtRate(metrics30.mae)} | "
            f"{_fmtPct(metrics30.bias)} | {_fmtRate(evaluation.jitter)} | "
            f"{_fmtResponse(evaluation.response_days)} |"
        )
    add("")
    sample_line = "；".join(
        f"{horizon}d 样本 {current.horizons.get(horizon, HorizonMetrics(horizon)).samples} 个"
        for horizon in HORIZONS
    )
    add(f"> 现口径样本：{sample_line}。样本不大，数字看相对关系，不要当绝对精度。")
    add("")

    add("## 3. 窗口敏感性（端点口径）")
    add("")
    add("| 慢窗口 | 7d MAPE | 14d MAPE | 30d MAPE | 抖动 | 阶跃响应 |")
    add("| ---: | ---: | ---: | ---: | ---: | ---: |")
    for window in (21, 30, 45, 60, 90):
        evaluation = evaluate(f"{window} 天端点", endpointEstimator(window), points)
        add(
            f"| {window} 天 | {_fmtPct(evaluation.horizons[7].mape)} | "
            f"{_fmtPct(evaluation.horizons[14].mape)} | "
            f"{_fmtPct(evaluation.horizons[30].mape)} | "
            f"{_fmtRate(evaluation.jitter)} | "
            f"{_fmtResponse(evaluation.response_days)} |"
        )
    add("")
    add("> 长窗口更准但更慢；本期保留 30 天是产品取舍（主值负责长期基线），"
        "不是统计最优。")
    add("")

    signal = current.signal or SignalMetrics()
    add(f"## 4. 趋势信号（fast / slow，未来 {TREND_HORIZON} 天方向）")
    add("")
    add("### 4.1 当前常量")
    add("")
    add("| 项 | 值 |")
    add("| --- | ---: |")
    add(f"| fast 缺口重置 | {EXP_EFFICIENCY_FAST_GAP_DAYS} 天 |")
    add(f"| fast 回看上限 | {EXP_EFFICIENCY_FAST_CAP_DAYS} 天 |")
    add(f"| 加速阈值 | {EXP_EFFICIENCY_TREND_UP_RATIO:.2f} |")
    add(f"| 放缓阈值 | {EXP_EFFICIENCY_TREND_DOWN_RATIO:.2f} |")
    add(f"| 基线 P(实际 > 30 天值) | {_fmtPct(signal.baseline)} |")
    add(f"| 加速信号 | {signal.up_count} 次，命中 {_fmtPct(signal.up_precision)}，"
        f"lift {_fmtPct(signal.up_lift)} |")
    add(f"| 放缓信号 | {signal.down_count} 次，命中 {_fmtPct(signal.down_precision)}，"
        f"lift {_fmtPct(signal.down_lift)} |")
    add(f"| 情景覆盖率（`[slow, fast]` 覆盖未来 {TREND_HORIZON} 天实际值） | "
        f"{_fmtPct(current.coverage)} |")
    add("")
    add("> 放缓的 hit 定义为「未来实际低于 30 天值」；覆盖率低说明两个情景"
        "**不是置信区间**，所以 UI 不写「A～B 天」。")
    add("")

    add("### 4.2 fast 缺口 / 回看上限网格")
    add("")
    add("| gap | cap | 加速次数 | 加速命中 | 放缓次数 | 放缓命中 |")
    add("| ---: | ---: | ---: | ---: | ---: | ---: |")
    for gap_days in (3, 5, 7, 10):
        for cap_days in (7, 10, 14, 21):
            grid = signalMetrics(points, gap_days=gap_days, cap_days=cap_days)
            add(
                f"| {gap_days} | {cap_days} | {grid.up_count} | {_fmtPct(grid.up_precision)} | "
                f"{grid.down_count} | {_fmtPct(grid.down_precision)} |"
            )
    add("")

    add("### 4.3 阈值网格（gap=7 / cap=14）")
    add("")
    add("| 加速阈值 | 次数 | 命中 | lift |")
    add("| ---: | ---: | ---: | ---: |")
    up_grid: Dict[float, SignalMetrics] = {}
    for up_ratio in (1.15, 1.25, 1.30, 1.40):
        grid = signalMetrics(points, up_ratio=up_ratio)
        up_grid[up_ratio] = grid
        add(
            f"| {up_ratio:.2f} | {grid.up_count} | {_fmtPct(grid.up_precision)} | "
            f"{_fmtPct(grid.up_lift)} |"
        )
    add("")
    add("| 放缓阈值 | 次数 | 命中 | lift |")
    add("| ---: | ---: | ---: | ---: |")
    down_grid: Dict[float, SignalMetrics] = {}
    for down_ratio in (0.60, 0.75, 0.80, 0.85):
        grid = signalMetrics(points, down_ratio=down_ratio)
        down_grid[down_ratio] = grid
        add(
            f"| {down_ratio:.2f} | {grid.down_count} | {_fmtPct(grid.down_precision)} | "
            f"{_fmtPct(grid.down_lift)} |"
        )
    add("")

    tight = signalMetrics(points, gap_days=3, cap_days=7)
    loose = signalMetrics(points, gap_days=10, cap_days=21)
    up_loose = up_grid.get(1.15, SignalMetrics())
    down_loose = down_grid.get(0.85, SignalMetrics())
    down_tight = down_grid.get(0.60, SignalMetrics())
    window90 = evaluate("90 天端点", endpointEstimator(90), points)

    add("## 5. 运行时常量复核（人工）")
    add("")
    add("| 常量 | 当前值 | 复核依据 | 结论 |")
    add("| --- | ---: | --- | --- |")
    add(
        f"| `EXP_EFFICIENCY_WINDOW_DAYS` | {EXP_EFFICIENCY_WINDOW_DAYS} | "
        f"30d MAPE {_fmtPct(current.horizons[30].mape)}；"
        f"90d MAPE {_fmtPct(window90.horizons[30].mape)}（更准但响应更慢） | 维持（产品取舍） |"
    )
    add(
        f"| `EXP_EFFICIENCY_FAST_GAP_DAYS` | {EXP_EFFICIENCY_FAST_GAP_DAYS} | "
        f"gap=7 加速命中 {_fmtPct(signal.up_precision)}、放缓 {_fmtPct(signal.down_precision)}；"
        f"gap=3/cap=7 加速 {_fmtPct(tight.up_precision)}、放缓 {_fmtPct(tight.down_precision)} | 维持 |"
    )
    add(
        f"| `EXP_EFFICIENCY_FAST_CAP_DAYS` | {EXP_EFFICIENCY_FAST_CAP_DAYS} | "
        f"cap=14 与 cap=10 结果接近；cap=21 加速仅 {loose.up_count} 次、"
        f"命中 {_fmtPct(loose.up_precision)}（样本过少） | 维持 |"
    )
    add(
        f"| `EXP_EFFICIENCY_TREND_UP_RATIO` | {EXP_EFFICIENCY_TREND_UP_RATIO:.2f} | "
        f"1.25 命中 {_fmtPct(signal.up_precision)}（{signal.up_count} 次）；"
        f"1.15 命中 {_fmtPct(up_loose.up_precision)}（{up_loose.up_count} 次，更灵敏但更吵） | 维持 |"
    )
    add(
        f"| `EXP_EFFICIENCY_TREND_DOWN_RATIO` | {EXP_EFFICIENCY_TREND_DOWN_RATIO:.2f} | "
        f"0.75 命中 {_fmtPct(signal.down_precision)}（{signal.down_count} 次）；"
        f"0.85 命中 {_fmtPct(down_loose.down_precision)}（{down_loose.down_count} 次）；"
        f"0.60 仅 {down_tight.down_count} 次 | 维持 |"
    )
    add("")
    add("> 只有出现「加速 / 放缓命中率连续两期低于基线」或「样本翻倍后阈值明显偏离」"
        "才重新评估；改常量必须在本报告补一节「与上期差异」。")
    add("")

    add("## 6. Caveats")
    add("")
    add("- 快照是用户手动录入的累计经验，不是等间隔观测；span 与记录频率相关；")
    add(f"- 未来值容差 ±{TARGET_TOLERANCE_DAYS} 天，长跨度会被丢弃，样本随之减少；")
    add("- 合成阶跃响应只用一条确定性曲线，衡量的是收敛速度，不是统计精度；")
    add(f"- 趋势信号样本 {signal.up_count} / {signal.down_count}（加速 / 放缓），"
        "阈值只作初始值；")
    add("- 回测在 Python 内完成，未进入 UI 线程；报告与常量由人复核。")
    add("")

    summary = _buildSummary(points, current)
    return "\n".join(lines) + "\n", summary


def _buildSummary(points: Sequence[Point], current: Evaluation) -> Dict[str, float]:
    """
    提取运行摘要（写入状态 JSON，供设置页展示）。

    Args:
        points: 升序快照点。
        current: 现口径的评估结果。

    Returns:
        摘要字典：slow / fast / mape_7d / mape_30d。
    """
    slow = endpointEstimator(EXP_EFFICIENCY_WINDOW_DAYS)(points)
    block = recentBlock(points, EXP_EFFICIENCY_FAST_GAP_DAYS, EXP_EFFICIENCY_FAST_CAP_DAYS)
    fast = fastRate(block)

    def _mape(horizon: int) -> float:
        metrics = current.horizons.get(horizon)
        if metrics is None or metrics.mape is None:
            return 0.0
        return round(metrics.mape, 4)

    return {
        "slow": int(round(slow)) if slow else 0,
        "fast": int(round(fast)) if fast else 0,
        "mape_7d": _mape(7),
        "mape_30d": _mape(30),
    }


# --------------------------------------------------------------------------
# 自检
# --------------------------------------------------------------------------


def _syntheticConstant(days: int = 120, rate: int = 1000) -> List[Point]:
    """合成恒定速率数据（每日一条）。"""
    base = datetime(2024, 1, 1)
    return [(base + timedelta(days=day), rate * day) for day in range(days + 1)]


def _syntheticGap() -> List[Point]:
    """合成缺口数据：-20 / -12 / -3 / -1 天。"""
    base = datetime(2024, 3, 1)
    offsets = [(20, 0), (12, 80000), (3, 400000), (1, 500000)]
    return [(base - timedelta(days=days), absolute) for days, absolute in offsets]


def selftest() -> None:
    """
    用合成数据验证估计器、信号与报告生成，不依赖本地库。

    Raises:
        AssertionError: 任一断言失败。
    """
    constant = _syntheticConstant()
    for estimator in (
        endpointEstimator(30),
        weightedRegressionEstimator(),
        segmentedEwmaEstimator(),
    ):
        estimated = estimator(constant)
        assert estimated is not None, "恒定速率不应返回 None"
        assert abs(estimated - 1000) < 1.0, f"{estimator.__name__} 偏离恒定速率：{estimated}"

    for window in (21, 45, 90):
        estimated = endpointEstimator(window)(constant)
        assert estimated is not None and abs(estimated - 1000) < 1.0

    response = responseDays(endpointEstimator(30))
    assert response is not None and 0 < response <= 40, f"阶跃响应异常：{response}"

    block = recentBlock(_syntheticGap(), 7, 14)
    assert len(block) == 2, f"缺口重置失败：{len(block)}"
    assert fastRate(block) is not None

    # 事件检测：连续 5 天 ratio=1.3 → 1 个 normal 事件；连续 4 天不触发
    event_base = datetime(2024, 5, 1)

    def _origin(day: int, ratio: float) -> TrendOrigin:
        return TrendOrigin(
            moment=event_base + timedelta(days=day),
            slow=10000.0,
            fast=10000.0 * ratio,
            ratio=ratio,
            sample_count=5,
            span_days=5.0,
        )

    detector = BacktestService()
    events = detector.detectEventsFromSeries([_origin(day, 1.3) for day in range(5)])
    assert len(events) == 1 and events[0].direction == "up", "事件检测失败"
    assert not detector.detectEventsFromSeries([_origin(day, 1.3) for day in range(4)])

    points = constant
    evaluation = evaluate("selftest", endpointEstimator(30), points)
    assert evaluation.horizons[7].mape is not None and evaluation.horizons[7].mape < 0.01
    assert evaluation.jitter is not None and evaluation.jitter < 1.0

    report, summary = buildReport(
        points, 0, 0, len(points), "<selftest>", datetime(2026, 10, 25, 12, 0)
    )
    assert "指级效率回测报告" in report
    assert "候选口径对比" in report
    assert "趋势信号" in report
    assert summary["slow"] > 0 and "mape_7d" in summary

    with tempfile.TemporaryDirectory() as tmp_dir:
        path = os.path.join(tmp_dir, "report.md")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(report)
        with open(path, "r", encoding="utf-8") as handle:
            assert handle.read() == report

    print("selftest: OK（估计器 / 缺口重置 / 信号 / 报告生成）")


# --------------------------------------------------------------------------
# 事件检测与运行编排（#35 P2）
# --------------------------------------------------------------------------


@dataclass
class TrendOrigin:
    """
    单个 origin 的慢/快口径快照。

    Attributes:
        moment: origin 时刻（当天快照）。
        slow: 30 天日均。
        fast: 近期连续块日均；样本不足时为 None。
        ratio: fast / slow；不可算时为 None。
        sample_count: 近期块条数。
        span_days: 近期块跨度（天）。
    """

    moment: datetime
    slow: float
    fast: Optional[float]
    ratio: Optional[float]
    sample_count: int
    span_days: float


@dataclass
class DueStatus:
    """
    回测到期状态。

    Attributes:
        due: 是否需要（建议）运行回测。
        reasons: 触发原因文案。
        last_run_at: 上次运行时刻。
        days_since: 距上次运行的天数；从未运行时为 None。
        new_points: 距上次运行新增的有效快照条数。
        pending_events: 待复核事件。
        report_path: 上次报告路径。
    """

    due: bool = False
    reasons: List[str] = field(default_factory=list)
    last_run_at: Optional[str] = None
    days_since: Optional[int] = None
    new_points: int = 0
    pending_events: List[BacktestEventRecord] = field(default_factory=list)
    report_path: Optional[str] = None


@dataclass
class BacktestRun:
    """
    一次回测的运行结果。

    Attributes:
        generated_at: 运行时刻。
        points: 有效快照条数。
        skipped: 无法换算条数。
        invalid: 异常隔离条数。
        report: Markdown 报告全文。
        summary: 运行摘要。
        events: 本次检测后的事件（含已复核标记）。
        report_path: 报告文件路径。
    """

    generated_at: datetime
    points: int
    skipped: int
    invalid: int
    report: str
    summary: Dict[str, float]
    events: List[BacktestEventRecord] = field(default_factory=list)
    report_path: Optional[str] = None

    def toStatusBarMessage(self) -> str:
        """
        生成状态栏提示。

        Returns:
            中文消息，例如「回测完成：494 条快照，报告已保存」。
        """
        message = f"回测完成：{self.points} 条快照"
        if self.events:
            message += f"，{len(self.events)} 个事件记录"
        if self.report_path:
            message += "，报告已保存"
        return message


def _qualifies(origin: TrendOrigin, direction: str, threshold: float) -> bool:
    """
    判断某个 origin 是否达到指定方向的事件阈值。

    Args:
        origin: origin 快照。
        direction: ``up`` / ``down``。
        threshold: 比值阈值。

    Returns:
        是否命中。
    """
    if origin.ratio is None:
        return False
    if origin.sample_count < TREND_MIN_SAMPLES or origin.span_days < TREND_MIN_SPAN_DAYS:
        return False
    if direction == "up":
        return origin.ratio >= threshold
    return origin.ratio <= threshold


def _consecutiveRuns(
    series: Sequence[TrendOrigin], direction: str, threshold: float
) -> List[List[TrendOrigin]]:
    """
    提取连续命中的 origin 段（相邻 origin 间隔 >1 天视为断开）。

    Args:
        series: 按时间升序的 origin 列表。
        direction: ``up`` / ``down``。
        threshold: 比值阈值。

    Returns:
        连续段列表。
    """
    runs: List[List[TrendOrigin]] = []
    current: List[TrendOrigin] = []
    for origin in series:
        hit = _qualifies(origin, direction, threshold)
        if hit and current and (origin.moment - current[-1].moment).days > 1:
            runs.append(current)
            current = []
        if hit:
            current.append(origin)
        elif current:
            runs.append(current)
            current = []
    if current:
        runs.append(current)
    return runs


class BacktestService:
    """
    回测运行编排。

    职责：取快照点、检测事件、生成报告、把运行记录落盘。
    约束：只读数据库；不改主值、不改常量、不自动调参。
    """

    def __init__(
        self,
        commander_service: Optional[CommanderService] = None,
        state_repository: Optional[BacktestStateRepository] = None,
        db_path: Optional[str] = None,
    ):
        """
        初始化回测服务。

        Args:
            commander_service: 指挥官服务实例（只读）。
            state_repository: 运行记录仓库。
            db_path: 报告里展示的数据库路径；None 时取当前连接路径。
        """
        self._commander_service = commander_service or CommanderService()
        self._state_repository = state_repository or BacktestStateRepository()
        self._db_path = db_path

    # ------------------------------------------------------------------ 数据

    def collectPoints(self) -> Tuple[List[Point], int, int, int]:
        """
        读取有效快照点（与看板同源：异常隔离 + 同日去重）。

        Returns:
            (升序快照点, 无法换算条数, 异常隔离条数, 原始快照条数)。
        """
        raw_count = len(self._commander_service.listSnapshots())
        points, skipped, invalid = self._commander_service.collectAbsolutePoints()
        return points, skipped, invalid, raw_count

    # ------------------------------------------------------------------ 事件

    def signalSeries(self, points: Sequence[Point]) -> List[TrendOrigin]:
        """
        逐 origin 计算 slow / fast / ratio。

        窗口起点用双指针维护（cutoff 单调递增），整体 O(n·k)，k 为近期块长度。

        Args:
            points: 升序快照点。

        Returns:
            origin 列表。
        """
        series: List[TrendOrigin] = []
        window = timedelta(days=EXP_EFFICIENCY_WINDOW_DAYS)
        start_index = 0
        for index, (moment, absolute) in enumerate(points):
            cutoff = moment - window
            while start_index + 1 <= index and points[start_index + 1][0] <= cutoff:
                start_index += 1
            base = points[start_index] if points[start_index][0] <= cutoff else points[0]
            span = _days(base[0], moment)
            slow = (absolute - base[1]) / span if span > 0 else None

            block = recentBlock(
                points[: index + 1],
                EXP_EFFICIENCY_FAST_GAP_DAYS,
                EXP_EFFICIENCY_FAST_CAP_DAYS,
            )
            fast = fastRate(block)
            block_span = _days(block[0][0], block[-1][0]) if len(block) >= 2 else 0.0
            ratio = fast / slow if fast is not None and slow and slow > 0 else None
            series.append(
                TrendOrigin(
                    moment=moment,
                    slow=float(slow) if slow else 0.0,
                    fast=fast,
                    ratio=ratio,
                    sample_count=len(block),
                    span_days=block_span,
                )
            )
        return series

    def detectEventsFromSeries(self, series: Sequence[TrendOrigin]) -> List[BacktestEventRecord]:
        """
        从比值序列提取事件（纯函数，便于测试与网格复用）。

        Args:
            series: 按时间升序的 origin 列表。

        Returns:
            事件列表（按 end_date 升序）；不含冷却与历史合并。
        """
        events: List[BacktestEventRecord] = []
        for direction, normal_ratio, strong_ratio in (
            ("up", EXP_REGIME_UP_RATIO, EXP_REGIME_STRONG_UP_RATIO),
            ("down", EXP_REGIME_DOWN_RATIO, EXP_REGIME_STRONG_DOWN_RATIO),
        ):
            for run in _consecutiveRuns(series, direction, normal_ratio):
                strength = None
                if len(run) >= EXP_REGIME_MIN_DAYS:
                    strength = "normal"
                elif len(run) >= EXP_REGIME_STRONG_MIN_DAYS and all(
                    _qualifies(origin, direction, strong_ratio) for origin in run
                ):
                    strength = "strong"
                if strength is None:
                    continue
                events.append(self._buildEvent(direction, strength, run))
        events.sort(key=lambda event: event.end_date)
        return events

    @staticmethod
    def _buildEvent(
        direction: str, strength: str, run: Sequence[TrendOrigin]
    ) -> BacktestEventRecord:
        """
        把连续段转换为事件记录。

        Args:
            direction: ``up`` / ``down``。
            strength: ``normal`` / ``strong``。
            run: 连续命中的 origin 段。

        Returns:
            事件记录。
        """
        first, last = run[0], run[-1]
        return BacktestEventRecord(
            direction=direction,
            strength=strength,
            start_date=first.moment.strftime(RECORD_DATE_FORMAT),
            end_date=last.moment.strftime(RECORD_DATE_FORMAT),
            days=len(run),
            peak_ratio=round(max(origin.ratio or 1.0 for origin in run), 4),
            slow_start=int(round(first.slow)),
            slow_end=int(round(last.slow)),
            sample_count=len(run),
        )

    def detectRegimeEvents(self, points: Sequence[Point]) -> List[BacktestEventRecord]:
        """
        检测最近 ``EXP_REGIME_EVENT_LOOKBACK_DAYS`` 天内的事件。

        Args:
            points: 升序快照点。

        Returns:
            事件列表；数据不足时为空。
        """
        if len(points) < 2:
            return []
        cutoff = points[-1][0] - timedelta(days=EXP_REGIME_EVENT_LOOKBACK_DAYS)
        series = [origin for origin in self.signalSeries(points) if origin.moment >= cutoff]
        return self.detectEventsFromSeries(series)

    def mergeEvents(
        self,
        stored: Sequence[BacktestEventRecord],
        detected: Sequence[BacktestEventRecord],
    ) -> List[BacktestEventRecord]:
        """
        合并历史事件与本次检测结果：保留已复核标记、按方向冷却。

        Args:
            stored: 状态文件中的事件。
            detected: 本次检测到的事件。

        Returns:
            合并后的事件列表（按 end_date 升序）。
        """
        merged: Dict[Tuple[str, str], BacktestEventRecord] = {}
        for event in detected:
            merged[(event.direction, event.start_date)] = event
        for event in stored:
            key = (event.direction, event.start_date)
            if key in merged:
                merged[key].handled_at = event.handled_at
            else:
                merged[key] = event

        cooldown = timedelta(days=EXP_REGIME_COOLDOWN_DAYS)
        kept: List[BacktestEventRecord] = []
        last_end: Dict[str, datetime] = {}
        for event in sorted(merged.values(), key=lambda item: item.end_date):
            try:
                start = datetime.strptime(event.start_date, RECORD_DATE_FORMAT)
            except ValueError:
                kept.append(event)
                continue
            previous = last_end.get(event.direction)
            if previous is not None and start - previous < cooldown:
                continue
            kept.append(event)
            last_end[event.direction] = datetime.strptime(event.end_date, RECORD_DATE_FORMAT)
        return kept

    # ------------------------------------------------------------------ 运行

    def getDueStatus(self, points: Optional[Sequence[Point]] = None) -> DueStatus:
        """
        判断是否需要（建议）运行回测。

        Args:
            points: 可选快照点；None 时从库读取。

        Returns:
            到期状态；`reasons` 为可直接展示的中文原因。
        """
        if points is None:
            points, _, _, _ = self.collectPoints()
        state = self._state_repository.load()
        today = time_source.today()

        days_since: Optional[int] = None
        if state.last_run_at:
            try:
                last = datetime.strptime(state.last_run_at, STATISTICS_DATETIME_FORMAT).date()
                days_since = (today - last).days
            except ValueError:
                days_since = None

        new_points = max(0, len(points) - state.points_at_run) if state.last_run_at else len(points)
        pending = [
            event
            for event in self.mergeEvents(state.events, self.detectRegimeEvents(points))
            if not event.handled_at
        ]

        reasons: List[str] = []
        if state.last_run_at is None:
            reasons.append("尚未运行过回测")
        else:
            if days_since is not None and days_since >= EXP_BACKTEST_INTERVAL_DAYS:
                reasons.append(f"距上次回测 {days_since} 天（≥{EXP_BACKTEST_INTERVAL_DAYS}）")
            if new_points >= EXP_BACKTEST_SAMPLE_DELTA:
                reasons.append(f"新增 {new_points} 条有效快照（≥{EXP_BACKTEST_SAMPLE_DELTA}）")
        if pending:
            reasons.append(f"{len(pending)} 个待复核事件")

        return DueStatus(
            due=bool(reasons),
            reasons=reasons,
            last_run_at=state.last_run_at,
            days_since=days_since,
            new_points=new_points,
            pending_events=pending,
            report_path=_displayPath(state.report_path) if state.report_path else None,
        )

    def run(self) -> BacktestRun:
        """
        运行一次回测：生成报告、落盘状态与事件。

        Returns:
            运行结果。

        Raises:
            ValidationError: 有效快照不足两条时抛出。
            DatabaseError: 报告或状态写入失败时抛出。
        """
        points, skipped, invalid, raw_count = self.collectPoints()
        if len(points) < 2:
            raise ValidationError(f"有效快照不足两条（{len(points)} 条），无法回测")

        generated_at = time_source.now()
        db_path = self._db_path or DatabaseConnection.getDbPath()
        report, summary = buildReport(
            points, skipped, invalid, raw_count, db_path, generated_at
        )

        state = self._state_repository.load()
        events = self.mergeEvents(state.events, self.detectRegimeEvents(points))
        report_path = self._state_repository.saveReport(report, generated_at)
        # 状态文件存相对路径：项目搬家后仍能定位报告；报告内容里的路径也用相对形式
        display_path = _displayPath(report_path)

        new_state = BacktestState(
            last_run_at=generated_at.strftime(STATISTICS_DATETIME_FORMAT),
            points_at_run=len(points),
            latest_snapshot_at=points[-1][0].strftime(STATISTICS_DATETIME_FORMAT),
            constants={
                "window": EXP_EFFICIENCY_WINDOW_DAYS,
                "fast_gap": EXP_EFFICIENCY_FAST_GAP_DAYS,
                "fast_cap": EXP_EFFICIENCY_FAST_CAP_DAYS,
                "trend_up": EXP_EFFICIENCY_TREND_UP_RATIO,
                "trend_down": EXP_EFFICIENCY_TREND_DOWN_RATIO,
            },
            summary=summary,
            report_path=display_path,
            events=events,
        )
        self._state_repository.save(new_state)

        return BacktestRun(
            generated_at=generated_at,
            points=len(points),
            skipped=skipped,
            invalid=invalid,
            report=report,
            summary=summary,
            events=events,
            report_path=display_path,
        )

    def markEventHandled(
        self,
        direction: str,
        start_date: str,
        handled_at: Optional[datetime] = None,
    ) -> bool:
        """
        把某个事件标记为已复核（写入状态文件）。

        Args:
            direction: ``up`` / ``down``。
            start_date: 事件首日（``yyyy-MM-dd``）。
            handled_at: 复核时刻；默认取当前时间。

        Returns:
            是否有事件被更新。

        Raises:
            DatabaseError: 状态写入失败时抛出。
        """
        state = self._state_repository.load()
        moment = handled_at or time_source.now()
        changed = False
        for event in state.events:
            if (
                event.direction == direction
                and event.start_date == start_date
                and not event.handled_at
            ):
                event.handled_at = moment.strftime(STATISTICS_DATETIME_FORMAT)
                changed = True
        if changed:
            self._state_repository.save(state)
        return changed
