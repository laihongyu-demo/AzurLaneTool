"""
日志工具模块。

提供统一的日志记录功能。
"""

import logging
import sys
from pathlib import Path
from typing import Optional


def setupLogger(
    name: str = "AzurLaneTool",
    level: int = logging.DEBUG,
    log_file: Optional[str] = None
) -> logging.Logger:
    """
    配置并返回日志记录器。

    Args:
        name: 日志记录器名称。
        level: 日志级别。
        log_file: 日志文件路径，为None时仅输出到控制台。

    Returns:
        配置好的日志记录器。
    """
    logger = logging.getLogger(name)
    logger.setLevel(level)

    if logger.handlers:
        return logger

    formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(level)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    if log_file:
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setLevel(level)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

    return logger


log = setupLogger()
