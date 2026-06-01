"""短链服务客户端：把长链通过自建 Shlink 实例转为短链。

设计要点（参照 client.py 的 aiohttp 复用风格）：
- 与 AstrBot 解耦，仅依赖标准库 + aiohttp，可脱框架单测；
- 任何失败（未配置 / 非 http(s) / 网络 / 4xx / 超时）都**回退返回原长链**，绝不抛异常、
  绝不返回空，保证短链不可用时推送照常进行；
- 进程内缓存 long->short，配合 Shlink 的 findIfExists 减少重复请求；
- 短链默认 2 天失效：``validUntil`` 用 ISO-8601 **带 UTC 偏移、无毫秒**的时间，且固定取目标日
  零点（``...T00:00:00+00:00``）。Shlink 要求日期带时区偏移、不含毫秒，裸日期 YYYY-MM-DD 会
  返回 400 INVALID_ARGUMENT；固定零点又使同一天内同一长链请求参数一致，findIfExists 能复用同一短码。

Shlink API：``POST {api_base}/rest/v3/short-urls``，头 ``X-Api-Key``，
body ``{longUrl, findIfExists:true, [validUntil], [domain]}``，成功返回 ``{shortUrl, ...}``。
"""

import asyncio
from datetime import date, datetime, time, timedelta, timezone
from typing import Optional
from urllib.parse import urlparse

import aiohttp

from .log import logger

_API_PATH = "/rest/v3/short-urls"


class LinkShortener:
    """Shlink 短链客户端，复用单个 aiohttp 会话。

    未配置（地址或 Key 为空）时 ``enabled=False``，``shorten`` 原样返回长链。
    """

    def __init__(
        self,
        api_base: str = "",
        api_key: str = "",
        domain: str = "",
        valid_days: int = 2,
        timeout: int = 10,
        concurrency: int = 5,
        cache_max: int = 2000,
    ):
        self._endpoint = self._build_endpoint(api_base)
        self._api_key = (api_key or "").strip()
        self._domain = (domain or "").strip()
        try:
            self._valid_days = int(valid_days)
        except (TypeError, ValueError):
            self._valid_days = 0
        self._timeout = aiohttp.ClientTimeout(total=max(1, timeout))
        self._sem = asyncio.Semaphore(max(1, concurrency))
        self._cache: dict = {}
        self._cache_max = max(1, cache_max)
        self._session: Optional[aiohttp.ClientSession] = None
        self._session_lock = asyncio.Lock()

    @staticmethod
    def _build_endpoint(api_base: str) -> str:
        """由实例根地址拼出短链创建端点；已填到 /rest/... 则原样用。空地址返回空串。"""
        base = (api_base or "").strip().rstrip("/")
        if not base:
            return ""
        return base if "/rest/" in base else base + _API_PATH

    @property
    def enabled(self) -> bool:
        return bool(self._endpoint and self._api_key)

    @staticmethod
    def _is_shortenable(url) -> bool:
        """仅 http/https 的链接才送去短化（空 / 相对路径 / magnet 等跳过）。"""
        if not url or not isinstance(url, str):
            return False
        try:
            return urlparse(url).scheme in ("http", "https")
        except Exception:  # noqa: BLE001
            return False

    def _valid_until(self) -> Optional[str]:
        """短链失效时间（ISO-8601 带 UTC 偏移、无毫秒）；valid_days<=0 表示永久（None）。

        Shlink 要求日期必须带时区偏移且不含毫秒，裸日期 YYYY-MM-DD 会被拒为 400
        INVALID_ARGUMENT（已对真实实例验证）。这里固定取目标日的 UTC 零点
        （``...T00:00:00+00:00``），既满足格式，又保证同一天内同一长链请求参数一致，
        让 findIfExists 复用同一短码。
        """
        if self._valid_days <= 0:
            return None
        target = date.today() + timedelta(days=self._valid_days)
        return datetime.combine(target, time.min, tzinfo=timezone.utc).isoformat(
            timespec="seconds"
        )

    async def _get_session(self) -> aiohttp.ClientSession:
        async with self._session_lock:
            if self._session is None or self._session.closed:
                self._session = aiohttp.ClientSession(timeout=self._timeout)
            return self._session

    async def shorten(self, url: str) -> str:
        """单条长链转短链；未配置 / 非法 / 任何失败都回退原 url。"""
        if not self.enabled or not self._is_shortenable(url):
            return url
        if url in self._cache:
            return self._cache[url]

        body = {"longUrl": url, "findIfExists": True}
        vu = self._valid_until()
        if vu:
            body["validUntil"] = vu
        if self._domain:
            body["domain"] = self._domain
        headers = {
            "X-Api-Key": self._api_key,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        try:
            session = await self._get_session()
            async with session.post(self._endpoint, json=body, headers=headers) as resp:
                if resp.status not in (200, 201):
                    detail = (await resp.text())[:200]
                    # 逐 URL 降为 debug；批量失败由 links 的聚合行（INFO）兜底告警
                    logger.debug(
                        "[shortlink] HTTP %s 回退原链；响应：%s",
                        resp.status,
                        detail,
                    )
                    return url
                data = await resp.json(content_type=None)
        except Exception as e:  # noqa: BLE001
            logger.debug("[shortlink] 创建短链失败回退原链: %s", e)
            return url

        short = data.get("shortUrl") if isinstance(data, dict) else None
        if not short:
            return url
        self._put_cache(url, short)
        return short

    def _put_cache(self, long_url: str, short: str) -> None:
        if len(self._cache) >= self._cache_max:
            self._cache.clear()  # 榜单链接量小，达上限直接清空足够
        self._cache[long_url] = short

    async def shorten_many(self, urls: list) -> dict:
        """批量短化，返回 ``{原url: 短链或原url}``（去重 + 并发）。"""
        uniq: list = []
        seen = set()
        for u in urls or []:
            if u and u not in seen:
                seen.add(u)
                uniq.append(u)
        if not uniq or not self.enabled:
            return {u: u for u in uniq}

        async def one(u):
            async with self._sem:
                return u, await self.shorten(u)

        pairs = await asyncio.gather(*[one(u) for u in uniq])
        return dict(pairs)

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()
