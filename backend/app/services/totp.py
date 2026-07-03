"""RFC 6238 TOTP (time-based one-time passwords) in pure standard library.

Implemented without a third-party dependency (pyotp) so MFA works in air-gapped
on-premise installs and keeps the dependency surface small — a banking preference.
Compatible with Google Authenticator, Microsoft Authenticator, Authy, etc.
(SHA-1, 6 digits, 30-second period).
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import struct
import time
from urllib.parse import quote

_DIGITS = 6
_STEP = 30


def generate_secret(num_bytes: int = 20) -> str:
    """Return a fresh base32 secret (no padding), suitable for an authenticator app."""
    return base64.b32encode(secrets.token_bytes(num_bytes)).decode("ascii").rstrip("=")


def _b32_key(secret_b32: str) -> bytes:
    s = secret_b32.strip().replace(" ", "").upper()
    s += "=" * ((8 - len(s) % 8) % 8)  # restore base32 padding
    return base64.b32decode(s)


def _hotp(secret_b32: str, counter: int, digits: int = _DIGITS) -> str:
    key = _b32_key(secret_b32)
    digest = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    code = struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF
    return str(code % (10**digits)).zfill(digits)


def totp_at(secret_b32: str, timestamp: float, digits: int = _DIGITS, step: int = _STEP) -> str:
    return _hotp(secret_b32, int(timestamp // step), digits)


def verify(
    secret_b32: str,
    code: str,
    timestamp: float | None = None,
    digits: int = _DIGITS,
    step: int = _STEP,
    window: int = 1,
) -> bool:
    """Check a code against the current step ±``window`` (clock-skew tolerance)."""
    if not secret_b32 or not code:
        return False
    code = code.strip().replace(" ", "")
    if len(code) != digits or not code.isdigit():
        return False
    ts = time.time() if timestamp is None else timestamp
    counter = int(ts // step)
    for drift in range(-window, window + 1):
        if hmac.compare_digest(_hotp(secret_b32, counter + drift, digits), code):
            return True
    return False


def provisioning_uri(secret_b32: str, account_name: str, issuer: str) -> str:
    """otpauth:// URI for QR provisioning in an authenticator app."""
    label = quote(f"{issuer}:{account_name}")
    return (
        f"otpauth://totp/{label}?secret={secret_b32}"
        f"&issuer={quote(issuer)}&algorithm=SHA1&digits={_DIGITS}&period={_STEP}"
    )
