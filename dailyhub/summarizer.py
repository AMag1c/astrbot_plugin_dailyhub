"""AI 日报源：RSS（橘鸦 AI 日报）抓取 + LLM 总结。

- 与具体 LLM 解耦：调用方注入 ``llm_ask: async (prompt) -> str``（参照 bilicard/summarizer.py），
  本模块只负责抓 RSS、拼 Prompt、清洗、按日期缓存总结结果。
- 产出标准化 dict，供 sources/render 的 ``ai`` 类别消费：
  ``{"date", "title", "link", "headlines": [{"no","title","link"}], "summary"?}``。
  headlines 取自 content:encoded 的「概览」分条；summary 仅在开启 LLM 总结时存在。
"""

import html
import re
import xml.etree.ElementTree as ET
from datetime import datetime
from email.utils import parsedate_to_datetime
from typing import Awaitable, Callable, Optional

import aiohttp

from .log import logger

DEFAULT_RSS_URL = "https://imjuya.github.io/juya-ai-daily/rss.xml"

# RSS 2.0 content:encoded 命名空间——橘鸦日报完整正文在此节点，description 仅截断摘要
_CONTENT_ENCODED = "{http://purl.org/rss/1.0/modules/content/}encoded"

_SUMMARY_PROMPT = """你是一个专业的 AI 资讯编辑。请将以下 AI 早报内容进行精炼总结，要求：
1. 提取最重要的 5-8 条新闻要点
2. 每条用一句话概括，突出关键信息（公司、产品、技术、数据）
3. 使用简洁的中文表述
4. 保持新闻的时效性和准确性

原文内容：
{content}

请输出总结："""

_MAX_CONTENT = 8000  # 送入 LLM 的最大字符数
_CACHE_KEEP = 12  # 总结缓存保留最近天数


