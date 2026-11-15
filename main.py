"""
碧蓝航线数据管理工具应用程序入口模块。

负责初始化应用程序和主窗口。
"""

import sys

from PyQt5.QtWidgets import QApplication, QMessageBox
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QIcon

from views.main_window import MainWindow
from services.codex_unlock_service import CodexUnlockService
from utils.constants import APP_NAME, APP_ICON_PATH
from utils.db_bootstrap import DatabaseInitReport, ensureDatabaseReady


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

    # 首次使用（无数据库）自动建库建表并写入必要种子；失败只告警，不阻止启动
    init_report = None
    try:
        init_report = ensureDatabaseReady()
        print(f"数据库就绪: {init_report.db_path}")
    except Exception as e:
        print(f"警告: 数据库初始化失败: {e}")

    unlock_service = CodexUnlockService()

    main_window = MainWindow(unlock_service=unlock_service)
    main_window.show()

    if init_report is not None and init_report.database_created:
        _showFirstRunNotice(main_window, init_report)

    return app.exec_()


def _showFirstRunNotice(window, report: DatabaseInitReport) -> None:
    """
    首次创建空白数据库后给一次说明。

    避免用户把「图鉴为空」误判成故障，并指出录入入口；只在真正新建数据库文件时调用。

    Args:
        window: 主窗口，作为对话框父对象。
        report: 数据库初始化结果。
    """
    lines = [
        f"已自动创建空白数据库：\n{report.db_path}",
        f"已建好 {report.table_count} 张业务表。",
    ]
    if report.level_exp_rows:
        lines.append(f"已写入 {report.level_exp_rows} 条指挥官等级经验基准。")
    if report.user_file_created:
        lines.append(f"已生成用户数据文件：\n{report.user_file_path}")
    lines.append("图鉴数据为空：可在「舰娘管理 → 新增舰娘」逐条录入，其它页签可直接使用。")

    QMessageBox.information(window, "首次运行", "\n\n".join(lines))


if __name__ == "__main__":
    sys.exit(main())
