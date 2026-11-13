"""TOTP 生成（纯标准库，RFC 6238）。

账号 2FA 的 secret 直接本地算验证码，不必走第三方网站。

用法：
    from lib.totp import now
    now("ZEHH67T4K2REUMX5YDBIHXDKY2HJZKGC")   # -> "123456"
"""

import base64
import hashlib
import hmac
import struct
import time


def _key(secret):
    s = (secret or "").strip().replace(" ", "").upper()
    pad = "=" * ((8 - len(s) % 8) % 8)
    return base64.b32decode(s + pad, casefold=True)


def totp(secret, digits=6, period=30, at=None):
    """返回指定时间（默认现在）的 TOTP 验证码。"""
    counter = int((at if at is not None else time.time()) // period)
    msg = struct.pack(">Q", counter)
    digest = hmac.new(_key(secret), msg, hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    code = struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF
    return str(code % (10 ** digits)).zfill(digits)


def now(secret, digits=6, period=30):
    """当前验证码。"""
    return totp(secret, digits=digits, period=period)


def seconds_left(period=30):
    """当前验证码剩余有效秒数。"""
    return period - int(time.time()) % period
