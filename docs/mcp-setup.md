# MCP 接入指南

## Claude Code / Codex CLI

在 `~/.claude/settings.json` 或项目 `.claude/settings.json` 加：

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

或本地开发版：

```json
{
  "mcpServers": {
    "goofish": {
      "command": "/Users/you/Desktop/goofish-cli/.venv/bin/goofish-mcp"
    }
  }
}
```

## Cursor

`~/.cursor/mcp.json`：同上格式。

## 可用工具

启动后 Claude 获得以下 tool：

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
