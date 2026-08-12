"""Unit tests for module entitlements: registry consistency, license-driven
resolution, config denylist and the API gating dependency (no DB required)."""
from datetime import date, timedelta

import pytest
from fastapi import HTTPException

from app.core import build
from app.core.config import settings
from app.core.modules import ALL_MODULE_KEYS, EDITIONS, MODULES, expand_modules
from app.services import license as lic
from app.services import modules as mod
from app.tools import license as lic_cli


# ----------------------------------------------------------------- registry ---
def test_edition_entries_reference_real_modules():
    for name, keys in EDITIONS.items():
        unknown = set(keys) - ALL_MODULE_KEYS
        assert not unknown, f"edition {name} references unknown modules: {unknown}"


def test_every_module_belongs_to_an_edition():
    bundled = {k for keys in EDITIONS.values() for k in keys}
    assert bundled == set(ALL_MODULE_KEYS)


def test_module_routes_are_unique():
    routes = [r for m in MODULES.values() for r in m["routes"]]
    assert len(routes) == len(set(routes))


def test_expand_modules():
    assert expand_modules(["all"]) == set(ALL_MODULE_KEYS)
    assert expand_modules(["*"]) == set(ALL_MODULE_KEYS)
    assert expand_modules(["core"]) == set()
    assert expand_modules(["islamic_banking"]) == {"shariah"}
    assert expand_modules(["islamic-banking"]) == {"shariah"}  # dash tolerated
    assert expand_modules(["Financial_Crime", "icfr"]) == {"aml", "fraud", "whistleblowing", "icfr"}
    assert expand_modules(["not_a_module"]) == set()  # unknown ignored


# ------------------------------------------------------------- license logic ---
@pytest.fixture
def signed_license(tmp_path, monkeypatch):
    """Real Ed25519 keypair; returns a factory that installs a license payload
    as the deployment's current license."""
    private_pem, public_pem = lic_cli.generate_keypair()
    monkeypatch.setattr(build, "VENDOR_PUBLIC_KEY_PEM", public_pem.decode("ascii"))
    monkeypatch.setattr(settings, "disabled_modules", "")

    def install(**payload) -> lic.LicenseInfo:
        base = {
            "licensed_to": "Test Bank",
            "plan": "test",
            "seats": 10,
            "issued": date.today().isoformat(),
            "expires": (date.today() + timedelta(days=30)).isoformat(),
            "deployment": "on-prem",
        }
        base.update(payload)
        token = lic_cli.sign_payload(base, private_pem)
        path = tmp_path / "license.key"
        path.write_text(token)
        monkeypatch.setattr(settings, "license_file", str(path))
        return lic.load_current(refresh=True)

    yield install
    # Don't leak the test license into other tests via the module-level cache.
    lic._cached = None


def test_license_with_modules_restricts(signed_license):
    info = signed_license(modules=["islamic_banking", "financial_crime"])
    assert info.valid
    enabled = mod.enabled_modules()
    assert enabled == {"shariah", "aml", "fraud", "whistleblowing"}
    assert mod.is_enabled("shariah")
    assert not mod.is_enabled("icfr")


def test_license_without_modules_unlocks_everything(signed_license):
    info = signed_license()
    assert info.valid and info.modules is None
    assert mod.enabled_modules() == set(ALL_MODULE_KEYS)


def test_expired_license_locks_optional_modules(signed_license):
    info = signed_license(expires=(date.today() - timedelta(days=1)).isoformat(),
                          modules=["all"])
    assert info.status == "expired"
    assert mod.enabled_modules() == set()


def test_config_denylist_subtracts(signed_license, monkeypatch):
    signed_license(modules=["all"])
    monkeypatch.setattr(settings, "disabled_modules", "shariah, ESG,ai-assist")
    enabled = mod.enabled_modules()
    assert "shariah" not in enabled
    assert "esg" not in enabled
    assert "ai_assist" not in enabled
    assert "aml" in enabled


def test_unlicensed_dev_install_enables_everything(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "license_file", str(tmp_path / "missing.key"))
    monkeypatch.setattr(settings, "disabled_modules", "")
    lic.load_current(refresh=True)
    try:
        assert mod.enabled_modules() == set(ALL_MODULE_KEYS)
    finally:
        lic._cached = None


