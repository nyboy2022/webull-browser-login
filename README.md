# Webull Browser Login

通过独立浏览器人工登录 Webull，将自己的会话凭证保存到本机，并在 Python 中接入现有非官方 Webull 客户端。

[English documentation](README.en.md) · [工作原理与 Python 接入](docs.md) · [MIT License](LICENSE)

**这是非官方工具，与 Webull 无隶属关系，不使用 Webull 官方 OpenAPI。** 需要用户亲自完成登录和 MFA，不绕过验证码或安全检查。不包含下单、撤单、交易机器人或投资策略。

## 能做什么

| 功能 | 说明 |
| --- | --- |
| 浏览器登录 | 独立 Chrome / Chromium 窗口，不使用已有浏览器资料 |
| 保存会话 | 提取同一响应对象的 access/refresh token 对，以及对应请求的设备标识 `did` |
| 本地网页 | 登录、取消、查看脱敏状态、查询遮罩账户列表 |
| 命令行 | 登录、查看本地字段状态、只读查询账户 |
| Python 接入 | 创建内存中的非官方客户端，显式核对并绑定账户 |
| 可选 PIN 示例 | 人工运行一次交易授权，检验授权响应；不下单、不保存 PIN 或交易 token |

登录成功只表示收到了 token；账户查询成功才表示该会话能读取账户列表；PIN 授权成功也不证明任何订单能够提交或成交。会话有效期、地区与账户权限由 Webull 决定。

## 安装

建议 Python 3.11；支持 Python 3.9 及以上。需要图形桌面和网络。以下命令适用于 macOS / Linux：

```bash
git clone https://github.com/nyboy2022/webull-browser-login.git
cd webull-browser-login
python3 -m venv .venv
source .venv/bin/activate
python -m pip install .
python -m playwright install chromium
```

已有 Google Chrome 时优先打开 Chrome；失败后尝试已安装的 Playwright Chromium。Windows 可以使用 `py -m venv .venv` 与 `.venv\Scripts\Activate.ps1`，但 Windows 实际运行与 ACL 保护尚未验证。

## 方法一：命令行

```bash
webull-browser-login login
webull-browser-login status
webull-browser-login accounts
```

1. `login` 打开独立浏览器；在官方页面中亲自登录并完成验证码/MFA。
2. 收到完整 token 对后保存到本机并关闭窗口。没有设备信息时会提示重新登录，账户接入被阻止。
3. `status` 只检查文件中必要字段是否存在，不联网、不验证有效期、不打印凭证。
4. `accounts` 进行只读账户查询，仅显示遮罩账号和区域，不使用交易 PIN。

Ctrl+C、关闭登录窗口或五分钟超时会中止未完成的登录，原凭证保持不变。计时从初始页面导航完成后开始，导航本身最多等待 45 秒。

所有命令都支持指定独立凭证文件：

```bash
webull-browser-login login --credentials /private/path/credentials.json
webull-browser-login accounts --credentials /private/path/credentials.json
```

请对同一会话始终使用同一个路径，避免和其他程序同时更新该文件。

## 方法二：本地网页

```bash
webull-browser-login serve
```

命令自动打开控制页，也会打印 `http://127.0.0.1:<随机端口>/`。点击“登录”，在另开的 Webull 窗口完成操作；回到控制页查询状态和账户。终端 Ctrl+C 关闭服务。

网页服务仅监听本机回环地址，校验 Host、Origin 和操作令牌。页面不接收 token、完整账户 ID 或 PIN；不要通过反向代理、端口转发或公网暴露该服务。

## 可选：单次交易 PIN 授权示例

在克隆的仓库根目录、已激活虚拟环境的交互终端中运行：

```bash
python examples/authorize_trade.py
# 自定义凭证路径：
python examples/authorize_trade.py --credentials /private/path/credentials.json
```

