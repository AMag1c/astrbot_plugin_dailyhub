"""HTML 模板（供框架 ``html_render`` 渲染，Jinja2 语法）。

为避免 Python f-string 的花括号与 CSS/Jinja2 花括号冲突，模板一律用普通字符串
拼接（``_page(body)``），CSS 与 ``{{ }}`` / ``{% %}`` 均为字面量，由 html_render 处理。

视觉：深色/浅色双主题（``body.dark`` / ``body.light``，由上下文 ``theme`` 决定），卡片式布局。
不依赖 AstrBot。
"""

# ====================================================================== #
# 共享 CSS
# ====================================================================== #
_CSS = """
* { margin:0; padding:0; box-sizing:border-box; }
body {
  font-family:"Noto Sans SC","Source Han Sans SC","Microsoft YaHei","PingFang SC","Hiragino Sans GB","WenQuanYi Micro Hei","Droid Sans Fallback",sans-serif;
  width:720px; padding:24px; line-height:1.6;
  zoom:2;                       /* 2 倍渲染，提升清晰度（参照 bilicard） */
  -webkit-font-smoothing:antialiased;
}
body.dark  { background:linear-gradient(150deg,#11141c,#1a2233,#1e2c44); color:#c7d5e0; }
body.light { background:linear-gradient(160deg,#eaf2ff 0%,#f4f7fd 48%,#eef4ff 100%); color:#2b3040; }

.header { display:flex; align-items:center; gap:12px; margin-bottom:18px; }
.header .emoji { font-size:30px; }
.header .htxt  { display:flex; flex-direction:column; }
.header h1 { font-size:23px; font-weight:800; letter-spacing:.5px; }
body.dark  .header h1 { color:#eaf2fb; }
body.light .header h1 { color:#1a1f2e; }
.header .sub { font-size:13px; opacity:.7; margin-top:2px; }

.panel { border-radius:16px; padding:8px 4px; backdrop-filter:blur(20px) saturate(160%); }
body.dark  .panel { background:rgba(30,46,68,.42); border:1px solid rgba(120,170,230,.12); }
body.light .panel { background:rgba(255,255,255,.74); border:1px solid rgba(150,180,230,.22); box-shadow:0 6px 24px rgba(70,110,180,.10); }

/* 榜单行 */
.row { display:flex; align-items:flex-start; gap:12px; padding:10px 14px; border-radius:10px; }
.row + .row { margin-top:2px; }
body.dark  .row:nth-child(odd)  { background:rgba(255,255,255,.03); }
body.light .row:nth-child(odd)  { background:rgba(65,135,245,.055); }
.rank { flex-shrink:0; width:26px; height:26px; border-radius:8px; font-size:14px; font-weight:800;
        display:flex; align-items:center; justify-content:center; color:#fff; background:#4a5568; }
.rank.top1 { background:linear-gradient(135deg,#ff5f6d,#ffc371); }
.rank.top2 { background:linear-gradient(135deg,#f7971e,#ffd200); }
.rank.top3 { background:linear-gradient(135deg,#56ccf2,#2f80ed); }
.row .body { flex:1; min-width:0; }
.row .ttl  { font-size:16px; font-weight:600; word-break:break-word; }
body.dark  .row .ttl { color:#e8edf3; }
body.light .row .ttl { color:#1d2330; }
.row .hot  { font-size:12px; opacity:.7; margin-top:2px; }
.row .cover { width:84px; height:54px; object-fit:cover; border-radius:8px; flex-shrink:0; }

/* 资讯条目 */
.art { padding:11px 14px; border-radius:10px; }
.art + .art { margin-top:2px; }
body.dark  .art:nth-child(odd) { background:rgba(255,255,255,.03); }
body.light .art:nth-child(odd) { background:rgba(65,135,245,.055); }
.art .ttl { font-size:16px; font-weight:700; }
body.dark  .art .ttl { color:#e8edf3; }
body.light .art .ttl { color:#1d2330; }
.art .desc { font-size:13px; opacity:.72; margin-top:4px; line-height:1.55; }

/* 金价 */
.gold-grid { display:grid; grid-template-columns:1fr 1fr; gap:10px; padding:6px; }
.gold-card { border-radius:12px; padding:12px 14px; }
body.dark  .gold-card { background:rgba(255,255,255,.04); }
body.light .gold-card { background:rgba(65,135,245,.05); }
.gold-card .gname { font-size:13px; opacity:.75; }
.gold-card .gprice { font-size:21px; font-weight:800; margin:3px 0; color:#e0a83a; }
.gold-card .gunit { font-size:12px; opacity:.6; font-weight:500; }
.gold-card .grange { font-size:11px; opacity:.6; margin-top:2px; }

/* AI / 文本卡 */
.textcard { padding:16px 18px; border-radius:12px; white-space:pre-wrap; word-break:break-word; font-size:15px; line-height:1.85; }
body.dark  .textcard { background:rgba(255,255,255,.04); }
body.light .textcard { background:rgba(65,135,245,.05); }
.textcard .lead { font-size:16px; font-weight:700; margin-bottom:8px; }

/* 番剧行 */
.bgm-cover { width:50px; height:68px; object-fit:cover; border-radius:8px; flex-shrink:0; }
.bgm-meta  { font-size:12px; opacity:.72; margin-top:3px; display:flex; gap:12px; flex-wrap:wrap; }
.bgm-meta .score { color:#e0a83a; font-weight:700; }

/* 游戏卡 */
.game-card  { border-radius:12px; overflow:hidden; }
body.dark  .game-card { background:rgba(255,255,255,.05); }
body.light .game-card { background:rgba(65,135,245,.06); }
.game-cover { width:100%; aspect-ratio:16/9; object-fit:cover; display:block; }
.game-body  { padding:10px 13px; }
.game-title { font-size:16px; font-weight:800; word-break:break-word; }
.game-meta  { font-size:12px; opacity:.74; margin-top:5px; display:flex; flex-direction:column; gap:3px; }
.game-meta .date { color:#42c767; font-weight:700; }

.footer { text-align:center; margin-top:16px; font-size:11px; opacity:.45; }
"""


