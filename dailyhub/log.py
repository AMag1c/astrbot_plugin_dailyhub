"""插件统一日志出口。

为什么不直接用 ``logging.getLogger(__name__)``：AstrBot 的日志经 loguru 桥接输出，
裸标准 logger 产生的 LogRecord 缺少 loguru 格式所需的 extra 字段（plugin_tag /
source_file / source_line 等），桥接时会被静默丢弃 —— 导致子模块（render / scheduler /
shortener 等）的日志在框架日志流中**完全不可见**。

解决：框架内统一复用 ``astrbot.api.logger``（与 main.py 同一个，可正常输出）；
脱离框架（``_localtest_*`` 单测）时回退标准 logging，保持子包可独立测试。
做法参照 astrbot_plugin_qq_group_daily_analysis 的 src/utils/logger.py。
"""

try:
    # 框架内：与 main.py 同源的可见 logger
    from astrbot.api import logger  # type: ignore
except Exception:  # noqa: BLE001 —— 脱框架单测：回退标准 logging
    import logging

    logger = logging.getLogger("astrbot_plugin_dailyhub")
    if not logger.handlers:
        _handler = logging.StreamHandler()
        _handler.setFormatter(logging.Formatter("[%(levelname)s] %(message)s"))
        logger.addHandler(_handler)
        logger.setLevel(logging.INFO)

__all__ = ["logger"]
