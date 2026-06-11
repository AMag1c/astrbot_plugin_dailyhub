"""astrbot_plugin_dailyhub 主入口（薄编排层）。

每日资讯推送：60秒新闻 / AI日报 / Epic / IT资讯 / 金价 / 抖音 / 小红书 / B站 / 微博。
- 手动获取：/新闻 /ai /epic /微博 … （所有人，回显当前会话）
- 手动推送：/推送 [源名]（管理员，推给已订阅会话）
- 订阅管理：/订阅资讯 [源名]、/取消订阅资讯 [源名]、/订阅状态、/资讯菜单

业务逻辑在 dailyhub 子包中，本文件只做装配、指令路由与生命周期。
"""

from pathlib import Path

import astrbot.api.message_components as Comp
from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import AstrMessageEvent, MessageChain, filter
from astrbot.api.star import Context, Star, StarTools, register

from .dailyhub import sources
from .dailyhub.client import DEFAULT_FALLBACK_HOSTS, SixtyClient
from .dailyhub.config import Config
from .dailyhub.render import Renderer
from .dailyhub.scheduler import HubScheduler
from .dailyhub.shortener import LinkShortener
from .dailyhub.store import JsonStore
from .dailyhub.subscription import SubscriptionStore
from .dailyhub.summarizer import DEFAULT_RSS_URL, AiDaily


