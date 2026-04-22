# Changelog

All notable changes to this project will be documented in this file.
The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added
- `goofish message list-chats`：拉取会话列表（对应网页左栏），返回 `session_id`、对方昵称、
  未读数、最后一条消息摘要、`sessionType`（1=真人 / 3=系统 / 6=互动 / 23=官方通知）。
  AI Agent 可基于 `sessionType=1 and unread>0` 一键过滤"待回复真人会话"。
- 接口：`mtop.taobao.idlemessage.pc.session.sync` v3.0，入参 `fetchNum`。

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
