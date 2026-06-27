"""调度与推送引擎。

职责：
- 为每个"已启用"的源按其 cron 独立定时（每源一个 asyncio 任务，便于热更配置）；
- 推送管线（拉取 → 去重 → 渲染 → 推送订阅者）由定时与手动 ``/推送`` 共用；
- 手动获取 ``get_one`` 复用拉取+渲染（不走订阅/去重）。

与 AstrBot 解耦：发送、LLM 调用、html_render 均由 main 注入。仅依赖标准库 + croniter。

cron 取值（每源）：
- ``source_schedules[key]`` 为 ``off``/空白/cron：off=不推送；空=类别默认；其余=自定义 cron；
- 类别默认：daily → 由 ``daily_push_time`` (HH:MM) 推导；hot → ``hot_push_cron``。
"""

import asyncio
from datetime import datetime
from typing import Any, Callable, List, Optional

from . import kinds
from .log import logger

try:
    from croniter import croniter

    HAS_CRONITER = True
except ImportError:
    HAS_CRONITER = False

_OFF_VALUES = {"off", "none", "no", "关", "关闭", "禁用", "停", "-", "无"}
_RECHECK_SEC = 1800  # 长等待时分段睡眠，便于热更配置


class HubScheduler:
    def __init__(
        self,
        *,
        cfg,  # Config
        srcs,  # sources 模块
        client,  # SixtyClient
        renderer,  # Renderer
        subs,  # SubscriptionStore
        ai_daily,  # AiDaily
        dedup_store,  # JsonStore（push_cache）
        send_rendered: Callable,  # async (umo, rendered_dict) -> bool
        llm_ask_factory: Optional[
            Callable
        ] = None,  # () -> (async (prompt)->str) | None
    ):
        self._cfg = cfg
        self._srcs = srcs
        self._client = client
        self._renderer = renderer
        self._subs = subs
        self._ai = ai_daily
        self._dedup = dedup_store
        self._send_rendered = send_rendered
        self._llm_ask_factory = llm_ask_factory
        self._tasks: List[asyncio.Task] = []

    # ------------------------------------------------------------------ #
    # 生命周期
    # ------------------------------------------------------------------ #
    def start(self) -> None:
        if not HAS_CRONITER:
            logger.warning(
                "[scheduler] 未安装 croniter，定时推送不可用（手动获取/推送不受影响）"
            )
            return
        self.stop()
        delay = self._cfg.int("startup_delay")
        for s in self._srcs.SOURCES:
            self._tasks.append(asyncio.create_task(self._source_task(s, delay)))
        # 启动时打印实际生效的排程，便于核对"哪些源会定时推、什么时间"（opt-in 默认应为空）
        scheduled = [
            f"{s.key}({self._source_cron(s)})"
            for s in self._enabled_sources()
            if self._source_cron(s)
        ]
        if scheduled:
            logger.info(
                "[scheduler] 定时推送已启用：%s；其余源仅手动获取/推送",
                "、".join(scheduled),
            )
        else:
            logger.info(
                "[scheduler] 所有源均未配置定时推送（opt-in），仅响应手动获取/推送"
            )

    def stop(self) -> None:
        for t in self._tasks:
            if not t.done():
                t.cancel()
        self._tasks = []

    # ------------------------------------------------------------------ #
    # 配置读取
    # ------------------------------------------------------------------ #
    def _src_cfg(self, source_key: str) -> dict:
        return self._cfg.src(source_key)

    def _is_enabled(self, source) -> bool:
        return bool(self._src_cfg(source.key).get("enabled", True))

    def _enabled_sources(self) -> list:
        return [s for s in self._srcs.SOURCES if self._is_enabled(s)]

    def _source_cron(self, source) -> Optional[str]:
        """返回该源的 cron；None 表示不定时推送（off / 留空且类别默认也空）。"""
        ov = str(self._src_cfg(source.key).get("schedule", "") or "").strip()
        if ov.lower() in _OFF_VALUES:
            return None
        if ov:
            return ov
        # 留空 → 用类别默认；类别默认也留空则不推送（仅手动获取/推送）
        if source.cadence == "daily":
            return self._daily_cron(source)
        cron = str(self._cfg.get("hot_push_cron") or "").strip()
        return cron or None

    def _daily_cron(self, source) -> Optional[str]:
        """由 daily_push_time (HH:MM) 推导 cron；留空/非法则不推送（None）。
        日级源按序号错峰分钟，避免同刻并发。"""
        t = str(self._cfg.get("daily_push_time") or "").strip()
        if not t:
            return None
        try:
            hh, mm = t.split(":")
            hour, minute = int(hh), int(mm)
        except Exception:  # noqa: BLE001
            return None
        daily_keys = [s.key for s in self._srcs.SOURCES if s.cadence == "daily"]
        idx = daily_keys.index(source.key) if source.key in daily_keys else 0
        minute = (minute + idx) % 60
        return f"{minute} {hour} * * *"

    # ------------------------------------------------------------------ #
    # 每源定时任务
    # ------------------------------------------------------------------ #
    async def _source_task(self, source, startup_delay: int) -> None:
        await asyncio.sleep(max(startup_delay, 1))
        while True:
            try:
                if not self._is_enabled(source):
                    await asyncio.sleep(600)
                    continue
                cron = self._source_cron(source)
                if not cron:
                    await asyncio.sleep(600)
                    continue
                try:
                    nxt = croniter(cron, datetime.now()).get_next(datetime)
                except Exception as e:  # noqa: BLE001
                    logger.error(
                        "[scheduler] 源 %s cron 无效 '%s': %s", source.key, cron, e
                    )
                    await asyncio.sleep(600)
                    continue
                wait = (nxt - datetime.now()).total_seconds()
                if wait > _RECHECK_SEC:
                    await asyncio.sleep(_RECHECK_SEC)
                    continue
                if wait > 0:
                    await asyncio.sleep(wait)
                await self._safe_push(source)
                await asyncio.sleep(1)  # 跨过触发分钟
            except asyncio.CancelledError:
                raise
            except Exception as e:  # noqa: BLE001
                logger.error("[scheduler] 源 %s 调度异常: %s", source.key, e)
                await asyncio.sleep(60)

    async def _safe_push(self, source) -> None:
        try:
            n = await self.push_source(source)
            if n > 0:
                logger.info(
                    "[scheduler] 源 %s 定时推送成功，覆盖 %d 个会话", source.key, n
                )
        except Exception as e:  # noqa: BLE001
            logger.error("[scheduler] 源 %s 推送失败: %s", source.key, e)

    # ------------------------------------------------------------------ #
    # 推送管线（定时 + 手动 /推送 共用）
    # ------------------------------------------------------------------ #
    async def fetch_raw(self, source) -> Any:
        if source.special == "ai":
            llm_ask = self._llm_ask_factory() if self._llm_ask_factory else None
            enable = bool(self._src_cfg("ai").get("enable_summary", False))
            return await self._ai.build(llm_ask, enable_summary=enable)
        if source.special == "bangumi":
            return await self._client.fetch_bangumi_today()
        if source.special == "game":
            return await self._client.fetch_rawg_games(
                str(self._cfg.get("rawg_api_key") or "").strip(),
                self._cfg.int("game_window_days"),
                self._cfg.int("list_top_n"),
            )
        return await self._client.fetch(source.endpoint)

    async def get_one(self, source) -> list:
        """手动获取：拉取 + 渲染，返回 part 列表（不涉及订阅/去重）。"""
        if (
            source.special == "game"
            and not str(self._cfg.get("rawg_api_key") or "").strip()
        ):
            return [
                {
                    "type": "text",
                    "value": f"{source.emoji} {source.name}\n需先在插件配置填写 RAWG API Key"
                    "（https://rawg.io/apidocs 免费注册获取）。",
                }
            ]
        raw = await self.fetch_raw(source)
        if raw is None:
            return [
                {
                    "type": "text",
                    "value": f"{source.emoji} {source.name}\n获取失败，请稍后再试 😢",
                }
            ]
        return await self._renderer.render(source, raw)

    async def push_source(self, source, force: bool = False) -> int:
        """拉取 → 去重 → 渲染 → 推送订阅者。返回成功推送的会话数。"""
        targets = self._subs.targets_of(source.key)
        if not targets:
            return 0
        raw = await self.fetch_raw(source)
        if raw is None:
            return 0

        dedup_on = bool(self._cfg.get("enable_dedup")) and not force
        sig = self._signature(source, raw) if dedup_on else None
        if dedup_on and sig == await self._dedup_get(source.key):
            logger.info("[scheduler] 源 %s 数据未更新，跳过推送", source.key)
            return 0

        rendered = await self._renderer.render(source, raw)
        sent = await self._send_to(targets, rendered)
        if sent > 0 and dedup_on:
            await self._dedup_put(source.key, sig)
        return sent

    async def push_all(self, force: bool = False) -> dict:
        """手动 ``/推送``：推送所有已启用且未设为 off 的源。返回 {key: 推送会话数}。

        设为 ``off`` 的源不参与批量推送（保持"仅手动获取"）；如需强制推送单个 off 源，
        用 ``/推送 <源名>`` 显式指定（见 push_source）。
        """
        result = {}
        for s in self._enabled_sources():
            if self._source_cron(s) is None:  # off：不参与批量推送
                continue
            try:
                result[s.key] = await self.push_source(s, force=force)
            except Exception as e:  # noqa: BLE001
                logger.error("[scheduler] /推送 源 %s 失败: %s", s.key, e)
                result[s.key] = 0
        return result

    async def _send_to(self, targets, rendered) -> int:
        sem = asyncio.Semaphore(5)
        sent = 0

        async def one(umo):
            nonlocal sent
            async with sem:
                try:
                    if await self._send_rendered(umo, rendered):
                        sent += 1
                except Exception as e:  # noqa: BLE001
                    logger.error("[scheduler] 推送到 %s 失败: %s", umo, e)

        await asyncio.gather(*[one(u) for u in targets])
        return sent

    # ------------------------------------------------------------------ #
    # 去重签名
    # ------------------------------------------------------------------ #
    def _signature(self, source, raw) -> str:
        """去重签名：委托给 kind 策略（时效内容按日期，榜单按标题哈希）。"""
        return kinds.kind_for(source).signature(raw)

    async def _dedup_get(self, key: str):
        try:
            return (await self._dedup.read()).get(key)
        except Exception:  # noqa: BLE001
            return None

    async def _dedup_put(self, key: str, sig) -> None:
        try:
            await self._dedup.update(lambda c: {**(c or {}), key: sig})
        except Exception as e:  # noqa: BLE001
            logger.warning("[scheduler] 去重缓存写入失败: %s", e)
