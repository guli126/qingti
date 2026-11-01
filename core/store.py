"""配置文件、密钥加密、历史记录。

数据目录优先用 %LOCALAPPDATA%\\轻提，取不到就退回脚本同级的 data/。
密钥用 Windows DPAPI 加密（作用域是当前用户），换机器/换账号解不开时
会返回空串，由界面提示「请重填」，而不是报「密钥丢了」。
"""

import base64
import copy
import json
import os
import sys
import threading
import time
import uuid

APP_NAME = "轻提"
_lock = threading.Lock()


# ---------------------------------------------------------------- 路径

def data_dir() -> str:
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    d = os.path.join(base, APP_NAME)
    try:
        os.makedirs(d, exist_ok=True)
        return d
    except OSError:
        d = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data")
        os.makedirs(d, exist_ok=True)
        return d


def config_path() -> str:
    return os.path.join(data_dir(), "config.json")


def history_path() -> str:
    return os.path.join(data_dir(), "history.json")


# ---------------------------------------------------------------- DPAPI

if sys.platform == "win32":
    import ctypes
    from ctypes import wintypes

    class _BLOB(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD),
                    ("pbData", ctypes.POINTER(ctypes.c_char))]

    class _GUID(ctypes.Structure):
        _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD),
                    ("Data3", wintypes.WORD), ("Data4", ctypes.c_byte * 8)]

    class _PROMPT(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.DWORD), ("hwndParent", wintypes.HWND),
                    ("pszCaption", wintypes.LPCWSTR), ("pszMessage", wintypes.LPCWSTR)]

    _crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    def _blob(data: bytes) -> _BLOB:
        buf = ctypes.create_string_buffer(data, len(data))
        return _BLOB(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))

    def _dpapi(data: bytes, decrypt: bool) -> bytes:
        blob_in = _blob(data)
        blob_out = _BLOB()
        if decrypt:
            ok = _crypt32.CryptUnprotectData(
                ctypes.byref(blob_in), None, None, None, None, 0x1,
                ctypes.byref(blob_out))
        else:
            ok = _crypt32.CryptProtectData(
                ctypes.byref(blob_in), "qingti", None, None, None, 0x1,
                ctypes.byref(blob_out))
        if not ok:
            raise OSError(ctypes.get_last_error(), "DPAPI 调用失败")
        try:
            return ctypes.string_at(blob_out.pbData, blob_out.cbData)
        finally:
            _kernel32.LocalFree(blob_out.pbData)

    def protect(text: str) -> str:
        if not text:
            return ""
        try:
            return "dpapi:" + base64.b64encode(_dpapi(text.encode("utf-8"), False)).decode()
        except OSError:
            return "dev:" + base64.b64encode(text.encode("utf-8")).decode()

    def unprotect(token: str) -> str:
        if not token:
            return ""
        try:
            if token.startswith("dpapi:"):
                return _dpapi(base64.b64decode(token[6:]), True).decode("utf-8")
            if token.startswith("dev:"):
                return base64.b64decode(token[4:]).decode("utf-8")
        except Exception:
            # 换机器 / 换账号后解不开，按「没配密钥」处理
            return ""
        return ""

else:
    def protect(text: str) -> str:
        return ("dev:" + base64.b64encode(text.encode()).decode()) if text else ""

    def unprotect(token: str) -> str:
        if token.startswith("dev:"):
            try:
                return base64.b64decode(token[4:]).decode()
            except Exception:
                return ""
        return ""


# ---------------------------------------------------------------- 默认配置

DEFAULT_CONFIG = {
    "connections": [],
    "active": "",
    "settings": {
        "detail": "标准",
        "max_rounds": 3,
        "temperature": 0.7,
    },
}


def _migrate(cfg: dict) -> dict:
    """老配置缺字段时补齐，绝不因为少了键就崩。"""
    cfg = cfg if isinstance(cfg, dict) else {}
    out = copy.deepcopy(DEFAULT_CONFIG)
    for k in ("connections", "active"):
        if k in cfg:
            out[k] = cfg[k]
    if isinstance(cfg.get("settings"), dict):
        out["settings"].update(cfg["settings"])
    return out


def load_config() -> dict:
    try:
        with open(config_path(), "r", encoding="utf-8") as f:
            return _migrate(json.load(f))
    except (OSError, ValueError):
        return copy.deepcopy(DEFAULT_CONFIG)


