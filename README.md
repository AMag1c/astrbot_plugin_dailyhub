# astrbot_plugin_dailyhub · 每日资讯推送

> 一个 [AstrBot](https://github.com/AstrBotDevs/AstrBot) 插件，聚合每日资讯与各平台热榜：
> **60秒读懂世界 / AI 日报 / Epic 免费游戏 / 实时 IT 资讯 / IT 之家热榜 / 黄金价格 / 抖音 / 小红书 / 哔哩哔哩 / 微博**。
> 支持「指令手动获取」+「按源订阅定时推送」，每个源的图片/文字输出与推送频率均可独立配置。

## ✨ 功能

- **10 个数据源**：AI 日报走 RSS（[橘鸦 AI 日报](https://imjuya.github.io/juya-ai-daily/)）+ 可选 LLM 总结，其余均来自 [60s API](https://github.com/vikiboss/60s)。
- **手动获取**：`/新闻`、`/微博`、`/epic` 等顶层指令，结果回显当前会话。
- **按源订阅 + 定时推送**：每个源在配置里是一张独立卡片，可订阅「全部」或「单个源」，推送频率独立可配，也可设为「只获取不推送」；并支持「一键把某会话加入/移出所有源」。
- **每源输出形式**：图片 / 文字 / 图文 三选一（文字带原文链接）。AI 日报默认推「标题 + 日报链接」，可选附 LLM 总结。
- **链接转短链（可选）**：接入自建 [Shlink](https://shlink.io/) 服务，把热榜长链转成短链（按源开关、只对前 N 条生效）。
- **AI 函数调用**：注册了 LLM 工具，用户与 AI 对话时（如「看看微博热搜」「今天金价」）AI 可自动调用并发送对应资讯卡片（图/文/图文按该源配置）。
- **出图失败兜底**：在线 `html_render` 出图，渲染服务故障/超时时自动回退纯文字，不影响内容送达。
- **多源容错**：60s 主源失败自动回退备用源，应对公共服务迁移。

## 📋 数据源与获取指令

> 指令大小写敏感；下表括号内为别名，与主指令等价。

| 源 | 获取指令（别名） | 来源 | 默认推送频率 |
|---|---|---|---|
| 📰 60秒读懂世界 | `/新闻`（60s、news、每日新闻） | `/v2/60s` | 每天 `daily_push_time`（默认 09:00） |
| 🤖 AI 日报 | `/ai`（AI、ai日报、AI日报、ainews、ai资讯、AI资讯） | RSS + 可选 LLM 总结 | 每天 `daily_push_time` |
| 🎮 Epic 免费游戏 | `/epic`（喜加一、epic游戏） | `/v2/epic` | 每天 `daily_push_time` |
| 💻 实时 IT 资讯 | `/it资讯`（itnews、it新闻） | `/v2/it-news` | 默认不推送（opt-in） |
| 🔥 IT 之家热榜 | `/it热搜`（IT热搜） | `/v2/it-news/rank` | 默认不推送（opt-in） |
| 🪙 黄金价格 | `/金价`（黄金、gold、黄金价格） | `/v2/gold-price` | 默认不推送（opt-in） |
| 🎵 抖音热搜 | `/抖音`（douyin、抖音热搜） | `/v2/douyin` | 默认不推送（opt-in） |
| 📕 小红书热搜 | `/小红书`（xhs、小红书热搜） | `/v2/rednote` | 默认不推送（opt-in） |
| 📺 哔哩哔哩热搜 | `/b站`（哔哩哔哩、bilibili、B站、b站热搜、B站热搜） | `/v2/bili` | 默认不推送（opt-in） |
| 🌐 微博热搜 | `/微博`（weibo、微博热搜） | `/v2/weibo` | 默认不推送（opt-in） |

> **关于定时推送（opt-in）**：默认仅 3 个周期源（60s / AI / Epic）在 `daily_push_time`（默认 09:00）推送；**7 个实时源默认不定时推送**。要让实时源定时推：填全局 `hot_push_cron` 批量开启，或在某个源的「推送计划」里填 Cron 单独开启。无论是否定时，所有源始终可用 `/源名` 手动获取、`/推送` 手动推送。

## 💬 指令一览

**手动获取（所有人）**：见上表，如 `/新闻`、`/金价`、`/微博`。

**AI 对话调用（无需指令）**：配好 LLM 后，直接问 AI（私聊 / 群里 @机器人）如「看看微博热搜」「今天金价多少」，AI 会自动调用 `get_daily_news` 工具并发送对应资讯卡片（图/文/图文按该源配置）。

> **想让 AI 更稳定地走插件出卡片（而非联网搜索）？** 把下面这段加进你所用 LLM 人格 / 系统提示的末尾（保存后对**新对话**生效）。这是提高 AI 命中本插件工具的关键——LLM 选哪个工具是它自己决定的，工具描述 + 这段系统提示一起能把命中率拉很高（但理论上非 100%，要绝对确定就发指令）：
>
> ```
> 【工具使用】每日资讯工具使用规范
> 当用户想看以下资讯时，调用 get_daily_news 工具获取（它会直接把官方数据卡片发送给用户），不要用网络搜索：
>
> 1. 今天金价 / 黄金多少钱 / 金价 → get_daily_news(source="金价")
> 2. 微博热搜 / 看看热搜 → get_daily_news(source="微博")
> 3. 60秒新闻 / 今日新闻 / 每日新闻 → get_daily_news(source="新闻")
> 4. AI日报 → get_daily_news(source="ai")
> 5. epic / 喜加一 / 免费游戏 → get_daily_news(source="epic")
> 6. IT资讯 / 科技新闻 → get_daily_news(source="it资讯")
> 7. IT热榜 / IT之家热榜 → get_daily_news(source="it热搜")
> 8. 抖音热搜 → get_daily_news(source="抖音")
> 9. 小红书热搜 → get_daily_news(source="小红书")
> 10. B站热搜 / 哔哩哔哩热搜 → get_daily_news(source="b站")
>
> 重要规则：
> - 上述资讯一律用 get_daily_news 获取；工具会直接把卡片发给用户，你不要再复述或总结卡片内容。
> - 只有当用户明确说"联网搜索 / 用网络搜索查最新"时，才改用 web_search。
> ```

**订阅管理（管理员）**：

| 指令 | 说明 |
|---|---|
| `/订阅资讯` | 本会话订阅**全部资讯** |
| `/订阅资讯 微博` | 仅订阅某个源（源名/别名见上表，如 `微博` `小红书热搜`） |
| `/取消订阅资讯 [源名]` | 取消订阅（无参 = 取消全部） |
| `/订阅状态` | 查看本会话订阅情况 |
| `/资讯菜单` | 列出全部源、获取指令与订阅状态 |

**手动推送（管理员，推给已订阅会话）**：

| 指令 | 说明 |
|---|---|
| `/推送` | 推送所有源到各自订阅会话 |
| `/推送 微博` | 仅推送某个源（可强制推送被设为「不推送」的源） |
| `/sid` | AstrBot 自带指令，获取当前会话标识 UMO（用于配置名单） |

> 订阅以会话为单位：在哪个群/私聊发出 `/订阅资讯`，就推送到哪里。

## ⚙️ 配置

在 AstrBot 管理面板的插件配置页设置（每项均有 hint）。

### 全局配置

| 配置 | 说明 | 默认 |
|---|---|---|
| `api_base_url` / `api_fallback_hosts` | 60s API 主源与备用源 | viki.moe 等 |
| `request_timeout` | 数据请求（API/RSS/封面图）超时（秒） | 15 |
| `render_timeout` | 在线出图渲染超时（秒），超时回退纯文字；t2i 慢可调大 | 50 |
| `dark_mode` / `list_top_n` | 图片深色主题 / 榜单取前 N 条 | true / 15 |
| `enable_dedup` | 定时推送去重（数据无变化不推） | true |
| `daily_push_time` | 周期源（60s/AI/Epic）默认推送时间；**留空=周期源不定时推送** | 09:00 |
| `hot_push_cron` | 实时源（其余 7 个）默认推送 Cron；**留空=实时源不定时推送** | **空** |
| `ai_rss_url` | AI 日报 RSS 地址 | 橘鸦 AI 日报 |
| `shortlink_api_base` / `shortlink_api_key` | 短链服务（Shlink）地址与 Key | 空（不启用） |
| `shortlink_domain` / `shortlink_valid_days` | 短链自定义域名 / 有效天数 | 空 / 2 |
| `bulk_add_umo` / `bulk_remove_umo` | 一键把会话 UMO 批量加入/移出**所有源**（保存重载后生效并自动清空） | 空 |

### 每源配置卡片（`src_*`）

配置页里每个数据源是一张卡片，含：

- **`enabled` 启用**：关闭则该源不响应获取指令也不推送。
- **`output` 输出形式**：图片 / 文字 / 图文。文字会带原文链接；AI 日报默认「文字」= 标题 + 日报链接。
- **`shorten_link` 链接转短链**（仅热榜类源，文字/图文模式生效）：开启后用上方 Shlink 服务把本源长链转短链（只对展示的前 `list_top_n` 条生效）。
- **`schedule` 推送计划**：留空 = 用类别默认；`off` = 只获取不推送；或填 5 位 Cron 自定义。
- **`targets` 推送/订阅名单**：本源定时/手动推送的目标会话（**仅控制推送，不影响获取指令——`/微博` 等获取指令所有会话都能用**）。点「添加」逐条填会话 UMO（目标会话发 `/sid` 获取），也可用 `/订阅资讯` 在会话内自助订阅。

AI 日报源额外有 `enable_summary`（是否调 LLM 总结）、`llm_provider_id`（留空 = 用当前默认模型）。

## 🔗 链接转短链（可选）

热榜条目自带的长链接会把文字消息撑得很长，QQ 等平台会把过长消息**折叠成「合并转发 / 聊天记录」**，要点开才能看，体验很差。开启短链就能避免——把每条长链换成简短的自建短链，消息更短、不被折叠。

接入自建 [Shlink](https://shlink.io/)：

1. **部署 Shlink**：本目录已附带 [`docker-compose.yml`](docker-compose.yml)（改好域名与数据库密码后 `docker compose up -d`），再用 Nginx 把你的短链域名 HTTPS 反代到 `127.0.0.1:48080`。
2. **生成 API Key**：`docker exec shlink shlink api-key:generate`。
3. **填进插件**：全局配置填 `shortlink_api_base`（实例根地址，如 `https://s.example.com`，无需带 `/rest/...`）和 `shortlink_api_key`。
4. **按源开启**：在需要的源卡片里打开 `shorten_link`，并把该源「输出形式」设为 **文字** 或 **图文**（图片模式不显示链接，故不短链）。

> 短链默认 2 天失效（`shortlink_valid_days`），到期自动清理避免短链库膨胀；只对展示的前 `list_top_n` 条生效；任何失败都回退用原始长链，不影响推送。

## 🚀 部署

1. 在 AstrBot 插件市场安装，或将本目录放入 AstrBot 的 `data/plugins/`。
2. 依赖：`aiohttp`、`croniter`（见 `requirements.txt`，框架会自动安装）。
3. 重启 / 重载 AstrBot。

## ⚠️ 注意事项

- **图片渲染**：走 AstrBot 内置的 `html_render`（远程 t2i 服务，需联网）。该服务故障/超时时本插件自动回退**纯文字**，所以即使渲染服务挂了也能出内容。建议把插件配置里的「文本转图像服务 API 地址」(`t2i_endpoint`)**留空**——留空时 AstrBot 会自动在官方多个端点间回退；一旦手填单个地址就只用那一个、不再回退。
- **60s 公共服务**：其当前部署平台 Deno Deploy Classic 预计 2026-07-20 停服。届时若公共源不可用，请在 `api_base_url` 填写其它公共实例或 [私有部署](https://github.com/vikiboss/60s) 地址。
- **AI 日报总结**：需在 AstrBot 配好可用的 LLM Provider；未配置时自动回退为只推标题与链接。

## 🙏 致谢

- 数据来源：[60s API](https://github.com/vikiboss/60s)（by vikiboss）、[橘鸦 AI 日报](https://imjuya.github.io/juya-ai-daily/)。

## 📄 License

MIT © AMag1c
