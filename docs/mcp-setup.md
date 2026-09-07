# MCP 接入指南

## OpenClaw / ClawHub

要求：OpenClaw `2026.6.1` 及以上，且 PATH 中可以执行 `uvx`。

ClawHub 发布后安装：

```bash
openclaw plugins install clawhub:openclaw-goofish
uvx --from goofish-cli==0.4.0 goofish auth login --qr
openclaw plugins inspect goofish --json
openclaw gateway restart
```

本地开发使用 link 安装：

```bash
openclaw plugins install -l /path/to/goofish-cli
openclaw plugins inspect goofish --json
```

`inspect` 应显示 `Format: bundle`、Codex subtype，以及 skills 和 MCP server 能力。
Gateway 重启后新会话中，工具名为 `goofish__<逻辑名>`，例如
`goofish__auth_status` 和 `goofish__item_get`。

bundle 默认过滤以下工具：

| 工具 | 原因 |
|---|---|
| `auth_login` | 会覆盖磁盘登录态，应由用户在终端执行 |
| `auth_reset_guard` | 恢复动作需要用户判断，且不能解除服务端风控 |
| `message_watch` | 常驻阻塞式连接，不适合作为单次 Agent tool |
| `skills_install` | bundle 已直接提供 skills，无需 Agent 再安装 |

OpenClaw `2026.7.1` 的 `openclaw mcp doctor` 只读取 `openclaw.json` 中的
`mcp.servers`，不会读取 bundle 的 `.mcp.json`；因此插件验收应使用 `plugins inspect`
和 embedded agent 新会话的 trajectory 工具目录，不要重复配置同一个 server
只为运行 doctor。验收时应看到 13 个 Goofish 业务工具，且不应看到上表的
4 个过滤工具。OpenClaw 还会为 MCP prompts/resources 生成
`goofish__prompts_*` 和 `goofish__resources_*` 4 个桥接工具，因此按
`goofish__*` 前缀统计的总数是 17，不代表 `toolFilter` 失效。

## Claude Code

在 `~/.claude/settings.json` 或项目 `.claude/settings.json` 加：

```json
{
  "mcpServers": {
    "goofish": {
      "command": "uvx",
      "args": ["goofish-cli"]
    }
  }
}
```

或本地开发版：

```json
{
  "mcpServers": {
    "goofish": {
      "command": "/Users/you/Desktop/goofish-cli/.venv/bin/goofish-cli"
    }
  }
}
```

## Cursor

`~/.cursor/mcp.json`：同上格式。

## 可用工具

启动后 Claude 获得以下 tool；skills 中使用 Claude 的
`mcp__goofish__<逻辑名>` 前缀：

| Tool 名 | 说明 |
|---|---|
| `auth_login` | 导入 cookie |
| `auth_status` | 检查登录态 |
| `auth_reset_guard` | 解除风控熔断 |
| `item_get` | 查询商品（只读） |
| `item_publish` | 发布商品（写） |
| `item_delete` | 下架商品（写） |
| `media_upload` | 上传图片 |
| `category_recommend` | AI 类目识别 |
| `location_default` | 获取默认地址 |

## 首次使用

1. 从 Chrome DevTools 导出 goofish.com cookie（JSON 数组）到本地文件
2. 跑一次 CLI 导入：`goofish auth login ~/Downloads/goofish-cookies.json`
3. Claude 会话里问："帮我查一下 itemId 1046118265141 的商品信息"
4. Claude 会自动调用 `item_get` tool

## 调试

列出所有注册的 tool：

```bash
python -c "
from goofish_cli.mcp_server import mcp, _register_all
import asyncio
_register_all()
for t in asyncio.run(mcp.list_tools()):
    print(t.name)
"
```
