# 独立桌面沙箱

沙箱把整个 goofish CLI/MCP 放进本机 Docker 容器。有窗口的 Chromium 在虚拟桌面里运行，搜索、详情、扫码登录和登录态刷新不会在宿主机弹出浏览器窗口，也不接管已有标签页。Docker 不可用或沙箱停止时，命令直接失败，不会回退到本机浏览器。

需要 Python 3.11+、运行中的本机 Docker Desktop / Docker Engine，以及首次构建镜像时的网络连接。首次会下载 Playwright Ubuntu 镜像和桌面依赖；默认容器资源上限为 3 CPU、3 GB 内存，另有 1 GB 共享内存上限。运行 Chromium 的兼容性仍取决于平台响应，沙箱不保证通过登录或风控验证。

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

## MCP

先在终端启动沙箱并完成登录，再将 MCP 客户端配置为：

```json
{
  "mcpServers": {
    "goofish-sandbox": {
      "command": "goofish",
      "args": ["sandbox", "mcp"]
    }
  }
}
```

使用 uvx 时，命令为 `uvx`，参数为 `["--from", "goofish-cli", "goofish", "sandbox", "mcp"]`。MCP 通过 `docker exec -i` 的 stdio 连接，没有浏览器调试端口或 MCP HTTP 端口。管理命令没有加入业务工具注册表；现有 MCP 工具集合不变。

`sandbox mcp` 应由客户端启动；直接在交互终端执行会提示配置方法并退出。

## 登录态与升级

登录态、设备标识、限流和熔断状态都位于专属卷 `goofish-sandbox-state`。卷不与宿主机 `~/.goofish-cli` 共享；不会读取或导入日常浏览器的 cookie。cookie 继续使用 CLI 现有加密格式，固定容器 hostname 和用户保证停机、重启及重建后可解密。该卷包含敏感登录信息，应按本机凭证保护；加密机制不是对 Docker 管理员的访问隔离。

每次浏览器调用仍使用独立临时 profile，放在容器 `/tmp`，结束后清理；该目录不放入登录态卷。

`stop` 会终止容器内浏览器，保留登录态。再次 `start` 使用同一容器和卷。升级 CLI 后执行：

```sh
goofish sandbox stop
goofish sandbox start --rebuild
```

镜像从当前安装的 CLI 代码构建，不会退回 PyPI 上的其他版本。`--rebuild` 只替换已停止且由 goofish 创建的容器，保留状态卷。首次启动可用 `--port 16081` 选择观察端口；已有容器继续使用原端口，要换端口需先停止并 `start --rebuild --port 16081`。

排查桌面启动问题可用 `docker logs goofish-sandbox`，以及 `docker exec goofish-sandbox cat /tmp/xvfb.log /tmp/novnc.log`。沙箱使用 Docker init 回收浏览器子进程。停止后宿主机没有沙箱浏览器窗口或鼠标键盘操作。
