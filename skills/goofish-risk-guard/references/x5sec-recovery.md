# RGV587 / x5sec 风控恢复指引

## 症状识别

当 MCP 工具调用返回以下情况，判定为"服务端风控"：

| 错误 | 含义 |
|---|---|
| `FAIL_SYS_ILLEGAL_ACCESS` | h5 mtop 接口明确拒绝 |
| `RGV587` | 淘系风控拦截码（可能出现在 response body） |
| `item_publish` / `item_delete` 返回 `GUARD_TRIPPED` | 本地熔断触发 |
| `search_items` / `item_view` 浏览器路径返回 ERR_ABORTED 或 CAPTCHA 页面 | 风控重定向 |

## 错误心智模型

```
┌────────────────────────────┐
│  本地熔断（GUARD_TRIPPED）  │  ← auth_reset_guard 能解
│  短时间多次失败触发         │
├────────────────────────────┤
│  服务端风控（RGV587）       │  ← auth_reset_guard 解不了
│  x5sec cookie 失效/缺失     │  ← 必须从浏览器重导
└────────────────────────────┘
```

两层是**独立**的。本地熔断是客户端保护，服务端风控是淘系真发招。

## 恢复流程（按顺序，不要跳步）

### Step 1 · 判断层级

```
auth_reset_guard → 再调原接口 → 仍失败 → 是服务端风控
                               ↓ 成功
                               只是本地熔断
```

### Step 2 · 如果是服务端风控

**不要建议用户 `auth login`**——重新导 cookie 会**覆盖掉当前带 x5sec 的 session**（如果还残留着），更糟。

**正确做法**（口播话术）：
> 看起来闲鱼服务端触发了风控，本地解锁没用。恢复姿势是：
> 1. 打开浏览器（Chrome / Edge），手动登录闲鱼
> 2. 正常浏览 3-5 分钟（进几个商品详情页、翻翻首页）——让 `x5sec` 和 `mtop_partitioned_detect` 这两个关键 cookie 下发
> 3. 回来执行 `goofish auth login --browser chrome`（从浏览器导入最新 cookie）
> 4. 再试刚才的操作

### Step 3 · 如果仍失败

说明风控等级高了。建议用户：
- **停手 2-6 小时**，不要再任何写操作
- 检查是否短时高频写了？（令牌桶是 1 写/分钟，连发超过 20 次就容易被盯上）
- 检查是否多号同 IP？（同 IP 多号是高触发项）
- 如果 24 小时仍不恢复，考虑账号本身已被标记

## 关键 cookie 字段

服务端风控关心的不只是 `cookie2`，还有：

| cookie | 用途 |
|---|---|
| `x5sec` | 风控通行证，缺失或过期 → 立即风控 |
| `mtop_partitioned_detect` | 淘系 partitioned cookie 检测标记 |
| `isg` | 行为指纹 session |
| `l` | 浏览器级会话标识 |

**导 cookie 必须带全这几个**——goofish-cli 的 `auth login --browser chrome` 默认会带（如果浏览器里有）。

## 预防

本 skill 给上游 skill 的建议：

1. **发布 / 删除 / 消息发送**：每次操作间隔 ≥ 60s（令牌桶自然满速）
2. **批量任务**：用户明确要"发 10 件"时，Agent 提示"受限流 1 件/分钟，预计 10 分钟"并逐个发
3. **触发过一次风控**：24 小时内主动降速（改 2 件/分钟）
4. **切忌**：不要在一个 Agent 对话里同时做"发布 + 批量下架 + 群发消息"——组合拳最容易触发

## 自动化链路的限度

goofish-cli v0.2.2-v0.2.4 有自动刷 token + 自动点"快速进入"，但**这些只解 session 过期，不解风控**。

```
FAIL_SYS_TOKEN_EXOIRED  → 自动刷 ✅
FAIL_SYS_SESSION_EXPIRED → 自动点"快速进入" ✅
FAIL_SYS_ILLEGAL_ACCESS  → 自动化救不了，必须人工介入 ❌
```

Agent 看到第三种错误，**不要重试、不要尝试自愈**，直接进入本文件的恢复流程。
