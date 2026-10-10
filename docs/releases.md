# 发布

PyPI 自动发布，ClawHub 手动发布。业务 PR 合入 main 后，release-please 根据 Conventional Commits 判断下一版本，维护发布 PR。程序只合并机器人生成、通过检查且仅修改版本、安装示例和 CHANGELOG 的发布 PR；生成 tag/GitHub Release 后自动启动 PyPI 发布。无需人工改版本、推 tag 或上传 Python 包。

`fix:` 通常递增 patch，`feat:` 通常递增 minor。0.x 的破坏性变更递增 minor。仓库的 Python、插件元数据、MCP 精确版本锁定和安装文档由同一发布 PR 同步；当前 ClawHub 上的旧 bundle 仍锁定其已发布 Python 版本，不会随 PyPI 自动更新。

## 流程与权限

`.github/workflows/release.yml` 使用仓库自己的 GITHUB_TOKEN 创建和合并发布 PR，不保存个人访问 token。仓库 Settings → Actions → General 必须允许 GitHub Actions 创建 PR；程序不会绕过 branch protection 或人工审核规则。后续若收紧 main 的规则，自动合并受到相同限制。

发布 PR 验证按完整 SHA 执行。非机器人、外部仓库、非 main 基线或版本文件范围外的 PR 不进入自动合并；版本 JSON/TOML 中除版本外的内容、MCP 其他参数以及文档非版本内容也不得改变。检查后候选或 main 更新会中止合并，下一次执行重新生成并验证。

GITHUB_TOKEN 创建的 tag 不会触发另一个 push workflow，所以程序显式 dispatch `publish.yml` 到版本 tag；不依赖 tag 事件级联。发布始终由 `publish.yml` 执行，保留既有 PyPI Trusted Publisher 的 workflow 身份。

## 上传与回读

`publish.yml` 只接受与元数据一致的稳定版本 tag，并要求该提交属于 main 历史。对应 tag 必须通过 Python 3.11/3.12、lint、敏感标识扫描、版本契约、插件打包检查和构建，才进入上传。手工推 tag 和手工运行 publisher 也受这些检查约束；不能从 main 分支直接运行 publisher 上传。

上传前使用 PyPI 官方 Simple JSON 安装索引，对照已存在文件的 SHA256；不一致则拒绝。上传使用专用 pypi environment 和 OIDC，无长期 PyPI API token。只有上传 job 有 id-token:write；安装验证 job 没有该权限。

上传后从 PyPI 安装精确版本，验证 CLI 版本、MCP 握手和核心工具目录，并对照发布工件哈希。安装索引尚未可见时最多 10 次有限重试；不将新版本 JSON 路由的 404 当作安装索引可见性；失败明确保留失败状态，不能把上传成功当成安装验证成功。

## 恢复

自动发布流程按仓库串行，publisher 按 tag 串行。发布准备、合并、生成 tag、上传、安装验证是独立阶段。查看两个 workflow 的实际结论，不以 GitHub Release 或 tag 存在代替 PyPI 成功。

同一发布运行可重跑失败 job。已上传文件仅在哈希与检查过的产物一致时跳过；缺失文件继续上传。产物冲突不能用删 tag、覆盖文件或再次 bump 版本掩盖。若 tag/release 已生成而发布未启动，可执行：

```bash
gh workflow run publish.yml --ref v<版本>
```

重新执行 `release.yml` 会继续处理已合并且待生成 tag 的发布 PR，不需要重新提交业务代码。只希望暂停自动版本发布时，禁用 Automatic PyPI release 工作流；手动 publisher 通道仍存在。

## ClawHub

ClawHub 不在任何自动 workflow 中上传。选择一个已通过 PyPI 安装验证的版本 tag，从干净源码打包，再按 CONTRIBUTING.md 运行真实 embedded-agent 工具过滤验收、dry-run、平台安全检查和注册表下载哈希核验后手动发布。命令见 CONTRIBUTING.md。不会自动生成或上传 ClawHub token。