def _page(body: str) -> str:
    return (
        "<!DOCTYPE html><html><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=720'><style>"
        + _CSS
        + "</style></head><body class='{{ theme }}'>"
        + "<div class='header'><div class='emoji'>{{ emoji }}</div>"
        "<div class='htxt'><h1>{{ title }}</h1>"
        "{% if subtitle %}<div class='sub'>{{ subtitle }}</div>{% endif %}</div></div>"
        + body
        + "<div class='footer'>{{ footer }}</div></body></html>"
    )


# ====================================================================== #
# 各类别模板
# ====================================================================== #
RANKLIST_TMPL = _page(
    "<div class='panel'>"
    "{% for it in items %}"
    "<div class='row'>"
    "<div class='rank {% if it.rank==1 %}top1{% elif it.rank==2 %}top2{% elif it.rank==3 %}top3{% endif %}'>{{ it.rank }}</div>"
    "<div class='body'><div class='ttl'>{{ it.title }}</div>"
    "{% if it.hot %}<div class='hot'>🔥 {{ it.hot }}</div>{% endif %}</div>"
    "{% if it.cover %}<img class='cover' src='{{ it.cover }}'/>{% endif %}"
    "</div>"
    "{% endfor %}"
    "</div>"
)

ITNEWS_TMPL = _page(
    "<div class='panel'>"
    "{% for it in items %}"
    "<div class='art'><div class='ttl'>{{ loop.index }}. {{ it.title }}</div>"
    "{% if it.desc %}<div class='desc'>{{ it.desc }}</div>{% endif %}</div>"
    "{% endfor %}"
    "</div>"
)

