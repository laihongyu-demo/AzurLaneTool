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

TASK_PERIOD_DAY = "day"
TASK_PERIOD_WEEK = "week"
TASK_PERIOD_MONTH = "month"
TASK_PERIOD_CRUISE = "cruise"

# 世界巡游：每 2 个自然月为一期，起点为偶数月 1 日
CRUISE_PERIOD_MONTHS = 2

# 录入时写入明细的来源名（沿用历史事件名；签到类由历史「每日签到」改名为「每月签到」）
TASK_CATEGORY_SIGNIN_LEGACY = "每日签到"
TASK_CATEGORY_SIGNIN = "每月签到"