def save_config(cfg: dict) -> None:
    with _lock:
        tmp = config_path() + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
        os.replace(tmp, config_path())


# ---------------------------------------------------------------- 连接

FIELDS = ("id", "name", "provider", "base_url", "model", "protocol",
          "timeout", "stream", "disable_thinking", "auth_style")


def fix_base_url(base: str) -> str:
    """把用户手填的地址收拾成能直接请求的形态。

    新手最常犯的三种错，全在这里兜住：
      1. 忘了写 https://   → 补上，否则 urllib 直接抛「unknown url type」
      2. 粘了完整的 /chat/completions → 截掉，不然会拼成 .../chat/completions/chat/completions
      3. 结尾多个斜杠或者带空格
    """
    base = (base or "").strip().rstrip("/")
    if not base:
        return ""
    low = base.lower()
    for tail in ("/chat/completions", "/completions", "/messages"):
        if low.endswith(tail):
            base = base[: -len(tail)].rstrip("/")
            break
    if not base.lower().startswith(("http://", "https://")):
        base = "https://" + base
    return base


def clean_connection(raw: dict, prev: dict | None = None) -> dict:
    """新建 / 编辑连接的唯一入口：去尾斜杠、夹取数值、加密密钥。"""
    prev = prev or {}
    conn = {}
    conn["id"] = raw.get("id") or prev.get("id") or uuid.uuid4().hex[:12]
    conn["name"] = (raw.get("name") or prev.get("name") or "未命名").strip()[:40]
    conn["provider"] = raw.get("provider") or prev.get("provider") or "自定义 / 中转站"
    base = (raw.get("base_url") if "base_url" in raw else prev.get("base_url")) or ""
    conn["base_url"] = fix_base_url(base)
    conn["model"] = (raw.get("model") if "model" in raw else prev.get("model")) or ""
    conn["model"] = conn["model"].strip()
    conn["protocol"] = raw.get("protocol") or prev.get("protocol") or "openai"
    try:
        conn["timeout"] = max(10, min(600, int(raw.get("timeout", prev.get("timeout", 120)))))
    except (TypeError, ValueError):
        conn["timeout"] = 120
    conn["stream"] = bool(raw.get("stream", prev.get("stream", True)))
    conn["disable_thinking"] = bool(raw.get("disable_thinking", prev.get("disable_thinking", False)))
    conn["auth_style"] = raw.get("auth_style") or prev.get("auth_style") or "bearer"

    key = raw.get("api_key")
    if key is None or key == "":
        # 前端不回传密钥；空表示「不改」
        conn["api_key_encrypted"] = prev.get("api_key_encrypted", "")
    elif key == "__CLEAR__":
        conn["api_key_encrypted"] = ""
    else:
        conn["api_key_encrypted"] = protect(str(key))
    return conn


def public_connection(conn: dict) -> dict:
    """给前端看的形态：绝不带明文密钥。"""
    out = {k: conn.get(k) for k in FIELDS}
    out["has_key"] = bool(conn.get("api_key_encrypted"))
    return out


def runtime_connection(conn: dict) -> dict:
    """给请求层用的形态：带明文密钥，用完即弃，绝不落盘。"""
    out = {k: conn.get(k) for k in FIELDS}
    out["api_key"] = unprotect(conn.get("api_key_encrypted", ""))
    return out


def find_connection(cfg: dict, conn_id: str | None) -> dict | None:
    conns = cfg.get("connections") or []
    if conn_id:
        for c in conns:
            if c.get("id") == conn_id:
                return c
    active = cfg.get("active")
    for c in conns:
        if c.get("id") == active:
            return c
    return conns[0] if conns else None


# ---------------------------------------------------------------- 历史

MAX_HISTORY = 100


def load_history() -> list:
    try:
        with open(history_path(), "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, list) else []
    except (OSError, ValueError):
        return []


def append_history(item: dict) -> None:
    with _lock:
        items = load_history()
        item.setdefault("id", uuid.uuid4().hex[:12])
        item["ts"] = int(time.time())
        items.insert(0, item)
        items = items[:MAX_HISTORY]
        tmp = history_path() + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(items, f, ensure_ascii=False)
        os.replace(tmp, history_path())


def clear_history() -> None:
    with _lock:
        with open(history_path(), "w", encoding="utf-8") as f:
            json.dump([], f)
