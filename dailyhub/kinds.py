"""展示类别（render_kind）策略。

把"每个类别怎么归一化 / 出文字 / 出 HTML 上下文 / 判有效 / 算去重签名 / 哪些链接可短化 /
用哪个模板"集中到一个 Kind 对象，避免这些 switch 分散在 sources、render、scheduler 多处
（此前新增一个类别要散弹式改 4-5 个文件）。新增类别 = 在此加一个 Kind 子类并登记到 KINDS。

不依赖 AstrBot，可脱框架单测。
"""

import hashlib
import html
import json
import re
from typing import Any

from . import templates


# ---------------------------------------------------------------------- #
# 展示工具
# ---------------------------------------------------------------------- #
def _esc(s: Any) -> str:
    """HTML 转义（html_render 的 Jinja2 不自动转义，需手动防注入/串版）。"""
    return html.escape(str(s if s is not None else ""))


def _truncate(s: str, n: int) -> str:
    s = s or ""
    return s if len(s) <= n else s[:n] + "…"


def _fmt_hot(v: Any) -> str:
    """热度数值格式化：12097407 -> 1209.7万。非数值原样返回。"""
    try:
        n = float(v)
    except (TypeError, ValueError):
        return str(v or "")
    if n >= 1e8:
        return f"{n / 1e8:.1f}亿"
    if n >= 1e4:
        return f"{n / 1e4:.1f}万"
    return str(int(n))


def _https(url: Any) -> str:
    """http 升级为 https（bgm 封面给的是 http，但 client 的 SSRF 防护只放行 https）。"""
    u = str(url or "").strip()
    return "https://" + u[7:] if u.startswith("http://") else u


def _norm_ranklist(source, raw: Any, top_n: int) -> dict:
    """热榜原始 list -> 渲染友好结构 ``{title, items:[{rank,title,hot,link,cover}]}``。"""
    items = raw if isinstance(raw, list) else []
    result = []
    for i, it in enumerate(items[:top_n], 1):
        if not isinstance(it, dict):
            continue
        rank = it.get("rank") or i
        title = it.get("title") or it.get("name") or it.get("word") or ""
        if "hot_value" in it:
            hot = _fmt_hot(it.get("hot_value"))
        elif "score" in it:
            hot = str(it.get("score") or "")
        elif "hot" in it:
            hot = _fmt_hot(it.get("hot"))
        else:
            hot = ""
        result.append(
            {
                "rank": rank,
                "title": str(title).strip(),
                "hot": hot,
                "link": it.get("link") or it.get("url") or "",
                "cover": it.get("cover") or "",
            }
        )
    return {"title": source.name, "items": result}


def _norm_news(raw: Any) -> dict:
    if not isinstance(raw, dict):
        return {}
    return {
        "date": raw.get("date", ""),
        "news": [str(x).strip() for x in (raw.get("news") or []) if str(x).strip()],
        "tip": raw.get("tip", "") or raw.get("micro_news", ""),
        "image": raw.get("image", ""),
    }


def ai_items(d: Any, top_n: int = 15) -> list:
    """AI 日报 headlines（``[{no,title,link}]``）-> ranklist 风格 items（hot/cover 恒空）。"""
    headlines = d.get("headlines") if isinstance(d, dict) else None
    items: list = []
    for i, h in enumerate((headlines or [])[:top_n], 1):
        if not isinstance(h, dict):
            continue
        try:
            rank = int(h.get("no") or i)
        except (TypeError, ValueError):
            rank = i
        items.append(
            {
                "rank": rank,
                "title": (h.get("title") or "").strip(),
                "hot": "",
                "cover": "",
                "link": h.get("link") or "",
            }
        )
    return items


