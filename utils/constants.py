"""
应用常量定义模块。

定义全局使用的常量，包括路径、默认值、配置项等。
"""

import os

APP_NAME = "DataInsight"
APP_VERSION = "1.0.0"

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SQL_DIR = os.path.join(BASE_DIR, 'sql')
DATA_DIR = os.path.join(BASE_DIR, 'data')

DEFAULT_DB_NAME = "AzurLaneStatisticalOfficeDB.db"
DEFAULT_DB_PATH = os.path.join(DATA_DIR, DEFAULT_DB_NAME)

WINDOW_MIN_WIDTH = 800
WINDOW_MIN_HEIGHT = 600
WINDOW_DEFAULT_WIDTH = 1024
WINDOW_DEFAULT_HEIGHT = 768

MAX_RETRY_COUNT = 3
DEFAULT_QUERY_TIMEOUT = 30
