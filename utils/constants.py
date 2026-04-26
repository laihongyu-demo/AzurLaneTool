"""
应用常量定义模块。

定义全局使用的常量，包括路径、默认值、配置项等。
支持从配置文件加载，同时保留硬编码默认值作为后备。
"""

import os

from utils.config import getConfig


_config = getConfig()

APP_NAME = _config.getAppName()
APP_VERSION = _config.getAppVersion()

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SQL_DIR = os.path.join(BASE_DIR, 'sql')
DATA_DIR = os.path.join(BASE_DIR, 'data')

DEFAULT_DB_NAME = _config.getDatabaseName()
DEFAULT_DB_PATH = _config.getDatabasePath()

WINDOW_MIN_WIDTH = _config.getWindowMinWidth()
WINDOW_MIN_HEIGHT = _config.getWindowMinHeight()
WINDOW_DEFAULT_WIDTH = _config.getWindowDefaultWidth()
WINDOW_DEFAULT_HEIGHT = _config.getWindowDefaultHeight()

MAX_RETRY_COUNT = _config.getMaxRetryCount()
DEFAULT_QUERY_TIMEOUT = _config.getQueryTimeout()