# ---------------------------------------------------------------------- #
# 策略基类
# ---------------------------------------------------------------------- #
class Kind:
    """一个展示类别的全部行为。子类按需覆写。"""

    name: str = ""
    template: str = (
        ""  # html_render 模板；空串表示该类别不走 html 模板（如 news 用官方图）
    )

    # —— 文字渲染（纯文字 / 兜底）——
    def to_text(self, source, raw: Any, top_n: int) -> str:
        return f"{source.emoji} {source.name}\n暂无数据"

    # —— HTML 上下文（纯数据；cover 留原始 URL，由 render 异步转 data URI）——
    def html_ctx(self, source, raw: Any, top_n: int, theme: str) -> dict:
        return self._base_ctx(source, theme)

    def has_content(self, ctx: dict) -> bool:
        return True

    @staticmethod
    def _base_ctx(source, theme: str) -> dict:
        return {
            "theme": theme,
            "emoji": source.emoji,
            "title": source.name,
            "subtitle": "",
            "footer": f"DailyHub · {source.name} · Powered by AstrBot",
        }

    # —— 去重签名：默认按稳定基准哈希；时效型按日期覆写 ——
    def signature(self, raw: Any) -> str:
        try:
            basis = json.dumps(
                self.dedup_basis(raw), ensure_ascii=False, sort_keys=True
            )
        except Exception:  # noqa: BLE001
            basis = str(raw)
        return "h:" + hashlib.md5(basis.encode("utf-8")).hexdigest()

    def dedup_basis(self, raw: Any) -> Any:
        return raw

    # —— 短链：收集可短化链接 / 用映射就地回填（默认无链接）——
    # top_n：只收集"会被展示"的前 N 条，避免短化用不到的尾部链接。
    def collect_links(self, raw: Any, top_n: int) -> list:
        return []

    def replace_links(self, raw: Any, mapping: dict) -> None:
        pass

    # —— news 专用：直接用官方图片 URL（其余返回 None）——
    def direct_image(self, raw: Any):
        return None


class _DateSigKind(Kind):
    """时效内容（日报/金价/60s）：同一天即视为同一份，按日期去重。"""

    def signature(self, raw: Any) -> str:
        date = raw.get("date", "") if isinstance(raw, dict) else ""
        return f"date:{date}"


# ---------------------------------------------------------------------- #
# 各类别
# ---------------------------------------------------------------------- #
class RanklistKind(Kind):
    name = "ranklist"
    template = templates.RANKLIST_TMPL

    def to_text(self, source, raw, top_n):
        items = _norm_ranklist(source, raw, top_n)["items"]
        if not items:
            return f"{source.emoji} {source.name}\n暂无数据"
        lines = [f"{source.emoji} {source.name}"]
        for it in items:
            hot = f"  🔥{it['hot']}" if it.get("hot") else ""
            lines.append(f"{it['rank']}. {it['title']}{hot}")
            if it.get("link"):
                lines.append(f"   🔗 {it['link']}")
        return "\n".join(lines)

    def html_ctx(self, source, raw, top_n, theme):
        ctx = self._base_ctx(source, theme)
        items = _norm_ranklist(source, raw, top_n)["items"]
        for it in items:
            it["title"] = _esc(it["title"])
            it["hot"] = _esc(it["hot"])
        ctx["items"] = items
        return ctx

    def has_content(self, ctx):
        return bool(ctx.get("items"))

    def dedup_basis(self, raw):
        return [
            (it.get("title") or it.get("name") or "")
            for it in (raw or [])
            if isinstance(it, dict)
        ]

    def collect_links(self, raw, top_n):
        items = [it for it in (raw or []) if isinstance(it, dict)][:top_n]
        return [c for c in ((it.get("link") or it.get("url")) for it in items) if c]

    def replace_links(self, raw, mapping):
        for it in raw or []:
            if not isinstance(it, dict):
                continue
            cur = it.get("link") or it.get("url")
            if not cur or cur not in mapping:
                continue
            if it.get("link"):
                it["link"] = mapping[cur]
            else:
                it["url"] = mapping[cur]


class NewsKind(_DateSigKind):
    name = "news"  # 60s 直接用官方排版图，无 html 模板

    def to_text(self, source, raw, top_n):
        n = _norm_news(raw)
        if not n or not n.get("news"):
            return f"{source.emoji} {source.name}\n暂无数据"
        lines = [f"{source.emoji} 每日60秒读懂世界 | {n.get('date', '')}", ""]
        for i, item in enumerate(n["news"], 1):
            lines.append(f"{i}. {item}")
        if n.get("tip"):
            lines += ["", f"【微语】{n['tip']}"]
        return "\n".join(lines)

    def direct_image(self, raw):
        return raw.get("image") if isinstance(raw, dict) else None


