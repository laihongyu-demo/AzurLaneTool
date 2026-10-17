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
