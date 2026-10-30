# Webull Browser Login

Sign in to Webull manually in an isolated browser, save your own session locally, and connect it to the unofficial Python client.

[中文文档](README.md) · [Implementation details (Chinese)](docs.md) · [MIT License](LICENSE)

This project is **unofficial and unaffiliated with Webull**. It does not use Webull's official OpenAPI. You complete passwords, CAPTCHA, and MFA yourself. There is no order placement, cancellation, trading strategy, or automated trading code.

## What it does

- Opens a separate Chrome / Chromium process with a fresh browser context, without loading your existing profile.
- Observes trusted HTTPS responses and extracts an access/refresh token pair from the same JSON object, plus the corresponding request's `did` device header.
- Saves credentials privately and atomically on your computer.
- Provides CLI commands and a loopback web UI for login, cancellation, sanitized status, and masked read-only account discovery.
- Provides a separate, explicit, one-shot trading PIN authorization example. It never places an order or persists the PIN / trading token.

Capturing tokens, successfully querying accounts, and receiving a trading authorization token are three distinct outcomes. None proves that an order can be submitted or filled.

## Install and run

Python 3.9+ and a graphical desktop are required; Python 3.11 is recommended. On macOS / Linux:

```bash
git clone https://github.com/nyboy2022/webull-browser-login.git
cd webull-browser-login
python3 -m venv .venv
source .venv/bin/activate
python -m pip install .
python -m playwright install chromium

webull-browser-login login
webull-browser-login status
webull-browser-login accounts
```

The CLI opens Chrome first and falls back to installed Playwright Chromium. Complete login and MFA in that window. A unique complete token pair is saved and the window closes. If `did` is missing, sign in again: account API access is blocked without it.

`status` only checks local field presence, without contacting Webull or validating expiry. `accounts` queries the account list, printing only masked account IDs and regions. Neither requires a trading PIN.

Ctrl+C, closing the browser, or timing out preserves existing credentials if the new login has not completed. The five-minute capture deadline starts after initial navigation, which has its own 45-second timeout.

For the local web UI:

```bash
webull-browser-login serve
```

Open the printed `http://127.0.0.1:<random-port>/` URL if it does not open automatically. Use Sign in, Cancel, and Check accounts. Stop the server with Ctrl+C. The UI checks Host, Origin, and a per-process operation token. It never receives session tokens, full account IDs, or a PIN. Do not proxy or forward it to a network. UI labels include English; detailed diagnostics are currently Chinese.

Every CLI command accepts a custom path:

```bash
webull-browser-login login --credentials /private/path/credentials.json
webull-browser-login accounts --credentials /private/path/credentials.json
```

On Windows, virtual environment setup uses `py -m venv .venv` and `.venv\Scripts\Activate.ps1`. Windows operation and filesystem ACL protection have not been tested.

## Optional: one-shot trading authorization

From the cloned repository root, with the virtual environment active:

```bash
python examples/authorize_trade.py
# Optional custom file:
python examples/authorize_trade.py --credentials /private/path/credentials.json
```

This example lists masked accounts, asks you to select an account number, checks account ownership again, and requires typing `AUTHORIZE` before a hidden six-digit PIN prompt. **It sends one real PIN authorization request to Webull.** It does not submit or cancel orders, save the PIN, print the trading token, or retry automatically.

A timeout may mean the request reached Webull. Check your account before trying again. PINs are not accepted through command-line arguments or pipes. Python cannot guarantee secure erasure of strings from process memory; the client exists only until the example exits.

## How it works

1. Playwright creates an isolated browser context and listens for response events.
2. Only HTTPS responses from `webull.com`, `webullbroker.com`, their subdomains, or explicitly listed `u1suser.webullfintech.com` are eligible. The entire `webullfintech.com` domain is not trusted automatically.
3. A bounded parser handles nested objects, lists, and selected JSON-serialized wrappers. It never joins partial tokens across objects or responses and rejects multiple distinct pairs.
4. The `did` value comes from that response's request header. Optional `uuid` metadata is not a substitute for a browser device ID. Upstream expiry metadata is preserved without interpreting its format.
5. An owner-only temporary file is flushed and fsynced, then atomically replaces the credential file.
6. A `webull==0.6.1` client is seeded in memory with the captured device identity, avoiding the library's default `did.bin` pickle I/O and implicit account requests.

The dependency's internal attributes and endpoints may change. There is no automatic token refresh, keepalive, or background login. Sign in again if the session expires.

## Storage and privacy

| Platform | Default path |
| --- | --- |
| macOS | `~/Library/Application Support/WebullBrowserLogin/credentials.json` |
| Linux | `$XDG_DATA_HOME/webull-browser-login/credentials.json`, defaulting to `~/.local/share/webull-browser-login/credentials.json` |
| Windows | `%LOCALAPPDATA%\WebullBrowserLogin\credentials.json` |

Credentials are **plaintext JSON**, not an encrypted vault. On POSIX systems, the newly created final directory uses mode `0700` and credential files use `0600`. Existing custom parent directories are not chmodded. On Windows, verify user ACLs yourself. Keychain support from the original application is not included.

Only allowlisted credential fields are saved. Diagnostics contain fixed labels, hosts, HTTP statuses, and presence flags, not tokens or raw responses. The tool does not read password form values; the official login page and browser still process the password you enter normally. No credentials are sent to the author or analytics services. Login, account queries, and explicitly requested authorization communicate with Webull; installation also downloads dependencies and browser binaries.

Never share real session files, account responses, or private screenshots. `.gitignore` is a convenience, not a security boundary. Deleting a local file does not revoke the server-side session.

Only one login / web-server process may use a given credential path. After a crash, confirm the process has exited before removing the adjacent `.lock` file. This lock does not coordinate other software: stop external programs that update the same session.

## Python integration

```python
from webull_browser_login.storage import default_path, load_credentials
from webull_browser_login.accounts import login_client, list_accounts, masked_accounts

client = login_client(load_credentials(default_path()))  # no implicit network call
accounts = list_accounts(client)                         # read-only request
print(masked_accounts(accounts))
```

Do not print the credentials or raw client/account objects. `bind_account(client, selected_account_id)` rechecks ownership and binds the account explicitly. Use a user-selected account, not an assumed first account. See the standalone authorization example for numbered selection.

## Tests and limits

```bash
python -m unittest discover -s tests -v
RUN_BROWSER_TESTS=1 python -m unittest discover -s tests -p test_browser.py -v
```

Unit tests use fictional credentials and mocked account / authorization APIs. Browser checks use real Chromium with locally fulfilled mock Webull pages, without external Webull requests, and the loopback UI. They do not read private credentials or send a real PIN. CI runs Linux unit tests on Python 3.9 / 3.11 / 3.13 plus Chromium checks.

See [validation record](VALIDATION.md) for actual execution results. This release has not been verified through a real account login, real PIN authorization, or order submission. Other regions and account types are unverified; changing pages, routes, or device checks can break this unofficial method.

## Sources

The login parser and authorization adapter were extracted from the author's Relay Trade project with trading infrastructure and private configuration removed. Dependencies are [Playwright Python](https://github.com/microsoft/playwright-python) and the [unofficial webull Python library](https://github.com/tedchou12/webull). Their licenses remain with their upstream projects; their source is not vendored here. Implementation was checked against the locally installed pinned library, not a claim about current upstream API compatibility.
