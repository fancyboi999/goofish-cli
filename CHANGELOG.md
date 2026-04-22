# Changelog

All notable changes to this project will be documented in this file.
The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/).

## [Unreleased]

## [0.3.0] - 2026-04-22

### Added
- **Claude Skills 套件**（5 个 skill，打包进 wheel）：把 goofish-cli 从"给 Agent 用的
  工具"升级成"给 Agent 的完整经验体"。Agent 在 Claude Code / Cursor 里识别到闲鱼任务
  即加载对应 skill 走 reference 知识库，不再 zero-shot 试错。
  - `goofish-overview`：总入口。介绍定位、账号模型、15 个 MCP 工具速查、风控硬红线，
    dispatch 到其他 4 个专项 skill。
  - `goofish-risk-guard`：知识库型 skill。内置违禁词表、外联词正则、发布红线清单、
    RGV587/x5sec 恢复指引。被 publish-item / reply-buyer 频繁引用。
  - `goofish-publish-item`：发布闭环。类目识别 → 标题 5 段式生成 → 风控扫描 →
    批量传图 → 用户确认 → `item_publish`。强约束"不跳过用户确认"。
  - `goofish-reply-buyer`：消息闭环。`message_watch/list_chats/history/send` 四件套
    + 议价小刀/大刀/屠龙刀三档策略 + 意图 5 分类。不托管发送权。
  - `goofish-shop-diagnosis`：限流诊断。`search_items` 买家视角搜 + `item_view`
    历史对比 → 归因清单给嫌疑排序 + 修复建议。纯读不写。
- **`goofish skills install` 命令**（`commands/skills/install.py`）：把内置 skill
  复制到 `~/.claude/skills/`（或 `--dest` 指定路径）。`--list` 仅列举，`--force`
  覆盖已存在。支持 `uvx --from goofish-cli goofish skills install` 一行装机。
- **`.claude-plugin/marketplace.json`**：Claude Code Plugin Marketplace 分发清单，
  5 个 skill 均登记在 `plugins` 数组，`install.cli` 指向 `goofish skills install`。
- **wheel 打包 skills**：hatch `force-include` 把项目根 `skills/` 装进
  `goofish_cli/_bundled_skills/`，运行时用 `goofish_cli.__file__` 拿包路径定位
  （不依赖 namespace package 的 importlib.resources 行为，避免 py 版本差异坑）。

### Changed
- `pyproject.toml` 新增 `[tool.hatch.build.targets.wheel.force-include]` 和
  `[tool.hatch.build.targets.sdist]` 段。wheel 只 force-include `skills/`（运行时
  `goofish skills install` 唯一需要的资源）；sdist 额外带 `.claude-plugin/` 和
  `README / CHANGELOG / LICENSE`，便于从源码分发时拿到完整元数据。

## [0.2.4] - 2026-04-22

### Added
- **`auth login --qr` 扫码登录兜底**（`core/qr_login.py`）：v0.2.3 的"快速进入"
  免密登录依赖浏览器免密记忆，换机 / 长期不登 / 清 cookie 后记忆失效就没法用。
  v0.2.4 补上扫码路径——Playwright 开干净 tmp profile goto 首页触发 passport
  iframe（`styleType=vertical` 布局里 QR canvas 首屏就在 DOM 里，无需切 tab），
  用户用手机闲鱼 App 扫码 + 手机确认后，轮询 `context.cookies()` 直到见到完整
  session cookie（`_m_h5_tk / unb / cookie2`）即判成功，抓快照写回
  `~/.goofish-cli/cookies.json`。
  - `--qr-timeout N`（默认 120s）/ `GOOFISH_QR_TIMEOUT=N` 可调；超时抛
    `AuthRequiredError`，提示延长超时重试。
  - 传 `goofish_page(cookies={})` 是关键——不传空 dict 会走 `Session.load` 把
    已有 cookie 灌进去，passport 就优先走"快速进入"跳过 QR，用户看不到扫码界面。
  - 和 v0.2.3 refresh 自动路径分工：refresh=无感续命（SESSION_EXPIRED 时自动
    点"快速进入"），qr_login=显式扫码（需用户拿手机）。不混用，不塞进 refresh
    自动 retry（扫码时间不可控，会违反"无感"语义）。

