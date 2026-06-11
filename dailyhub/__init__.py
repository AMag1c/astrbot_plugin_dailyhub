"""astrbot_plugin_dailyhub 业务子包（均与 AstrBot 框架解耦，可脱离框架单测）。

- config         配置统一访问（默认值集中）
- sources        数据源注册表 + 别名解析
- kinds          各展示类别（render_kind）策略：文字/HTML上下文/去重签名/短链字段集中于此
- client         60s API 客户端 + 图片抓取（SSRF 防护）
- summarizer     AI 日报抓取 + LLM 总结
- store          通用 JSON 持久化（原子写）
- render / templates / links   展示编排、HTML 模板、短链应用
- subscription / scheduler   订阅管理与定时推送
- log            日志适配（框架内走 astrbot logger，脱框架回退标准 logging）

main.py 仅做薄编排层（注册指令、生命周期、装配模块）。
"""
