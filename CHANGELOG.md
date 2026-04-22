# Changelog

All notable changes to this project will be documented in this file.
The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/).

## [Unreleased]

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

[Unreleased]: https://github.com/fancyboi999/goofish-cli/compare/v0.2.1...HEAD
[0.2.1]: https://github.com/fancyboi999/goofish-cli/compare/v0.2.0...v0.2.1
[0.2.0]: https://github.com/fancyboi999/goofish-cli/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/fancyboi999/goofish-cli/releases/tag/v0.1.0
