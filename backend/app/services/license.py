"""Offline license verification (Ed25519, no phone-home).

A license is a signed token: ``base64url(payload_json).base64url(signature)``.
The vendor holds the Ed25519 private key and signs licenses; the deployment
verifies them against :data:`app.core.build.VENDOR_PUBLIC_KEY_PEM`, which is
compiled into the image. Verification is fully local, so it works in air-gapped
banks.

This module can *verify* but not *sign*: ``generate_keypair``/``sign_payload``
live in ``app/tools/license.py``, which is excluded from release images. Shipping
the signing helpers alongside the verifier handed every client the machinery to
mint their own licenses.

The ``cryptography`` import is lazy: in a dev build a missing package leaves the
app *unconfigured/unlicensed* instead of crashing. In a release build
(``build.PRODUCTION_BUILD``) enforcement is unconditional — an invalid or absent license
fails startup, and no environment variable can turn that off. An expired license does not:
it gets grace and then read-only mode (``services/licence_state.py``).
"""
from __future__ import annotations

import base64
import json
import logging
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from app.core import build
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
    # Licensed module entitlements: edition names and/or module keys (see
    # app/core/modules.py). None (field absent from the payload) means the
    # license predates module packaging and unlocks everything.
    modules: list[str] | None = None
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
            "modules": self.modules,
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


def canonical(payload: dict) -> bytes:
    """Byte form that gets signed. Shared with the vendor signing CLI, so any
    change here must change both sides or every existing license breaks."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


# ---------------------------------------------------------------------- enforcement ---
def enforcement_enabled() -> bool:
    """True in a release image. Compiled in at build time, not configurable."""
    return build.PRODUCTION_BUILD


# ---------------------------------------------------------------------- verification ---
def _load_public_key():
    from cryptography.hazmat.primitives import serialization

    pem = build.VENDOR_PUBLIC_KEY_PEM.strip()
    if not pem:
        return None
    return serialization.load_pem_public_key(pem.encode("ascii"))


def verify_token(token: str) -> LicenseInfo:
    try:
        from cryptography.exceptions import InvalidSignature
    except ModuleNotFoundError:
        return LicenseInfo(status="unconfigured", message="cryptography package not installed")

    pub = None
    try:
        pub = _load_public_key()
    except Exception as exc:  # noqa: BLE001
        return LicenseInfo(status="unconfigured", message=f"embedded vendor key unreadable: {exc}")
    if pub is None:
        return LicenseInfo(status="unconfigured", message="no vendor public key embedded in this build")

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
        modules=list(payload["modules"]) if payload.get("modules") is not None else None,
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


def signature_ok(info: LicenseInfo) -> bool:
    """The licence was issued by the vendor, whatever its dates: ``valid`` or ``expired``.

    An expired licence still identifies the customer, its seats and modules — decision 1
    keeps the installation working through grace and then read-only
    (``services/licence_state.py``), never locked out."""
    return info.status in ("valid", "expired")


# ------------------------------------------------------------------------- runtime ---
_cached: LicenseInfo | None = None
#: (path, modification time) the cache was read from: a licence file replaced on disk is
#: picked up on the next call, without a restart.
_cached_source: tuple[str, float | None] | None = None


def _source() -> tuple[str, float | None]:
    path = Path(settings.license_file)
    try:
        return str(path), path.stat().st_mtime if path.is_file() else None
    except OSError:
        return str(path), None


def load_current(refresh: bool = False) -> LicenseInfo:
    """Load + verify the deployment's license file (cached until the file changes)."""
    global _cached, _cached_source
    source = _source()
    if _cached is not None and not refresh and _cached_source == source:
        return _cached
    path = Path(settings.license_file)
    _cached_source = source
    if not path.is_file():
        _cached = LicenseInfo(status="unlicensed", message="no license file present")
        return _cached
    _cached = verify_token(path.read_text())
    return _cached


class LicenceInstallError(ValueError):
    """A licence offered for installation that must not replace the current one."""


def install_token(token: str) -> LicenseInfo:
    """Verify ``token`` and, when it is a current licence from the vendor, write it to
    ``settings.license_file`` (atomically, keeping the previous file as ``.previous``) and
    reload. Raises :class:`LicenceInstallError` with a message for the administrator."""
    global _cached
    text_ = (token or "").strip()
    if not text_:
        raise LicenceInstallError("The licence file is empty.")
    info = verify_token(text_)
    if info.status == "unconfigured":
        raise LicenceInstallError(f"This build cannot verify licences: {info.message}.")
    if info.status == "invalid":
        raise LicenceInstallError(f"This is not a valid licence: {info.message}.")
    if info.status == "expired":
        raise LicenceInstallError(
            f"This licence expired on {info.expires}. Ask your vendor for a renewed licence."
        )
    path = Path(settings.license_file)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_file():
        path.with_name(path.name + ".previous").write_text(path.read_text())
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text_ + "\n")
    tmp.replace(path)
    _cached = None
    return load_current(refresh=True)


def enforce_on_startup() -> None:
    """Fail startup on an invalid license in a release build (banking mode)."""
    if not enforcement_enabled():
        info = load_current()
        logger.info("License status: %s (%s) — dev build, enforcement off", info.status, info.message)
        return
    # A release image with no embedded key can never validate anything: that is a
    # broken build on our side, not a licensing decision, so say so plainly.
    if not build.VENDOR_PUBLIC_KEY_PEM.strip():
        raise RuntimeError(
            "This release image was built without an embedded vendor public key. "
            "Run `python -m app.tools.license keygen` before building."
        )
    info = load_current(refresh=True)
    # Decision 1: a missing or forged licence refuses start-up; an expired one never does.
    # It runs through grace and then read-only (services/licence_state.py), so a bank can
    # always read its records.
    if not signature_ok(info):
        raise RuntimeError(
            f"License is {info.status}: {info.message}. "
            f"Install a valid license at {settings.license_file}."
        )
    if info.status == "expired":
        logger.warning(
            "License for %s expired on %s — starting in grace or read-only mode; install a renewed license",
            info.licensed_to, info.expires,
        )
        return
    logger.info("License valid — licensed to %s (%s), expires %s", info.licensed_to, info.plan, info.expires)


def has_feature(feature: str) -> bool:
    info = load_current()
    # Without enforcement (dev/self-host), don't gate features.
    if not enforcement_enabled() and info.status in ("unlicensed", "unconfigured"):
        return True
    # An expired licence keeps its features through grace and read-only (decision 1).
    return signature_ok(info) and feature in info.features