class ItnewsKind(Kind):
    name = "itnews"
    template = templates.ITNEWS_TMPL

    def to_text(self, source, raw, top_n):
        items = [
            x for x in (raw if isinstance(raw, list) else []) if isinstance(x, dict)
        ][:top_n]
        if not items:
            return f"{source.emoji} {source.name}\n暂无数据"
        lines = [f"{source.emoji} {source.name}", ""]
        for i, it in enumerate(items, 1):
            title = (it.get("title") or "").strip()
            if title:
                lines.append(f"{i}. {title}")  # 文字版仅标题，详情见图片版（避免刷屏）
        return "\n".join(lines)

    def html_ctx(self, source, raw, top_n, theme):
        ctx = self._base_ctx(source, theme)
        items = [x for x in (raw or []) if isinstance(x, dict)][:top_n]
        ctx["items"] = [
            {
                "title": _esc((it.get("title") or "").strip()),
                "desc": _esc(_truncate((it.get("description") or "").strip(), 100)),
            }
            for it in items
        ]
        return ctx

    def has_content(self, ctx):
        return bool(ctx.get("items"))

    def dedup_basis(self, raw):
        return [(it.get("title") or "") for it in (raw or []) if isinstance(it, dict)]


class GoldKind(_DateSigKind):
    name = "gold"
    template = templates.GOLD_TMPL

    def to_text(self, source, raw, top_n):
        raw = raw if isinstance(raw, dict) else {}
        metals = raw.get("metals") or []
        if not metals:
            return f"{source.emoji} {source.name}\n暂无数据"
        lines = [
            f"{source.emoji} {source.name} | {raw.get('date', '')}".rstrip(" |"),
            "",
        ]
        for m in metals:
            if not isinstance(m, dict):
                continue
            price = m.get("today_price") or m.get("sell_price") or ""
            unit = m.get("unit", "")
            extra = []
            if m.get("high_price"):
                extra.append(f"高{m['high_price']}")
            if m.get("low_price"):
                extra.append(f"低{m['low_price']}")
            extra_s = f"（{' '.join(extra)}）" if extra else ""
            lines.append(f"· {m.get('name', '')}：{price} {unit}{extra_s}".rstrip())
        upd = metals[0].get("updated", "") if isinstance(metals[0], dict) else ""
        if upd:
            lines += ["", f"更新：{upd}"]
        return "\n".join(lines)

    def html_ctx(self, source, raw, top_n, theme):
        ctx = self._base_ctx(source, theme)
        raw = raw if isinstance(raw, dict) else {}
        ctx["subtitle"] = _esc(raw.get("date", ""))
        metals = []
        for m in raw.get("metals") or []:
            if not isinstance(m, dict):
                continue
            rng = []
            if m.get("high_price"):
                rng.append(f"高 {m['high_price']}")
            if m.get("low_price"):
                rng.append(f"低 {m['low_price']}")
            metals.append(
                {
                    "name": _esc(m.get("name", "")),
                    "price": _esc(m.get("today_price") or m.get("sell_price") or ""),
                    "unit": _esc(m.get("unit", "")),
                    "range": _esc(" / ".join(rng)),
                }
            )
        ctx["metals"] = metals
        return ctx

    def has_content(self, ctx):
        return bool(ctx.get("metals"))


class EpicKind(Kind):
    name = "epic"
    template = templates.EPIC_TMPL

    def to_text(self, source, raw, top_n):
        games = [
            g for g in (raw if isinstance(raw, list) else []) if isinstance(g, dict)
        ]
        if not games:
            return f"{source.emoji} {source.name}\n暂无数据"
        lines = [f"{source.emoji} {source.name}", ""]
        for g in games:
            title = g.get("title", "未知游戏")
            if g.get("is_free_now"):
                status = f"✅ 现在免费（至 {g.get('free_end', '')}）"
            else:
                status = f"⏳ 即将免费（{g.get('free_start', '')} ~ {g.get('free_end', '')}）"
            lines.append(f"【{title}】")
            lines.append(status)
            price = g.get("original_price_desc", "")
            if price and price != "0":
                lines.append(f"原价：{price}")
            lines.append("")
        return "\n".join(lines).rstrip()

    def html_ctx(self, source, raw, top_n, theme):
        ctx = self._base_ctx(source, theme)
        games = []
        for g in raw or []:
            if not isinstance(g, dict):
                continue
            desc = re.sub(r"\[/?[a-zA-Z0-9]+\]", "", str(g.get("description", "")))
            games.append(
                {
                    "is_free_now": g.get("is_free_now", False),
                    "free_start": _esc(g.get("free_start", "")),
                    "free_end": _esc(g.get("free_end", "")),
                    "title": _esc(g.get("title", "")),
                    "description": _esc(_truncate(desc, 120)),
                    "cover": g.get("cover", ""),
                }
            )
        ctx["games"] = games
        return ctx

    def has_content(self, ctx):
        return bool(ctx.get("games"))

    def dedup_basis(self, raw):
        return [
            (g.get("title", ""), g.get("is_free_now", False))
            for g in (raw or [])
            if isinstance(g, dict)
        ]