# 黄金价格：独立模板（橙色标题横幅 + 蓝表头网格表格，不复用 _page 深色主题）
GOLD_TMPL = (
    "<!DOCTYPE html><html><head><meta charset='utf-8'>"
    "<meta name='viewport' content='width=1419'><style>"
    "*{margin:0;padding:0;box-sizing:border-box;}"
    "body{font-family:'Microsoft YaHei','PingFang SC','Noto Sans SC','Source Han Sans SC',sans-serif;"
    "width:1419px;-webkit-font-smoothing:antialiased;}"
    "body.light{background:#fff;color:#333;}"
    "body.dark{background:#141a26;color:#c7d5e0;}"
    ".gh{background:linear-gradient(90deg,#ff7a18,#ff6a00);padding:36px 0 28px;text-align:center;}"
    ".gh h1{color:#fff;font-size:48px;font-weight:800;letter-spacing:2px;}"
    ".gh .sub{color:rgba(255,255,255,.92);font-size:22px;margin-top:13px;}"
    ".gw{padding:32px 40px 14px;}"
    ".tw{border-radius:12px;overflow:hidden;}"
    "body.light .tw{box-shadow:0 3px 20px rgba(80,120,200,.12);}"
    "body.dark .tw{box-shadow:0 3px 20px rgba(0,0,0,.35);}"
    "table.gt{width:100%;border-collapse:collapse;table-layout:fixed;}"
    "table.gt th{background:#4187f5;color:#fff;font-size:27px;font-weight:700;padding:20px 8px;"
    "text-align:center;border:1px solid #cfe0f7;}"
    "table.gt td{padding:30px 8px;text-align:center;font-size:29px;}"
    "body.light table.gt td{border:1px solid #e3e8f2;}"
    "body.dark table.gt td{border:1px solid #2c3a52;}"
    "body.light table.gt tbody tr:nth-child(odd){background:#eef3fc;}"
    "body.light table.gt tbody tr:nth-child(even){background:#fff;}"
    "body.dark table.gt tbody tr:nth-child(odd){background:#1c2740;}"
    "body.dark table.gt tbody tr:nth-child(even){background:#161f33;}"
    "table.gt td.nm{font-weight:600;}"
    "body.light table.gt td.nm{color:#222;}"
    "body.dark table.gt td.nm{color:#eaf0f8;}"
    "table.gt td.sl{font-weight:800;font-size:30px;}"
    "body.light table.gt td.sl{color:#e4393c;}"
    "body.dark table.gt td.sl{color:#ff6b6e;}"
    ".gf{display:flex;justify-content:space-between;padding:20px 40px 32px;font-size:18px;}"
    "body.light .gf{color:#9aa0a6;}"
    "body.dark .gf{color:#6b7688;}"
    "</style></head><body class='{{ theme }}'>"
    "<div class='gh'><h1>{{ title }}</h1>"
    "{% if subtitle %}<div class='sub'>{{ subtitle }}</div>{% endif %}</div>"
    "<div class='gw'><div class='tw'><table class='gt'>"
    "<colgroup><col style='width:20%'><col style='width:13.4%'><col style='width:13.3%'>"
    "<col style='width:13.3%'><col style='width:13.3%'><col style='width:13.3%'>"
    "<col style='width:13.4%'></colgroup>"
    "<thead><tr>"
    "<th>名称</th><th>卖出价格</th><th>今日价格</th><th>最高价格</th>"
    "<th>最低价格</th><th>价格单位</th><th>报价时间</th>"
    "</tr></thead><tbody>"
    "{% for m in metals %}<tr>"
    "<td class='nm'>{{ m.name }}</td><td class='sl'>{{ m.sell }}</td>"
    "<td>{{ m.today }}</td><td>{{ m.high }}</td><td>{{ m.low }}</td>"
    "<td>{{ m.unit }}</td><td>{{ m.time }}</td>"
    "</tr>{% endfor %}"
    "</tbody></table></div></div>"
    "<div class='gf'><span>{{ footer_left }}</span><span>{{ footer_right }}</span></div>"
    "</body></html>"
)

