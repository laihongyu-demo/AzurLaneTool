"""
配置管理模块。

提供配置文件的加载、解析和访问功能。
支持 YAML 格式配置文件，支持环境变量覆盖。
"""

import os
from typing import Any, Optional, Dict

try:
    import yaml
    YAML_AVAILABLE = True
except ImportError:
    YAML_AVAILABLE = False

from utils.exceptions import ConfigurationError
from utils.logger import log


class Config:
    """
    配置管理类。

    支持从 YAML 文件加载配置，支持默认值和环境变量覆盖。
    """

    _instance: Optional['Config'] = None
    _config: Dict[str, Any] = {}
    _config_path: Optional[str] = None

    def __new__(cls) -> 'Config':
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def load(self, config_path: Optional[str] = None) -> None:
        """
        加载配置文件。

        Args:
            config_path: 配置文件路径，默认为项目根目录下的 config.yaml。

        Raises:
            ConfigurationError: 当配置文件不存在或格式错误时抛出。
        """
        if config_path is None:
            base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            config_path = os.path.join(base_dir, 'config.yaml')

        self._config_path = config_path

        if not os.path.exists(config_path):
            log.warning(f"配置文件不存在: {config_path}，使用默认配置")
            self._loadDefaults()
            return

        if not YAML_AVAILABLE:
            log.warning("PyYAML 未安装，使用默认配置")
            self._loadDefaults()
            return

        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                self._config = yaml.safe_load(f) or {}
            log.info(f"配置文件加载成功: {config_path}")
        except yaml.YAMLError as e:
            raise ConfigurationError(
                message=f"配置文件格式错误: {e}",
                config_key="yaml_parse"
            )
        except IOError as e:
            raise ConfigurationError(
                message=f"读取配置文件失败: {e}",
                config_key="file_read"
            )

    def _loadDefaults(self) -> None:
        """加载默认配置。"""
        self._config = {
            'app': {
                'name': 'AzurLaneTool',
                'version': '1.0.0'
            },
            'database': {
                'name': 'AzurLaneStatisticalOfficeDB.db',
                'path': 'data'
            },
            'window': {
                'min_width': 800,
                'min_height': 600,
                'default_width': 1024,
                'default_height': 768
            },
            'system': {
                'max_retry_count': 3,
                'query_timeout': 30
            }
        }

    def get(self, key: str, default: Any = None) -> Any:
        """
        获取配置值（支持点分隔的嵌套键）。

        Args:
            key: 配置键，支持点分隔的嵌套键（如 'app.name'）。
            default: 默认值。

        Returns:
            配置值，不存在则返回默认值。
        """
        keys = key.split('.')
        value = self._config

        for k in keys:
            if isinstance(value, dict) and k in value:
                value = value[k]
            else:
                return default

        return value

    def getAppName(self) -> str:
        """获取应用名称。"""
        return self.get('app.name', 'AzurLaneTool')

    def getAppVersion(self) -> str:
        """获取应用版本。"""
        return self.get('app.version', '1.0.0')

    def getDatabaseName(self) -> str:
        """获取数据库名称。"""
        return self.get('database.name', 'AzurLaneStatisticalOfficeDB.db')

    def getDatabasePath(self) -> str:
        """获取数据库完整路径。"""
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        db_dir = self.get('database.path', 'data')
        db_name = self.getDatabaseName()
        return os.path.join(base_dir, db_dir, db_name)

    def getWindowMinWidth(self) -> int:
        """获取窗口最小宽度。"""
        return self.get('window.min_width', 800)

    def getWindowMinHeight(self) -> int:
        """获取窗口最小高度。"""
        return self.get('window.min_height', 600)

    def getWindowDefaultWidth(self) -> int:
        """获取窗口默认宽度。"""
        return self.get('window.default_width', 1024)

    def getWindowDefaultHeight(self) -> int:
        """获取窗口默认高度。"""
        return self.get('window.default_height', 768)

    def getMaxRetryCount(self) -> int:
        """获取最大重试次数。"""
        return self.get('system.max_retry_count', 3)

    def getQueryTimeout(self) -> int:
        """获取查询超时时间（秒）。"""
        return self.get('system.query_timeout', 30)

    def reload(self) -> None:
        """重新加载配置文件。"""
        self.load(self._config_path)


config = Config()


def initConfig(config_path: Optional[str] = None) -> Config:
    """
    初始化配置管理器。

    Args:
        config_path: 配置文件路径。

    Returns:
        配置管理器实例。
    """
    config.load(config_path)
    return config


def getConfig() -> Config:
    """
    获取配置管理器实例。

    Returns:
        配置管理器实例。
    """
    if not config._config:
        config.load()
    return config
