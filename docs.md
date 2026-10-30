# 工作原理与 Python 接入

## 为什么用浏览器

此方案复用正常网页登录流程，让用户在官方网页中完成密码、验证码与 MFA，再监听当前独立浏览器上下文中的响应。它不是密码登录接口的替代实现，也不会绕过设备验证。

Playwright 启动新浏览器进程与临时上下文，不加载个人 Chrome profile。程序监听 response 事件，仅解析可信 HTTPS 域名的 XHR/fetch 或认证路径响应；重定向及非成功 HTTP 响应不作为凭证来源。

解析器支持嵌套对象、列表和有限的 JSON 字符串包装。access 与 refresh token 必须在同一个对象中同时出现；存在多个不同 token 对时拒绝猜测。设备标识取自该响应所对应请求的 `did` 请求头，不拿 `uuid` 代替。

## 保存的字段

| 字段 | 来源与用途 |
| --- | --- |
| `access_token` | 响应 `accessToken` 或 `access_token`；用于后续接口请求 |
| `refresh_token` | 同对象 `refreshToken` 或 `refresh_token`；保留供会话接入，本工具不自动刷新 |
| `did` | 对应浏览器请求头；复用登录设备身份，不等于已通过券商设备校验 |
| `uuid` | token 对对象或祖先对象的可选元数据；不作为设备标识替代值 |
| `token_expire` | 上游 `tokenExpireTime` 或 `token_expire`；原样保留，不推断有效性 |

以下值完全虚构，仅用于解释格式。不要复制成真实凭证：

```json
{
  "access_token": "FICTIONAL_ACCESS_TOKEN",
  "refresh_token": "FICTIONAL_REFRESH_TOKEN",
  "did": "FICTIONAL_BROWSER_DEVICE",
  "uuid": "FICTIONAL_OPTIONAL_UUID",
  "token_expire": "FICTIONAL_UPSTREAM_EXPIRY"
}
```

写入先创建仅用户可读写的临时文件，flush/fsync 后原子替换旧文件。取消、超时及替换前写入失败保留旧文件。缺少 `did` 的 token 对仍可保存，但工具会明确提示重新登录，账户客户端拒绝使用。

## 在 Python 中使用

```python
from webull_browser_login.accounts import login_client, list_accounts, masked_accounts, bind_account
from webull_browser_login.storage import default_path, load_credentials

# 不打印 credentials 或原始账户响应。
client = login_client(load_credentials(default_path()))
accounts = list_accounts(client)  # 一次只读 Webull 账户列表请求
print(masked_accounts(accounts))

# 在自己的应用中先明确让用户选定账户，再核对归属：
selected_account_id = accounts[0]["id"]  # 示例索引；真实应用须由用户选择
bind_account(client, selected_account_id)
```

`login_client` 只创建内存客户端，不自动查询、刷新或进行交易授权。它使用捕获的 `did` 覆盖第三方库的设备读取方法，避免库默认读取当前目录中的 pickle `did.bin`。`bind_account` 重新查询账户所属关系并设置 `_account_id`、`zone_var`；这些是 `webull==0.6.1` 的内部接口，升级依赖前必须重新测试。

PIN 授权实现见 `webull_browser_login/accounts.py` 和独立示例。它沿用固定版本客户端的 PIN 编码及授权端点，保留经过筛选的错误类别，网络超时、响应不兼容或服务端拒绝均不重试。该实现不代表 Webull 的长期接口承诺。

## 本地网页接口

网页仅在 `127.0.0.1` 的随机端口提供：

| 方法与路径 | 用途 |
| --- | --- |
| `GET /` | 本地控制页与当前进程操作令牌 |
| `POST /api/start` | 启动一次人工登录 |
| `POST /api/cancel` | 取消当前登录 |
| `POST /api/status` | 脱敏登录状态与凭证字段存在性 |
| `POST /api/accounts` | 遮罩账户列表 |

所有请求校验 Host；POST 还要求同源 Origin、`X-Operation-Token`，且不接受请求体。无跨域访问许可、无凭证导出接口、无 PIN 接口。操作令牌只是本机网页请求保护，不是 Webull token；该服务不能作为面向其他用户的远程登录服务。

## 来源

浏览器监听、响应解析和单次授权逻辑提取自作者的 Relay Trade 项目，并移除了机器人、交易账本与运行配置依赖。依赖为 [Playwright Python](https://github.com/microsoft/playwright-python) 和 [非官方 webull Python 库](https://github.com/tedchou12/webull)；本仓库不复制这些库源码，依赖许可证分别由上游维护。当前实现依据本地固定版本源码核对，未声明已验证上游最新接口。
