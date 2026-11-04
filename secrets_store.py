# -*- coding: utf-8 -*-
"""凭据存储：用 Windows DPAPI 加密，只对当前 Windows 用户可解密。

· 加密后的 secrets.dat 即使被复制到别的电脑、别的账户，也解不开；
· 明文只在内存里短暂存在，不写日志、不进邮件、不出现在异常信息里；
· 非 Windows 平台降级为明文存储并告警（本工具本身只支持 Windows）。
"""
import base64
import ctypes
import ctypes.wintypes as wt
import json
import os

import paths


class SecretError(RuntimeError):
    pass


# ---------- DPAPI ----------

class _Blob(ctypes.Structure):
    _fields_ = [("cbData", wt.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]


def _make_blob(data: bytes):
    """返回 (blob, buf)。buf 必须被调用方持有，否则可能在系统调用前被回收。"""
    buf = ctypes.create_string_buffer(data, len(data) or 1)
    blob = _Blob(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))
    return blob, buf


def _dpapi(protect: bool, data: bytes) -> bytes:
    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    blob_in, buf_in = _make_blob(data)   # 保持 buf_in 引用存活
    blob_out = _Blob()

    # 显式声明参数类型，避免 64 位指针被截断
    LPVOID_P = ctypes.c_void_p
    fn = crypt32.CryptProtectData if protect else crypt32.CryptUnprotectData
    fn.argtypes = [
        ctypes.POINTER(_Blob), LPVOID_P, ctypes.POINTER(_Blob),
        LPVOID_P, LPVOID_P, wt.DWORD, ctypes.POINTER(_Blob),
    ]
    fn.restype = wt.BOOL

    desc = "usst-homework-reminder"
    ok = fn(ctypes.byref(blob_in), None, None, None, None, 0, ctypes.byref(blob_out))
    if not ok:
        raise SecretError(f"DPAPI {'加密' if protect else '解密'}失败（错误码 {kernel32.GetLastError()}）")
    try:
        return ctypes.string_at(blob_out.pbData, blob_out.cbData)
    finally:
        kernel32.LocalFree(blob_out.pbData)
        del buf_in, desc


def _available():
    return os.name == "nt"


# ---------- 读写 ----------

# 数据结构（v2）：
#   {
#     "accounts": {                 # 按平台分开，新增平台不互相干扰
#       "usst": {"user": "...", "password": "..."},
#       "chaoxing": {"user": "...", "password": "..."}
#     },
#     "email": {                    # 提醒邮件的发信配置
#       "sender": "...", "auth_code": "...", "recipient": "...",
#       "host": "smtp.qq.com", "port": 465
#     }
#   }
LEGACY_KEYS = ("usst", "smtp", "recipient", "portal_base_url")


def _migrate(d):
    """v1 → v2：v1 用 usst / smtp / recipient 三个顶层键，这里就地升级。"""
    if not isinstance(d, dict) or not any(k in d for k in LEGACY_KEYS):
        return d, False
    accounts = d.setdefault("accounts", {})
    old_usst = d.pop("usst", None)
    old_smtp = d.pop("smtp", None)
    old_rcpt = d.pop("recipient", None)
    d.pop("portal_base_url", None)
    if isinstance(old_usst, dict) and old_usst.get("user"):
        accounts.setdefault("usst", {}).update(
            {"user": old_usst.get("user", ""), "password": old_usst.get("password", "")}
        )
    if isinstance(old_smtp, dict) and old_smtp.get("auth_code"):
        email = d.setdefault("email", {})
        email.setdefault("sender", old_smtp.get("user", ""))
        email.setdefault("auth_code", old_smtp.get("auth_code", ""))
        if old_smtp.get("host"):
            email.setdefault("host", old_smtp.get("host"))
            email.setdefault("port", old_smtp.get("port", 465))
    if old_rcpt:
        d.setdefault("email", {}).setdefault("recipient", old_rcpt)
    return d, True


def load():
    """读取凭据；自动把旧格式升级为按平台分账号的结构。"""
    if not paths.SECRETS.exists():
        return {}
    raw = paths.SECRETS.read_bytes()
    try:
        if raw.startswith(b"DPAPI1"):
            plain = _dpapi(False, raw[6:])
        else:
            plain = base64.b64decode(raw)
    except Exception as e:
        raise SecretError(f"无法读取凭据文件（可能不是本机本账户生成的）：{e}")
    data = json.loads(plain.decode("utf-8"))
    data, changed = _migrate(data)
    if changed:                       # 升级后立刻回写，下次就不用再转换
        try:
            save(data)
        except Exception:
            pass
    return data


def save(secrets: dict):
    data = json.dumps(secrets, ensure_ascii=False).encode("utf-8")
    if _available():
        blob = b"DPAPI1" + _dpapi(True, data)
    else:
        blob = base64.b64encode(data)
    paths.ensure()
    tmp = paths.SECRETS.with_suffix(".tmp")
    tmp.write_bytes(blob)
    tmp.replace(paths.SECRETS)
    try:
        os.chmod(paths.SECRETS, 0o600)
    except Exception:
        pass


def exists():
    return paths.SECRETS.exists()


def get(key_path, default=""):
    """按 "usst.user" 这样的路径取值。"""
    d = load()
    for k in key_path.split("."):
        if not isinstance(d, dict):
            return default
        d = d.get(k, default)
    return d


def update(**sections):
    """合并写入，例如 update(accounts={"usst": {...}})。"""
    d = load()
    for sec, vals in sections.items():
        if isinstance(vals, dict):
            d.setdefault(sec, {}).update(vals)
        else:
            d[sec] = vals
    save(d)
    return d


def account(platform_key):
    """返回某平台的账号 {"user","password"}；未配置时返回 None。"""
    a = (load().get("accounts") or {}).get(platform_key) or {}
    return a if a.get("user") and a.get("password") else None


def save_account(platform_key, **fields):
    d = load()
    d.setdefault("accounts", {})[platform_key] = fields
    save(d)
    return d


def email_config():
    """返回邮件配置；发件邮箱或授权码缺失时返回 None。"""
    e = load().get("email") or {}
    if not e.get("sender") or not e.get("auth_code"):
        return None
    e.setdefault("recipient", e["sender"])
    e.setdefault("host", "smtp.qq.com")
    e.setdefault("port", 465)
    return e


def save_email(sender, auth_code, recipient="", host="", port=465):
    d = load()
    d["email"] = {
        "sender": sender,
        "auth_code": auth_code,
        "recipient": recipient or sender,
        "host": host or "smtp.qq.com",
        "port": int(port or 465),
    }
    save(d)
    return d


def mask(value: str, keep: int = 2) -> str:
    value = value or ""
    if len(value) <= keep * 2:
        return "*" * len(value)
    return value[:keep] + "*" * (len(value) - keep * 2) + value[-keep:]


def mask_email(addr: str) -> str:
    addr = addr or ""
    if "@" not in addr:
        return mask(addr)
    local, domain = addr.split("@", 1)
    return (local[:2] + "*" * max(1, len(local) - 2)) + "@" + domain
