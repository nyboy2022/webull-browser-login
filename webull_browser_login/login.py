"""User-driven Webull login in an isolated browser; never log credentials."""

import json
import threading
import time
from urllib.parse import urlsplit

from .storage import save_credentials


ACTIVE = {"opening", "waiting", "cancelling"}
# NewUserDomain in app.webull.com's public webquotes configuration.
USER_API_HOSTS = {"u1suser.webullfintech.com"}


def trusted_login_url(url):
    parsed = urlsplit(url)
    host = (parsed.hostname or "").lower()
    trusted = host in USER_API_HOSTS or any(host == domain or host.endswith("." + domain)
                  for domain in ("webull.com", "webullbroker.com"))
    return parsed.scheme == "https" and trusted


def inspect_payload(data, device_id=""):
    pairs = {}
    flags = {"access_present": False, "refresh_present": False, "ambiguous": False}
    budget = [250]

    def visit(node, metadata, depth):
        if depth > 8 or budget[0] <= 0:
            return
        budget[0] -= 1
        if isinstance(node, list):
            for item in node[:50]:
                visit(item, metadata, depth + 1)
        elif isinstance(node, dict):
            metadata = dict(metadata)
            for key, value in (("uuid", node.get("uuid")),
                               ("token_expire", node.get("tokenExpireTime") or node.get("token_expire"))):
                if isinstance(value, str) and value:
                    metadata[key] = value
            access = node.get("accessToken") or node.get("access_token")
            refresh = node.get("refreshToken") or node.get("refresh_token")
            has_access = isinstance(access, str) and bool(access.strip())
            has_refresh = isinstance(refresh, str) and bool(refresh.strip())
            flags["access_present"] |= has_access
            flags["refresh_present"] |= has_refresh
            # Never join tokens from different objects, responses, or sessions.
            if has_access and has_refresh:
                pairs[(access.strip(), refresh.strip())] = {
                    **metadata, "access_token": access.strip(), "refresh_token": refresh.strip()}
            for key, value in list(node.items())[:100]:
                if isinstance(value, str) and key in {"data", "result", "payload", "tokenInfo"}:
                    if len(value) < 100_000 and value.lstrip().startswith(("{", "[")):
                        try:
                            value = json.loads(value)
                        except ValueError:
                            continue
                if isinstance(value, (dict, list)):
                    visit(value, metadata, depth + 1)

    visit(data, {"did": device_id} if device_id else {}, 0)
    flags["ambiguous"] = len(pairs) > 1
    return (next(iter(pairs.values())) if len(pairs) == 1 else None), flags


def extract_credentials(data, device_id=""):
    return inspect_payload(data, device_id)[0]


