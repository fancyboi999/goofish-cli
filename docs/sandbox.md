# 独立桌面沙箱

沙箱把整个 goofish CLI/MCP 放进本机 Docker 容器。有窗口的 Chromium 在虚拟桌面里运行，搜索、详情、扫码登录和登录态刷新不会在宿主机弹出浏览器窗口，也不接管已有标签页。Docker 不可用或沙箱停止时，命令直接失败，不会回退到本机浏览器。

需要 Python 3.11+、运行中的本机 Docker Desktop / Docker Engine，以及首次构建镜像时的网络连接。首次会下载 Playwright Ubuntu 镜像和桌面依赖；默认容器资源上限为 3 CPU、3 GB 内存，另有 1 GB 共享内存上限。运行 Chromium 的兼容性仍取决于平台响应，沙箱不保证通过登录或风控验证。

## 安装与版本检查

安装支持沙箱的 `goofish-cli` 版本后确认命令存在：

```sh
pip install --upgrade goofish-cli
goofish sandbox --help
```

若当前发行版尚未包含该命令，可安装已合并的源码：

```sh
git clone https://github.com/fancyboi999/goofish-cli.git
cd goofish-cli
uv tool install .
goofish sandbox --help
```

`goofish`、`docker` 必须在执行终端和 MCP 客户端可用的 PATH 中。GUI 客户端通常不会读取交互 shell 的配置；找不到 `goofish` 时，先在终端执行 `command -v goofish`，再把得到的绝对路径填入 MCP 的 `command`。Docker 也必须能从该客户端进程的 PATH 找到。

## 启动和登录

```sh
goofish sandbox start
# http://127.0.0.1:16080/vnc.html?autoconnect=1&resize=scale

goofish sandbox login
```

手动打开上面的观察链接。使用手机闲鱼 App 扫码，并在手机上确认。登录命令默认等待 600 秒，可通过 `--timeout` 调整。扫码数据保存后会调用账号接口确认登录有效；日志不输出 cookie、账号 ID 或昵称。二维码过期时可在虚拟桌面内刷新，或重新执行登录命令。

命令不会自动打开宿主机浏览器。只有用户主动打开观察链接，才会显示虚拟桌面。观察端口仅绑定 `127.0.0.1`，VNC 端口没有映射到宿主机。不要将观察端口转发到公网或不可信网络。

## 执行 CLI

```sh
goofish sandbox run auth status --format json
goofish sandbox run search items '机械键盘' --limit 3 --format json
goofish sandbox run item view <商品ID> --format json
goofish sandbox status
goofish sandbox stop
```

`sandbox run` 保留参数和业务命令退出码。命令运行在容器内，文件路径也指容器路径；宿主机文件不会被自动挂载。需要上传本地图片时，可显式使用 `docker cp /本机图片 goofish-sandbox:/tmp/图片`，再传入容器内路径。发布、消息发送等写操作仍使用原有风控、限流和结果校验，不因沙箱模式改变。

## 平台验证

沙箱内的 `item view` 和 `item get` 都读取商品页自身发出的详情响应，并核对请求和返回的商品 ID。不会在页面加载后补发详情 API 请求。`item get` 保持原有 JSON 结构；本机模式的直签路径不变。

平台返回需要验证时，命令以风控退出码 `76` 结束，保留当前页面。使用：

```sh
goofish sandbox browse --item-id <商品ID> --timeout 900
```

打开观察链接，亲自完成平台验证。该命令在同一页面等待目标商品的真实成功响应；如果商品已经显示，可手动刷新一次。成功后重新执行查询。不会自动解滑块、反复重试或切换到宿主机浏览器。

停止容器会结束浏览器进程。磁盘登录态可恢复，但平台可能在重启、会话过期或后续访问时重新要求人工验证；不要把保持登录等同于保证免验证。

## MCP

先在终端启动沙箱并完成登录，再**替换**客户端已有的 Goofish server。保持名称 `goofish`，让内置 Skills 的工具前缀继续匹配。支持 `mcpServers` JSON 的客户端配置为：

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

