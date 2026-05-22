"""API Key 等敏感字段的本地加密 (transparent secret).

设计目标:
- Windows: 用系统 DPAPI (用户级密钥, 跨机器/跨用户都解不开), 不引依赖, ctypes 直接调
- 其他平台: 暂无可靠的"用户级且无依赖"加密方案, 退化成 base64 obfuscation + 警告
- token 自带 scheme 前缀 ("dpapi$..." / "plain$..."), 解密时按前缀分发, 便于以后切方案
- 解密任何错误都吞回原文, 避免老 plain config 一升级就洗白用户的 key

公开 API:
    encrypt(plain: str) -> str
    decrypt(token: str) -> str
    is_encrypted(token: str) -> bool

幂等: encrypt(encrypt(x)) 不会再加一层; decrypt 一个明文返回它本身.
"""
from __future__ import annotations

import base64
import logging
import sys

log = logging.getLogger(__name__)

_SCHEME_DPAPI = "dpapi"
_SCHEME_PLAIN = "plain"  # 明文 base64, 仅用于非 Windows 占位


def is_encrypted(token: str) -> bool:
    if not isinstance(token, str) or not token:
        return False
    return token.startswith(f"{_SCHEME_DPAPI}$") or token.startswith(f"{_SCHEME_PLAIN}$")


def encrypt(plain: str) -> str:
    if not plain:
        return ""
    if is_encrypted(plain):
        return plain  # 幂等
    if sys.platform == "win32":
        try:
            blob = _dpapi_protect(plain.encode("utf-8"))
            return f"{_SCHEME_DPAPI}${base64.b64encode(blob).decode('ascii')}"
        except Exception as e:
            log.warning("DPAPI encrypt failed, falling back to plain: %s", e)
    # 非 Windows / DPAPI 不可用: 仅做编码占位, 注意不是真加密
    return f"{_SCHEME_PLAIN}${base64.b64encode(plain.encode('utf-8')).decode('ascii')}"


def decrypt(token: str) -> str:
    if not token:
        return ""
    if not is_encrypted(token):
        return token  # 兼容旧版明文 / 用户手填
    scheme, _, body = token.partition("$")
    try:
        raw = base64.b64decode(body.encode("ascii"))
    except Exception:
        return token
    if scheme == _SCHEME_DPAPI:
        if sys.platform != "win32":
            log.warning("DPAPI ciphertext on non-Windows host, cannot decrypt")
            return ""
        try:
            return _dpapi_unprotect(raw).decode("utf-8")
        except Exception as e:
            log.warning("DPAPI decrypt failed: %s", e)
            return ""
    if scheme == _SCHEME_PLAIN:
        try:
            return raw.decode("utf-8")
        except Exception:
            return ""
    return token


# ─── Windows DPAPI 绑定 ────────────────────────────────────────

if sys.platform == "win32":
    import ctypes
    from ctypes import wintypes

    class _DATA_BLOB(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

    _crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    _CryptProtectData = _crypt32.CryptProtectData
    _CryptProtectData.argtypes = [
        ctypes.POINTER(_DATA_BLOB), wintypes.LPCWSTR,
        ctypes.POINTER(_DATA_BLOB), ctypes.c_void_p,
        ctypes.c_void_p, wintypes.DWORD,
        ctypes.POINTER(_DATA_BLOB),
    ]
    _CryptProtectData.restype = wintypes.BOOL

    _CryptUnprotectData = _crypt32.CryptUnprotectData
    _CryptUnprotectData.argtypes = _CryptProtectData.argtypes
    _CryptUnprotectData.restype = wintypes.BOOL

    _LocalFree = _kernel32.LocalFree
    _LocalFree.argtypes = [wintypes.HLOCAL]
    _LocalFree.restype = wintypes.HLOCAL

    _CRYPTPROTECT_UI_FORBIDDEN = 0x1
    _DESC = "Qianjuange.api_key"

    def _to_blob(data: bytes) -> _DATA_BLOB:
        buf = ctypes.create_string_buffer(data, len(data))
        return _DATA_BLOB(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))

    def _from_blob(blob: _DATA_BLOB) -> bytes:
        try:
            return ctypes.string_at(blob.pbData, blob.cbData)
        finally:
            if blob.pbData:
                _LocalFree(ctypes.cast(blob.pbData, wintypes.HLOCAL))

    def _dpapi_protect(plain: bytes) -> bytes:
        in_blob = _to_blob(plain)
        out_blob = _DATA_BLOB()
        ok = _CryptProtectData(
            ctypes.byref(in_blob), _DESC,
            None, None, None, _CRYPTPROTECT_UI_FORBIDDEN,
            ctypes.byref(out_blob),
        )
        if not ok:
            raise OSError(ctypes.get_last_error(), "CryptProtectData failed")
        return _from_blob(out_blob)

    def _dpapi_unprotect(blob_bytes: bytes) -> bytes:
        in_blob = _to_blob(blob_bytes)
        out_blob = _DATA_BLOB()
        ok = _CryptUnprotectData(
            ctypes.byref(in_blob), None,
            None, None, None, _CRYPTPROTECT_UI_FORBIDDEN,
            ctypes.byref(out_blob),
        )
        if not ok:
            raise OSError(ctypes.get_last_error(), "CryptUnprotectData failed")
        return _from_blob(out_blob)
else:  # pragma: no cover - 非 Windows 占位
    def _dpapi_protect(plain: bytes) -> bytes:
        raise OSError("DPAPI only available on Windows")

    def _dpapi_unprotect(blob_bytes: bytes) -> bytes:
        raise OSError("DPAPI only available on Windows")


__all__ = ["encrypt", "decrypt", "is_encrypted"]
