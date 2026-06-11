"""渲染编排：把某个源的数据渲染为「图片 URL / 纯文字」。

返回与 AstrBot 解耦的中性 ``RenderPart`` 列表，由 main.py 转成消息组件。

出图只走在线 html_render（远程 t2i 服务），失败或超时即回退纯文字——不做本地 Pillow
兜底（容器多无中文字体会渲染成方块且阻塞耗时）。各源到底出图/出文字由其「输出形式」
决定（见 render）；各类别的具体渲染逻辑见 kinds.py。本模块只负责"按输出形式编排 +
调后端 + 异步填充封面"。
"""

import asyncio
from typing import Literal, Optional, TypedDict

from . import kinds, links, sources
from .config import Config
from .log import logger


class RenderPart(TypedDict):
    """render → main 的中性产物：``type`` 决定转成哪种消息组件。"""

    type: Literal["image_url", "text"]
    value: str


def text_part(value: str) -> RenderPart:
    return {"type": "text", "value": value}


class Renderer:
    def __init__(self, cfg: Config, client, html_render_fn, shortener=None):
        self._cfg = cfg
        self.client = client
        self._html_render = html_render_fn  # Star.html_render，或 None（不可用时）
        self.shortener = shortener  # LinkShortener，或 None（未配置/不启用）

    def _top_n(self) -> int:
        return self._cfg.int("list_top_n")

    def _theme(self) -> str:
        return "dark" if self._cfg.bool("dark_mode") else "light"

    def _output_mode(self, source) -> str:
        val = self._cfg.src(source.key).get("output")
        return val if val in ("图片", "文字", "图文") else "图片"

    # ------------------------------------------------------------------ #
    # 主入口
    # ------------------------------------------------------------------ #
    async def render(self, source: "sources.SourceDef", raw) -> list:
        """按各源「输出形式」渲染，返回 RenderPart 列表（可含图片+文字）。

        全程打 INFO 流水日志（输出形式 → 图片成败 → 文字 → 完成），让指令路径也能在
        WebUI 跟踪到进度（AI 工具路径另有框架的「使用工具」日志）。图片失败的具体原因
        由 _make_image 记 WARNING；实际发送/推送由调用方（框架 / scheduler）记录。
        """
        out = self._output_mode(source)
        top_n = self._top_n()
        logger.info("[render] 源=%s：输出形式=%s，开始渲染", source.key, out)
        if self._should_shorten(source, out):
            await links.apply_shortlinks(
                self.shortener, kinds.kind_for(source), source.key, raw, top_n
            )
        text = sources.render_text(source, raw, top_n)
        parts: list = []
        want_text = out in ("文字", "图文")  # 这些模式本就要发文字

        if out in ("图片", "图文"):
            img = await self._make_image(source, raw, top_n)
            if img:
                logger.info("[render] 源=%s：图片渲染成功", source.key)
                parts.append(img)
            else:
                # 失败原因已由 _make_image 记 WARNING，这里只记流程走向
                logger.info("[render] 源=%s：图片渲染失败，回退文字", source.key)
                want_text = want_text or out == "图片"

        if want_text:
            parts.append(text_part(text))
            logger.info("[render] 源=%s：文字已生成", source.key)

        logger.info(
            "[render] 源=%s：渲染完成，共 %d 条消息待发送", source.key, len(parts)
        )
        return parts or [text_part(text)]

    # ------------------------------------------------------------------ #
    # 短链：是否对本次渲染应用（应用细节在 links.py）
    # ------------------------------------------------------------------ #
    def _should_shorten(self, source, out: str) -> bool:
        sl = self._cfg.src(source.key).get("shorten_link")
        enabled = bool(self.shortener and self.shortener.enabled)
        ok = out in ("文字", "图文") and enabled and bool(sl)
        if not ok:
            logger.debug(
                "[shortlink] 跳过 源=%s output=%s enabled=%s 开关=%r",
                source.key,
                out,
                enabled,
                sl,
            )
        return ok

    # ------------------------------------------------------------------ #
    # 图片后端（仅在线 html_render；失败/超时回退纯文字）
    # ------------------------------------------------------------------ #
    async def _make_image(self, source, raw, top_n) -> Optional[RenderPart]:
        """在线渲染出图；失败或超时返回 None（由上层回退纯文字）。"""
        try:
            return await self._api_image(source, raw, top_n)
        except asyncio.TimeoutError:
            logger.warning(
                "[render] 在线渲染超时（>%ss），回退纯文字 %s",
                self._cfg.int("render_timeout"),
                source.key,
            )
            return None
        except Exception as e:  # noqa: BLE001
            logger.warning("[render] 在线渲染失败 %s: %s", source.key, e)
            return None

    async def _api_image(self, source, raw, top_n) -> Optional[RenderPart]:
        strat = kinds.kind_for(source)
        direct = strat.direct_image(raw)  # 60s 等：直接用官方图片 URL
        if direct:
            return {"type": "image_url", "value": direct}
        if not strat.template or self._html_render is None:
            return None
        ctx = strat.html_ctx(source, raw, top_n, self._theme())
        if not strat.has_content(ctx):
            return None
        await self._fill_covers_in_ctx(ctx)
        # 给在线渲染加总超时（可配 render_timeout，默认 50s）：AstrBot 内部 html_render
        # 默认不设总超时，远程 t2i 504/挂起会拖很久；超时即抛 TimeoutError → 回退纯文字。
        url = await asyncio.wait_for(
            self._html_render(
                strat.template, ctx, options={"full_page": True, "type": "png"}
            ),
            timeout=self._cfg.int("render_timeout"),
        )
        # 仅当是有效 http(s) URL 才用（strip 掉配置/返回里可能的空格）；
        # 否则（空 / 本地路径 / 异常）返回 None → 上层回退纯文字
        url = url.strip() if isinstance(url, str) else ""
        if url.startswith(("http://", "https://")):
            return {"type": "image_url", "value": url}
        return None

    # ------------------------------------------------------------------ #
    # 封面：把上下文里带 cover 的条目并发转 data URI
    # ------------------------------------------------------------------ #
    async def _fill_covers_in_ctx(self, ctx: dict) -> None:
        targets = []
        for v in ctx.values():
            if isinstance(v, list):
                targets += [it for it in v if isinstance(it, dict) and it.get("cover")]
        await self._fill_covers(targets)

    async def _fill_covers(self, items: list) -> None:
        if not items:
            return
        sem = asyncio.Semaphore(5)

        async def one(it):
            async with sem:
                it["cover"] = await self.client.fetch_image_data_uri(it["cover"]) or ""

        await asyncio.gather(*[one(it) for it in items])
