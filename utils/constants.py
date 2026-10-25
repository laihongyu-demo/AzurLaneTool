"""
应用常量定义模块。

定义全局使用的常量，包括路径、默认值、配置项等。
"""

import os
import sys

APP_NAME = "AzurLaneTool"
APP_VERSION = "1.0.0"


def _resolveBaseDir() -> str:
    """
    解析项目根目录。

    兼容源码运行与 PyInstaller 打包后运行两种环境。

    Returns:
        项目根目录（打包后为资源解压目录）的绝对路径。
    """
    if getattr(sys, 'frozen', False):
        return getattr(
            sys,
            '_MEIPASS',
            os.path.dirname(os.path.abspath(sys.executable))
        )
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


BASE_DIR = _resolveBaseDir()
SQL_DIR = os.path.join(BASE_DIR, 'sql')
DATA_DIR = os.path.join(BASE_DIR, 'data')
ASSETS_DIR = os.path.join(BASE_DIR, 'assets')
ICON_DIR = os.path.join(ASSETS_DIR, 'icon')
APP_ICON_PATH = os.path.join(ICON_DIR, '250px-Manjuu_logo1.ico')

DEFAULT_DB_NAME = "AzurLaneStatisticalOfficeDB.db"
DEFAULT_DB_PATH = os.path.join(DATA_DIR, DEFAULT_DB_NAME)

WINDOW_MIN_WIDTH = 800
WINDOW_MIN_HEIGHT = 600
WINDOW_DEFAULT_WIDTH = 1024
WINDOW_DEFAULT_HEIGHT = 768

MAX_RETRY_COUNT = 3
DEFAULT_QUERY_TIMEOUT = 30

# ---- 资源统计（魔方 / 红尖尖）----

RESOURCE_TYPE_CUBE = "cube"
RESOURCE_TYPE_RED_GEM = "red_gem"
RESOURCE_TYPES = (RESOURCE_TYPE_CUBE, RESOURCE_TYPE_RED_GEM)

RESOURCE_DISPLAY_NAMES = {
    RESOURCE_TYPE_CUBE: "魔方",
    RESOURCE_TYPE_RED_GEM: "红尖尖",
}

RESOURCE_DIRECTION_INCOME = "income"
RESOURCE_DIRECTION_EXPENSE = "expense"
RESOURCE_DIRECTIONS = (RESOURCE_DIRECTION_INCOME, RESOURCE_DIRECTION_EXPENSE)

RESOURCE_DIRECTION_NAMES = {
    RESOURCE_DIRECTION_INCOME: "收入",
    RESOURCE_DIRECTION_EXPENSE: "支出",
}

RESOURCE_DETAIL_MODE_DETAIL = "detail"
RESOURCE_DETAIL_MODE_SUMMARY_ONLY = "summary_only"

# ---- 日期与时间格式 ----

# Python strftime 口径（服务层 / 迁移脚本使用）
RECORD_DATE_FORMAT = "%Y-%m-%d"
RECORD_TIME_FORMAT = "%Y-%m-%d %H:%M:%S"
STATISTICS_DATETIME_FORMAT = "%Y-%m-%d %H:%M"

# Qt 控件口径（QDateEdit / QDateTimeEdit 的 setDisplayFormat 与 fromString 使用）
QT_DATE_DISPLAY_FORMAT = "yyyy-MM-dd"
QT_RECORD_TIME_DISPLAY_FORMAT = "yyyy-MM-dd HH:mm:ss"
QT_DATETIME_DISPLAY_FORMAT = "yyyy-MM-dd HH:mm"

# ---- 指挥官等级 ----

COMMANDER_LEVEL_MIN = 1
COMMANDER_LEVEL_MAX = 200
COMMANDER_SNAPSHOT_RECENT_LIMIT = 30

# ---- 指级效率（#16 / #23）----
#
# 口径见 docs/指级效率算法优化方案_20261018.md（v2）与
# docs/20261025_指级效率回测报告.md（#23 P2 回测）。修改下列常量必须同步回测报告，
# 或在提交说明里写清依据。

# 慢窗口天数：取最近 30 天内的快照算日均（主值，语义与 v1 完全一致）
EXP_EFFICIENCY_WINDOW_DAYS = 30
# 少于两条快照无法构成区间，直接降级
EXP_EFFICIENCY_MIN_SAMPLES = 2
# 卡片单位
EXP_EFFICIENCY_UNIT = "/天"

# 近期节奏（fast）：从最新有效快照往回走，遇到超过 7 天的缺口就重置，
# 最多回看 14 天；至少 2 条、跨度 >=1 天才给值（宁可 None，不拿旧点冒充"近期"）
EXP_EFFICIENCY_FAST_GAP_DAYS = 7
EXP_EFFICIENCY_FAST_CAP_DAYS = 14
EXP_EFFICIENCY_FAST_MIN_SAMPLES = 2
EXP_EFFICIENCY_FAST_MIN_SPAN_DAYS = 1.0

