"""
错误处理工具模块。

提供统一的错误处理和异常转换功能。
"""

import traceback
from typing import Optional

from PyQt5.QtWidgets import QWidget

from utils.logger import log


def handleException(
    parent: Optional[QWidget],
    exception: Exception,
    title: str = "错误",
    default_message: str = "操作失败"
) -> str:
    """
    处理异常并返回用户友好的错误消息。

    Args:
        parent: 父控件。
        exception: 异常对象。
        title: 错误标题。
        default_message: 默认错误消息。

    Returns:
        用户友好的错误消息。
    """
    error_message = str(exception) if str(exception) else default_message

    log.error(f"{title}: {error_message}")
    log.debug(f"异常堆栈:\n{traceback.format_exc()}")

    return error_message
