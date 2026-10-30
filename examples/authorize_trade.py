"""Explicit, one-shot PIN authorization. Never places or cancels an order."""
import argparse
import getpass
import sys
import warnings

from webull_browser_login.accounts import bind_account, list_accounts, login_client, unlock_trade
from webull_browser_login.storage import default_path, load_credentials


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--credentials", default=default_path())
    args = parser.parse_args()
    if not sys.stdin.isatty():
        print("请在交互终端运行；不接受管道或命令行 PIN。", file=sys.stderr)
        return 1
    try:
        client = login_client(load_credentials(args.credentials))
        accounts = list_accounts(client)
        for index, row in enumerate(accounts, 1):
            print(f'{index}. ****{row["id"][-4:]} ({row["region"]})')
        selected = input("账户编号 / Account number: ").strip()
        if not selected.isascii() or not selected.isdigit() or not 1 <= int(selected) <= len(accounts):
            raise RuntimeError("未选择有效账户；未提交 PIN")
        bind_account(client, accounts[int(selected) - 1]["id"])
        if input("将提交一次 PIN 授权请求，不下单。输入 AUTHORIZE 继续: ") != "AUTHORIZE":
            print("已取消；未提交 PIN。")
            return 0
        with warnings.catch_warnings():
            warnings.simplefilter("error", getpass.GetPassWarning)
            pin = getpass.getpass("交易 PIN / Trading PIN: ")
        try:
            unlock_trade(client, pin)
        finally:
            del pin
        print("交易授权成功；交易 token 仅在本进程内，退出后不保留。未下单。")
        return 0
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except (KeyboardInterrupt, EOFError):
        print("操作中止；若已提交请求，请先在 Webull 核对，勿盲目重试。", file=sys.stderr)
        return 130
    except Exception:
        print("授权未完成；详情已隐藏。未自动重试，请先检查账户状态。", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
