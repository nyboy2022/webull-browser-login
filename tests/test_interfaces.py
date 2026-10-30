import contextlib
import http.client
import io
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

import requests

from webull_browser_login.accounts import (TradeAuthorizationError, bind_account, list_accounts,
                                         login_client, masked_accounts, parse_accounts, unlock_trade)
from webull_browser_login.cli import main
from webull_browser_login.login import WebullLogin
from webull_browser_login.server import make_server
from webull_browser_login.storage import credential_status, load_credentials, login_lock, save_credentials

PAIR = {"access_token": "fictional-access", "refresh_token": "fictional-refresh", "did": "fictional-device"}
PAYLOAD = {"success": True, "data": [{"secAccountId": "10000000001234", "rzone": "fictional-zone"}]}


class StorageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "private" / "credentials.json"

    def test_atomic_failure_keeps_old_file_and_removes_temporary(self):
        save_credentials(self.path, PAIR)
        with patch("webull_browser_login.storage.os.replace", side_effect=OSError("secret")):
            with self.assertRaises(OSError):
                save_credentials(self.path, {**PAIR, "access_token": "new"})
        self.assertEqual(load_credentials(self.path), PAIR)
        self.assertEqual(list(self.path.parent.iterdir()), [self.path])
        if os.name == "posix":
            self.assertEqual(self.path.parent.stat().st_mode & 0o777, 0o700)
            self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)

    def test_allowlisted_storage_and_safe_status(self):
        save_credentials(self.path, {**PAIR, "password": "fictional-password"})
        self.assertNotIn("password", json.loads(self.path.read_text()))
        state = credential_status(self.path)
        self.assertTrue(state["device_ready"])
        self.assertNotIn("fictional", str(state))

    def test_exclusive_lock(self):
        with login_lock(self.path):
            with self.assertRaises(RuntimeError):
                with login_lock(self.path):
                    self.fail("second writer")
        self.assertFalse(self.path.with_name("credentials.json.lock").exists())

    def test_cli_status_and_readonly_accounts_mask_identifiers(self):
        save_credentials(self.path, PAIR)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(main(["status", "--credentials", str(self.path)]), 0)
        self.assertNotIn("fictional", out.getvalue())
        with patch("webull_browser_login.cli.list_accounts", return_value=parse_accounts(PAYLOAD)), contextlib.redirect_stdout(out):
            self.assertEqual(main(["accounts", "--credentials", str(self.path)]), 0)
        self.assertNotIn("10000000001234", out.getvalue())
        self.assertIn("****1234", out.getvalue())


class AccountTests(unittest.TestCase):
    def test_no_network_or_pickle_during_client_construction(self):
        with patch("requests.sessions.Session.request", side_effect=AssertionError("network")), patch("builtins.open", side_effect=AssertionError("file I/O")):
            client = login_client(PAIR)
        self.assertEqual(client.build_req_headers()["did"], PAIR["did"])
        self.assertEqual(client._access_token, PAIR["access_token"])
        with self.assertRaises(RuntimeError):
            login_client({"access_token": "a", "refresh_token": "b"})

    def test_parse_and_bind(self):
        rows = parse_accounts(PAYLOAD)
        self.assertEqual(masked_accounts(rows)[0]["account"], "****1234")
        client = login_client(PAIR)
        with patch("webull_browser_login.accounts.list_accounts", return_value=rows):
            bind_account(client, rows[0]["id"])
            self.assertEqual(client.zone_var, rows[0]["region"])
            with self.assertRaises(RuntimeError):
                bind_account(client, "9999")
        for bad in ({}, {"success": True, "data": []}, {"success": True, "data": PAYLOAD["data"] * 2}):
            with self.assertRaises(RuntimeError):
                parse_accounts(bad)

    def test_account_query_no_redirect_and_sanitized_failure(self):
        client = login_client(PAIR)
        with patch("requests.get", return_value=Mock(status_code=200, json=lambda: PAYLOAD)) as request:
            self.assertEqual(list_accounts(client), parse_accounts(PAYLOAD))
            self.assertFalse(request.call_args.kwargs["allow_redirects"])
        with patch("requests.get", side_effect=requests.Timeout("secret")):
            with self.assertRaisesRegex(RuntimeError, "账户查询失败") as error:
                list_accounts(client)
            self.assertNotIn("secret", str(error.exception))

    def test_pin_validation_authorization_and_failure_classification(self):
        client = login_client(PAIR)
        with patch("requests.post") as post:
            for pin in ("", "123", "１２３４５６"):
                with self.assertRaises(TradeAuthorizationError):
                    unlock_trade(client, pin)
            post.assert_not_called()
        with patch("requests.post", return_value=Mock(status_code=200, json=lambda: {"tradeToken": "fictional-trade"})) as post:
            unlock_trade(client, "123456")
            post.assert_called_once()
            self.assertEqual(client._trade_token, "fictional-trade")
            self.assertNotIn("123456", str(post.call_args))
        for code, reason in (("INVALID_PASSWORD", "hard"), ("TOKEN_EXPIRED", "session"), ("secret", "ambiguous")):
            with patch("requests.post", return_value=Mock(status_code=400, json=lambda: {"code": code})) as post:
                with self.assertRaises(TradeAuthorizationError) as error:
                    unlock_trade(client, "123456")
                self.assertEqual(error.exception.reason, reason)
                self.assertNotIn("secret", str(error.exception))
                post.assert_called_once()
        with patch("requests.post", side_effect=requests.Timeout("secret")) as post:
            with self.assertRaises(TradeAuthorizationError):
                unlock_trade(client, "123456")
            post.assert_called_once()


