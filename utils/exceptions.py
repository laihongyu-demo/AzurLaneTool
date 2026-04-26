"""
自定义异常类模块。

定义应用中使用的所有自定义异常，确保异常处理的一致性。
"""


class DatabaseError(Exception):
    """数据库操作相关异常。"""
    pass


class ConnectionError(Exception):
    """数据库连接相关异常。"""
    pass


class ValidationError(Exception):
    """数据验证相关异常。"""
    pass


class ConfigurationError(Exception):
    """配置相关异常。"""
    pass


class SecurityError(Exception):
    """安全相关异常。"""
    pass
