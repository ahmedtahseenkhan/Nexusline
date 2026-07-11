"""Unit tests for module entitlements: registry consistency, license-driven
resolution, config denylist and the API gating dependency (no DB required)."""
from datetime import date, timedelta

import pytest
from fastapi import HTTPException

from app.core.config import settings
from app.core.modules import ALL_MODULE_KEYS, EDITIONS, MODULES, expand_modules
from app.services import license as lic
from app.services import modules as mod


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
    private_pem, public_pem = lic.generate_keypair()
    pub = tmp_path / "pubkey.pem"
    pub.write_bytes(public_pem)
    monkeypatch.setattr(settings, "license_public_key_path", str(pub))
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
        token = lic.sign_payload(base, private_pem)
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
