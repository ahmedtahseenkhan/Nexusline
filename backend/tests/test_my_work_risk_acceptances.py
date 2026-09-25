"""Pending risk acceptances reach the approver's queue.

They used to show only on the risk's own page, so nobody was told one was waiting."""
from app.services import my_work


def test_risk_acceptances_are_a_decision_section():
    assert my_work.BUILDERS["risk_acceptance"] is my_work.risk_acceptances_to_decide
    assert my_work.KIND_LABELS["risk_acceptance"] == "Risk acceptances to decide"
    kinds = [k for k, _label, _hint in my_work.KINDS]
    assert kinds.index("risk_acceptance") < kinds.index("vuln_acceptance")
