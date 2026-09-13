"""Phase 3 §3.3: an organisation switches modules on within its licence, and onboarding."""
from app.api.v1.tenant_settings import module_choice_problem
from app.core.modules import MODULES
from app.services import modules as m


def test_no_choice_means_everything_the_installation_allows():
    assert m.effective_modules({"aml", "shariah"}, None) == {"aml", "shariah"}


def test_an_organisation_can_only_narrow_what_the_licence_allows():
    assert m.effective_modules({"aml", "shariah"}, ["aml", "fraud"]) == {"aml"}


def test_a_choice_outside_the_licence_is_refused_with_the_module_names():
    problem = module_choice_problem(["aml", "shariah"], available={"aml"})
    assert problem and "Shariah Governance" in problem
    assert module_choice_problem(["not_a_module"], available={"aml"}).startswith("Unknown modules")
    assert module_choice_problem(None, available=set()) is None
    assert module_choice_problem(["aml"], available={"aml"}) is None


def test_the_starter_set_is_real_and_leaves_shariah_to_islamic_banks():
    assert set(m.STARTER_MODULES) <= set(MODULES)
    assert len(m.STARTER_MODULES) == 8
    assert "shariah" not in m.STARTER_MODULES


def test_module_states_report_the_organisation_layer_separately():
    states = {s["key"]: s for s in m.module_states(frozenset({"aml"}))}
    assert states["aml"]["enabled_by_organisation"] is True
    assert states["fraud"]["enabled_by_organisation"] is False
    assert states["fraud"]["enabled"] is False
    everything = {s["key"]: s for s in m.module_states(None)}
    assert all(s["enabled_by_organisation"] for s in everything.values())


def test_a_feed_request_without_a_session_resolves_no_tenant():
    from starlette.requests import Request

    scope = {"type": "http", "headers": [(b"authorization", b"Bearer not-a-jwt")]}
    assert m._tenant_of(Request(scope)) is None
    assert m._tenant_of(Request({"type": "http", "headers": []})) is None


def test_downloading_a_file_needs_permission_to_read_its_record():
    # Any signed-in user could fetch any file by id before; a board pack or restricted
    # evidence must follow the permission of the record it belongs to.
    import inspect

    from app.api.v1 import collab

    source = inspect.getsource(collab.download_file)
    assert "require_read(user, sf.entity_type)" in source
