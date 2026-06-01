"""短链应用：渲染前把 raw 里的长链就地替换为短链。

这是"数据预处理"而非渲染职责，故独立于 render。具体哪些字段含链接由各 Kind 策略
（``collect_links`` / ``replace_links``）决定，本模块只做通用编排，任何异常都保持原样。
"""

from typing import Any

from .log import logger


async def apply_shortlinks(
    shortener, kind, source_key: str, raw: Any, top_n: int
) -> None:
    """用 shortener 把 raw 中该 kind 的可短化链接就地替换为短链。

    诊断日志（INFO）便于一眼定位：无链接 / 待短化 N 条 / 成功短化 M 条。
    """
    logger.info("[shortlink] 触发短化：源=%s kind=%s", source_key, kind.name)
    try:
        originals = kind.collect_links(raw, top_n)
        if not originals:
            logger.info("[shortlink] 源=%s 无可短化链接", source_key)
            return
        mapping = await shortener.shorten_many(originals)
        kind.replace_links(raw, mapping)
        changed = sum(1 for u in originals if mapping.get(u) and mapping[u] != u)
        logger.info(
            "[shortlink] 源=%s 待短化 %d 条，成功短化 %d 条",
            source_key,
            len(originals),
            changed,
        )
    except Exception as e:  # noqa: BLE001
        logger.warning("[shortlink] 替换失败 %s: %s", source_key, e)
