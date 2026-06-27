"""数据源注册表：把"每个源是什么 / 怎么取 / 属于哪个展示类别"集中成一张表。

新增一个 60s 数据源，通常只需在 ``SOURCES`` 里加一条 ``SourceDef``；若它复用已有
``render_kind``（ranklist/news/itnews/gold/epic/ai），则连渲染都不用改——具体类别行为
在 kinds.py。本模块只管"源的元信息 + 别名解析"，渲染文字经 ``render_text`` 委托给 kind 策略。

不依赖 AstrBot，可脱离框架单测。
"""

from dataclasses import dataclass
from typing import Optional

from . import kinds


@dataclass(frozen=True)
class SourceDef:
    key: str  # 唯一标识
    name: str  # 中文名，用于标题/菜单
    emoji: str  # 文本/标题前缀图标
    aliases: tuple  # 触发别名（含手动获取指令名）
    category: str  # 周期资讯 / 资讯 / 热榜 / 游戏
    cadence: str  # daily / hot：决定默认推送频率
    render_kind: str  # 展示类别：ranklist/news/epic/itnews/gold/ai
    endpoint: str = ""  # 60s 端点；ai 源留空（由 summarizer 处理）
    special: str = ""  # "ai" = 不走 client.fetch，由 AI 日报模块处理


# 注：顺序即菜单展示顺序。aliases 的第一项通常作为推荐的手动获取指令名。
SOURCES = [
    SourceDef(
        "news60s",
        "60秒读懂世界",
        "📰",
        ("新闻", "60s", "news", "每日新闻"),
        "周期资讯",
        "daily",
        "news",
        "/v2/60s",
    ),
    SourceDef(
        "ai",
        "AI 日报",
        "🤖",
        ("ai", "ai日报", "ainews", "ai资讯", "AI", "AI日报", "AI资讯"),
        "周期资讯",
        "daily",
        "ai",
        special="ai",
    ),
    SourceDef(
        "epic",
        "Epic免费游戏",
        "🎮",
        ("epic", "喜加一", "epic游戏"),
        "游戏",
        "daily",
        "epic",
        "/v2/epic",
    ),
    SourceDef(
        "itnews",
        "实时IT资讯",
        "💻",
        ("it资讯", "itnews", "it新闻"),
        "资讯",
        "hot",
        "itnews",
        "/v2/it-news",
    ),
    SourceDef(
        "ithome",
        "IT之家热榜",
        "🔥",
        ("it热搜", "IT热搜"),
        "热榜",
        "hot",
        "ranklist",
        "/v2/it-news/rank",
    ),
    SourceDef(
        "gold",
        "黄金价格",
        "🪙",
        ("金价", "黄金", "gold", "黄金价格"),
        "资讯",
        "hot",
        "gold",
        "/v2/gold-price",
    ),
    SourceDef(
        "douyin",
        "抖音热搜",
        "🎵",
        ("抖音", "douyin", "抖音热搜"),
        "热榜",
        "hot",
        "ranklist",
        "/v2/douyin",
    ),
    SourceDef(
        "rednote",
        "小红书热搜",
        "📕",
        ("小红书", "xhs", "小红书热搜"),
        "热榜",
        "hot",
        "ranklist",
        "/v2/rednote",
    ),
    SourceDef(
        "bili",
        "哔哩哔哩热搜",
        "📺",
        ("b站", "哔哩哔哩", "bilibili", "B站", "b站热搜", "B站热搜"),
        "热榜",
        "hot",
        "ranklist",
        "/v2/bili",
    ),
    SourceDef(
        "weibo",
        "微博热搜",
        "🌐",
        ("微博", "weibo", "微博热搜"),
        "热榜",
        "hot",
        "ranklist",
        "/v2/weibo",
    ),
    SourceDef(
        "bangumi",
        "今日番剧",
        "🎬",
        ("新番", "番剧", "今日番剧", "bangumi", "新番放送"),
        "番剧",
        "hot",
        "bangumi",
        special="bangumi",
    ),
    SourceDef(
        "game",
        "即将发售游戏",
        "🕹",
        ("游戏", "新游", "游戏发售", "即将发售", "游戏发售日"),
        "游戏",
        "hot",
        "game",
        special="game",
    ),
]

SOURCE_MAP = {s.key: s for s in SOURCES}

# 别名 → key（含 key 本身、中文名、各 alias，统一小写匹配）
_ALIAS_MAP: dict = {}
for _s in SOURCES:
    _ALIAS_MAP[_s.key.lower()] = _s.key
    _ALIAS_MAP[_s.name.lower()] = _s.key
    for _a in _s.aliases:
        _ALIAS_MAP[_a.lower()] = _s.key


def resolve(name: str) -> Optional[str]:
    """把用户输入（key / 中文名 / 别名）解析为源 key；无法识别返回 None。"""
    if not name:
        return None
    return _ALIAS_MAP.get(str(name).strip().lower())


def all_keys() -> list:
    return [s.key for s in SOURCES]


def render_text(source: SourceDef, raw, top_n: int = 15) -> str:
    """纯文字渲染（纯文字模式 / 出图失败兜底）——委托给对应 kind 策略。"""
    return kinds.kind_for(source).to_text(source, raw, top_n)
