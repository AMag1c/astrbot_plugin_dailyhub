"""配置访问统一入口。

把"读哪个键、默认值是多少"集中到一处，避免默认值散落各模块导致漂移
（曾出现 daily_push_time 代码兜底 08:00、schema 默认 09:00 的不一致）。
``DEFAULTS`` 是顶层标量配置的唯一默认值来源，且与 ``_conf_schema.json`` 对齐。

各模块统一依赖 ``Config``，不再各自 ``config.get(key, 字面量默认)``：
- ``get(key)`` 缺省时回退 DEFAULTS；``int(key)`` 容错转 int；
- ``src(key)`` 取某源的配置卡片（``src_<key>`` dict）；
- ``raw`` 暴露底层 AstrBotConfig 以便订阅模块直接增删 targets 后 ``save()``。

不依赖 AstrBot，可用普通 dict 构造，便于脱框架单测。
"""

from typing import Any, Callable, Optional

# 顶层标量默认值（与 _conf_schema.json 保持一致；list/dict 型默认见各自调用处）
DEFAULTS: dict = {
    "api_base_url": "https://60s.viki.moe",
    "request_timeout": 15,
    "render_mode": "自动",
    "dark_mode": True,
    "list_top_n": 15,
    "enable_dedup": True,
    "enable_get_commands": True,
    "daily_push_time": "09:00",
    "hot_push_cron": "0 12,20 * * *",
    "ai_rss_url": "https://imjuya.github.io/juya-ai-daily/rss.xml",
    "shortlink_api_base": "",
    "shortlink_api_key": "",
    "shortlink_domain": "",
    "shortlink_valid_days": 2,
    "shortlink_timeout": 10,
    "startup_delay": 8,  # 未在 schema 暴露的隐藏项：插件启动后多少秒再跑定时
}


class Config:
    """AstrBotConfig 的薄包装：统一默认值与访问方式。"""

    def __init__(self, raw: Any):
        self.raw = raw if raw is not None else {}

    def get(self, key: str, default: Any = None) -> Any:
        """取顶层配置；缺省时优先回退 DEFAULTS，再回退入参 default。"""
        fallback = DEFAULTS[key] if key in DEFAULTS else default
        return self.raw.get(key, fallback)

    def int(self, key: str, default: Optional[int] = None) -> int:
        """取整型配置（容错：空/非法回退默认）。"""
        base = default if default is not None else DEFAULTS.get(key, 0)
        try:
            return int(self.raw.get(key, base) or base)
        except (TypeError, ValueError):
            return int(base)

    def bool(self, key: str) -> bool:
        return bool(self.get(key))

    def src(self, key: str) -> dict:
        """取某源的配置卡片（``src_<key>``）；不存在或类型不符返回空 dict。"""
        d = self.raw.get(f"src_{key}")
        return d if isinstance(d, dict) else {}

    def as_getter(self) -> Callable[[str, Any], Any]:
        """兼容仍需 ``(key, default) -> value`` 回调签名的旧接口。"""
        return self.get

    def save(self) -> None:
        save = getattr(self.raw, "save_config", None)
        if callable(save):
            save()
