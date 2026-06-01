"""渲染编排：把某个源的数据渲染为「图片 URL / 图片 base64 / 纯文字」。

返回与 AstrBot 解耦的中性 ``RenderPart`` 列表，由 main.py 转成消息组件。

渲染优先级（render_mode）：纯文字直出；API渲染走 html_render；本地渲染走 Pillow；
自动（默认）= html_render → Pillow → 文字 三级降级。各类别的具体渲染逻辑见 kinds.py，
本模块只负责"按输出形式编排 + 调后端 + 异步填充封面"。
"""

import asyncio
from typing import Literal, Optional, TypedDict

from . import kinds, links, local_render, sources
from .config import Config
from .log import logger


class RenderPart(TypedDict):
    """render → main 的中性产物：``type`` 决定转成哪种消息组件。"""

    type: Literal["image_url", "image_b64", "text"]
    value: str


def text_part(value: str) -> RenderPart:
    return {"type": "text", "value": value}


class Renderer:
    def __init__(self, cfg: Config, client, html_render_fn, shortener=None):
        self._cfg = cfg
        self.client = client
        self._html_render = html_render_fn  # Star.html_render，或 None（不可用时）
        self.shortener = shortener  # LinkShortener，或 None（未配置/不启用）
        self._local = local_render.LocalCardRenderer()

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
        """按各源「输出形式」渲染，返回 RenderPart 列表（可含图片+文字）。"""
        out = self._output_mode(source)
        top_n = self._top_n()
        if self._should_shorten(source, out):
            await links.apply_shortlinks(
                self.shortener, kinds.kind_for(source), source.key, raw, top_n
            )
        text = sources.render_text(source, raw, top_n)
        parts: list = []

        if out in ("图片", "图文"):
            img = await self._make_image(source, raw, top_n)
            if img:
                parts.append(img)
            elif out == "图片":
                parts.append(text_part(text))  # 出图失败兜底文字

        if out in ("文字", "图文"):
            parts.append(text_part(text))

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
    # 图片后端
    # ------------------------------------------------------------------ #
    async def _make_image(self, source, raw, top_n) -> Optional[RenderPart]:
        """按 render_mode 产出图片 part；失败返回 None。"""
        mode = self._cfg.get("render_mode")
        if mode == "本地渲染":
            return self._local_card(source, sources.render_text(source, raw, top_n))
        try:
            res = await self._api_image(source, raw, top_n)
            if res:
                return res
        except Exception as e:  # noqa: BLE001
            logger.warning("[render] API 渲染失败 %s: %s", source.key, e)
        if mode != "API渲染":  # 自动 → 回退本地 Pillow
            return self._local_card(source, sources.render_text(source, raw, top_n))
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
        url = await self._html_render(
            strat.template, ctx, options={"full_page": True, "type": "png"}
        )
        return {"type": "image_url", "value": url} if url else None

    def _local_card(self, source, text: str) -> Optional[RenderPart]:
        b64 = self._local.render(text, self._cfg.bool("dark_mode"))
        return {"type": "image_b64", "value": b64} if b64 else None

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
