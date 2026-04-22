---
name: goofish-overview
description: |
  闲鱼（goofish.com）自动化运营的总入口 skill。何时激活：用户首次提到
  闲鱼 / 咸鱼 / goofish / 二手交易 / 挂闲置 / 回买家消息 / 发商品到闲鱼，
  或用户询问本工具如何使用、有哪些能力、能做什么。本 skill 介绍 goofish-cli
  的定位、账号模型、15 个 MCP 工具速查、风控底线，并指向其它专项 skill
  （goofish-publish-item / goofish-reply-buyer / goofish-risk-guard /
  goofish-shop-diagnosis）。
metadata:
  author: goofish-cli
  version: "0.3.0"
  tags: [xianyu, goofish, overview, index]
---

# goofish-cli 总览

## 这是什么

`goofish-cli` 是一个 **Python CLI + MCP server + Claude Skills** 三合一工具包，
让 AI Agent 能像熟练卖家一样操作闲鱼：发商品、回消息、查风控、诊断店铺。

你（Agent）在 Claude Code / Cursor 里通过 MCP 看到的工具，都来自同一个
`goofish` server（`FastMCP("goofish")`）。

## 四个专项 Skill 的分工

遇到具体任务时，**优先跳到对应专项 skill**，不要在本 overview 里硬推断：

| 用户说 | 激活的 skill |
|---|---|
| "帮我发布 / 上架 / 挂闲置" | `goofish-publish-item` |
| "回复买家消息 / 看未读 / 议价" | `goofish-reply-buyer` |
| "发布前检查 / 这话能说吗 / 风控 / 被限流怎么办" | `goofish-risk-guard` |
| "我店铺怎么没流量 / 为什么曝光掉 / 诊断一下" | `goofish-shop-diagnosis` |

跨 skill 协作：**发布 / 回消息前都应该先让 `goofish-risk-guard` 过一遍**
（避免绝对化词、外联词）。这是个推荐 convention，不是硬强制。

## 账号与登录态

- 登录态由 `mcp__goofish__auth_status` 检查，返回 `{valid: bool}`。
- 自动刷新链路已内置（v0.2.2 - v0.2.4）：token 过期自动续、session 过期
  自动点 passport "快速进入"、浏览器免密失效需用户 `goofish auth login --qr`。
- **Agent 不应主动调 `auth_login`**，这是敏感命令（会覆盖磁盘 cookie）。
  只在 `auth_status` 返回 invalid 时提示用户手动 `goofish auth login` 或
  `goofish auth login --qr`。
- 账号身份细节见 `references/accounts.md`。

## 15 个 MCP 工具速查

详单在 `references/mcp-tools-index.md`。读不读看任务：
- 发商品 → 只需 `category_recommend / media_upload / location_default / item_publish`
- 回消息 → 只需 `message_watch / message_list_chats / message_history / message_send`
- 诊断 → 只需 `search_items / item_view / item_get`
- 登录态诊断 → `auth_status`
- 下架/删除 → `item_delete`

**工具命名**：MCP 注册为 `mcp__goofish__{namespace}_{name}` 下划线格式。
例如 CLI 里的 `message list-chats` 在 MCP 是 `mcp__goofish__message_list_chats`。

## 合规硬红线（本工具禁止协助）

**以下行为写在合规声明里且 skills 拒绝指导**：
- 刷单 / 虚假交易 / 伪造物流
- 批量设备 ID 伪造 / 绕过滑块验证 / 规避封号
- 针对闲鱼平台的 SaaS 化转售
- 恶意评价 / 敲诈话术 / 外联引流（微信/VX/威信/V 信等）

若用户请求明显违反上述任一条，**拒绝执行并解释原因**，不要寻找绕过路径。

## 风控基础概念

详见 `references/xianyu-concepts.md`，这里只给 Agent 一个思维锚：

- **闲气值**：卖家信用分，< 80 开始限权（搜索曝光 -50% 起步）。
- **流量池**：每件新商品有 24 小时初始推荐窗口，错过不再有。
- **降价改标**：发布后先降价再改标题会触发"虚假促销"，流量腰斩。
- **外联词**：微信 / 威信 / V信 / VX / +我 都命中，轻则降权重则封号。

## 工作流惯例

Agent 在 goofish 任务里请遵守：

1. **任何写操作前先读 `auth_status`**，避免 token 已过期却继续写 → 白忙一场。
2. **`item_publish / media_upload / message_send` 都有速率限制**（令牌桶
   1 写/分钟），不要短时间连发。RGV587 触发后需用户手动 `goofish auth reset-guard`。
3. **所有对外发送（发商品、发消息）务必让用户先确认文案**，不要自动提交。
4. **多步任务中途报状态**：上一步完成了什么、下一步准备做什么。闲鱼任务
   通常是 3-6 步，用户期望有进度感。
