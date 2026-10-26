# MCP 接入指南

## OpenClaw / ClawHub

要求：OpenClaw `2026.6.1` 及以上，且 PATH 中可以执行 `uvx`。

ClawHub 发布后安装：

<!-- x-release-please-start-version -->
```bash
openclaw plugins install clawhub:openclaw-goofish
uvx --from goofish-cli==0.6.3 goofish auth login --qr
openclaw plugins inspect goofish --json
openclaw gateway restart
```
<!-- x-release-please-end -->

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

在项目根目录 `.mcp.json` 配置（[Claude Code 官方 MCP 配置说明](https://code.claude.com/docs/en/mcp#project-scope)）：

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
| `item_view` | 浏览器商品详情 |
| `item_list` | 查询自己的商品 |
| `item_publish` | 发布商品（写） |
| `item_delete` | 下架商品（写） |
| `media_upload` | 上传图片 |
| `category_recommend` | AI 类目识别 |
| `location_default` | 获取默认地址 |
| `search_items` | 搜索商品 |
| `message_history` | 消息历史 |
| `message_list_chats` | 会话列表 |
| `message_send` | 发送消息（写） |
| `message_watch` | 监听消息（常驻） |
| `skills_install` | 安装内置 Skills |

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
## 独立桌面模式

浏览器自动化需要隔离到 Docker 虚拟桌面时，先在终端完成：

```sh
goofish sandbox --help
goofish sandbox start
goofish sandbox login
goofish sandbox run auth status --format json
```

需要运行中的本机 Docker，以及包含沙箱命令的 CLI 版本。终端会输出观察链接，默认 `http://127.0.0.1:16080/vnc.html?autoconnect=1&resize=scale`，由用户手动打开、扫码确认。不要把观察链接填成 MCP URL；MCP 使用 stdio。缺少命令时，见[源码安装及升级](sandbox.md#安装与版本检查)。

随后替换已有的 `goofish` server，保留这个名称以兼容 Skills。不要另留一个本机 Goofish server 让 Agent 选择。普通 `uvx goofish-cli` 不会进入沙箱。

### Claude Code / Cursor

Claude Code 项目根目录 `.mcp.json`、Cursor 的 MCP JSON 配置中使用：

```json
{
  "mcpServers": {
    "goofish": {
      "command": "goofish",
      "args": ["sandbox", "mcp"]
    }
  }
}
```

Claude Code 也可在目标项目内执行 `claude mcp add --transport stdio --scope project goofish -- goofish sandbox mcp`。已有同名 server 时修改原条目，并检查其他作用域是否仍有旧定义。项目/用户作用域以[官方说明](https://code.claude.com/docs/en/mcp#scope-hierarchy-and-precedence)为准。

### Codex

在 `~/.codex/config.toml` 的现有条目中配置（[OpenAI 官方 MCP 说明](https://learn.chatgpt.com/docs/extend/mcp#configure-with-configtoml)）：

```toml
[mcp_servers.goofish]
command = "goofish"
args = ["sandbox", "mcp"]
```

也可使用 `codex mcp add goofish -- goofish sandbox mcp`，已有条目时直接修改原配置。配置按 stdio 连接容器，不需要浏览器调试端口、HTTP MCP 地址或登录 token。

### 连接验证与恢复

桌面客户端找不到 `goofish` 时，将 `command` 改为终端中 `command -v goofish` 输出的绝对路径；同时确保客户端 PATH 中能找到 `docker`。源码安装尚未发布时，使用该源码环境内的 `goofish` 路径。

更新配置后重新连接 MCP 或新建客户端会话。先调用 `auth_status`，应返回 `ok=true` 且 `valid=true`；然后调用 `search_items` 和 `item_get`/`item_view`。`sandbox mcp` 不负责构建或启动容器，容器停止时会明确失败，不会改用本机浏览器。

平台要求验证时，在终端执行 `goofish sandbox browse --item-id <商品ID>`，由用户在同一虚拟桌面完成验证。升级 CLI 后，执行 `goofish sandbox stop`、`goofish sandbox start --rebuild`，再重新连接客户端，原状态卷保留。完整的端口、状态保存、uvx 和常见问题见[沙箱指南](sandbox.md)。

OpenClaw bundle 的默认 `.mcp.json` 仍是本机模式，本次没有增加 bundle 沙箱开关；不要把安装 bundle 等同于启用沙箱。
