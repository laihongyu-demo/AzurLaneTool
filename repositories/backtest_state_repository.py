"""
回测运行记录与报告文件的数据访问（#35 P2）。

- 状态文件：``data/efficiency_backtest.json``（本机用户数据，不入库、不进 Git）；
- 报告目录：``data/backtest/``（同上）；
- 读取容错：文件缺失或 JSON 损坏时按“从未回测”处理，不阻塞界面；
- 写入原子化：先写临时文件再 ``os.replace``，避免中途崩溃留下半个 JSON。
"""

import json
import os
from datetime import datetime
from typing import Optional

from models.backtest_model import BacktestState
from utils.constants import DATA_DIR
from utils.exceptions import DatabaseError

REPORT_DIR_NAME = "backtest"
STATE_FILE_NAME = "efficiency_backtest.json"


class BacktestStateRepository:
    """
    回测运行记录仓库。

    只负责持久化，不判断“是否到期”、不计算指标。
    """

    def __init__(
        self,
        file_path: Optional[str] = None,
        report_dir: Optional[str] = None,
    ):
        """
        初始化仓库。

        Args:
            file_path: 状态 JSON 路径；默认 ``data/efficiency_backtest.json``。
            report_dir: 报告目录；默认 ``data/backtest/``。
        """
        self._filePath = file_path or os.path.join(DATA_DIR, STATE_FILE_NAME)
        self._reportDir = report_dir or os.path.join(DATA_DIR, REPORT_DIR_NAME)

    def load(self) -> BacktestState:
        """
        读取运行记录。

        Returns:
            运行记录；文件不存在或内容损坏时返回空记录。
        """
        if not os.path.exists(self._filePath):
            return BacktestState()
        try:
            with open(self._filePath, "r", encoding="utf-8") as handle:
                payload = json.load(handle)
        except (json.JSONDecodeError, OSError):
            # 状态文件是辅助数据：坏了就当作从未回测，不能让设置页报错
            return BacktestState()
        return BacktestState.fromDict(payload)

    def save(self, state: BacktestState) -> None:
        """
        写入运行记录（原子替换）。

        Args:
            state: 运行记录。

        Raises:
            DatabaseError: 写入失败时抛出。
        """
        directory = os.path.dirname(self._filePath)
        try:
            if directory:
                os.makedirs(directory, exist_ok=True)
            temporary = f"{self._filePath}.tmp"
            with open(temporary, "w", encoding="utf-8") as handle:
                json.dump(state.toDict(), handle, ensure_ascii=False, indent=2)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self._filePath)
        except OSError as error:
            raise DatabaseError(f"保存回测记录失败: {error}")

    def saveReport(self, text: str, generated_at: datetime) -> str:
        """
        把 Markdown 报告写入报告目录。

        Args:
            text: 报告全文。
            generated_at: 生成时刻（用于文件名）。

        Returns:
            报告文件路径。

        Raises:
            DatabaseError: 写入失败时抛出。
        """
        path = os.path.join(self._reportDir, f"{generated_at.strftime('%Y%m%d_%H%M')}.md")
        try:
            os.makedirs(self._reportDir, exist_ok=True)
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(text)
        except OSError as error:
            raise DatabaseError(f"保存回测报告失败: {error}")
        return path
