---
name: goofish-risk-guard
description: |
  闲鱼风控/合规预检 skill。何时激活：用户要发商品、回消息、降价改标前让你
  "看看这样行不行"、"会不会违规"、"会不会封号"、"会不会限流"；或用户说
  "被限流了/曝光掉了怎么办"；或被 `goofish-publish-item` / `goofish-reply-buyer`
  调用做预检。功能：发布前扫描（绝对化词、类目偏差、降价改标、9 图合规），
  发送前扫描（外联词、误导承诺），触发 RGV587 风控后的恢复指引。
  **本 skill 主要是知识库 + 检查清单，不直接替用户改文案**——由调用方 skill 拿检查结果去改。
metadata:
  author: goofish-cli
  version: "0.3.0"
  tags: [xianyu, risk, compliance, guard]
allowed-tools:
  - mcp__goofish__auth_status
  - mcp__goofish__search_items
  - mcp__goofish__item_get
  - mcp__goofish__auth_reset_guard
---

# 闲鱼风控预检

## 定位

这是 **被其它 skill 频繁调用的知识库型 skill**。Agent 读它的 references，不一定要调 MCP 工具。

其它 skill 什么时候应该引用本 skill：

| 上游 skill | 引用点 |
|---|---|
| `goofish-publish-item` | 标题/描述生成后、发布前 → `forbidden-words.md` + `publish-red-lines.md` |
| `goofish-reply-buyer` | 起草回复后、send 前 → `external-contact-keywords.md` |
| `goofish-shop-diagnosis` | 归因分析阶段 → `publish-red-lines.md` 里的降权触发项 |

## 三道闸门

### 闸门 1 · 发布前扫描

输入：标题 / 描述 / 价格 / 图片数 / 类目 / 历史价格（若有）
输出：`{ blockers: [...], warnings: [...], suggestions: [...] }`

**blockers（必须改，否则拒绝发布）**：
- 绝对化词（最/顶/第一/绝对/全网最低等，详见 `forbidden-words.md`）
- 外联词（同上，消息和商品描述都禁）
- 品牌侵权（非授权卖 Nike/LV 等一线品牌）
- 类目明显错放（比如"手机壳"放到"数码-手机"）

**warnings（建议改）**：
- 标题缺结构（没品牌 / 没核心词 / 没规格）
- 图片 < 3 张
- 首图非 1:1
- 描述 < 30 字（信息不足，买家不问直接跳过）

**suggestions（可选优化）**：
- 按"品牌+核心词+属性+场景+情感" 5 段式补全
- 建议加成色描述（95 新 / 8 成新 / 有瑕疵具体说明）

具体规则见 `references/publish-red-lines.md`。

### 闸门 2 · 发消息前扫描

输入：草稿 text
输出：`{ block: bool, reason: str, replacement: str | None }`

命中规则（详见 `references/external-contact-keywords.md`）：
- 外联关键词 → `block=True`，提供合规替换
- 诱导线下担保 → `block=True`
- 误导性承诺（"包真"、"假一赔十"但无凭证）→ `warning`
- 情绪失控词（"你脑子有病"、"去死"）→ `warning`

### 闸门 3 · RGV587 / x5sec 恢复

当 MCP 调用返回 `FAIL_SYS_ILLEGAL_ACCESS` 或 `RGV587`：

**不要做**：
- 重试（会进一步触发风控）
- 建议用户 `auth_login`（覆盖 cookie 后丢失 x5sec，更糟）
- 建议用户 `auth reset-guard`（**只解本地熔断，不解服务端**）

**要做**（按顺序）：
1. 告诉用户：**服务端风控已触发**，原因可能是短时高频写 / 多号同 IP / 新增风险行为
2. 引导用户：打开浏览器登录闲鱼，正常浏览 3-5 分钟，触发 `x5sec` / `mtop_partitioned_detect` cookie 下发
3. 用户执行 `goofish auth login --browser chrome` 重新导入（带 x5sec）
4. 如果仍失败 → 建议 2-6 小时后再来

详见 `references/x5sec-recovery.md`。

## 决策框架：什么时候"拒绝帮忙"

这些请求 **拒绝并解释**，不要找绕过路径：

| 用户请求 | 为什么拒 |
|---|---|
| "帮我写个微信号的隐藏方式" / "帮我躲过外联词检测" | 违反平台规则 + 本工具合规声明红线 |
| "帮我刷单/做假交易" | 同上 |
| "帮我批量注册小号" / "帮我伪造设备 ID" | 同上 |
| "帮我把这个假货说成真的" | 欺诈 |
| "帮我写差评报复别的卖家" | 恶意 |
| "帮我规避封号后的账号找回" | 绕过平台风控 |

**话术模板**：
> 这个请求踩到了闲鱼平台的合规红线（{具体项}），本工具不协助这类操作。你可以考虑 {合规替代方案}。

## 工具使用

大部分检查不需要调 MCP 工具——读 references 就够。需要时：

- `search_items`：查买家视角能否搜到自家商品（诊断限流）
- `item_get`：拉自家商品历史元数据（判断是否降价改标了）
- `auth_status`：调其它工具前确认登录态

**写操作本 skill 完全不调**（`item_publish / media_upload / message_send / item_delete` 都不在 allowed-tools）。
