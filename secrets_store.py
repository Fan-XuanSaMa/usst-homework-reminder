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

def load():
    """返回 {"usst": {"user","password"}, "smtp": {"auth_code"}, "recipient"}。"""
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
    return json.loads(plain.decode("utf-8"))


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
    """合并写入，例如 update(usst={"user": "...", "password": "..."})。"""
    d = load()
    for sec, vals in sections.items():
        if isinstance(vals, dict):
            d.setdefault(sec, {}).update(vals)
        else:
            d[sec] = vals
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