### Changed
- `auth login` 新增 `--qr` / `--qr-timeout` flag；`--qr` 与 `<source>` /
  `--raw` / `--browser` 互斥，组合使用会直接报错（QR 走独立 Playwright 浏览器，
  同时传其它来源会让用户困惑）。

## [0.2.3] - 2026-04-22

### Added
- **自动点击 passport 弹窗"快速进入"免密登录**（`core/refresh.py::_try_quick_enter`）：
  v0.2.2 的 Playwright goto 首页在系统 Chrome 里抓出的 cookie 指纹不匹配时会弹
  `#alibaba-login-box` 登录框，服务端拒发完整 session cookie 导致后续 mtop 报
  `FAIL_SYS_SESSION_EXPIRED`。v0.2.3 起自动识别弹窗并点"快速进入"走浏览器免密
  记忆登录，无需用户交互完成 session 恢复。刷新后追加访问 `/bought` 触发强鉴权页
  下发完整 `cookie2 / sgcookie / _tb_token_`。
- `goofish_page()` 已经支持的 `cookies=` 注入点被 refresh 复用，调用方 session
  和浏览器上下文的登录态保持一致（承接 v0.2.2 Copilot review 的改造）。

### Changed
- mtop auto-refresh 错误码匹配从"仅 token 层"扩展到**也处理 session 层失效**
  （`FAIL_SYS_SESSION_EXPIRED`）。`_is_token_expired_error` 重命名为
  `_is_recoverable_auth_error`，语义更清晰。`FAIL_SYS_ILLEGAL_ACCESS` 仍不在
  可恢复列表（风控层问题，刷 cookie 救不了）。

## [0.2.2] - 2026-04-22

### Added
- **`_m_h5_tk` 自动刷新机制**（`core/refresh.py`）：mtop 调用遇
  `FAIL_SYS_TOKEN_EXOIRED` / `FAIL_SYS_TOKEN_EMPTY` / `令牌过期` 时，自动用
  Playwright `goto` 一次 `https://www.goofish.com` 触发服务端 `Set-Cookie` 续 token，
  合并回 session 后重试一次原请求。开关：`GOOFISH_AUTO_REFRESH_TOKEN=0` 关闭（CI 或
  想自定义刷新策略时）。
  - **只处理 token 层失效**：`FAIL_SYS_SESSION_EXPIRED` / `FAIL_SYS_ILLEGAL_ACCESS` 不触发
    自动刷新（意味着 `unb` / `cookie2` 也失效了，刷 `_m_h5_tk` 救不了，仍按原 AuthRequiredError 抛）。
  - **避免跨 domain 同名 cookie 并存**：Playwright 写回的新 cookie 和 `browser_cookie3`
    导入的旧 cookie 有不同 domain，`requests.CookieJar` 允许两者并存，但后续
    `cookies.get(name)` 会抛 `CookieConflictError`。刷新时先 `clear(domain, path, name)`
    掉所有同名旧条目再 `update(fresh)`。
  - 刷新成功后自动写回 `~/.goofish-cli/cookies.json`，下次启动不用再刷。

### Changed
- mtop `call()` 新增 `_auto_refresh` 参数（默认 True），递归重试时置 False 避免死循环。

## [0.2.1] - 2026-04-22

### Changed
- MCP script entry 新增 `goofish-cli`（与 package 名一致），`uvx goofish-cli` 即可直接拉起
  MCP server。Claude Code 等 AI Agent 的 MCP 配置应使用这个入口。`goofish-mcp` 作为
  次级入口保留，但只在本包已装到某 env 时可用（`pip install goofish-cli` /
  `uv tool install goofish-cli` / `uvx --from goofish-cli goofish-mcp`）——单写
  `uvx goofish-mcp` 仍会因 PyPI 无同名包解析失败。
- `goofish_cli.__version__` 改为从 `importlib.metadata` 动态读取 package 版本，避免和
  `pyproject.toml` 的 `version` 字段 drift（之前硬编码在 `__init__.py` 里，0.2.0 忘了同步）。

## [0.2.0] - 2026-04-22

