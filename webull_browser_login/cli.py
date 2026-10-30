import argparse
import json
import sys
import time
from pathlib import Path

from .accounts import list_accounts, login_client, masked_accounts
from .login import WebullLogin
from .storage import credential_status, default_path, load_credentials, login_lock


def main(argv=None):
    parser = argparse.ArgumentParser(description="Webull 人工浏览器登录 / User-driven Webull browser login")
    parser.add_argument("command", choices=("login", "status", "accounts", "serve"))
    parser.add_argument("--credentials", type=Path, default=default_path(), help="本机凭证文件 / local credentials file")
    args = parser.parse_args(argv)
    path = args.credentials.expanduser().absolute()
    try:
        if args.command == "status":
            result = credential_status(path)
        elif args.command == "accounts":
            result = masked_accounts(list_accounts(login_client(load_credentials(path))))
        else:
            with login_lock(path):
                login = WebullLogin(path)
                try:
                    if args.command == "serve":
                        from .server import serve
                        serve(login, path)
                        return 0
                    login.start()
                    print("请在独立浏览器中完成登录和 MFA；Ctrl+C 取消。", flush=True)
                    while login.thread.is_alive():
                        time.sleep(0.2)
                    result = login.status()
                finally:
                    login.shutdown()
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0 if result["state"] == "success" else 1
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except KeyboardInterrupt:
        print("已停止；未完成的登录不会覆盖原凭证。", file=sys.stderr)
        return 130
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except Exception:
        print("操作失败；详情已隐藏以保护凭证。请检查安装、文件权限和网络。", file=sys.stderr)
        return 1
