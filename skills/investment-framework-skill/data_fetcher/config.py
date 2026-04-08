"""
配置管理模块

加载、保存、初始化配置文件
"""

import os
import yaml
from typing import Dict, Any
from .exceptions import ConfigError

DEFAULT_CONFIG_PATH = os.path.expanduser('~/.investment_framework/config.yaml')

DEFAULT_CONFIG = {
    'data_sources': {
        'priority': ['tencent', 'sina', 'eastmoney'],
        'tencent': {'enabled': True},
        'sina': {'enabled': True},
        'eastmoney': {'enabled': True},
        'tushare': {'enabled': False},
        'lixinger': {'enabled': False},
    },
    'api_keys': {
        'tushare': {
            'token': '',
            'enabled': False,
        },
        'lixinger': {
            'token': '',
            'enabled': False,
        },
    },
    'fallback': {
        'use_cache': True,
        'cache_ttl': 300,  # 5 分钟
        'allow_manual_input': True,
        'timeout': 5,
    },
    'preferences': {
        'a_share_prefix': {
            'sh': 'sh',
            'sz': 'sz',
        },
        'default_fields': [
            'price',
            'change_percent',
            'pe',
            'pb',
            'market_cap',
        ],
    },
}


def load_config(config_path: str = None) -> Dict[str, Any]:
    """
    加载配置文件
    
    Args:
        config_path: 配置文件路径，默认 ~/.investment_framework/config.yaml
    
    Returns:
        配置字典
    """
    if config_path is None:
        config_path = DEFAULT_CONFIG_PATH
    
    if not os.path.exists(config_path):
        # 配置文件不存在，创建默认配置
        init_config(config_path)
        return DEFAULT_CONFIG.copy()
    
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f)
        
        # 合并默认配置（确保所有字段存在）
        merged = DEFAULT_CONFIG.copy()
        if config:
            deep_merge(merged, config)
        
        return merged
    except Exception as e:
        raise ConfigError(f"加载配置文件失败：{e}")


def save_config(config: Dict[str, Any], config_path: str = None) -> None:
    """
    保存配置文件
    
    Args:
        config: 配置字典
        config_path: 配置文件路径
    """
    if config_path is None:
        config_path = DEFAULT_CONFIG_PATH
    
    try:
        # 确保目录存在
        os.makedirs(os.path.dirname(config_path), exist_ok=True)
        
        with open(config_path, 'w', encoding='utf-8') as f:
            yaml.dump(config, f, allow_unicode=True, default_flow_style=False)
        
        # 设置文件权限（仅用户可读）
        os.chmod(config_path, 0o600)
        
    except Exception as e:
        raise ConfigError(f"保存配置文件失败：{e}")


def init_config(config_path: str = None) -> bool:
    """
    初始化配置文件
    
    Args:
        config_path: 配置文件路径
    
    Returns:
        True: 创建了新配置
        False: 配置已存在
    """
    if config_path is None:
        config_path = DEFAULT_CONFIG_PATH
    
    if os.path.exists(config_path):
        return False
    
    save_config(DEFAULT_CONFIG, config_path)
    
    print("✅ 配置文件已创建：", config_path)
    print("📝 编辑配置填写 API Key（可选）：")
    print("   - Tushare Pro: https://tushare.pro/user/token")
    print("   - 理杏仁：https://www.lixinger.com/api/token")
    
    return True


def deep_merge(base: Dict, update: Dict) -> None:
    """深度合并字典"""
    for key, value in update.items():
        if key in base and isinstance(base[key], dict) and isinstance(value, dict):
            deep_merge(base[key], value)
        else:
            base[key] = value


def get_api_key(provider: str, config: Dict = None) -> str:
    """
    获取 API Key
    
    Args:
        provider: 提供商名称（tushare, lixinger）
        config: 配置字典
    
    Returns:
        API Key 字符串
    """
    if config is None:
        config = load_config()
    
    api_keys = config.get('api_keys', {})
    provider_config = api_keys.get(provider, {})
    
    if not provider_config.get('enabled', False):
        return None
    
    token = provider_config.get('token', '')
    if not token:
        return None
    
    return token
