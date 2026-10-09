# MCP 工具速查（共 17 个）

> 下表使用 registry 逻辑名。OpenClaw 调 `goofish__<逻辑名>`，Claude Code / Cursor
> 调 `mcp__goofish__<逻辑名>`。例：CLI `goofish message list-chats` 的逻辑名是
> `message_list_chats`。`goofish skills install` 也会被 registry 扫到并暴露为 `skills_install`，
> 但它是给**用户在终端跑**的辅助命令，Agent 通常不主动调。

## Auth（3 个）

| 工具 | 用途 | 何时调 | 副作用 |
|---|---|---|---|
| `auth_status` | 查登录态（返回 `{unb, tracknick, nick, valid, h5_token_exp}`） | 任何写操作前第一步 | 无 |
| `auth_login` | 导入登录态（browser auto-detect / 指定源 / `--qr` 扫码） | **Agent 不主动调**，只建议用户手动执行 | 覆盖磁盘 cookies.json |
| `auth_reset_guard` | 解本地熔断 | RGV587 触发后的恢复步骤之一，但**不解服务端风控** | 清 local guard 状态 |

## Item（5 个）

| 工具 | 用途 | 典型入参 | 风险 |
|---|---|---|---|
| `item_get` | HTTP 视角拉详情（只读） | `item_id` | 无 |
| `item_list` | 查看当前账号的在售商品 | `limit?` | 无 |
| `item_view` | 浏览器视角拉详情（字段更全、抗风控） | `item_id` | 触发 Playwright 启动 |
| `item_publish` | 发布商品（自动类目+默认地址） | `title, desc, price, images?, images_json?, category_json?, location_json?` | **写操作**，item.write 默认 1 次/分钟 |
| `item_delete` | 下架/删除商品 | `item_id` | **写操作** + 风控护栏 |

**发布前强依赖**：`category_recommend` 拿 catId、`media_upload` 拿图片收据、`location_default` 兜底 location_json。

## Message（4 个）

| 工具 | 用途 | 典型入参 | 备注 |
|---|---|---|---|
| `message_list_chats` | 按最近活动排序的会话摘要 | `fetch_num?, watch_secs?, timeout?` | 默认 5 秒 WS 发现并读取最近消息；检查 metadata_status，不能把 has_more 当全部会话完整性 |
| `message_history` | 某 cid 的历史消息 | `cid, limit_per_page?, limit?, timeout?` | limit=0 翻页到底；正数只读最近 N 条，保留 message_id/created_at |
| `message_watch` | 常驻 IM 长连接，事件以 JSONL 输出 | `secs?` | 阻塞式；Skill 里慎用，短连接更合适 |
| `message_send` | 发消息（text/image） | `cid, text` 或 `cid, image_url, w, h` | **写操作** + 外联词风控 |

## Category / Media / Search / Location（4 个）

| 工具 | 用途 | 备注 |
|---|---|---|
| `category_recommend` | AI 识别类目（输入标题+图片返回 catId/catName） | 发布前必跑，类目错放会降权 |
| `media_upload` | 上传图片到闲鱼 CDN | 返回 `{url, width, height}`，给 `item_publish` 直接用 |
| `search_items` | 搜闲鱼商品（浏览器路径，抗风控） | 诊断限流时用"卖家视角 vs 买家视角"对比 |
| `location_default` | 账号默认发布地址 | `item_publish` 不传 location_json 时的兜底 |

## Skills（1 个，辅助类）

| 工具 | 用途 | 备注 |
|---|---|---|
| `skills_install` | 把内置 Claude Skills 复制到 `~/.claude/skills/`（或 `--dest`） | `--list` 仅列出、`--force` 覆盖已有；给**用户**在终端跑，Agent 一般不主动调 |

## 调用模式速记

**发布闭环**（场景：挂一件闲置）
```
auth_status → category_recommend → media_upload (×N) → location_default → item_publish
```

**回消息闭环**（场景：处理未读）
```
auth_status → message_list_chats → message_history (按 cid) → [LLM 意图分类 + 起草] → 用户确认 → message_send
```

**诊断闭环**（场景：查为什么没流量）
```
auth_status → search_items (用自家核心词，买家视角) → item_view (拉自家详情) → item_get (历史元数据对比)
```

## 写操作预算与错误恢复

- 同账号发布和下架使用 `item.write`，消息使用 `message.write`，默认各 1 次/分钟。
- 上传使用独立 `media.write`，默认 9 次/分钟；上传收据通过 `images_json` 复用。
- CLI 进程与 MCP 线程共享加锁、原子保存的状态；损坏文件拒绝写入。
- 本机预算不代表平台额度；平台风控触发账号熔断，`auth_reset_guard` 只改变本机状态。
- 发布失败保留图片、类目、地址及提交状态；`submission_unknown` 先回读，不能自动重发。
- 搜索 `complete=false` 是未完成，CLI 非零退出，MCP `ok=false` 仍带部分 `data`。
- 搜索的品牌、成色未知时是 null；用 labels 查看原始标签，不能按顺序猜属性。空查询命中不含网页推荐。

## 错误类型映射

| 错误 | 含义 | 处理 |
|---|---|---|
| `FAIL_SYS_TOKEN_EXOIRED` | `_m_h5_tk` 过期（10 分钟 TTL） | 自动刷 token（已内置），Agent 无需干预 |
| `FAIL_SYS_SESSION_EXPIRED` | `cookie2` session 失效 | 自动点 passport "快速进入"；失败则提示用户 `goofish auth login --qr` |
| `FAIL_SYS_ILLEGAL_ACCESS` | 风控拒绝 | **不要连续重试**（会加深风控）；按 `goofish-risk-guard/references/x5sec-recovery.md` 走——让用户从浏览器重导 cookie，或停手 2-6 小时 |
| `RATE_LIMITED` | 本地令牌桶耗尽 | 等下一分钟 |
| `GUARD_TRIPPED` | 本地熔断（连续风控触发） | `auth_reset_guard` + 从浏览器重导 cookie |
