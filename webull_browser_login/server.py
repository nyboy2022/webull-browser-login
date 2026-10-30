"""Loopback-only UI. No account IDs or session tokens are sent to the page."""
import json
import secrets
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .accounts import list_accounts, login_client, masked_accounts
from .storage import credential_status, load_credentials


class LocalServer(ThreadingHTTPServer):
    daemon_threads = True
    block_on_close = False


def make_server(login, path):
    token = secrets.token_urlsafe(32)
    html = Path(__file__).with_name("index.html").read_text(encoding="utf-8").replace("__TOKEN__", token)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def reply(self, code, data, content_type="application/json; charset=utf-8"):
            raw = data.encode() if isinstance(data, str) else json.dumps(data, ensure_ascii=False).encode()
            self.send_response(code)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(raw)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", "default-src 'none'; script-src 'nonce-" + token + "'; style-src 'nonce-" + token + "'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'")
            self.send_header("Referrer-Policy", "no-referrer")
            self.end_headers()
            self.wfile.write(raw)

        def trusted_host(self):
            return self.headers.get("Host") == self.server.authority

        def do_GET(self):
            if not self.trusted_host():
                return self.reply(403, {"error": "Invalid Host"})
            if self.path != "/":
                return self.reply(404, {"error": "Not found"})
            self.reply(200, html, "text/html; charset=utf-8")

        def do_POST(self):
            if (not self.trusted_host() or self.headers.get("Origin") != self.server.origin
                    or not secrets.compare_digest(self.headers.get("X-Operation-Token", "").encode(), token.encode())):
                return self.reply(403, {"error": "Invalid local request"})
            if self.headers.get("Content-Length", "0") != "0" or self.headers.get("Transfer-Encoding"):
                return self.reply(400, {"error": "Request body not accepted"})
            try:
                if self.path == "/api/start":
                    login.start()
                    result = login.status()
                elif self.path == "/api/cancel":
                    login.cancel()
                    result = login.status()
                elif self.path == "/api/status":
                    result = {"login": login.status(), "credentials": credential_status(path)}
                elif self.path == "/api/accounts":
                    with login.lock:
                        if login.status()["active"]:
                            raise RuntimeError("请先完成或取消登录，再查询账户")
                        result = masked_accounts(list_accounts(login_client(load_credentials(path))))
                else:
                    return self.reply(404, {"error": "Not found"})
                self.reply(200, result)
            except RuntimeError as exc:
                self.reply(409, {"error": str(exc)})
            except Exception:
                self.reply(500, {"error": "操作失败，详情已隐藏；请检查安装、凭证文件与网络"})

    server = LocalServer(("127.0.0.1", 0), Handler)
    server.authority = "127.0.0.1:" + str(server.server_port)
    server.origin = "http://" + server.authority
    return server


def serve(login, path):
    with make_server(login, path) as server:
        print("本地控制页 / Local UI: " + server.origin + "/", flush=True)
        print("Ctrl+C 关闭。PIN 授权仅通过独立终端示例运行。", flush=True)
        webbrowser.open(server.origin + "/")
        server.serve_forever(poll_interval=0.2)