# 趋势（trend = fast / slow）：偏离 30 天值 ±25% 才判定，
# 且要求连续块 >=3 条、跨度 >=3 天，避免"一条爆肝记录 + 1 天跨度"就报加速
EXP_EFFICIENCY_TREND_UP_RATIO = 1.25
EXP_EFFICIENCY_TREND_DOWN_RATIO = 0.75
EXP_EFFICIENCY_TREND_MIN_SAMPLES = 3
EXP_EFFICIENCY_TREND_MIN_SPAN_DAYS = 3.0

# 数据质量提示阈值：窗口内最大缺口 >=7 天、数据截止距今 >=7 天才进 tooltip
EXP_EFFICIENCY_GAP_HINT_DAYS = 7
EXP_EFFICIENCY_STALE_DAYS = 7

# ---- 魔方任务看板 ----

TASK_GROUP_DAILY = "daily"
TASK_GROUP_WEEKLY = "weekly"
TASK_GROUP_SIGNIN = "signin"
TASK_GROUP_CRUISE = "cruise"
TASK_GROUPS = (TASK_GROUP_DAILY, TASK_GROUP_WEEKLY, TASK_GROUP_SIGNIN, TASK_GROUP_CRUISE)

TASK_GROUP_TITLES = {
    TASK_GROUP_DAILY: "日常任务",
    TASK_GROUP_WEEKLY: "周常任务",
    TASK_GROUP_SIGNIN: "每月签到",
    TASK_GROUP_CRUISE: "世界巡游",
}

# 展示分组：任务（日常 + 周常）／每月签到／世界巡游
TASK_DISPLAY_GROUPS = (
    ("task", "任务", (TASK_GROUP_DAILY, TASK_GROUP_WEEKLY)),
    ("signin", "每月签到", (TASK_GROUP_SIGNIN,)),
    ("cruise", "世界巡游", (TASK_GROUP_CRUISE,)),
)

# 红尖尖固定来源只有世界巡游一个展示分组
RED_GEM_TASK_DISPLAY_GROUPS = (
    ("cruise", "世界巡游", (TASK_GROUP_CRUISE,)),
)

TASK_DISPLAY_GROUPS_BY_RESOURCE = {
    RESOURCE_TYPE_CUBE: TASK_DISPLAY_GROUPS,
    RESOURCE_TYPE_RED_GEM: RED_GEM_TASK_DISPLAY_GROUPS,
}

TASK_PERIOD_DAY = "day"
TASK_PERIOD_WEEK = "week"
TASK_PERIOD_MONTH = "month"
TASK_PERIOD_CRUISE = "cruise"
TASK_PERIODS = (TASK_PERIOD_DAY, TASK_PERIOD_WEEK, TASK_PERIOD_MONTH, TASK_PERIOD_CRUISE)

# 世界巡游：每 2 个自然月为一期，起点为偶数月 1 日
CRUISE_PERIOD_MONTHS = 2

# 录入时写入明细的来源名（沿用历史事件名；签到类由历史「每日签到」改名为「每月签到」）
TASK_CATEGORY_SIGNIN_LEGACY = "每日签到"
TASK_CATEGORY_SIGNIN = "每月签到"
TASK_CATEGORY_WORLD_CRUISE = "世界巡游"

# ---- 贸易许可证 ----

TRADE_LICENSE_DAYS = 30
TRADE_LICENSE_REWARD = 500
TRADE_LICENSE_RENEWAL_WINDOW_DAYS = 7
TRADE_LICENSE_CATEGORY = "贸易许可证"

# ---- 活动记录 ----
#
# 活动记录与魔方明细的关联口径：
# - build_count（建造次数）是手工统计值，包含建造券抽，不能由魔方支出反推
#   （历史平均 1.80 魔方/次）；
# - resource_transaction.event_id 只用于汇总该活动的魔方支出与笔数。

# 唯一允许关联活动记录的支出类型（魔方）
EVENT_BUILD_CATEGORY = "活动建造"

# 状态建议值：自由文本存储，用户可输入其它值；空串表示未标记
EVENT_STATUS_GRADUATED = "毕业"
EVENT_STATUS_MISSING = "缺"
EVENT_STATUS_ONGOING = "进行中"
EVENT_STATUS_OPTIONS = (EVENT_STATUS_GRADUATED, EVENT_STATUS_MISSING, EVENT_STATUS_ONGOING)

# 单次建造消耗的魔方数：轻型 1，重型 / 特型 / 多数活动池 2
EVENT_BUILD_COST_OPTIONS = (1, 2)
EVENT_DEFAULT_BUILD_COST = 2

# 展示兜底文案
EVENT_UNNAMED_LABEL = "（未命名活动）"
EVENT_STATUS_UNSET_LABEL = "未标记"
EVENT_SELECTOR_NONE_LABEL = "（不关联活动）"

# 字段长度与数量上限（仅拦截误输入）
MAX_EVENT_NAME_LENGTH = 100
MAX_EVENT_TYPE_LENGTH = 50
MAX_EVENT_STATUS_LENGTH = 20
MAX_EVENT_STATUS_NOTE_LENGTH = 200
MAX_EVENT_NOTE_LENGTH = 200
MAX_EVENT_BUILD_COUNT = 100_000