class AiDaily:
    """AI 日报抓取 + 总结。cache 为可选的 JsonStore（按日期缓存总结）。"""

    def __init__(self, rss_url: str = DEFAULT_RSS_URL, cache=None, timeout: int = 30):
        self.rss_url = rss_url or DEFAULT_RSS_URL
        self.cache = cache
        self._timeout = aiohttp.ClientTimeout(total=timeout)

    async def fetch_latest(self) -> Optional[dict]:
        """抓取 RSS 最新一篇，返回 {title, link, content, pub_date, date}；失败返回 None。"""
        headers = {
            "User-Agent": "Mozilla/5.0 (compatible; AstrBot-dailyhub/1.0)",
            "Accept": "application/rss+xml, application/xml, text/xml, */*",
        }
        try:
            async with aiohttp.ClientSession(timeout=self._timeout) as session:
                async with session.get(self.rss_url, headers=headers) as resp:
                    if resp.status != 200:
                        logger.warning("AI 日报 RSS 返回 HTTP %s", resp.status)
                        return None
                    xml_text = await resp.text()
        except Exception as e:  # noqa: BLE001
            logger.error("AI 日报 RSS 抓取失败: %s", e)
            return None

        try:
            root = ET.fromstring(xml_text)
        except ET.ParseError as e:
            logger.error("AI 日报 RSS 解析失败: %s", e)
            return None

        channel = root.find("channel")
        item = channel.find("item") if channel is not None else None
        if item is None:
            logger.warning("AI 日报 RSS 无 item")
            return None

        title = (item.findtext("title", "") or "").strip()
        link = (item.findtext("link", "") or "").strip()
        description = (item.findtext("description", "") or "").strip()
        pub_date = (item.findtext("pubDate", "") or "").strip()
        if not title:
            return None

        # content:encoded 是完整正文（含「概览」分条）；description 仅截断摘要
        encoded = (item.findtext(_CONTENT_ENCODED, "") or "").strip()
        headlines = self._parse_overview(encoded)
        content = self._clean_html(encoded or description)  # 供 LLM 总结的正文
        return {
            "title": title,
            "link": link,
            "content": content,
            "headlines": headlines,
            "pub_date": pub_date,
            "date": self._parse_date(pub_date, title),
        }

    @staticmethod
    def _parse_overview(html_text: str) -> list:
        """解析 content:encoded 的「概览」区，提取每条要点。

        概览形如 ``<h2>概览</h2>`` 后若干
        ``<h3>分类</h3><ul><li>要点 <a ...>↗</a> <code>#N</code></li></ul>``，
        至第一个 ``<hr>`` 结束（其后为各条详情，不并入）。
        返回 ``[{"no","title","link"}]``；无链接条目 link 为空串。
        """
        if not html_text:
            return []
        m = re.search(r"概览\s*</h2>(.*?)(?:<hr|$)", html_text, re.S)
        region = m.group(1) if m else html_text
        items: list = []
        for li in re.findall(r"<li>(.*?)</li>", region, re.S):
            nm = re.search(r"<code>\s*#?(\d+)\s*</code>", li)
            no = nm.group(1) if nm else str(len(items) + 1)
            lm = re.search(r'<a\s+[^>]*href="([^"]+)"', li)
            link = lm.group(1) if lm else ""
            title = re.sub(r"<code>.*?</code>", "", li, flags=re.S)  # 去编号
            title = re.sub(r"<[^>]+>", "", title)  # 去其余标签
            title = html.unescape(title).replace("↗", " ")
            title = re.sub(r"\s+", " ", title).strip()
            if title:
                items.append({"no": no, "title": title, "link": link})
        return items

    async def build(
        self,
        llm_ask: Optional[Callable[[str], Awaitable[str]]],
        enable_summary: bool = True,
    ) -> Optional[dict]:
        """抓取并产出标准化 dict（带缓存）。无法抓取返回 None。"""
        article = await self.fetch_latest()
        if not article:
            return None
        date, title, link = article["date"], article["title"], article["link"]
        content = article["content"]
        base = {
            "date": date,
            "title": title,
            "link": link,
            "headlines": article.get("headlines") or [],
        }

        if enable_summary and llm_ask is not None:
            cached = await self._cache_get(date)
            if cached:
                return {**base, "summary": cached}
            summary = await self.summarize(content, llm_ask)
            if summary:
                await self._cache_put(date, summary)
                return {**base, "summary": summary}

        # 默认：带「概览」分条（文字逐条列出、图片走热榜榜单样式）
        return base

    async def summarize(
        self, content: str, llm_ask: Callable[[str], Awaitable[str]]
    ) -> Optional[str]:
        if not content or len(content.strip()) < 50:
            logger.info("AI 日报正文过短，跳过总结")
            return None
        if len(content) > _MAX_CONTENT:
            content = content[:_MAX_CONTENT] + "\n...(内容过长已截断)"
        try:
            out = await llm_ask(_SUMMARY_PROMPT.format(content=content))
        except Exception as e:  # noqa: BLE001
            logger.error("AI 总结调用失败: %s", e)
            return None
        return (out or "").strip() or None

    # ------------------------------------------------------------------ #
    # 缓存
    # ------------------------------------------------------------------ #
    async def _cache_get(self, date: str) -> Optional[str]:
        if not self.cache or not date:
            return None
        try:
            data = await self.cache.read()
            return data.get(date)
        except Exception:  # noqa: BLE001
            return None

    async def _cache_put(self, date: str, summary: str) -> None:
        if not self.cache or not date:
            return

        def _upd(c):
            c = dict(c or {})
            c[date] = summary
            if len(c) > _CACHE_KEEP:
                for k in sorted(c)[:-_CACHE_KEEP]:
                    c.pop(k, None)
            return c

        try:
            await self.cache.update(_upd)
        except Exception as e:  # noqa: BLE001
            logger.warning("AI 总结缓存写入失败: %s", e)

    # ------------------------------------------------------------------ #
    # 工具
    # ------------------------------------------------------------------ #
    @staticmethod
    def _clean_html(text: str) -> str:
        if not text:
            return ""
        clean = re.sub(r"<[^>]+>", "", text)
        clean = (
            clean.replace("&nbsp;", " ")
            .replace("&amp;", "&")
            .replace("&lt;", "<")
            .replace("&gt;", ">")
            .replace("&quot;", '"')
        )
        return re.sub(r"\n{3,}", "\n\n", clean).strip()

    @staticmethod
    def _parse_date(pub_date: str, title: str) -> str:
        if pub_date:
            try:
                return parsedate_to_datetime(pub_date).strftime("%Y-%m-%d")
            except Exception:  # noqa: BLE001
                pass
        m = re.search(r"(\d{4}-\d{2}-\d{2})", title or "")
        if m:
            return m.group(1)
        return datetime.now().strftime("%Y-%m-%d")
