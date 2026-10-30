# 验证记录 / Validation record

日期：2026-10-30（America/New_York）。

## 本地执行

环境：macOS Apple Silicon，Python 3.11.15，Playwright 1.60.0，Chromium 148.0.7778.96，webull 0.6.1。

| 检查 | 结果 |
| --- | --- |
| 新建虚拟环境，`python -m pip install .` | 成功构建 wheel 并安装 |
| `python -m pip check` | 无依赖冲突 |
| `webull-browser-login --help` | 正常显示命令与参数 |
| `RUN_BROWSER_TESTS=1 python -m unittest discover -s tests -v` | 32 项全部通过，无跳过 |
| 真实 Chromium、本地模拟网页登录、CLI 保存 | 通过；模拟 Webull 请求全部在浏览器内本地满足 |
| 真实 Chromium、本地网页登录/取消/账户遮罩 | 通过；无页面脚本错误；检查了窄屏截图 |
| 凭证原子替换、写入失败、取消、超时与窗口关闭 | 旧凭证保留；POSIX 权限检查通过 |
| 可信域名、token 配对、脱敏输出、Host/Origin/操作令牌 | 对应用例通过 |
| 虚构账户与 PIN 授权、非交互终端阻断、明确确认 | 对应用例通过；无真实 PIN 请求 |

原有测试首次使用非凭证字段模拟旧文件，与新版字段白名单冲突，已改用虚构的合法 token 字段。首次浏览器 UI 测试的字符串求值被页面 CSP 拒绝，已改用 Playwright locator 断言，未放宽页面 CSP。上表记录修正后完整测试结果。

## 未验证项目

- 未使用真实账户重新登录、读取实际账户、提交真实 PIN 或下单。
- 未验证 Webull 当前生产页面、所有地区路由、账户类型或交易权限。
- Windows 运行与 ACL、Linux 桌面交互和其他 macOS 硬件未在本机实测。
- GitHub Actions 的 Linux / Python 多版本与浏览器任务单独执行，最终状态以 [Actions](https://github.com/nyboy2022/webull-browser-login/actions) 为准。

## English

On 2026-10-30, all 32 tests passed locally on macOS Apple Silicon with Python 3.11, including real Chromium checks using locally fulfilled mock Webull requests and the loopback UI. Installation, dependency consistency, CLI help, atomic-write failure behavior, cancellation, timeout, closed-window handling, POSIX permissions, account masking, local request protection, and explicit PIN-example interaction were checked.

No live Webull login, real account query, real PIN authorization, or order submission was performed. Production API compatibility, other regions/account types, and Windows ACL behavior remain unverified. The Actions link above reports independent Linux CI results.
