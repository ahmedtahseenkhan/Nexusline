"""Global-search catalogue invariants.

Search fans out over every register in one UNION, so a bad target is not a missing
result — it is a 500 on every search. Each target must name a real title column and a
real permission code, and the union branches must project compatible columns.
"""
from app.api.v1.search import _TARGETS
from app.core.permissions import ALL_PERMISSIONS


def test_permission_codes_exist():
    known = set(ALL_PERMISSIONS)
    bad = [t.type_label for t in _TARGETS if t.read_perm not in known]
    assert bad == []


def test_title_attributes_exist_on_their_model():
    bad = [
        f"{t.model.__name__}.{t.title_attr}"
        for t in _TARGETS
        if not hasattr(t.model, t.title_attr)
    ]
    assert bad == []


def test_links_are_absolute_paths():
    bad = [t.link for t in _TARGETS if not t.link.startswith("/")]
    assert bad == []


def test_type_labels_are_unique():
    """The label prefixes each hit; duplicates make results ambiguous to the user."""
    labels = [t.type_label for t in _TARGETS]
    assert len(set(labels)) == len(labels)


def test_banking_modules_are_searchable():
    """Search used to cover only the core registers, so a bank's own data — findings,
    obligations, KRIs, SARs — was unreachable except by opening the right module."""
    covered = {t.model.__name__ for t in _TARGETS}
    expected = {
        "Issue", "AuditFinding", "RcsaAssessment", "KeyRiskIndicator", "LossEvent",
        "RegulatoryChange", "Obligation", "IcfrProcess", "ModelInventory",
        "SuspiciousActivityReport", "FraudRisk", "ShariahRuling", "Dpia",
        "OutsourcingArrangement", "BiaAssessment", "WhistleblowingReport",
    }
    assert expected <= covered
