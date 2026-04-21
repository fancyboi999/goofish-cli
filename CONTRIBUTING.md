# Contributing to goofish-cli

感谢参与 👋。本文档讲清楚：环境搭建、加命令的流程、写测试和验证的要求、合规红线。

## 环境

```bash
git clone https://github.com/fancyboi999/goofish-cli
cd goofish-cli
uv venv --python 3.11
uv pip install -e ".[dev]"
```

运行时依赖 Node.js（`pyexecjs` 跑签名 JS）：

```bash
brew install node       # macOS
sudo apt install nodejs # Debian/Ubuntu
```

## 验证

```bash
uv run pytest
uv run ruff check src tests
```

单测全绿 **不等于** 功能可用。下面三种情况是硬门槛：

1. **新增 HTTP 命令** — 必须用 `goofish auth login` 后的真实 cookie 跑一次对应 `goofish <cmd>`，并把 ret/data 的要点贴到 PR。
2. **新增 WebSocket 行为** — 必须让 `message watch` 跑起来并实际收到一条远端消息（或 send 到真实 cid），贴出现场日志。
3. **改签名 / 风控相关** — 必须手工跑 `goofish auth status` 验证旧 cookie 仍有效，以及新逻辑不触发 `RGV587_ERROR` / `FAIL_SYS_USER_VALIDATE`。

"我只是小改" 也不能跳过。参考 [真实验证准则](./docs/architecture.md#验证准则)。

## 加命令：典型流程

1. 在 `src/goofish_cli/commands/<namespace>/<cmd>.py` 写一个函数
2. 函数加 `@command(namespace="...", name="...", description="...", strategy=..., columns=[...], write=True/False)` 装饰器
3. 入参用 `typer.Option / typer.Argument` 声明
4. 返回 `dict` / `list[dict]`，格式由 `--format` 渲染
5. 写单测：纯函数逻辑（解析/编码/状态）用 pytest 覆盖。HTTP/WS 不要 mock 骨架，走真实 Session 的要标 `@pytest.mark.integration`。
6. 跑一次真实 CLI 验证，贴输出到 PR

新命令自动被 `registry()` 发现，同时对 MCP server 可见。**无需**改别的地方。

## 合规红线

- 任何情况下都**不要** commit cookie、`_m_h5_tk`、IM accessToken、可复现签名的 JSON fixture
- 新命令不得让工具更容易做：刷单、虚假交易、批量骚扰、规避平台封禁（例如"换设备重登"、"免滑块"）
- 风控能用人工解（`goofish auth reset-guard` + 浏览器滑块）就用，别 PR "自动过滑块"、"自动生成 x5sec" 这类
- 写 demo 请脱敏：itemId 可公开，unb/cid 掩码处理

## 风格

- `ruff check` 零告警
- 函数/类名用英文。用户可见的 description、log、error 用简体中文
- 每个文件开头一行中文说明它在干啥
- 避免无用注释 / 无用 docstring