Codex 的 TOML、Claude Code 的配置位置及客户端验证步骤见 [MCP 接入指南](mcp-setup.md#独立桌面模式)。修改配置后重新连接 MCP 或新建客户端会话，先调用 `auth_status` 确认 `valid=true`，再执行搜索和详情查询。MCP 命令不负责构建、启动沙箱或等待扫码。

已发布包含沙箱功能的版本时，也可使用 uvx，命令为 `uvx`，参数为 `["--from", "goofish-cli", "goofish", "sandbox", "mcp"]`。MCP 通过 `docker exec -i` 的 stdio 连接。浏览器调试端口只监听容器内的 `127.0.0.1:9222`，不映射到宿主机；没有 MCP HTTP 端口。管理命令没有加入业务工具注册表；现有 MCP 工具集合不变。

宿主机 CLI 与镜像应使用同一版本；更新安装后重建镜像。源码安装尚未发布时，请使用本地 `goofish` 的绝对路径，不要让 uvx 拉取缺少沙箱命令的旧发行版。

`sandbox mcp` 应由客户端启动；直接在交互终端执行会提示配置方法并退出。

## 登录态与升级

登录态、设备标识、限流和熔断状态都位于专属卷 `goofish-sandbox-state`。卷不与宿主机 `~/.goofish-cli` 共享；不会读取或导入日常浏览器的 cookie。CLI cookie 和额外会话快照继续使用现有加密格式，浏览器 profile 由 Chromium 管理。固定容器 hostname 和用户保证停机、重启及重建后可解密。该卷包含敏感登录信息，应按本机凭证保护；加密机制不是对 Docker 管理员的访问隔离。

沙箱启动时运行一个常驻 Chromium，浏览器命令串行复用同一个页面。命令结束只断开控制连接，页面、sessionStorage 和人工验证后的上下文继续保留。另一项浏览器任务运行或等待人工验证时，新任务直接提示忙碌，不会打开第二个窗口。纯 HTTP 查询不占用浏览器锁。

浏览器 profile 位于状态卷的 `desktop-profile/`，完整 cookie 属性另存为加密的 `desktop-session.enc`，用于恢复重启时浏览器丢弃的会话 cookie。CLI 从同一文件内容读取 cookie 记录和版本摘要，退出时加锁检查版本并原子回写，旧浏览器任务不会覆盖期间发生的新登录。显式注入的 cookie 不自动回写 CLI 登录文件。账号不一致时直接报错，要求在沙箱内重新登录。

`stop` 会终止容器内浏览器，保留登录态。再次 `start` 使用同一容器和卷。升级 CLI 后执行：

```sh
goofish sandbox stop
goofish sandbox start --rebuild
```

镜像从当前安装的 CLI 代码构建，不会退回 PyPI 上的其他版本。`--rebuild` 只替换已停止且由 goofish 创建的容器，保留状态卷。首次启动可用 `--port 16081` 选择观察端口；已有容器继续使用原端口，要换端口需先停止并 `start --rebuild --port 16081`。

排查桌面启动问题可用 `docker logs goofish-sandbox`，以及 `docker exec goofish-sandbox cat /tmp/xvfb.log /tmp/browser.log /tmp/novnc.log`。沙箱使用 Docker init 回收浏览器子进程。停止后宿主机没有沙箱浏览器窗口或鼠标键盘操作。

## 常见情况

| 现象 | 处理 |
|---|---|
| `sandbox` 命令不存在 | 更新到包含沙箱功能的版本，或从已合并源码安装；确认客户端调用的是同一个可执行文件 |
| Docker 不可用 / 沙箱未运行 | 启动 Docker，在终端执行 `goofish sandbox start`；不会回退到本机浏览器 |
| MCP 找不到命令 | 使用 `goofish` 绝对路径，并检查客户端进程的 Docker PATH |
| 账号与 CLI 登录态不同 | 在沙箱内执行 `goofish sandbox login` 重新登录；不会混用账号 |
| 浏览器任务忙碌 | 完成正在运行的任务或人工验证，再发起下一次浏览器任务 |
| 详情返回风控错误 | 在终端执行 `sandbox browse --item-id <商品ID>`，亲自完成平台验证后重试 |

沙箱配置只改变对应 MCP server 的执行位置。终端或 Skills 中直接运行的 `goofish <业务命令>` 仍为本机模式，需显式使用 `goofish sandbox run <业务命令>`。OpenClaw bundle 的默认启动配置也仍为本机模式；本指南的 MCP 配置适用于可自定义 stdio 启动命令的客户端，bundle 本身尚未提供沙箱开关。