class WebullLogin:
    def __init__(self, path, log=lambda message, level: None, timeout=300):
        self.path = path
        self.lock = threading.RLock()
        self.log = log
        self.timeout = timeout
        self.cancelled = threading.Event()
        self.thread = None
        self.state = "idle"
        self.message = "尚未开始登录"
        self.diagnostics = []
        self.response_count = 0

    def status(self):
        with self.lock:
            return {"state": self.state, "message": self.message,
                    "active": self.state in ACTIVE,
                    "response_count": self.response_count,
                    "diagnostics": [dict(item) for item in self.diagnostics]}

    def update(self, state, message):
        with self.lock:
            self.state, self.message = state, message

    def start(self):
        with self.lock:
            if self.state in ACTIVE or (self.thread and self.thread.is_alive()):
                raise RuntimeError("已有 Webull 登录窗口正在等待操作")
            self.cancelled.clear()
            self.diagnostics = []
            self.response_count = 0
            self.update("opening", "正在打开独立登录窗口")
            self.thread = threading.Thread(target=self.run, daemon=True)
            self.thread.start()

    def cancel(self):
        with self.lock:
            if self.state in ACTIVE:
                self.cancelled.set()
                self.update("cancelling", "正在关闭登录窗口")

    def accept(self, credentials):
        with self.lock:
            if self.cancelled.is_set():
                return False
            save_credentials(self.path, credentials)
            self.update("success", "登录凭证及设备信息已保存；尚未验证交易 API" if credentials.get("did")
                        else "token 已保存，但缺少设备信息，请重新登录；暂不能接入账户 API")
            self.log("Webull 登录凭证已在本机更新，未启动交易。", "info")
            return True

    def observe_response(self, response):
        if not trusted_login_url(response.url):
            return None
        parsed = urlsplit(response.url)
        auth_path = any(word in parsed.path.lower() for word in ("passport", "login", "auth", "token"))
        if response.request.resource_type not in {"xhr", "fetch"} and not auth_path:
            return None
        event = {"host": parsed.hostname, "status": response.status,
                 "category": "authentication" if auth_path else "other_api"}
        credentials = None
        if 300 <= response.status < 400:
            event["result"] = "redirect"
        elif not 200 <= response.status < 300:
            event["result"] = "http_error"
        else:
            try:
                data = response.json()
            except Exception:
                event["result"] = "not_json_or_unreadable"
            else:
                credentials, flags = inspect_payload(data)
                event.update(flags)
                event["result"] = "complete_pair" if credentials else "no_unique_pair"
                if credentials:
                    try:
                        device = response.request.header_value("did")
                        if isinstance(device, str) and device.strip():
                            credentials["did"] = device.strip()
                    except Exception:
                        pass
                    event["device_present"] = bool(credentials.get("did"))
        with self.lock:
            self.response_count += 1
            self.diagnostics.append(event)
            self.diagnostics = self.diagnostics[-20:]
        # Only fixed labels, host, status and presence flags enter the log.
        if auth_path or credentials or event.get("access_present") or event.get("refresh_present"):
            self.log("Webull 登录诊断: " + json.dumps(event, ensure_ascii=False), "info")
        return credentials

    def run(self):
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            self.update("error", "缺少登录组件，请安装本工具及 Playwright 浏览器")
            return
        try:
            with sync_playwright() as playwright:
                browser = None
                try:
                    try:
                        browser = playwright.chromium.launch(channel="chrome", headless=False)
                    except Exception:
                        browser = playwright.chromium.launch(headless=False)
                    context = browser.new_context(accept_downloads=False)
                    captured = []

                    def response_received(response):
                        if captured or self.cancelled.is_set():
                            return
                        try:
                            credentials = self.observe_response(response)
                            if credentials:
                                captured.append(credentials)
                        except Exception:
                            self.log("Webull 登录诊断: 响应处理失败（详情已隐藏）", "info")

                    context.on("response", response_received)
                    page = context.new_page()
                    self.update("waiting", "请在 Webull 窗口完成登录和验证码（5 分钟内）")
                    page.goto("https://app.webull.com/", wait_until="domcontentloaded", timeout=45000)
                    deadline = time.monotonic() + self.timeout
                    while not captured and not self.cancelled.is_set():
                        if not browser.is_connected() or not context.pages:
                            self.update("cancelled", "登录窗口已关闭，原凭证未修改")
                            return
                        if time.monotonic() >= deadline:
                            self.update("error", "未收到完整登录凭证，已超时；原凭证未修改")
                            return
                        context.pages[0].wait_for_timeout(200)
                    if self.cancelled.is_set():
                        self.update("cancelled", "已取消登录，原凭证未修改")
                    elif captured:
                        if not self.accept(captured[0]):
                            self.update("cancelled", "已取消登录，原凭证未修改")
                finally:
                    if browser:
                        try:
                            browser.close()
                        except Exception:
                            pass
        except Exception:
            # Browser exceptions may contain URLs or response details: never expose them.
            if self.cancelled.is_set():
                self.update("cancelled", "已取消登录，原凭证未修改")
            elif self.state != "success":
                self.update("error", "登录窗口无法继续。请检查 Chrome 安装与网络，或重试登录。")

    def shutdown(self):
        self.cancel()
        if self.thread:
            self.thread.join(timeout=50)
