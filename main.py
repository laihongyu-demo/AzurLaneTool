"""
碧蓝航线数据管理工具应用程序入口模块。

负责初始化应用程序和主窗口。
"""

import sys
import os

from PyQt5.QtWidgets import QApplication
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QIcon

from views.main_window import MainWindow
from services.codex_unlock_service import CodexUnlockService
from utils.constants import APP_NAME, APP_ICON_PATH, DEFAULT_DB_PATH
from utils.db_schema import ensureCodexGroupSchema, ensureResourceStatisticsSchema


def main() -> int:
    """
    应用程序主入口函数。

    Returns:
        应用程序退出码。
    """
    if hasattr(Qt, 'AA_EnableHighDpiScaling'):
        QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    if hasattr(Qt, 'AA_UseHighDpiPixmaps'):
        QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)

    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setWindowIcon(QIcon(APP_ICON_PATH))

    if not os.path.exists(DEFAULT_DB_PATH):
        print(f"警告: 数据库文件不存在: {DEFAULT_DB_PATH}")
    else:
        # 幂等建表：旧库缺少资源统计相关表时自动补齐，缺失不应阻止应用启动
        try:
            ensureResourceStatisticsSchema()
        except Exception as e:
            print(f"警告: 资源统计表结构初始化失败: {e}")

        # 幂等补列：旧库的 codex_group 缺少舰队位置列时补列并回填
        try:
            ensureCodexGroupSchema()
        except Exception as e:
            print(f"警告: 图鉴表结构初始化失败: {e}")

    unlock_service = CodexUnlockService()

    main_window = MainWindow(unlock_service=unlock_service)
    main_window.show()

    return app.exec_()


if __name__ == "__main__":
    sys.exit(main())