# AI 日报：可选「AI 总结」卡 + 概览榜单（榜单复用热搜的 .panel/.row/.rank 视觉）
AI_TMPL = _page(
    "{% if summary %}<div class='textcard' style='margin-bottom:14px;'>"
    "<div class='lead'>🤖 AI 总结</div>{{ summary }}</div>{% endif %}"
    "<div class='panel'>"
    "{% for it in items %}"
    "<div class='row'>"
    "<div class='rank {% if it.rank==1 %}top1{% elif it.rank==2 %}top2{% elif it.rank==3 %}top3{% endif %}'>{{ it.rank }}</div>"
    "<div class='body'><div class='ttl'>{{ it.title }}</div></div>"
    "</div>"
    "{% endfor %}"
    "</div>"
)

# Epic：移植自旧 epic 插件的卡片风格（精简版）
EPIC_TMPL = _page(
    "<div style='display:grid;grid-template-columns:1fr 1fr;gap:18px;padding:6px;'>"
    "{% for g in games %}"
    "<div class='gold-card' style='padding:14px;'>"
    "{% if g.is_free_now %}<div style='font-size:13px;font-weight:700;color:#42c767;margin-bottom:6px;'>现在免费 · 至 {{ g.free_end }}</div>"
    "{% else %}<div style='font-size:13px;font-weight:700;color:#ffa726;margin-bottom:6px;'>即将免费 · {{ g.free_start }} ~ {{ g.free_end }}</div>{% endif %}"
    "{% if g.cover %}<img src='{{ g.cover }}' style='width:100%;aspect-ratio:16/10;object-fit:cover;border-radius:9px;margin-bottom:8px;'/>{% endif %}"
    "<div style='font-size:17px;font-weight:800;margin-bottom:5px;'>{{ g.title }}</div>"
    "<div class='desc' style='font-size:13px;opacity:.72;line-height:1.55;'>{{ g.description }}</div>"
    "</div>"
    "{% endfor %}"
    "</div>"
)

# 今日番剧：封面缩略图 + 中文名 + 评分 + 在看人数（复用榜单 .panel/.row/.rank 视觉）
BANGUMI_TMPL = _page(
    "<div class='panel'>"
    "{% for it in items %}"
    "<div class='row'>"
    "<div class='rank {% if it.rank==1 %}top1{% elif it.rank==2 %}top2{% elif it.rank==3 %}top3{% endif %}'>{{ it.rank }}</div>"
    "{% if it.cover %}<img class='bgm-cover' src='{{ it.cover }}'/>{% endif %}"
    "<div class='body'><div class='ttl'>{{ it.title }}</div>"
    "<div class='bgm-meta'>"
    "{% if it.score %}<span class='score'>★ {{ it.score }}</span>{% endif %}"
    "{% if it.doing %}<span>👁 {{ it.doing }} 在看</span>{% endif %}"
    "</div></div>"
    "</div>"
    "{% endfor %}"
    "</div>"
)

# 即将发售游戏：封面(16:9) + 名称 + 发售日 + 平台 + 评分（双列卡片）
GAME_TMPL = _page(
    "<div style='display:grid;grid-template-columns:1fr 1fr;gap:16px;padding:6px;'>"
    "{% for g in games %}"
    "<div class='game-card'>"
    "{% if g.cover %}<img class='game-cover' src='{{ g.cover }}'/>{% endif %}"
    "<div class='game-body'>"
    "<div class='game-title'>{{ g.title }}</div>"
    "<div class='game-meta'>"
    "<span class='date'>🗓 {{ g.released }}</span>"
    "{% if g.platforms %}<span>🕹 {{ g.platforms }}</span>{% endif %}"
    "{% if g.score %}<span>★ {{ g.score }}</span>{% endif %}"
    "</div></div></div>"
    "{% endfor %}"
    "</div>"
)

# 注：模板选择已下沉到各 Kind（kinds.py 的 ``Kind.template``），此处仅提供模板常量。
