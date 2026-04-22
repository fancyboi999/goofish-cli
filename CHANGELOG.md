# Changelog

All notable changes to this project will be documented in this file.
The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added
- **浏览器自动化子系统**（`core/browser.py`）：基于 Playwright + 系统 Chrome（`channel="chrome"`）
  启动持久化 profile（`~/.goofish-cli/chrome-profile/`），自动注入 `cookies.json` 的登录态。
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
  record 带 `source` 字段（`baseline` / `watch`）。watch 记录只有 cid / item_id / ts，
  要正文要自己调 `message history <cid>`。

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

[Unreleased]: https://github.com/fancyboi999/goofish-cli/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/fancyboi999/goofish-cli/releases/tag/v0.1.0
