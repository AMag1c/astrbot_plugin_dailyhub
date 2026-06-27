"""60s API 客户端 + 图片抓取。

设计要点：
- 统一处理 base_url + 多备用源回退；请求头带 ``Accept-Encoding: identity`` 规避部分镜像的 Brotli 解码坑；
- 统一解析 60s 的 ``{code, message, data}`` 信封，只返回 ``data``；
- 所有方法失败返回 ``None`` 并记日志，不向上抛异常；可脱离框架单测。

注意：60s 公共 API 当前所在的 Deno Deploy Classic 预计 2026-07-20 停服，
故 base_url 与备用源均可在插件配置中覆盖，必要时指向私有部署。
"""

import asyncio
import base64
import datetime
import ipaddress
from typing import Any, Optional
from urllib.parse import urlparse

import aiohttp

from .log import logger

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)

DEFAULT_BASE_URL = "https://60s.viki.moe"

# 已知可用的公共镜像，主源失败时依次回退
DEFAULT_FALLBACK_HOSTS = [
    "https://60s.b23.run",
    "https://60s-api-cf.viki.moe",
    "https://60s-api.114128.xyz",
    "https://60s-api-cf.114128.xyz",
]


class SixtyClient:
    """60s API 客户端，复用单个 aiohttp 会话。"""

    def __init__(
        self,
        base_url: str = DEFAULT_BASE_URL,
        fallback_hosts: Optional[list] = None,
        timeout: int = 15,
    ):
        self._bases = self._build_bases(base_url, fallback_hosts)
        self._timeout = aiohttp.ClientTimeout(total=timeout)
        self._session: Optional[aiohttp.ClientSession] = None
        self._session_lock = asyncio.Lock()

    @staticmethod
    def _build_bases(base_url: str, fallback_hosts: Optional[list]) -> list:
        """合并主源与备用源，去重去空、去掉尾部斜杠，保持顺序。"""
        bases: list = []
        candidates = [base_url] + list(fallback_hosts or DEFAULT_FALLBACK_HOSTS)
        for b in candidates:
            if not b or not isinstance(b, str):
                continue
            b = b.strip().rstrip("/")
            if b and b not in bases:
                bases.append(b)
        return bases or [DEFAULT_BASE_URL]

    async def _get_session(self) -> aiohttp.ClientSession:
        async with self._session_lock:
            if self._session is None or self._session.closed:
                self._session = aiohttp.ClientSession(timeout=self._timeout)
            return self._session

    # ------------------------------------------------------------------ #
    # 数据接口
    # ------------------------------------------------------------------ #
    async def fetch(self, endpoint: str, params: Optional[dict] = None) -> Any:
        """GET ``{base}{endpoint}``，解析 ``{code,message,data}`` 返回 data。

        逐个尝试主源与备用源，任一成功即返回；全部失败返回 None。
        """
        ep = endpoint if endpoint.startswith("/") else "/" + endpoint
        session = await self._get_session()
        headers = {"Accept-Encoding": "identity", "User-Agent": _UA}
        last_err: Optional[Exception] = None

        for base in self._bases:
            url = base + ep
            try:
                async with session.get(url, params=params, headers=headers) as resp:
                    if resp.status != 200:
                        logger.warning("60s 请求 %s 返回 HTTP %s", url, resp.status)
                        continue
                    # content_type=None：部分镜像 JSON 的 Content-Type 不规范
                    payload = await resp.json(content_type=None)
            except Exception as e:  # noqa: BLE001
                logger.warning("60s 请求 %s 出错: %s", url, e)
                last_err = e
                continue

            data = self._extract(payload)
            if data is not None:
                return data
            logger.info("60s %s 未返回有效 data，尝试下一个源", url)

        if last_err:
            logger.error("60s 所有源均失败（端点 %s），最后错误: %s", ep, last_err)
        return None

    @staticmethod
    def _extract(payload: Any) -> Any:
        """从 60s 信封中取 data：校验业务码，异常返回 None。"""
        if isinstance(payload, dict):
            if "data" in payload:
                code = payload.get("code", 200)
                if code in (200, 0, None):
                    return payload.get("data")
                logger.warning("60s 业务码 %s: %s", code, payload.get("message"))
                return None
            return payload  # 少数端点可能直接返回对象
        if isinstance(payload, list):
            return payload
        return None

    # ------------------------------------------------------------------ #
    # 外部 API（非 60s 信封）：Bangumi 番组计划 / RAWG 游戏
    # ------------------------------------------------------------------ #
    async def fetch_json(
        self, url: str, params: Optional[dict] = None, headers: Optional[dict] = None
    ) -> Any:
        """通用 GET → 原样返回解析后的 JSON；失败返回 None，不抛异常。"""
        session = await self._get_session()
        hdr = {"User-Agent": _UA, "Accept-Encoding": "identity"}
        if headers:
            hdr.update(headers)
        try:
            async with session.get(url, params=params, headers=hdr) as resp:
                if resp.status != 200:
                    logger.warning("外部请求 %s 返回 HTTP %s", url, resp.status)
                    return None
                return await resp.json(content_type=None)
        except Exception as e:  # noqa: BLE001
            logger.warning("外部请求 %s 出错: %s", url, e)
            return None

    async def fetch_bangumi_today(self) -> Optional[list]:
        """取 Bangumi 番组计划当天放送番剧（api.bgm.tv/calendar）。

        返回当天 items 列表（每项含 name_cn/name/rating/images/collection 等原始字段，
        由 BangumiKind 归一化）；失败/无数据返回 None。
        """
        data = await self.fetch_json("https://api.bgm.tv/calendar")
        if not isinstance(data, list):
            return None
        # weekday.id：1=周一..7=周日；Python date.weekday()：0=周一..6=周日 → +1
        today_id = datetime.date.today().weekday() + 1
        for day in data:
            if (
                isinstance(day, dict)
                and (day.get("weekday") or {}).get("id") == today_id
            ):
                items = day.get("items")
                return items if isinstance(items, list) else None
        return None

    async def fetch_rawg_games(
        self, api_key: str, window_days: int, top_n: int
    ) -> Optional[list]:
        """取 RAWG 即将发售游戏（未来 window_days 天，按期待度 ``-added`` 排序）。

        返回 results 列表（含 name/released/background_image/parent_platforms/rating
        等，由 GameKind 归一化）；未配 key / 失败返回 None。不加 stores 过滤——实测加了
        会把未来游戏几乎全过滤掉。
        """
        if not api_key:
            return None
        today = datetime.date.today()
        future = today + datetime.timedelta(days=max(int(window_days or 1), 1))
        params = {
            "key": api_key,
            "dates": f"{today},{future}",
            "ordering": "-added",
            "page_size": max(int(top_n or 10), 1),
        }
        data = await self.fetch_json("https://api.rawg.io/api/games", params=params)
        if not isinstance(data, dict):
            return None
        results = data.get("results")
        return results if isinstance(results, list) else None

    # ------------------------------------------------------------------ #
    # 图片抓取（封面图，带 SSRF 防护）
    # ------------------------------------------------------------------ #
    async def fetch_image_data_uri(self, url: str) -> Optional[str]:
        """下载图片并转为 data URI，规避防盗链；失败返回 None。"""
        safe = await self.sanitize_image_url(url)
        if not safe:
            return None
        try:
            session = await self._get_session()
            async with session.get(safe, headers={"User-Agent": _UA}) as resp:
                if resp.status != 200:
                    return None
                ctype = resp.headers.get("Content-Type", "image/jpeg").split(";")[0]
                raw = await resp.read()
            b64 = base64.b64encode(raw).decode("ascii")
            return f"data:{ctype};base64,{b64}"
        except Exception as e:  # noqa: BLE001
            logger.warning("图片下载失败 %s: %s", safe, e)
            return None

    @staticmethod
    async def sanitize_image_url(url: str) -> str:
        """封面图 URL 防 SSRF：仅 https、拒内网/回环、DNS 解析防 Rebinding。

        合法返回原 URL，非法返回空串。
        """
        if not url or not isinstance(url, str):
            return ""
        try:
            parsed = urlparse(url)
            if parsed.scheme != "https":
                return ""
            hostname = (parsed.hostname or "").lower()
            blocked = {
                "localhost",
                "localhost.localdomain",
                "ip6-localhost",
                "ip6-loopback",
            }
            if hostname in blocked or hostname.endswith(".local"):
                return ""
            loop = asyncio.get_running_loop()
            addr_info = await loop.getaddrinfo(hostname, None)
            for res in addr_info:
                ip = ipaddress.ip_address(res[4][0])
                if (
                    ip.is_private
                    or ip.is_loopback
                    or ip.is_link_local
                    or ip.is_reserved
                    or ip.is_multicast
                    or ip.is_unspecified
                    or not getattr(ip, "is_global", True)
                ):
                    return ""
            return url
        except Exception:  # noqa: BLE001
            return ""

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()