程序读取账户列表，让你选择编号，重新核对账户归属，再要求输入 `AUTHORIZE` 和隐藏输入的六位交易 PIN。**这一步会向 Webull 发送一次真实授权请求。** PIN 与返回的交易 token 不写入文件、不回显；程序没有下单或撤单代码，也不自动重试。请求超时不代表 PIN 错误或未被接收，应先在 Webull 核对。

程序不接受命令行或管道 PIN，避免进入 shell 历史。Python 无法保证从进程内存中安全擦除字符串；退出进程后不继续保留授权客户端。

## 凭证文件与隐私

默认路径：

| 系统 | 位置 |
| --- | --- |
| macOS | `~/Library/Application Support/WebullBrowserLogin/credentials.json` |
| Linux | `$XDG_DATA_HOME/webull-browser-login/credentials.json`，默认 `~/.local/share/webull-browser-login/credentials.json` |
| Windows | `%LOCALAPPDATA%\WebullBrowserLogin\credentials.json` |

文件是**明文 JSON，不是加密保险库**。POSIX 系统中新建最终目录使用 `0700`，临时文件与替换后的凭证使用 `0600`。自定义路径不会修改已有父目录的权限；Windows 需要自行核对账户 ACL。可选 macOS 钥匙串功能没有从原应用移植。

只有规定字段会保存；日志仅记录域名、HTTP 状态、固定分类和字段存在性。不采集登录表单密码，不读取已有 Chrome profile，不导出 HAR、完整请求头或原始响应；登录页面和浏览器自身仍会正常处理你输入的密码。工具不把凭证发送给作者或第三方服务器；登录、只读查询和显式 PIN 授权与 Webull 通信，安装依赖另需访问包和浏览器下载服务。

`.gitignore` 只是辅助保护，**不要提交或分享真实凭证、截图、账户响应及诊断中的额外私人信息**。泄漏后应在 Webull 官方渠道处理会话与账户安全；仅删除本地文件不会注销服务器会话。

## 原理与限制

登录监听 → 可信 HTTPS 域名筛选 → 在同一个 JSON 对象内提取 token 对 → 从对应请求读取 `did` → 原子保存 → 显式只读验证。详见 [原理、字段及接入示例](docs.md)。

不会把不同对象或响应中的 token 拼成一组；多组不同凭证会被拒绝。响应解析有深度与节点数量限制。登录成功不保证设备受信任，`token_expire` 仅保留上游元数据，不保证其格式和有效性。

不实现自动刷新、后台保活或自动重登。会话失效时重新人工登录。只允许一个本工具的登录/网页进程使用同一凭证路径；异常崩溃后若 `.lock` 残留，先确认相关进程退出，再删除该路径旁的 `.lock` 文件。该锁不能约束其他软件，使用前应停止会更新同一会话的外部程序。

Webull 页面、接口、地区路由或验证要求变化都可能使方案失效；当前可信域名包括 `webull.com`、`webullbroker.com` 的 HTTPS 子域及明确列出的 `u1suser.webullfintech.com`，不会自动信任整个 `webullfintech.com`。不保证美国以外地区、所有账户或全部交易接口适用。

## 测试与验证范围

```bash
python -m unittest discover -s tests -v
RUN_BROWSER_TESTS=1 python -m unittest discover -s tests -p test_browser.py -v
```

普通测试使用虚构凭证和模拟账户/授权响应。浏览器测试使用真实 Chromium 与本地构造页面，拦截并本地满足所有模拟 Webull 请求，不访问真实 Webull；本地网页测试只访问回环服务。测试不会读取真实凭证或发送真实 PIN。

GitHub Actions 配置 Python 3.9 / 3.11 / 3.13 的 Linux 单元测试，以及 Chromium 浏览器测试。实际执行结果与限制见 [验证记录](VALIDATION.md)。没有通过真实账户登录、PIN 授权或下单来验证本次发布；未验证平台不能视为已支持实测。
