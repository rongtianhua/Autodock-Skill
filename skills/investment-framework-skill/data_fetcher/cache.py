"""
缓存管理模块

内存缓存 + 可选的文件缓存
"""

import time
import json
import os
from typing import Any, Optional
from datetime import datetime
from .exceptions import CacheError

CACHE_DIR = os.path.expanduser('~/.investment_framework/cache')


class CacheManager:
    """缓存管理器"""
    
    def __init__(self, ttl: int = 300, use_file_cache: bool = False):
        """
        初始化缓存
        
        Args:
            ttl: 缓存有效期（秒），默认 300 秒（5 分钟）
            use_file_cache: 是否使用文件缓存
        """
        self.ttl = ttl
        self.use_file_cache = use_file_cache
        self._cache = {}  # 内存缓存
        
        if use_file_cache:
            os.makedirs(CACHE_DIR, exist_ok=True)
    
    def get(self, key: str) -> Optional[Any]:
        """
        获取缓存
        
        Args:
            key: 缓存键
        
        Returns:
            缓存值，过期或不存在返回 None
        """
        # 先查内存缓存
        if key in self._cache:
            entry = self._cache[key]
            if time.time() < entry['expires']:
                return entry['data']
            else:
                # 过期，删除
                del self._cache[key]
        
        # 再查文件缓存
        if self.use_file_cache:
            file_path = self._get_file_path(key)
            if os.path.exists(file_path):
                try:
                    with open(file_path, 'r', encoding='utf-8') as f:
                        entry = json.load(f)
                    
                    if time.time() < entry['expires']:
                        # 回写到内存缓存
                        self._cache[key] = entry
                        return entry['data']
                    else:
                        # 过期，删除
                        os.remove(file_path)
                except Exception:
                    pass
        
        return None
    
    def set(self, key: str, data: Any, ttl: int = None) -> None:
        """
        设置缓存
        
        Args:
            key: 缓存键
            data: 缓存数据
            ttl: 有效期（秒），None 使用默认值
        """
        ttl = ttl if ttl is not None else self.ttl
        expires = time.time() + ttl
        
        entry = {
            'data': data,
            'expires': expires,
            'timestamp': datetime.now().isoformat(),
        }
        
        # 写入内存缓存
        self._cache[key] = entry
        
        # 写入文件缓存
        if self.use_file_cache:
            try:
                file_path = self._get_file_path(key)
                with open(file_path, 'w', encoding='utf-8') as f:
                    json.dump(entry, f, ensure_ascii=False, indent=2)
            except Exception as e:
                raise CacheError(f"写入文件缓存失败：{e}")
    
    def delete(self, key: str) -> bool:
        """
        删除缓存
        
        Args:
            key: 缓存键
        
        Returns:
            True: 删除成功，False: 键不存在
        """
        deleted = False
        
        if key in self._cache:
            del self._cache[key]
            deleted = True
        
        if self.use_file_cache:
            file_path = self._get_file_path(key)
            if os.path.exists(file_path):
                os.remove(file_path)
                deleted = True
        
        return deleted
    
    def clear(self) -> None:
        """清空所有缓存"""
        self._cache.clear()
        
        if self.use_file_cache:
            if os.path.exists(CACHE_DIR):
                for filename in os.listdir(CACHE_DIR):
                    file_path = os.path.join(CACHE_DIR, filename)
                    try:
                        os.remove(file_path)
                    except Exception:
                        pass
    
    def _get_file_path(self, key: str) -> str:
        """获取文件缓存路径"""
        # 使用 MD5 或哈希避免非法文件名
        import hashlib
        key_hash = hashlib.md5(key.encode()).hexdigest()
        return os.path.join(CACHE_DIR, f"{key_hash}.json")
    
    def cleanup_expired(self) -> int:
        """
        清理过期缓存
        
        Returns:
            清理的缓存数量
        """
        count = 0
        now = time.time()
        
        # 清理内存缓存
        expired_keys = [
            key for key, entry in self._cache.items()
            if now >= entry['expires']
        ]
        for key in expired_keys:
            del self._cache[key]
            count += 1
        
        # 清理文件缓存
        if self.use_file_cache and os.path.exists(CACHE_DIR):
            for filename in os.listdir(CACHE_DIR):
                file_path = os.path.join(CACHE_DIR, filename)
                try:
                    with open(file_path, 'r', encoding='utf-8') as f:
                        entry = json.load(f)
                    
                    if now >= entry['expires']:
                        os.remove(file_path)
                        count += 1
                except Exception:
                    # 文件损坏，删除
                    try:
                        os.remove(file_path)
                        count += 1
                    except Exception:
                        pass
        
        return count
    
    def stats(self) -> dict:
        """
        获取缓存统计
        
        Returns:
            统计信息字典
        """
        now = time.time()
        
        # 内存缓存统计
        memory_count = len(self._cache)
        memory_valid = sum(
            1 for entry in self._cache.values()
            if now < entry['expires']
        )
        
        # 文件缓存统计
        file_count = 0
        file_valid = 0
        
        if self.use_file_cache and os.path.exists(CACHE_DIR):
            for filename in os.listdir(CACHE_DIR):
                file_count += 1
                file_path = os.path.join(CACHE_DIR, filename)
                try:
                    with open(file_path, 'r', encoding='utf-8') as f:
                        entry = json.load(f)
                    if now < entry['expires']:
                        file_valid += 1
                except Exception:
                    pass
        
        return {
            'memory': {
                'total': memory_count,
                'valid': memory_valid,
                'expired': memory_count - memory_valid,
            },
            'file': {
                'total': file_count,
                'valid': file_valid,
                'expired': file_count - file_valid,
            },
            'ttl': self.ttl,
        }
