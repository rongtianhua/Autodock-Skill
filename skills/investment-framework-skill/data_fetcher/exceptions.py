"""
异常定义
"""


class DataFetchError(Exception):
    """数据获取失败"""
    pass


class ConfigError(Exception):
    """配置错误"""
    pass


class APIKeyError(Exception):
    """API Key 错误或缺失"""
    pass


class CacheError(Exception):
    """缓存错误"""
    pass


class ProviderError(Exception):
    """数据源错误"""
    def __init__(self, provider: str, message: str):
        self.provider = provider
        super().__init__(f"[{provider}] {message}")