### Added
- **浏览器自动化子系统**（`core/browser.py`）：基于 Playwright + 系统 Chrome（`channel="chrome"`）
  每次调用独立 tmp profile（`~/.goofish-cli/profiles/chrome-<tmp>/`），退出清理——
  避开 Chrome `SingletonLock` 并发冲突。自动从 `Session.load()` 注入登录态。
  默认 **headful**（headless 会被闲鱼识别为"非法访问"），CI 可 `GOOFISH_HEADLESS=1` 切回。
- `goofish search items <query>` [`--limit N`]：浏览器路径搜索商品。对标 OpenCLI
  `xianyu/search.js`，打开搜索页 → 自动滚动触发懒加载 → 从 DOM 提卡片。返回
  `rank / item_id / title / price / condition / brand / location / badge / url`。
- `goofish item view <item_id>`：浏览器视角看商品详情。在商品页上下文里调
  `window.lib.mtop.request('mtop.taobao.idle.pc.detail')`，从 `itemDO/sellerDO/itemLabelExtList`
  抽 20+ 字段（description / want_count / browse_count / 成色 / 品牌 / seller_score /
  reply_ratio_24h / image_urls 等）。和现有 `item get`（CLI 直签，字段浅）并存。
- `goofish message list-chats`：拉取会话列表（对应网页左栏），返回 `session_id`、对方昵称、
  未读数、最后一条消息摘要、`sessionType`（1=真人 / 3=系统 / 6=互动 / 23=官方通知）。
  AI Agent 可基于 `sessionType=1 and unread>0` 一键过滤"待回复真人会话"。
- 接口：`mtop.taobao.idlemessage.pc.session.sync` v3.0，入参 `fetchNum`。
- `list-chats --watch-secs N`：在 baseline 之上连 WS 收 N 秒 `ackDiff(pts=0)` 的历史推送，
  补 h5 `session.sync` 漏掉的 cid（网页左栏 50 条也靠 ACCS 累积，单次 HTTP 拿不到）。每条
  record 带 `source` 字段（`baseline` / `watch`）。watch 记录只有 cid / session_type /
  item_id / ts，要正文要自己调 `message history <cid>`。

### Changed
- MCP handler 用 `asyncio.to_thread` 包装同步命令调用，避免 `asyncio.run()` 在已有事件
  循环里抛 `RuntimeError` —— `search items` / `item view` / `list-chats --watch-secs` 现在
  可以通过 MCP 正常调用。

## [0.1.0] - 2026-04-21

### Added
- 初始发布。12 个命令覆盖闲鱼核心运营链路：
  - `auth`：login / status / reset-guard
  - `item`：get / publish / delete
  - `media upload`、`category recommend`、`location default`
  - `message`：watch / history / send（WebSocket IM）
- `message watch` 三类事件分类输出（JSONL）：
  - `event=message`：收到消息正文
  - `event=read`：对方已读回执（带 msg_ids）
  - `event=new_msg`：轻量新消息通知（无正文，需 history 拉取）
- WebSocket 自动重连 + 指数退避
- 全局速率限制（令牌桶 1 写/分钟）+ RGV587 熔断器
- MCP server：`goofish-mcp` 同一命令集自动暴露给 Claude Code / Cursor / Codex
- 统一输出契约 `--format json/yaml/table/md/csv`
- 29 个单测

### Notes
- 本版本需要用户手动从浏览器导入 cookie（含 `unb` / `_m_h5_tk` / `x5sec`）
- 遇到 `RGV587_ERROR` 风控时，需在浏览器完成滑块验证并**重新导出**带 `x5sec` 的 cookie

[Unreleased]: https://github.com/fancyboi999/goofish-cli/compare/v0.3.0...HEAD
[0.3.0]: https://github.com/fancyboi999/goofish-cli/compare/v0.2.4...v0.3.0
[0.2.4]: https://github.com/fancyboi999/goofish-cli/compare/v0.2.3...v0.2.4
[0.2.3]: https://github.com/fancyboi999/goofish-cli/compare/v0.2.2...v0.2.3
[0.2.2]: https://github.com/fancyboi999/goofish-cli/compare/v0.2.1...v0.2.2
[0.2.1]: https://github.com/fancyboi999/goofish-cli/compare/v0.2.0...v0.2.1
[0.2.0]: https://github.com/fancyboi999/goofish-cli/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/fancyboi999/goofish-cli/releases/tag/v0.1.0