class AiKind(_DateSigKind):
    name = "ai"
    template = templates.AI_TMPL

    def to_text(self, source, raw, top_n):
        """AI 日报文字版。"""
        d = raw if isinstance(raw, dict) else {}
        if not d:
            return f"{source.emoji} {source.name}\n暂无数据"
        date = (d.get("date") or "").strip()
        link = (d.get("link") or "").strip()
        summary = (d.get("summary") or "").strip()
        sep = "=" * 28
        if summary:  # 开启总结：AI 早报速递排版
            lines = [
                f"📰 AI 早报速递 | {date}".rstrip(" |"),
                sep,
                "",
                "🤖 AI 总结：",
                "",
                summary,
                "",
                sep,
            ]
            if link:
                lines.append(f"🔗 原文链接：{link}")
            return "\n".join(lines)
        # 默认无总结：逐条列出「今日概览」（完整不截断）
        head = f"{source.emoji} {source.name} | {date}".rstrip(" |")
        lines = [head, ""]
        items = ai_items(d, top_n=99)
        if items:
            lines.append("📋 今日概览")
            for it in items:
                lines.append(f"{it['rank']}. {it['title']}")
                if it.get("link"):
                    lines.append(f"   🔗 {it['link']}")
        else:
            lines.append("暂无概览数据")
        if link:
            lines += ["", f"🔗 完整日报：{link}"]
        return "\n".join(lines)

    def html_ctx(self, source, raw, top_n, theme):
        ctx = self._base_ctx(source, theme)
        d = raw if isinstance(raw, dict) else {}
        ctx["subtitle"] = _esc(d.get("date", ""))
        items = ai_items(d, top_n)
        for it in items:
            it["title"] = _esc(it["title"])  # 榜单标题需转义；hot/cover 恒空
        ctx["items"] = items
        ctx["summary"] = _esc((d.get("summary") or "").strip())
        return ctx

    def has_content(self, ctx):
        return bool(ctx.get("items") or ctx.get("summary"))

    def collect_links(self, raw, top_n):
        # AI 文字版会完整列出全部概览（不截断），故短化不受 top_n 限制。
        if not isinstance(raw, dict):
            return []
        heads = [h for h in (raw.get("headlines") or []) if isinstance(h, dict)]
        urls = [h["link"] for h in heads if h.get("link")]
        if raw.get("link"):
            urls.append(raw["link"])
        return urls

    def replace_links(self, raw, mapping):
        if not isinstance(raw, dict):
            return
        for h in raw.get("headlines") or []:
            if isinstance(h, dict) and h.get("link") and h["link"] in mapping:
                h["link"] = mapping[h["link"]]
        if raw.get("link") and raw["link"] in mapping:
            raw["link"] = mapping[raw["link"]]


