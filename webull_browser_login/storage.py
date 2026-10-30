"""Private, atomic JSON storage; never expose file contents in errors."""
import json
import os
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path

FIELDS = ("access_token", "refresh_token", "did", "uuid", "token_expire")


def default_path():
    if sys.platform == "darwin":
        return Path.home() / "Library/Application Support/WebullBrowserLogin/credentials.json"
    if sys.platform == "win32":
        return Path(os.environ.get("LOCALAPPDATA", Path.home())) / "WebullBrowserLogin/credentials.json"
    return Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share")) / "webull-browser-login/credentials.json"


def prepare_directory(path):
    # Only set permissions on directories created here, never chmod a user-supplied parent.
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)


def save_credentials(path, credentials):
    path = Path(path).expanduser()
    prepare_directory(path)
    fd, temporary = tempfile.mkstemp(prefix=".credentials-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump({key: credentials[key] for key in FIELDS if key in credentials}, stream,
                      ensure_ascii=False, indent=2, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def load_credentials(path):
    try:
        data = json.loads(Path(path).expanduser().read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError()
        return {key: data[key] for key in FIELDS if isinstance(data.get(key), str)}
    except (OSError, ValueError):
        raise RuntimeError("凭证文件不存在、无法读取或格式无效，请先登录") from None


def credential_status(path):
    if not Path(path).exists():
        return {"saved": False, "fields": {}, "device_ready": False}
    data = load_credentials(path)
    return {"saved": True, "fields": {key: bool(data.get(key, "").strip()) for key in FIELDS},
            "device_ready": all(bool(data.get(key, "").strip()) for key in FIELDS[:3])}


@contextmanager
def login_lock(path):
    path = Path(path)
    prepare_directory(path)
    lock = path.with_name(path.name + ".lock")
    try:
        fd = os.open(lock, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        raise RuntimeError("另一个登录程序正在使用此凭证文件；若进程已退出，请手动删除对应 .lock 文件") from None
    try:
        os.close(fd)
        yield
    finally:
        lock.unlink()
