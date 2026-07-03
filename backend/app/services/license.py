"""Offline license verification (Ed25519, no phone-home).

A license is a signed token: ``base64url(payload_json).base64url(signature)``.
The vendor holds the Ed25519 private key and signs licenses; the deployment ships
only the public key (``license_public_key_path``) and the signed license file
(``license_file``). Verification is fully local, so it works in air-gapped banks.

The ``cryptography`` import is lazy: if the package is missing the app still boots
and simply reports an *unconfigured/unlicensed* state instead of crashing. When
``settings.enforce_license`` is true, an invalid/expired/absent license fails
startup (fail-closed) — banks turn this on; dev leaves it off.
"""
from __future__ import annotations

import base64
import json
import logging
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from app.core.config import settings

logger = logging.getLogger("nexusline.license")


@dataclass
class LicenseInfo:
    valid: bool = False
    status: str = "unlicensed"  # valid | expired | invalid | unlicensed | unconfigured
    licensed_to: str = ""
    plan: str = ""
    seats: int = 0
    features: list[str] = field(default_factory=list)
    issued: str = ""
    expires: str = ""
    deployment: str = ""
    message: str = ""

    def to_public(self) -> dict:
        return {
            "valid": self.valid,
            "status": self.status,
            "licensed_to": self.licensed_to,
            "plan": self.plan,
            "seats": self.seats,
            "features": self.features,
            "issued": self.issued,
            "expires": self.expires,
            "deployment": self.deployment,
            "message": self.message,
        }


def _b64u_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _b64u_decode(text: str) -> bytes:
    pad = "=" * ((4 - len(text) % 4) % 4)
    return base64.urlsafe_b64decode(text + pad)


def _canonical(payload: dict) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


# ------------------------------------------------------------------ keys / signing ---
def generate_keypair() -> tuple[bytes, bytes]:
    """Return (private_pem, public_pem). Vendor-side, run once via the CLI."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    key = Ed25519PrivateKey.generate()
    private_pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    public_pem = key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return private_pem, public_pem


def sign_payload(payload: dict, private_pem: bytes) -> str:
    """Vendor-side: sign a license payload dict, returning the license token string."""
    from cryptography.hazmat.primitives import serialization

    key = serialization.load_pem_private_key(private_pem, password=None)
    message = _canonical(payload)
    signature = key.sign(message)
    return f"{_b64u_encode(message)}.{_b64u_encode(signature)}"


# ---------------------------------------------------------------------- verification ---
def _load_public_key():
    from cryptography.hazmat.primitives import serialization

    path = Path(settings.license_public_key_path)
    if not path.is_file():
        return None
    return serialization.load_pem_public_key(path.read_bytes())


def verify_token(token: str) -> LicenseInfo:
    try:
        from cryptography.exceptions import InvalidSignature
    except ModuleNotFoundError:
        return LicenseInfo(status="unconfigured", message="cryptography package not installed")

    pub = None
    try:
        pub = _load_public_key()
    except Exception as exc:  # noqa: BLE001
        return LicenseInfo(status="unconfigured", message=f"public key unreadable: {exc}")
    if pub is None:
        return LicenseInfo(status="unconfigured", message="no license public key configured")

    try:
        message_b64, sig_b64 = token.strip().split(".", 1)
        message = _b64u_decode(message_b64)
        signature = _b64u_decode(sig_b64)
    except Exception:  # noqa: BLE001
        return LicenseInfo(status="invalid", message="malformed license token")

    try:
        pub.verify(signature, message)
    except InvalidSignature:
        return LicenseInfo(status="invalid", message="signature does not match the trusted key")
    except Exception as exc:  # noqa: BLE001
        return LicenseInfo(status="invalid", message=f"verification error: {exc}")

    try:
        payload = json.loads(message)
    except Exception:  # noqa: BLE001
        return LicenseInfo(status="invalid", message="license payload is not valid JSON")

    info = LicenseInfo(
        licensed_to=str(payload.get("licensed_to", "")),
        plan=str(payload.get("plan", "")),
        seats=int(payload.get("seats", 0) or 0),
        features=list(payload.get("features", []) or []),
        issued=str(payload.get("issued", "")),
        expires=str(payload.get("expires", "")),
        deployment=str(payload.get("deployment", "")),
    )
    # Expiry check.
    if info.expires:
        try:
            if date.fromisoformat(info.expires) < date.today():
                info.status = "expired"
                info.message = f"license expired on {info.expires}"
                return info
        except ValueError:
            info.status = "invalid"
            info.message = "unparseable expiry date"
            return info

    info.valid = True
    info.status = "valid"
    info.message = "license verified"
    return info


# ------------------------------------------------------------------------- runtime ---
_cached: LicenseInfo | None = None


def load_current(refresh: bool = False) -> LicenseInfo:
    """Load + verify the deployment's license file (cached)."""
    global _cached
    if _cached is not None and not refresh:
        return _cached
    path = Path(settings.license_file)
    if not path.is_file():
        _cached = LicenseInfo(status="unlicensed", message="no license file present")
        return _cached
    _cached = verify_token(path.read_text())
    return _cached


def enforce_on_startup() -> None:
    """Fail startup on an invalid license when enforcement is on (banking mode)."""
    if not settings.enforce_license:
        info = load_current()
        logger.info("License status: %s (%s) — enforcement off", info.status, info.message)
        return
    info = load_current(refresh=True)
    if not info.valid:
        raise RuntimeError(
            f"License enforcement is on but the license is {info.status}: {info.message}. "
            f"Install a valid license at {settings.license_file}."
        )
    logger.info("License valid — licensed to %s (%s), expires %s", info.licensed_to, info.plan, info.expires)


def has_feature(feature: str) -> bool:
    info = load_current()
    # When unlicensed/unconfigured (dev/self-host), don't gate features.
    if info.status in ("unlicensed", "unconfigured"):
        return True
    return info.valid and feature in info.features
