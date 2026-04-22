# 账号模型

## 登录态存储

- 磁盘：`~/.goofish-cli/cookies.json`（可通过 `GOOFISH_COOKIES_PATH` 覆盖）
- 内存：`Session.http.cookies`（requests 的 CookieJar）
- `mcp__goofish__auth_status` 返回 `{unb, tracknick, nick, valid, h5_token_exp}`

## 关键 cookie 字段

| cookie | 用途 | 失效表现 |
|---|---|---|
| `_m_h5_tk` | h5 mtop 签名（**10 分钟** TTL） | `FAIL_SYS_TOKEN_EXOIRED`（拼写来自服务端非笔误） |
| `unb` | 用户 id | — |
| `cookie2` | 真正的 session token | `FAIL_SYS_SESSION_EXPIRED` |
| `sgcookie / _tb_token_` | 完整 session 三件套 | 同上 |
| `x5sec` | 风控通行（可选） | RGV587 风险时需要重导 |
| `tracknick` | 昵称跟踪 | — |

## 自动续命链路（v0.2.2 - v0.2.4）

```
mtop 调用 → FAIL_SYS_TOKEN_EXOIRED
   ↓
refresh_cookies_via_browser（自动）
   ↓
Playwright goto 首页 → 若弹 #alibaba-login-box → 点"快速进入"免密登录
   ↓
goto /bought 触发完整 session cookie 下发 → 合并回 session → 重试原请求
```

如果**浏览器免密记忆失效**（换机 / 清 cookie / 首次用），自动链路失败。
此时用户需显式 `goofish auth login --qr` 扫码。**Agent 不主动调 auth_login**。

## 环境变量

| 变量 | 作用 |
|---|---|
| `GOOFISH_COOKIES_PATH` | 自定义 cookies.json 路径 |
| `GOOFISH_AUTO_REFRESH_TOKEN=0` | 关掉自动刷新（CI 用） |
| `GOOFISH_QR_TIMEOUT=N` | 扫码超时秒数（默认 120） |
| `GOOFISH_HEADLESS=1` | 浏览器 headless（会触发风控，慎用） |
| `GOOFISH_NO_CHROME_BOOTSTRAP=1` | 禁止从本机 Chrome 自动抓 cookie |
