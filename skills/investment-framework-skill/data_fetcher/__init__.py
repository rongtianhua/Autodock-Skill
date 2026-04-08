"""
投资框架数据获取层

统一数据接口，免费优先，付费可选
"""

from .core import DataFetcher
from .config import load_config, save_config, init_config
from .cache import CacheManager
from .exceptions import DataFetchError, ConfigError, APIKeyError

__version__ = '1.0.0'
__all__ = [
    'DataFetcher',
    'load_config',
    'save_config',
    'init_config',
    'CacheManager',
    'DataFetchError',
    'ConfigError',
    'APIKeyError',
]