def test_module_states_shape(signed_license):
    signed_license(modules=["islamic_banking"])
    states = {s["key"]: s for s in mod.module_states()}
    assert set(states) == set(ALL_MODULE_KEYS)
    assert states["shariah"]["enabled"] and states["shariah"]["licensed"]
    assert not states["aml"]["enabled"] and not states["aml"]["licensed"]


# ------------------------------------------------- tamper resistance (Layer 1) ---
@pytest.fixture
def release_build(monkeypatch):
    """Pretend this process is a stamped release image."""
    monkeypatch.setattr(build, "PRODUCTION_BUILD", True)
    yield
    lic._cached = None


def test_enforcement_is_not_environment_configurable():
    # ENFORCE_LICENSE used to be a settings field, i.e. a one-line bypass in .env.
    assert not hasattr(settings, "enforce_license")
    assert not hasattr(settings, "license_public_key_path")


def test_a_foreign_key_cannot_mint_a_license(signed_license, tmp_path, monkeypatch):
    """The client generating their own keypair must not yield a valid license."""
    signed_license()  # installs the real vendor key for this test
    attacker_priv, _attacker_pub = lic_cli.generate_keypair()
    forged = tmp_path / "forged.key"
    forged.write_text(lic_cli.sign_payload(
        {"licensed_to": "Self", "plan": "free", "seats": 9999,
         "issued": date.today().isoformat(),
         "expires": (date.today() + timedelta(days=36500)).isoformat()},
        attacker_priv,
    ))
    monkeypatch.setattr(settings, "license_file", str(forged))
    info = lic.load_current(refresh=True)
    assert not info.valid and info.status == "invalid"


def test_release_build_grants_nothing_when_unlicensed(release_build, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "license_file", str(tmp_path / "missing.key"))
    monkeypatch.setattr(settings, "disabled_modules", "")
    lic.load_current(refresh=True)
    assert mod.enabled_modules() == set()


def test_release_build_refuses_to_start_without_a_license(release_build, tmp_path, monkeypatch):
    monkeypatch.setattr(build, "VENDOR_PUBLIC_KEY_PEM", "-----BEGIN PUBLIC KEY-----\nx\n")
    monkeypatch.setattr(settings, "license_file", str(tmp_path / "missing.key"))
    with pytest.raises(RuntimeError, match="unlicensed"):
        lic.enforce_on_startup()


def test_release_build_without_an_embedded_key_is_a_build_error(release_build, monkeypatch):
    monkeypatch.setattr(build, "VENDOR_PUBLIC_KEY_PEM", "")
    with pytest.raises(RuntimeError, match="without an embedded vendor public key"):
        lic.enforce_on_startup()


def test_dev_build_starts_unlicensed(tmp_path, monkeypatch):
    monkeypatch.setattr(build, "PRODUCTION_BUILD", False)
    monkeypatch.setattr(settings, "license_file", str(tmp_path / "missing.key"))
    try:
        lic.enforce_on_startup()  # must not raise
    finally:
        lic._cached = None


def test_keygen_embeds_the_public_key(tmp_path):
    stub = tmp_path / "build.py"
    stub.write_text('VENDOR_PUBLIC_KEY_PEM = ""\n\nPRODUCTION_BUILD = False\n')
    _priv, pub = lic_cli.generate_keypair()
    lic_cli.embed_public_key(pub, target=stub)
    ns: dict = {}
    exec(compile(stub.read_text(), str(stub), "exec"), ns)  # noqa: S102 - test fixture
    assert ns["VENDOR_PUBLIC_KEY_PEM"].strip() == pub.decode("ascii").strip()
    assert ns["PRODUCTION_BUILD"] is False  # stamping the key must not touch the flag


# ------------------------------------------------------------------- gating ---
@pytest.mark.asyncio
async def test_require_module_blocks_disabled(signed_license):
    signed_license(modules=["financial_crime"])
    await mod.require_module("aml")()  # enabled: no exception
    with pytest.raises(HTTPException) as exc:
        await mod.require_module("shariah")()
    assert exc.value.status_code == 403
    assert "Shariah" in exc.value.detail


@pytest.mark.asyncio
async def test_require_module_ignores_unknown_keys(signed_license):
    signed_license(modules=["core"])
    await mod.require_module("not_registered")()  # core platform: never gated
