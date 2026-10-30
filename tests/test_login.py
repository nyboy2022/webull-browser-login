import json
import stat
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from webull_browser_login.login import WebullLogin, extract_credentials, save_credentials, trusted_login_url


PAIR = {"accessToken": "test-access", "refreshToken": "test-refresh",
        "uuid": "test-device", "tokenExpireTime": "test-expiry"}


class LoginTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "credentials.json"
        self.log = Mock()
        self.login = WebullLogin(self.path, self.log, timeout=0)

    def test_only_https_webull_auth_hosts(self):
        self.assertTrue(trusted_login_url("https://userapi.webull.com/api/passport/login"))
        self.assertTrue(trusted_login_url("https://user.webullbroker.com/passport/login"))
        self.assertTrue(trusted_login_url("https://u1suser.webullfintech.com/api/passport/login"))
        for url in ("http://user.webull.com/login", "https://webull.com.evil.test/login",
                    "https://evilwebull.com/login", "https://u1suser.webullfintech.com.evil.test/login",
                    "https://other.webullfintech.com/login", "http://u1suser.webullfintech.com/login"):
            self.assertFalse(trusted_login_url(url), url)

    def test_extract_pair_metadata_and_nested_response(self):
        result = extract_credentials({"data": PAIR, "password": "never-store"})
        self.assertEqual(result, {"access_token": "test-access", "refresh_token": "test-refresh",
                                  "uuid": "test-device", "token_expire": "test-expiry"})

    def test_requires_complete_nonempty_pair(self):
        for data in ({"accessToken": "test"}, {"accessToken": "test", "refreshToken": " "},
                     {"accessToken": 123, "refreshToken": "test"}, [], None):
            self.assertIsNone(extract_credentials(data))

    def test_device_header_fallback(self):
        result = extract_credentials({"accessToken": "a", "refreshToken": "b"}, "device")
        self.assertEqual(result["did"], "device")
        self.assertNotIn("uuid", result)

    def test_atomic_private_save_and_no_secret_status(self):
        self.assertTrue(self.login.accept(extract_credentials(PAIR)))
        self.assertEqual(stat.S_IMODE(self.path.stat().st_mode), 0o600)
        self.assertEqual(json.loads(self.path.read_text())["refresh_token"], "test-refresh")
        self.assertEqual(list(Path(self.directory.name).iterdir()), [self.path])
        self.assertNotIn("test-access", str(self.login.status()) + str(self.log.call_args))

    def test_cancel_preserves_existing_credentials(self):
        save_credentials(self.path, {"access_token": "old-access", "refresh_token": "old-refresh"})
        self.login.update("waiting", "waiting")
        self.login.cancel()
        self.assertFalse(self.login.accept(extract_credentials(PAIR)))
        self.assertEqual(json.loads(self.path.read_text()), {"access_token": "old-access", "refresh_token": "old-refresh"})

    def test_duplicate_login_rejected(self):
        self.login.update("opening", "opening")
        with self.assertRaises(RuntimeError):
            self.login.start()

    def fake_browser(self, url, payload, status=200):
        context = Mock()
        page = Mock()
        context.pages = [page]
        context.new_page.return_value = page
        callbacks = {}
        context.on.side_effect = lambda name, callback: callbacks.update({name: callback})
        response = Mock(url=url, status=status)
        response.json.return_value = payload
        response.request.resource_type = "fetch"
        response.request.header_value.return_value = "test-device"
        page.goto.side_effect = lambda *args, **kwargs: callbacks["response"](response)
        browser = Mock()
        browser.new_context.return_value = context
        browser.is_connected.return_value = True
        playwright = Mock()
        playwright.chromium.launch.return_value = browser
        resource = Mock()
        resource.__enter__ = Mock(return_value=playwright)
        resource.__exit__ = Mock(return_value=False)
        module = SimpleNamespace(sync_playwright=lambda: resource)
        return module, browser

    def test_full_browser_flow_saves_and_closes(self):
        module, browser = self.fake_browser("https://user.webull.com/passport/login", PAIR)
        with patch.dict("sys.modules", {"playwright.sync_api": module}):
            self.login.run()
        self.assertEqual(self.login.status()["state"], "success")
        browser.close.assert_called_once()
        self.assertTrue(self.path.exists())
        saved = json.loads(self.path.read_text())
        self.assertEqual(saved["did"], "test-device")
        self.assertEqual(saved["uuid"], PAIR["uuid"])

    def test_timeout_and_closed_window_preserve_old_pair(self):
        old = {"access_token": "old-access", "refresh_token": "old-refresh"}
        for closed in (False, True):
            save_credentials(self.path, old)
            module, browser = self.fake_browser("https://app.webull.com/passport/login", {})
            if closed:
                browser.new_context.return_value.pages = []
            with patch.dict("sys.modules", {"playwright.sync_api": module}):
                self.login.run()
            self.assertEqual(self.login.state, "cancelled" if closed else "error")
            self.assertEqual(json.loads(self.path.read_text()), old)
            browser.close.assert_called_once()

    def test_browser_write_failure_preserves_old_pair_and_hides_error(self):
        old = {"access_token": "old-access", "refresh_token": "old-refresh"}
        save_credentials(self.path, old)
        module, browser = self.fake_browser("https://app.webull.com/passport/login", PAIR)
        with patch.dict("sys.modules", {"playwright.sync_api": module}), patch(
                "webull_browser_login.storage.os.replace", side_effect=OSError("sensitive-error")):
            self.login.run()
        self.assertEqual(self.login.state, "error")
        self.assertEqual(json.loads(self.path.read_text()), old)
        self.assertNotIn("sensitive-error", str(self.login.status()))
        browser.close.assert_called_once()

    def test_current_user_api_domain_captured(self):
        module, _ = self.fake_browser("https://u1suser.webullfintech.com/api/passport/login", PAIR)
        with patch.dict("sys.modules", {"playwright.sync_api": module}):
            self.login.run()
        self.assertEqual(self.login.state, "success")
        self.assertTrue(self.path.exists())

    def test_redirect_is_not_http_error_or_parsed_as_token(self):
        response = Mock(url="https://passport.webull.com/login?secret=hidden", status=302)
        response.request.resource_type = "document"
        self.assertIsNone(self.login.observe_response(response))
        response.json.assert_not_called()
        self.assertEqual(self.login.diagnostics[-1]["result"], "redirect")
        self.assertNotIn("hidden", str(self.login.status()))

    def test_new_endpoint_and_nested_lists(self):
        module, _ = self.fake_browser("https://user.webull.com/session/verify?secret=hidden",
                                      {"payload": [{"session": PAIR}]}, 201)
        with patch.dict("sys.modules", {"playwright.sync_api": module}):
            self.login.run()
        self.assertEqual(self.login.state, "success")
        public = str(self.login.status()) + str(self.log.call_args_list)
        for secret in ("test-access", "test-refresh", "test-device", "hidden", "session/verify"):
            self.assertNotIn(secret, public)

    def test_serialized_wrapper_and_parent_metadata(self):
        result = extract_credentials({"uuid": "parent-device", "payload": json.dumps({
            "session": {"access_token": "a", "refresh_token": "b"}})})
        self.assertEqual(result["uuid"], "parent-device")

    def test_partial_and_multiple_pairs_never_combined(self):
        self.assertIsNone(extract_credentials([{"accessToken": "a"}, {"refreshToken": "b"}]))
        self.assertIsNone(extract_credentials([PAIR, {"accessToken": "other", "refreshToken": "pair"}]))

    def test_missing_device_header_does_not_discard_pair(self):
        response = Mock(url="https://user.webull.com/session/verify", status=200)
        response.request.resource_type = "xhr"
        response.json.return_value = {"accessToken": "a", "refreshToken": "b"}
        response.request.header_value.side_effect = RuntimeError("sensitive-error")
        self.assertIsNotNone(self.login.observe_response(response))
        self.assertNotIn("sensitive-error", str(self.login.status()))

    def test_foreign_or_failed_response_cannot_overwrite(self):
        for url, status in (("https://evil.test/login", 200), ("https://webull.com/login", 401)):
            module, browser = self.fake_browser(url, PAIR, status)
            with patch.dict("sys.modules", {"playwright.sync_api": module}):
                self.login.run()
            self.assertEqual(self.login.status()["state"], "error")
            self.assertFalse(self.path.exists())
            browser.close.assert_called_once()


if __name__ == "__main__":
    unittest.main()
