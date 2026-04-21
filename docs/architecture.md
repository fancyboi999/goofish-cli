# Architecture

> 一句话：**Single Registry → CLI / MCP / Skill 三态共享**。加一个新命令只需在 `commands/` 下添一个文件，三种形态自动获得。

参照 [opencli](https://github.com/jackwener/opencli) 的 single registry 思路实现。

## 分层

```
┌─────────────────────────────────────────────────────────────┐
│  形态层（Surface）                                           │
│  ├─ cli.py          Typer → registry 生成子命令树           │
│  ├─ mcp_server.py   FastMCP → registry 注册 @mcp.tool()     │
│  └─ skills/*        SKILL.md（v0.2 规划）                    │
└─────────────────────────────────────────────────────────────┘
                             ▲
                             │ iter_commands()
┌─────────────────────────────────────────────────────────────┐
│  Registry 层                                                 │
│  core/registry.py   @command(...) 注册中心（单例）          │
└─────────────────────────────────────────────────────────────┘
                             ▲
                             │ discover()
┌─────────────────────────────────────────────────────────────┐
│  命令层（Business）                                          │
│  commands/<ns>/<action>.py                                  │
│    auth/    login, status, reset-guard                      │
│    item/    get, publish, delete                            │
│    media/   upload                                          │
│    category/recommend                                       │
│    location/default                                         │
└─────────────────────────────────────────────────────────────┘
                             ▲
                             │ call / acquire / watch
┌─────────────────────────────────────────────────────────────┐
│  Core 层（Infra）                                            │
│  core/sign.py       pyexecjs → goofish_js_version_2.js      │
│  core/session.py    cookie 加载 + requests.Session          │
│  core/mtop.py       统一 mtop 调用 + 错误分类               │
│  core/limiter.py    令牌桶限流（1 写/分钟，可配）          │
│  core/guard.py      风控熔断（RGV587 → trip）              │
│  core/output.py     统一渲染 json/yaml/table/md/csv         │
│  core/errors.py     异常体系 + exit_code                    │
└─────────────────────────────────────────────────────────────┘
```

## 关键设计：`@command` 装饰器

每个命令文件长这样：

```python
from goofish_cli.core import Session, Strategy, command
from goofish_cli.core.mtop import call

@command(
    namespace="item",
    name="get",
    description="查询闲鱼商品详情（只读）",
    strategy=Strategy.COOKIE,
    columns=["item_id", "title", "price", "seller_nick", "status"],
)
def get(item_id: str) -> dict:
    session = Session.load()
    raw = call(session, api="mtop.taobao.idle.pc.detail",
               data={"itemId": item_id}, version="1.0")
    ...
```

- **namespace + name** → CLI 路径 `goofish item get`，MCP tool 名 `item_get`
- **columns** → 输出契约（table/csv/md 场景的列顺序）
- **strategy** → 认证要求（PUBLIC / COOKIE / WS）
- **write=True** → 自动触发限流 + 风控熔断

## 风控护栏

1. **令牌桶**（`core/limiter.py`）：默认 1 写/分钟，持久化在 `~/.goofish-cli/limiter.json`
2. **熔断**（`core/guard.py`）：`watch()` 上下文内命中 `RiskControlError` → 写 `circuit.json`，默认熔断 10 分钟
3. **响应体识别**（`core/mtop.py`）：自动扫 `RGV587_ERROR / punish / FAIL_SYS_USER_VALIDATE` 等关键字

这些护栏在 **底层强制**，Agent 层无法绕过。

## 实现要点

- **`t` 毫秒位**：`int(time.time() * 1000)` 取真实毫秒（避免 `int(time.time()) * 1000` 把末三位抹成 000 的精度陷阱）
- **默认地址**：`commonAddresses[0]` 兜底，参数化接口支持显式指定 `addressId`
- **风控识别**：扫描响应体关键字（`RGV587_ERROR` / `punish` / `FAIL_SYS_USER_VALIDATE`），命中即熔断
- **限流**：令牌桶持久化在 `~/.goofish-cli/limiter.json`
- **形态**：CLI + MCP（+ Skill 规划），同一份 registry 输出三种形态
- **命令组织**：每命令一个文件，`@command(...)` 装饰器自注册，参照 opencli
