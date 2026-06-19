"""HTTP + 本地缓存基础设施。"""
from __future__ import annotations

import hashlib
import os
import time
from typing import Optional

import requests

DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)


class HttpClient:
    """带文件缓存的简单 HTTP 客户端。"""

    def __init__(self, cache_dir: str = "data/cache", ttl_minutes: int = 30, timeout: int = 15):
        self.cache_dir = cache_dir
        self.ttl = ttl_minutes * 60
        self.timeout = timeout
        os.makedirs(cache_dir, exist_ok=True)

    def _cache_path(self, key: str) -> str:
        h = hashlib.md5(key.encode("utf-8")).hexdigest()
        return os.path.join(self.cache_dir, f"{h}.cache")

    def _read_cache(self, key: str) -> Optional[str]:
        path = self._cache_path(key)
        if not os.path.exists(path):
            return None
        if self.ttl > 0 and (time.time() - os.path.getmtime(path)) > self.ttl:
            return None
        try:
            with open(path, "r", encoding="utf-8") as f:
                return f.read()
        except OSError:
            return None

    def _write_cache(self, key: str, text: str) -> None:
        try:
            with open(self._cache_path(key), "w", encoding="utf-8") as f:
                f.write(text)
        except OSError:
            pass

    def get(self, url: str, headers: Optional[dict] = None, cache_key: Optional[str] = None,
            use_cache: bool = True) -> Optional[str]:
        key = cache_key or url
        if use_cache:
            cached = self._read_cache(key)
            if cached is not None:
                return cached
        hdrs = {"User-Agent": DEFAULT_UA}
        if headers:
            hdrs.update(headers)
        try:
            resp = requests.get(url, headers=hdrs, timeout=self.timeout)
            resp.raise_for_status()
            text = resp.text
            self._write_cache(key, text)
            return text
        except requests.RequestException as e:  # 网络/超时/HTTP 错误统一降级
            # 失败时尝试回退到「过期缓存」，总比没有强
            stale = None
            path = self._cache_path(key)
            if os.path.exists(path):
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        stale = f.read()
                except OSError:
                    stale = None
            if stale is not None:
                return stale
            print(f"[datasource] 请求失败 {url}: {e}")
            return None