class AuthorizationExampleTests(unittest.TestCase):
    def setUp(self):
        spec = importlib.util.spec_from_file_location("authorize_example", Path(__file__).resolve().parents[1] / "examples/authorize_trade.py")
        self.example = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.example)

    def test_noninteractive_terminal_never_reads_credentials(self):
        with patch("sys.argv", ["example"]), patch("sys.stdin.isatty", return_value=False), patch.object(
                self.example, "load_credentials") as load, contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(self.example.main(), 1)
            load.assert_not_called()

    def test_explicit_choice_and_confirmation_make_one_authorization_attempt(self):
        for confirmation in ("CANCEL", "AUTHORIZE"):
            output = io.StringIO()
            with patch("sys.argv", ["example"]), patch("sys.stdin.isatty", return_value=True), patch.object(
                    self.example, "load_credentials", return_value=PAIR), patch.object(
                    self.example, "login_client", return_value=Mock()), patch.object(
                    self.example, "list_accounts", return_value=parse_accounts(PAYLOAD)), patch.object(
                    self.example, "bind_account") as bind, patch("builtins.input", side_effect=["1", confirmation]), patch.object(
                    self.example.getpass, "getpass", return_value="123456") as prompt, patch.object(
                    self.example, "unlock_trade") as unlock, contextlib.redirect_stdout(output):
                self.assertEqual(self.example.main(), 0)
                bind.assert_called_once()
                if confirmation == "AUTHORIZE":
                    unlock.assert_called_once()
                else:
                    prompt.assert_not_called()
                    unlock.assert_not_called()
                self.assertNotIn("123456", output.getvalue())
                self.assertNotIn("10000000001234", output.getvalue())


class ServerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "credentials.json"
        save_credentials(self.path, PAIR)
        self.login = WebullLogin(self.path)
        self.server = make_server(self.login, self.path)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.stop)
        self.token = self.request("GET", "/")[1].split("const token = '")[1].split("'")[0]

    def stop(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()

    def request(self, method, url, headers=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=5)
        connection.request(method, url, headers=headers or {})
        response = connection.getresponse()
        result = response.status, response.read().decode()
        connection.close()
        return result

    def headers(self):
        return {"Origin": self.server.origin, "X-Operation-Token": self.token}

    def test_rejects_foreign_host_origin_missing_or_invalid_token(self):
        for headers in ({}, {**self.headers(), "Origin": "https://evil.test"},
                        {**self.headers(), "Host": "evil.test"},
                        {**self.headers(), "X-Operation-Token": "bad"}):
            self.assertEqual(self.request("POST", "/api/start", headers)[0], 403)
        self.assertEqual(self.request("GET", "/", {"Host": "evil.test"})[0], 403)

    def test_status_never_discloses_credentials_and_accounts_masked(self):
        status, body = self.request("POST", "/api/status", self.headers())
        self.assertEqual(status, 200)
        self.assertNotIn("fictional", body)
        with patch("webull_browser_login.server.list_accounts", return_value=parse_accounts(PAYLOAD)):
            status, body = self.request("POST", "/api/accounts", self.headers())
        self.assertEqual(status, 200)
        self.assertIn("****1234", body)
        self.assertNotIn("10000000001234", body)
        self.login.update("waiting", "waiting")
        self.assertEqual(self.request("POST", "/api/accounts", self.headers())[0], 409)

    def test_start_and_cancel(self):
        with patch.object(self.login, "start") as start:
            self.assertEqual(self.request("POST", "/api/start", self.headers())[0], 200)
            start.assert_called_once()
        self.login.update("waiting", "waiting")
        self.assertEqual(self.request("POST", "/api/cancel", self.headers())[0], 200)
        self.assertTrue(self.login.cancelled.is_set())


if __name__ == "__main__":
    unittest.main()