# 元数据以 metadata.yaml 为唯一来源；此处保持与其一致，避免两份漂移。
@register(
    "astrbot_plugin_dailyhub",
    "AMag1c",
    "60s新闻 / AI日报 / Epic免费游戏 / IT资讯 / 黄金价格 / 抖音 / 小红书 / B站 / 微博 "
    "等多源资讯聚合，支持指令手动获取与按源订阅定时推送。",
    "0.2.0",
    "https://github.com/AMag1c/astrbot_plugin_dailyhub",
)
class DailyHub(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.config = config or {}
        self.cfg = Config(self.config)  # 配置统一入口（默认值集中、避免漂移）

        try:
            data_dir = Path(StarTools.get_data_dir("astrbot_plugin_dailyhub"))
        except Exception:  # noqa: BLE001
            data_dir = Path(__file__).parent
        data_dir.mkdir(parents=True, exist_ok=True)

        self._dedup_store = JsonStore(str(data_dir / "push_cache.json"))
        self._ai_cache = JsonStore(str(data_dir / "ai_summary_cache.json"))

        self.client = SixtyClient(
            base_url=self.cfg.get("api_base_url"),
            fallback_hosts=self.cfg.get("api_fallback_hosts") or DEFAULT_FALLBACK_HOSTS,
            timeout=self.cfg.int("request_timeout"),
        )
        self.ai = AiDaily(
            rss_url=self.cfg.get("ai_rss_url") or DEFAULT_RSS_URL, cache=self._ai_cache
        )
        self.shortener = LinkShortener(
            api_base=self.cfg.get("shortlink_api_base"),
            api_key=self.cfg.get("shortlink_api_key"),
            domain=self.cfg.get("shortlink_domain"),
            valid_days=self.cfg.int("shortlink_valid_days"),
            timeout=self.cfg.int("shortlink_timeout"),
        )
        self.renderer = Renderer(
            self.cfg, self.client, self.html_render, self.shortener
        )
        self.subs = SubscriptionStore(self.cfg, sources.all_keys())
        self.scheduler = HubScheduler(
            cfg=self.cfg,
            srcs=sources,
            client=self.client,
            renderer=self.renderer,
            subs=self.subs,
            ai_daily=self.ai,
            dedup_store=self._dedup_store,
            send_rendered=self._send_rendered,
            llm_ask_factory=self._make_llm_ask,
        )

    # ------------------------------------------------------------------ #
    # 配置 / 工具
    # ------------------------------------------------------------------ #
    def _c(self, key, default=None):
        return self.cfg.get(key, default)

    def _int(self, key, default):
        return self.cfg.int(key, default)

    def _save_config(self) -> None:
        try:
            self.cfg.save()
        except Exception as e:  # noqa: BLE001
            logger.error("[dailyhub] 保存配置失败: %s", e)

    def _src_cfg(self, key: str) -> dict:
        return self.cfg.src(key)

    def _apply_bulk_ops(self) -> None:
        """处理「一键批量」：把 bulk_add_umo / bulk_remove_umo 分发到所有源后清空。"""
        add = [
            str(x).strip()
            for x in (self.config.get("bulk_add_umo") or [])
            if str(x).strip()
        ]
        rem = [
            str(x).strip()
            for x in (self.config.get("bulk_remove_umo") or [])
            if str(x).strip()
        ]
        if not add and not rem:
            return
        for umo in add:
            self.subs.add_all(umo)
        for umo in rem:
            self.subs.remove_all(umo)
        self.config["bulk_add_umo"] = []
        self.config["bulk_remove_umo"] = []
        self._save_config()
        logger.info(
            "[dailyhub] 批量订阅分发完成：添加 %d、移除 %d 个 UMO", len(add), len(rem)
        )

    def _make_llm_ask(self):
        """构造 AI 总结用的 llm_ask（留空配置=默认模型，否则用指定 provider）。无可用则返回 None。"""
        pid = self._src_cfg("ai").get("llm_provider_id", "") or ""
        provider = (
            self.context.get_provider_by_id(pid)
            if pid
            else self.context.get_using_provider()
        )
        if not provider:
            logger.warning("[dailyhub] 无可用 LLM Provider，AI 总结将回退原文摘要")
            return None

        async def llm_ask(prompt: str) -> str:
            resp = await provider.text_chat(prompt=prompt, session_id="dailyhub_ai")
            return getattr(resp, "completion_text", "") or ""

        return llm_ask

    def _parts_to_components(self, parts: list) -> list:
        comps = []
        for p in parts or []:
            ptype, val = p.get("type"), p.get("value")
            if not val:
                continue
            if ptype == "image_url":
                comps.append(Comp.Image.fromURL(val))
            elif ptype == "image_b64":
                comps.append(Comp.Image.fromBase64(val))
            else:
                comps.append(Comp.Plain(str(val)))
        return comps or [Comp.Plain("获取失败，请稍后再试 😢")]

    def _split_chains(self, parts: list) -> list:
        """把 parts 拆成多条消息链——每个 part 独立成一条消息。

        用于「图文」分开发：先发图片、再发文字，避免图片与长文本挤在同一条消息，
        被 QQ 平台的 forward_threshold 折叠成「合并转发（聊天记录）」。
        """
        chains = []
        for p in parts or []:
            if not p or not p.get("value"):
                continue
            chains.append(self._parts_to_components([p]))
        return chains or [[Comp.Plain("获取失败，请稍后再试 😢")]]

    async def _send_rendered(self, umo: str, parts: list) -> bool:
        """推送：逐条发送（「图文」=先图后文，各自成一条消息）。"""
        for comps in self._split_chains(parts):
            mc = MessageChain()
            mc.chain = comps
            await self.context.send_message(umo, mc)
        return True

    # ------------------------------------------------------------------ #
    # 生命周期
    # ------------------------------------------------------------------ #
    async def initialize(self):
        self._apply_bulk_ops()
        self.scheduler.start()
        logger.info(
            "[dailyhub] 短链服务 enabled=%s（已填地址=%s，已填Key=%s）",
            self.shortener.enabled,
            bool(self._c("shortlink_api_base", "")),
            bool(self._c("shortlink_api_key", "")),
        )
        logger.info("[dailyhub] 每日资讯推送已初始化")

    async def terminate(self):
        self.scheduler.stop()
        await self.client.close()
        await self.shortener.close()
        logger.info("[dailyhub] 已停用")

    # ================================================================== #
    # 手动获取指令（所有人，回显当前会话）
    # ================================================================== #
    async def _emit(self, event: AstrMessageEvent, key: str):
        if not self._c("enable_get_commands", True):
            return
        parts = await self.scheduler.get_one(sources.SOURCE_MAP[key])
        for comps in self._split_chains(parts):
            yield event.chain_result(comps)

    @filter.command("新闻", alias={"60s", "news", "每日新闻"})
    async def cmd_news(self, event: AstrMessageEvent):
        """获取每日60秒读懂世界"""
        async for r in self._emit(event, "news60s"):
            yield r

    @filter.command(
        "ai", alias={"ai日报", "ainews", "ai资讯", "AI", "AI日报", "AI资讯"}
    )
    async def cmd_ai(self, event: AstrMessageEvent):
        """获取 AI 日报（标题 + 链接，可选 AI 总结）"""
        if not self._c("enable_get_commands", True):
            return
        if self._src_cfg("ai").get("enable_summary", False):
            yield event.plain_result("🤖 正在获取并总结 AI 日报，请稍候…")
        parts = await self.scheduler.get_one(sources.SOURCE_MAP["ai"])
        for comps in self._split_chains(parts):
            yield event.chain_result(comps)

    @filter.command("epic", alias={"喜加一", "epic游戏"})
    async def cmd_epic(self, event: AstrMessageEvent):
        """获取 Epic 免费游戏"""
        async for r in self._emit(event, "epic"):
            yield r

    @filter.command("it资讯", alias={"itnews", "it新闻"})
    async def cmd_itnews(self, event: AstrMessageEvent):
        """获取实时 IT 资讯"""
        async for r in self._emit(event, "itnews"):
            yield r

    @filter.command("it热搜", alias={"IT热搜"})
    async def cmd_ithome(self, event: AstrMessageEvent):
        """获取 IT 之家热榜"""
        async for r in self._emit(event, "ithome"):
            yield r

    @filter.command("金价", alias={"黄金", "gold", "黄金价格"})
    async def cmd_gold(self, event: AstrMessageEvent):
        """获取黄金价格"""
        async for r in self._emit(event, "gold"):
            yield r

    @filter.command("抖音", alias={"douyin", "抖音热搜"})
    async def cmd_douyin(self, event: AstrMessageEvent):
        """获取抖音热搜"""
        async for r in self._emit(event, "douyin"):
            yield r

    @filter.command("小红书", alias={"xhs", "小红书热搜"})
    async def cmd_rednote(self, event: AstrMessageEvent):
        """获取小红书热搜"""
        async for r in self._emit(event, "rednote"):
            yield r

    @filter.command("b站", alias={"哔哩哔哩", "bilibili", "B站", "b站热搜", "B站热搜"})
    async def cmd_bili(self, event: AstrMessageEvent):
        """获取哔哩哔哩热搜"""
        async for r in self._emit(event, "bili"):
            yield r

    @filter.command("微博", alias={"weibo", "微博热搜"})
    async def cmd_weibo(self, event: AstrMessageEvent):
        """获取微博热搜"""
        async for r in self._emit(event, "weibo"):
            yield r

    # ================================================================== #
    # LLM 函数工具（用户与 AI 对话时，AI 可自动调用获取资讯）
    # ================================================================== #
    @filter.llm_tool(name="get_daily_news")
    async def llm_get_news(self, event: AstrMessageEvent, source: str):
        """获取并发送某个每日资讯或平台热榜的卡片（图/文/图文按该源「输出形式」配置，与对应指令一致）。当用户想查看/获取某个资讯源（新闻、热搜、金价等）时调用。

        Args:
            source(string): 资讯源名称。可选：新闻、60s、ai、epic、it资讯、it热搜、金价、抖音、小红书、b站、微博；也支持中文全名如「微博热搜」「黄金价格」
        """
        key = sources.resolve(source)
        if not key:
            names = "、".join(s.name for s in sources.SOURCES)
            yield event.plain_result(f"未识别的资讯源「{source}」。可用源：{names}")
            return
        src = sources.SOURCE_MAP[key]
        # 与指令同款渲染：按该源「输出形式」出图/文/图文
        for comps in self._split_chains(await self.scheduler.get_one(src)):
            yield event.chain_result(comps)
        event.stop_event()  # 卡片已发，终止事件，避免 AI 再附加一段回复

    # ================================================================== #
    # 手动推送（管理员，推给已订阅会话）
    # ================================================================== #
    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("推送", alias={"推送资讯"})
    async def cmd_push(self, event: AstrMessageEvent, name: str = ""):
        """/推送 [源名] —— 推送到已订阅会话；无参=推送所有源"""
        if not name:
            res = await self.scheduler.push_all()
            pushed = {k: v for k, v in res.items() if v}
            if pushed:
                detail = "，".join(
                    f"{sources.SOURCE_MAP[k].name}×{v}" for k, v in pushed.items()
                )
                yield event.plain_result(f"✅ 推送完成：{detail}")
            else:
                yield event.plain_result(
                    "没有会话订阅，或各源数据均无更新。请在目标会话用 /订阅资讯 订阅。"
                )
            return
        key = sources.resolve(name)
        if not key:
            yield event.plain_result(
                f"未识别的源：「{name}」。发送 /资讯菜单 查看可用源。"
            )
            return
        source = sources.SOURCE_MAP[key]
        n = await self.scheduler.push_source(source, force=True)
        if n > 0:
            yield event.plain_result(f"✅ 已推送【{source.name}】到 {n} 个订阅会话。")
        else:
            yield event.plain_result(
                f"【{source.name}】暂无会话订阅，或获取失败。可在目标会话 /订阅资讯 {source.aliases[0]}。"
            )

    # ================================================================== #
    # 订阅管理（管理员）
    # ================================================================== #
    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("订阅资讯", alias={"订阅咨询", "dailyhub订阅"})
    async def cmd_sub(self, event: AstrMessageEvent, name: str = ""):
        """/订阅资讯 [源名] —— 订阅到本会话；无参=订阅全部源"""
        umo = event.unified_msg_origin
        if not name:
            n = self.subs.add_all(umo)
            total = len(sources.all_keys())
            yield event.plain_result(
                f"✅ 已订阅全部资讯（新增 {n}/{total} 个源），本会话将按计划收到推送。\n取消：/取消订阅资讯"
                if n
                else "本会话已订阅全部资讯。"
            )
            return
        key = sources.resolve(name)
        if not key:
            yield event.plain_result(
                f"未识别的源：「{name}」。发送 /资讯菜单 查看可订阅项。"
            )
            return
        src = sources.SOURCE_MAP[key]
        ok = self.subs.add(umo, key)
        yield event.plain_result(
            f"✅ 已订阅【{src.name}】，将按计划推送到本会话。\n取消：/取消订阅资讯 {src.aliases[0]}"
            if ok
            else f"本会话已订阅【{src.name}】。"
        )

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("取消订阅资讯", alias={"退订"})
    async def cmd_unsub(self, event: AstrMessageEvent, name: str = ""):
        """/取消订阅资讯 [源名] —— 取消；无参=取消全部资讯订阅"""
        umo = event.unified_msg_origin
        if not name:
            n = self.subs.remove_all(umo)
            yield event.plain_result(
                f"✅ 已退订全部资讯（移除 {n} 个源）。"
                if n
                else "本会话当前未订阅任何源。"
            )
            return
        key = sources.resolve(name)
        if not key:
            yield event.plain_result(f"未识别的源：「{name}」。")
            return
        src = sources.SOURCE_MAP[key]
        ok = self.subs.remove(umo, key)
        yield event.plain_result(
            f"✅ 已取消订阅【{src.name}】。" if ok else f"本会话未订阅【{src.name}】。"
        )

    @filter.command("订阅状态", alias={"我的订阅"})
    async def cmd_substatus(self, event: AstrMessageEvent):
        """查看本会话订阅情况"""
        umo = event.unified_msg_origin
        keys = self.subs.list_for_umo(umo)
        if not keys:
            yield event.plain_result(
                "本会话暂无订阅。用 /订阅资讯 订阅全部，或 /订阅资讯 微博 订阅单个源。"
            )
            return
        total = len(sources.all_keys())
        scope = "（全部）" if len(keys) >= total else ""
        names = "、".join(
            sources.SOURCE_MAP[k].name for k in keys if k in sources.SOURCE_MAP
        )
        yield event.plain_result(
            f"📌 本会话已订阅{scope}：{names}\n用 /资讯菜单 查看各源推送时间。"
        )

    @filter.command("资讯菜单", alias={"资讯帮助", "dailyhub"})
    async def cmd_menu(self, event: AstrMessageEvent):
        """列出全部可用源、获取指令与推送计划"""
        umo = event.unified_msg_origin
        my = set(self.subs.list_for_umo(umo))
        lines = ["📚 每日资讯推送 · 可用源", ""]
        for s in sources.SOURCES:
            enabled = self._src_cfg(s.key).get("enabled", True)
            flag = "🔔" if s.key in my else "·"
            tail = "（已禁用）" if not enabled else ""
            lines.append(f"{flag} {s.emoji} {s.name}{tail} → /{s.aliases[0]}")
        lines += [
            "",
            "🔔=本会话已订阅",
            "订阅：/订阅资讯 [源名]（无参=全部） · 取消：/取消订阅资讯 [源名]",
            "推送：/推送 [源名]（管理员，推给订阅会话）",
        ]
        yield event.plain_result("\n".join(lines))
