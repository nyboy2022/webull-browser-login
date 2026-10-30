"""Read-only account discovery and explicit account binding for webull 0.6.x."""

import hashlib
import json


def login_client(credentials):
    """Seed an in-memory client without implicit network calls or did.bin pickle I/O."""
    from webull import webull
    for key in ("access_token", "refresh_token", "did"):
        if not isinstance(credentials.get(key), str) or not credentials[key].strip():
            raise RuntimeError("缺少完整 token 或设备信息，请重新进行浏览器登录")

    class BrowserSession(webull):
        def _get_did(self, path=""):
            return credentials["did"]

    client = BrowserSession()
    client.timeout = 10
    client._browser_device_verified = True
    client._access_token = credentials["access_token"]
    client._refresh_token = credentials["refresh_token"]
    client._uuid = credentials.get("uuid", "")
    client._token_expire = credentials.get("token_expire", "")
    return client


class TradeAuthorizationError(RuntimeError):
    def __init__(self, message, reason="ambiguous"):
        self.reason = reason
        super().__init__(message)


def unlock_trade(client, pin):
    """One authorization attempt with sanitized diagnostics; never log the payload."""
    import requests
    if getattr(client, "_browser_device_verified", False) is not True:
        raise TradeAuthorizationError("缺少已验证的浏览器设备信息 did，请重新登录 Webull；未提交交易密码", "hard")
    if not isinstance(pin, str) or len(pin) != 6 or not pin.isascii() or not pin.isdigit():
        raise TradeAuthorizationError("交易 PIN 格式应为 6 位数字；未提交交易密码", "hard")
    # Match the installed library's PIN encoding and endpoint, but retain safe failure details.
    encoded = hashlib.md5(("wl_app-a&b@!423^" + pin).encode("utf-8")).hexdigest()
    try:
        response = requests.post(client._urls.trade_token(), headers=client.build_req_headers(),
                                 json={"pwd": encoded}, timeout=10, allow_redirects=False)
    except requests.RequestException:
        raise TradeAuthorizationError("Webull 交易授权请求未完成（网络或超时）；未自动重试，请先检查账户状态") from None
    details = {"http_status": response.status_code}
    try:
        payload = response.json()
    except ValueError:
        raise TradeAuthorizationError("Webull 交易授权响应不是 JSON；" + json.dumps(details)) from None
    if not isinstance(payload, dict):
        raise TradeAuthorizationError("Webull 交易授权响应格式不兼容；" + json.dumps(details))
    nested = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    tokens = {value for value in (payload.get("tradeToken"), nested.get("tradeToken"))
              if isinstance(value, str) and value.strip()}
    rejected = payload.get("success") is False or nested.get("success") is False
    if 200 <= response.status_code < 300 and not rejected and len(tokens) == 1:
        client._trade_token = next(iter(tokens))
        return
    code = payload.get("code", payload.get("errorCode", nested.get("code")))
    known_codes = {"INVALID_TOKEN", "TOKEN_EXPIRED", "INVALID_PASSWORD", "ACCOUNT_LOCKED",
                   "MFA_REQUIRED", "DEVICE_NOT_TRUSTED", "TOO_MANY_REQUESTS"}
    details.update({"trade_token_present": bool(tokens), "explicit_rejection": rejected,
                    "error_code_present": code is not None,
                    "error_category": code if isinstance(code, str) and code in known_codes else "unclassified"})
    category = code if isinstance(code, str) else None
    reason = ("hard" if category in {"INVALID_PASSWORD", "ACCOUNT_LOCKED", "MFA_REQUIRED", "DEVICE_NOT_TRUSTED", "TOO_MANY_REQUESTS"}
              else "session" if category in {"INVALID_TOKEN", "TOKEN_EXPIRED"} or response.status_code == 401
              else "ambiguous")
    raise TradeAuthorizationError("Webull 交易授权未完成，不一定是 PIN 错误；脱敏诊断：" + json.dumps(details), reason)


def parse_accounts(payload):
    if not isinstance(payload, dict) or payload.get("success") is not True:
        raise RuntimeError("Webull 未返回成功的账户列表，请检查凭证是否有效")
    rows = payload.get("data")
    if not isinstance(rows, list):
        raise RuntimeError("Webull 账户响应格式不兼容")
    accounts = []
    seen = set()
    for row in rows:
        if not isinstance(row, dict):
            raise RuntimeError("Webull 账户响应格式不兼容")
        raw_id = row.get("secAccountId")
        # The API also returns records without a trading account ID.
        if raw_id is None or (isinstance(raw_id, str) and not raw_id.strip()):
            continue
        account_id = str(raw_id)
        region = row.get("rzone")
        if not account_id.isdigit() or not isinstance(region, str) or not region.strip() or account_id in seen:
            raise RuntimeError("账户 ID 或区域信息无效，未选择任何账户")
        seen.add(account_id)
        accounts.append({"id": account_id, "region": region})
    if not accounts:
        raise RuntimeError("当前登录账号没有返回可用交易账户")
    return accounts


def list_accounts(client):
    import requests
    try:
        # Same endpoint and header builder used by the library's get_account_id.
        response = requests.get(client._urls.account_id(), headers=client.build_req_headers(),
                                timeout=10, allow_redirects=False)
        if response.status_code != 200:
            raise RuntimeError("http failure")
        payload = response.json()
    except Exception:
        raise RuntimeError("账户查询失败，可能是凭证失效、网络错误或 Webull 接口变化") from None
    return parse_accounts(payload)


def bind_account(client, account_id):
    matches = [account for account in list_accounts(client) if account["id"] == str(account_id)]
    if len(matches) != 1:
        raise RuntimeError("所选账户不属于当前登录账号，请重新查询并选择账户")
    # webull 0.6.x has no set_account_id; reproduce its verified get_account_id binding.
    client._account_id = matches[0]["id"]
    client.zone_var = matches[0]["region"]


def masked_accounts(accounts):
    return [{"account": "****" + row["id"][-4:], "region": row["region"]} for row in accounts]