class BangumiKind(Kind):
    """今日番剧（Bangumi 番组计划）：中文名 + 评分 + 在看人数 + 封面。"""

    name = "bangumi"
    template = templates.BANGUMI_TMPL

    @staticmethod
    def _items(raw, top_n):
        return [
            x for x in (raw if isinstance(raw, list) else []) if isinstance(x, dict)
        ][:top_n]

    @staticmethod
    def _name(it) -> str:
        return (it.get("name_cn") or it.get("name") or "").strip()

    def to_text(self, source, raw, top_n):
        items = self._items(raw, top_n)
        if not items:
            return f"{source.emoji} {source.name}\n暂无数据"
        lines = [f"{source.emoji} {source.name}", ""]
        n = 0
        for it in items:
            name = self._name(it)
            if not name:
                continue
            n += 1
            rating = it.get("rating") if isinstance(it.get("rating"), dict) else {}
            score = rating.get("score")
            lines.append(f"{n}. {name}" + (f"  ⭐ {score}" if score else ""))
        return "\n".join(lines)

    def html_ctx(self, source, raw, top_n, theme):
        ctx = self._base_ctx(source, theme)
        items = []
        for it in self._items(raw, top_n):
            name = self._name(it)
            if not name:
                continue
            rating = it.get("rating") if isinstance(it.get("rating"), dict) else {}
            images = it.get("images") if isinstance(it.get("images"), dict) else {}
            coll = (
                it.get("collection") if isinstance(it.get("collection"), dict) else {}
            )
            doing = coll.get("doing")
            items.append(
                {
                    "rank": len(items) + 1,
                    "title": _esc(name),
                    "score": _esc(rating.get("score") or ""),
                    "doing": _esc(_fmt_hot(doing) if doing else ""),
                    "cover": _https(images.get("common") or images.get("medium") or ""),
                }
            )
        ctx["items"] = items
        return ctx

    def has_content(self, ctx):
        return bool(ctx.get("items"))

    def dedup_basis(self, raw):
        return sorted(
            str(it.get("id") or self._name(it))
            for it in (raw or [])
            if isinstance(it, dict)
        )


# RAWG parent_platforms 名称 → 简称
_PLATFORM_MAP = {
    "PC": "PC",
    "PlayStation": "PS",
    "Xbox": "Xbox",
    "Nintendo": "NS",
    "Apple Macintosh": "Mac",
    "Linux": "Linux",
}


class GameKind(Kind):
    """即将发售游戏（RAWG）：名称 + 发售日 + 平台 + 媒体分 + 封面。"""

    name = "game"
    template = templates.GAME_TMPL

    @staticmethod
    def _games(raw, top_n):
        return [
            x for x in (raw if isinstance(raw, list) else []) if isinstance(x, dict)
        ][:top_n]

    @staticmethod
    def _platforms(g) -> str:
        names = []
        for w in g.get("parent_platforms") or []:
            if isinstance(w, dict):
                p = (w.get("platform") or {}).get("name") or ""
                if p:
                    names.append(_PLATFORM_MAP.get(p, p))
        return " / ".join(names)

    def to_text(self, source, raw, top_n):
        games = self._games(raw, top_n)
        if not games:
            return f"{source.emoji} {source.name}\n暂无即将发售的游戏"
        lines = [f"{source.emoji} {source.name}", ""]
        for g in games:
            name = (g.get("name") or "").strip()
            if not name:
                continue
            lines.append(f"🗓 {g.get('released') or '待定'}")
            lines.append(f"🎮 {name}")
            plats = self._platforms(g)
            if plats:
                lines.append(f"🕹 {plats}")
            lines.append("")  # 空行分隔每款游戏
        return "\n".join(lines).rstrip()

    def html_ctx(self, source, raw, top_n, theme):
        ctx = self._base_ctx(source, theme)
        games = []
        for g in self._games(raw, top_n):
            name = (g.get("name") or "").strip()
            if not name:
                continue
            mc = g.get("metacritic")
            games.append(
                {
                    "title": _esc(name),
                    "released": _esc(g.get("released") or "待定"),
                    "platforms": _esc(self._platforms(g)),
                    "score": _esc(f"MC {mc}" if mc else ""),
                    "cover": g.get("background_image") or "",
                }
            )
        ctx["games"] = games
        return ctx

    def has_content(self, ctx):
        return bool(ctx.get("games"))

    def dedup_basis(self, raw):
        return sorted(
            str(g.get("id") or g.get("slug") or g.get("name") or "")
            for g in (raw or [])
            if isinstance(g, dict)
        )


# ---------------------------------------------------------------------- #
# 注册表
# ---------------------------------------------------------------------- #
KINDS: dict = {
    k.name: k
    for k in (
        RanklistKind(),
        NewsKind(),
        ItnewsKind(),
        GoldKind(),
        EpicKind(),
        AiKind(),
        BangumiKind(),
        GameKind(),
    )
}


def kind_for(source) -> Kind:
    """按 source.render_kind 取策略；未知类别回退 AI（与历史行为一致）。"""
    return KINDS.get(source.render_kind, KINDS["ai"])
