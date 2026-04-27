"""
碧蓝航线数据管理工具应用程序入口模块。

负责初始化应用程序和主窗口。
"""

import sys
import os

from PyQt5.QtWidgets import QApplication
from PyQt5.QtCore import Qt

from views.main_window import MainWindow
from services.codex_unlock_service import CodexUnlockService
from utils.constants import APP_NAME, DEFAULT_DB_PATH


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
    
    app.setStyleSheet("""
        QLabel {
            background-color: transparent;
        }
        QGroupBox {
            background-color: transparent;
        }
    """)

    if not os.path.exists(DEFAULT_DB_PATH):
        print(f"警告: 数据库文件不存在: {DEFAULT_DB_PATH}")

    unlock_service = CodexUnlockService()

    main_window = MainWindow(unlock_service=unlock_service)
    main_window.show()

    return app.exec_()


if __name__ == "__main__":
    sys.exit(main())
