"""Opt-in real Chromium checks using locally fulfilled pages and mock API responses only."""
import contextlib
import json
import io
import os
from pathlib import Path
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from webull_browser_login.cli import main
from webull_browser_login.login import WebullLogin
from webull_browser_login.server import make_server
from webull_browser_login.storage import load_credentials


@unittest.skipUnless(os.environ.get("RUN_BROWSER_TESTS") == "1", "Set RUN_BROWSER_TESTS=1 after installing Chromium")
class BrowserTests(unittest.TestCase):
    def test_real_browser_capture_with_zero_external_requests(self):
        from playwright.sync_api import sync_playwright
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "credentials.json"
            seen = []

            @contextlib.contextmanager
            def local_playwright():
                with sync_playwright() as engine:
                    def launch(**kwargs):
                        browser = engine.chromium.launch(headless=True)
                        def setup(context):
                            def route(request_route):
                                request = request_route.request
                                seen.append(request.url)
                                if request.url == "https://app.webull.com/":
                                    request_route.fulfill(content_type="text/html", body='''
                                        <h1>Local mock sign-in</h1><button id="login">Mock login</button>
                                        <script>document.querySelector('button').onclick=()=>fetch('/api/passport/login',
                                        {headers:{did:'fictional-browser-device'}});
                                        setTimeout(()=>document.querySelector('button').click(),100);</script>''')
                                elif request.url == "https://app.webull.com/api/passport/login":
                                    request_route.fulfill(content_type="application/json", body=json.dumps({
                                        "accessToken": "fictional-access", "refreshToken": "fictional-refresh"}))
                                else:
                                    request_route.abort()
                            context.route("**/*", route)
                        browser.on("context", setup)
                        return browser
                    yield SimpleNamespace(chromium=SimpleNamespace(launch=launch))

            output = io.StringIO()
            with patch("playwright.sync_api.sync_playwright", local_playwright), contextlib.redirect_stdout(output):
                self.assertEqual(main(["login", "--credentials", str(path)]), 0)
            self.assertIn('"state": "success"', output.getvalue())
            self.assertEqual(load_credentials(path)["did"], "fictional-browser-device")
            self.assertEqual(len(seen), 2)

    def test_real_local_ui_start_cancel_and_masked_accounts(self):
        from playwright.sync_api import sync_playwright, expect
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "credentials.json"
            login = WebullLogin(path)
            with make_server(login, path) as server:
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()
                try:
                    with sync_playwright() as engine:
                        browser = engine.chromium.launch(headless=True)
                        page = browser.new_page()
                        errors = []
                        page.on("pageerror", lambda error: errors.append(str(error)))
                        page.goto(server.origin)
                        with patch.object(login, "start", side_effect=lambda: login.update("waiting", "mock waiting")):
                            page.locator("#start").click()
                            expect(page.locator("#cancel")).to_be_enabled()
                        page.locator("#cancel").click()
                        expect(page.locator("#message")).to_contain_text("cancelling")
                        login.cancelled.clear()
                        login.accept({"access_token": "fictional-access", "refresh_token": "fictional-refresh", "did": "fictional-device"})
                        expect(page.locator("#accounts")).to_be_enabled()
                        with patch("webull_browser_login.server.list_accounts", return_value=[{"id": "10000000001234", "region": "mock"}]):
                            page.locator("#accounts").click()
                            expect(page.locator("#message")).to_contain_text("****1234")
                        self.assertNotIn("fictional-access", page.locator("body").inner_text())
                        page.set_viewport_size({"width": 390, "height": 844})
                        page.screenshot(path="/tmp/webull-browser-login-ui.png", full_page=True)
                        self.assertEqual(errors, [])
                        browser.close()
                finally:
                    server.shutdown()
                    thread.join()
