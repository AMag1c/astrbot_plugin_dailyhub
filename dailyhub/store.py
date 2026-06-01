"""通用 JSON 持久化：原子写 + asyncio 锁。

供去重缓存 / AI 总结缓存等运行期数据使用（订阅名单另存于插件 config）。便于脱离框架单测。
"""

import asyncio
import json
import os
import tempfile
from typing import Any, Callable

from .log import logger


class JsonStore:
    """单文件 JSON 存储，带异步锁与原子写（先写临时文件再 os.replace）。"""

    def __init__(self, filepath: str):
        self._path = str(filepath)
        self._lock = asyncio.Lock()
        os.makedirs(os.path.dirname(self._path) or ".", exist_ok=True)

    async def read(self, default: Any = None) -> Any:
        async with self._lock:
            return self._read_unlocked(default)

    def _read_unlocked(self, default: Any = None) -> Any:
        try:
            if os.path.exists(self._path):
                with open(self._path, "r", encoding="utf-8") as f:
                    return json.load(f)
        except Exception as e:  # noqa: BLE001
            logger.error("读取 %s 失败: %s", self._path, e)
        return {} if default is None else default

    async def write(self, data: Any) -> None:
        async with self._lock:
            self._atomic_write(data)

    async def update(self, fn: Callable[[Any], Any]) -> Any:
        """读-改-写原子操作：new = fn(old)，全程持锁。返回写入后的数据。"""
        async with self._lock:
            data = self._read_unlocked()
            new_data = fn(data)
            self._atomic_write(new_data)
            return new_data

    def _atomic_write(self, data: Any) -> None:
        dir_path = os.path.dirname(self._path) or "."
        try:
            fd, tmp = tempfile.mkstemp(dir=dir_path, suffix=".tmp")
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
                os.replace(tmp, self._path)
            except Exception:
                try:
                    os.unlink(tmp)
                except OSError:
                    pass
                raise
        except Exception as e:  # noqa: BLE001
            logger.error("写入 %s 失败: %s", self._path, e)
            raise
