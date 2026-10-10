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
npm test
npm run pack:check
```

改动 OpenClaw bundle 时还要用隔离配置做一次 link 或打包后的 `.tgz` archive 安装，确认
`openclaw plugins inspect goofish --json` 能识别 skills 和 MCP server。OpenClaw
`2026.7.1` 的 `mcp doctor` 不读取 bundle MCP 配置，不能代替这个检查。
发布 ClawHub bundle 前必须先在 PyPI 发布同版本 `goofish-cli`，并实际运行
`uvx --from goofish-cli==<version> goofish-cli` 完成 MCP handshake；`.mcp.json`
故意精确锁定两个包的版本，不会自动回退到旧版 Python 运行时。
用 ClawHub CLI 发布时要显式指定 bundle family：

```bash
npm pack
clawhub package publish ./openclaw-goofish-<version>.tgz \
  --family bundle-plugin --bundle-format codex --host-targets openclaw --dry-run
```

`openclaw.plugin.json` 只提供 ClawHub 包身份和空配置 schema；实际运行入口仍是
`.codex-plugin/plugin.json` 和 `.mcp.json`，`package.json` 不得增加 `openclaw.extensions`。
工具过滤必须通过 `openclaw agent --local` 的 embedded-agent 会话 trajectory 验证；
`openclaw mcp probe` 不读取 bundle 的 `.mcp.json`，不能作为 bundle E2E 证据。
预期为 13 个业务工具可见，4 个 `toolFilter.exclude` 工具不可见；OpenClaw
另外生成的 4 个 prompts/resources 桥接工具不计入业务工具数。

单测全绿 **不等于** 功能可用。下面三种情况是硬门槛：

1. **新增 HTTP 命令** — 必须用 `goofish auth login` 后的真实 cookie 跑一次对应 `goofish <cmd>`，并把 ret/data 的要点贴到 PR。
2. **新增 WebSocket 行为** — 必须让 `message watch` 跑起来并实际收到一条远端消息（或 send 到真实 cid），贴出现场日志。
3. **改签名 / 风控相关** — 必须手工跑 `goofish auth status` 验证旧 cookie 仍有效，以及新逻辑不触发 `RGV587_ERROR` / `FAIL_SYS_USER_VALIDATE`。

"我只是小改" 也不能跳过。参考 [真实验证准则](./docs/architecture.md#验证准则)。

## 版本与发布

PyPI 由程序自动维护版本 PR、验证、合并、生成 tag 并发布；ClawHub 保持手动。触发规则、权限和失败恢复见 [发布流程](docs/releases.md)。新增自动化不能依赖个人 token，也不能跳过 tag、工件哈希或 PyPI 实装验证。

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
