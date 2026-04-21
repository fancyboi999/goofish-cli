<div align="center">

# goofish-cli

**闲鱼 CLI · 原生支持 MCP · 为 AI Agent 而生**

*Goofish (Xianyu) automation CLI · MCP-ready · Built for AI Agents*

[![CI](https://github.com/fancyboi999/goofish-cli/actions/workflows/ci.yml/badge.svg)](https://github.com/fancyboi999/goofish-cli/actions/workflows/ci.yml)
[![PyPI version](https://img.shields.io/pypi/v/goofish-cli.svg)](https://pypi.org/project/goofish-cli/)
[![Python](https://img.shields.io/pypi/pyversions/goofish-cli.svg)](https://pypi.org/project/goofish-cli/)
[![License](https://img.shields.io/badge/license-Apache%202.0-blue.svg)](./LICENSE)
[![MCP](https://img.shields.io/badge/MCP-ready-8A2BE2)](https://modelcontextprotocol.io)
[![GitHub stars](https://img.shields.io/github/stars/fancyboi999/goofish-cli?style=social)](https://github.com/fancyboi999/goofish-cli)

</div>

`goofish-cli` 把闲鱼（Xianyu/Goofish）的核心运营能力抽成一套结构化命令，
**同一份定义**同时输出给三种消费者：

- 👨‍💻 **人类**：`goofish item get 12345 --format table`
- 🤖 **AI Agent（Claude Code / Cursor / Codex）**：`uvx goofish-mcp` → 自动注册成 MCP tool
- 🧩 **Claude Skills**（规划中）：`skills/` 目录直接放进 Agent

> 架构思想来自 [opencli](https://github.com/jackwener/opencli) 的 single-registry 设计。

---

## ✨ 核心特性

- 🔐 **12 个命令覆盖核心链路**：发布、下架、查询、图片上传、AI 类目识别、默认地址、IM 收发
- 📡 **真·实时 IM**：WebSocket 长连 + 自动重连 + **三类事件分类输出**
  - `event=message`（收到消息）· `event=read`（已读回执）· `event=new_msg`（轻量通知）
- 🛡 **内置风控护栏**：令牌桶限流（1 写/分钟）+ RGV587 自动熔断
- 🧠 **AI-first I/O**：`--format json/yaml/table/md/csv`，给 LLM 喂 JSON、给人看表格
- ⚡ **一次定义，三种入口**：CLI / MCP / Skill 共享同一 registry
- ✅ **真实端到端验证**：每个命令都跑过真实账号

---

## 🚀 60 秒上手

```bash
# 1. 安装
pip install goofish-cli    # 或 uv pip install goofish-cli

# 2. 导入 cookie（从浏览器 DevTools → Application → Cookies 导出）
goofish auth login ~/Downloads/goofish-cookies.json

# 3. 验证登录态
goofish auth status
# → {"unb":"2214350705775","tracknick":"xy575986224572","nick":"...","valid":true}

# 4. 干活
goofish item get 1045171414271
goofish message watch                               # 实时接收消息
goofish message send <cid> <toid> --text "在的"    # 发消息
```

---

## 📟 命令详略与真实输出

<details open>
<summary><b><code>goofish list-commands</code></b> — 注册表全景</summary>

```bash
$ goofish list-commands --format table
```

| 命令 | 说明 | 写操作 |
|---|---|:-:|
| `auth login` | 从 JSON 文件或 cookie 字符串导入登录态 | ❌ |
| `auth status` | 检查登录态是否有效 | ❌ |
| `auth reset-guard` | 手动解除风控熔断 | ❌ |
| `item get` | 查询闲鱼商品详情 | ❌ |
| `item publish` | 发布商品（自动识别类目 + 默认地址） | ✅ |
| `item delete` | 下架/删除商品 | ✅ |
| `media upload` | 上传图片到闲鱼 CDN | ✅ |
| `category recommend` | AI 识别商品类目 | ❌ |
| `location default` | 获取默认发布地址 | ❌ |
| `message history` | 拉取会话历史消息 | ❌ |
| `message send` | 发送文本/图片 | ✅ |
| `message watch` | 常驻 IM 长连（JSONL 输出） | ❌ |

</details>

<details>
<summary><b><code>goofish auth status</code></b> — 登录态健康检查</summary>

```json
{
  "unb": "2214350705775",
  "tracknick": "xy575986224572",
  "nick": "闲鱼用户昵称",
  "valid": true,
  "h5_token_exp": "2026-04-21T20:30:00+08:00"
}
```
</details>

<details>
<summary><b><code>goofish message watch</code></b> — 三类事件 JSONL 流</summary>

```bash
$ goofish message watch
```

实时输出（小号给主号发 3 条 + 主号读了所有消息）：

```jsonl
{"event":"message","cid":"60585751957","send_user_id":"2215266653893","send_user_name":"小号昵称","send_message":"测试消息1"}
{"event":"message","cid":"60585751957","send_user_id":"2215266653893","send_user_name":"小号昵称","send_message":"测试消息2"}
{"event":"message","cid":"60585751957","send_user_id":"2215266653893","send_user_name":"小号昵称","send_message":"测试消息3"}
{"event":"read","cid":"60585751957","msg_ids":["4077151826249.PNM","4066820235744.PNM","4066826134477.PNM"],"status":1,"ts":"1776770953455"}
```

| 事件 | 字段 |
|---|---|
| `message` | cid · send_user_id · send_user_name · send_message · content_type |
| `read` | cid · msg_ids[] · status · ts |
| `new_msg` | cid · msg_id · ts（服务端只推指针，需 `message history` 拉正文） |

**自动跳过噪音**：`/s/para`（对方正在输入）、`contentType=8`（会话激活心跳）。
</details>

<details>
<summary><b><code>goofish message send</code></b> — 主动发消息</summary>

```bash
$ goofish message send 60585751957 2215266653893 \
    --text "在的 claude 测试成功 ✅" --item-id 1045171414271
```

```json
{"ok": true, "mid": "1061776769407570", "cid": "60585751957"}
```
</details>

<details>
<summary><b><code>goofish item publish</code></b> — 发布商品（含风控护栏）</summary>

```bash
$ goofish item publish \
    --title "男士毛呢大衣 驼色长款" \
    --desc "全新未拆封 原价 2999 现 999" \
    --images ./a.png,./b.png \
    --price 999
```

流程：
1. `media upload` 每张图 → CDN URL + 尺寸
2. `category recommend` 拿 AI 识别的 catId
3. `location default` 拿默认地址
4. `mtop.idle.pc.idleitem.publish` 落库

返回：
```json
{"ok": true, "itemId": "1046118265141", "status": "published"}
```

**触发令牌桶限流**（1 写/分钟）。高频调用会被本地拒绝，避免被闲鱼风控。
</details>

---

## 🔌 接入 Claude Code（MCP）

在 `~/.config/claude-code/config.json`：

```json
{
  "mcpServers": {
    "goofish": {
      "command": "uvx",
      "args": ["goofish-mcp"]
    }
  }
}
```

Claude 会自动把全部命令看成 tool：`goofish_item_get` / `goofish_item_publish` / `goofish_message_watch`... 你在对话里直接说"帮我看下 itemId=xxx 的详情"，Claude 就会调用。

---

## 🎯 项目亮点

| 能力 | 说明 |
|---|---|
| 11 个核心 mtop 接口 | 发布/下架/查询/图片/类目/地址/IM 全覆盖 |
| CLI + `--format` 多格式输出 | `json` / `yaml` / `table` / `md` / `csv`，人机两用 |
| MCP Server | `uvx goofish-mcp` 一行接入 Claude Code / Cursor |
| WebSocket 批量 push 全量解码 | 一帧多条消息全部还原，不丢单 |
| WebSocket 自动重连 | 断线自退避重连，长跑无感知 |
| 已读回执 / typing / 新消息通知分类 | `/s/sync` 元事件结构化为三类 JSONL |
| 全局限流 + 风控熔断 | 令牌桶 1 写/分钟 + RGV587 自动熔断 |
| 单元测试 | 29 个，ruff 零告警 |
| 包分发 | `pip install goofish-cli` / `uvx goofish-mcp` |

---

## 🗺 Roadmap

- [x] v0.1：12 个命令 + MCP + IM 三类事件
- [ ] v0.2：`goofish message create-chat`（主动与陌生用户建会话）
- [ ] v0.2：Claude Skills 包装（`skills/` 目录）
- [ ] v0.3：`goofish order`（订单状态查询 / 发货）
- [ ] v0.3：支持发视频消息

---

## 🛠 开发

```bash
git clone https://github.com/fancyboi999/goofish-cli
cd goofish-cli
uv venv --python 3.11
uv pip install -e ".[dev]"

uv run pytest                # 29 测全绿
uv run ruff check src tests  # 零告警
```

详细请看 [CONTRIBUTING.md](./CONTRIBUTING.md) 和 [docs/architecture.md](./docs/architecture.md)。

---

## ⚠️ 合规声明

本工具**仅用于用户自有账号**的自动化运营。**严禁**：

- 欺诈 / 刷单 / 虚假交易
- 针对闲鱼平台的 SaaS 化转售
- 违反闲鱼、淘宝、阿里巴巴用户协议的行为

工具不提供：绕过滑块验证、批量设备 ID 伪造、自动化规避封号。遇到风控请人工处理（见 [docs/compliance.md](./docs/compliance.md)）。

---

## 📜 License

Apache-2.0 © 2026 fancy。详见 [LICENSE](./LICENSE) 和 [NOTICE](./NOTICE)。
