"""ICFR ratings, tests and the enterprise-control link (client report).

Pins: an RCM control's design and operating effectiveness follow its latest conclusive
test of each kind (a failed test makes it ineffective; an ineffective design caps the
operating rating), a hand rating stands only until a test concludes; a test cannot
report more exceptions than its sample or "pass" with exceptions; the link to the
enterprise control is a relationship with a reverse ``Control.icfr_controls`` so both
pages show it. Pure — no database.
"""
import uuid
from datetime import date, datetime, timezone
from types import SimpleNamespace

import pytest
from pydantic import ValidationError
from sqlalchemy.orm import configure_mappers

import app.models  # noqa: F401 - registers every mapper
from app.api.v1 import icfr as icfr_api
from app.models.enums import ControlEffectiveness as E
from app.models.icfr import IcfrTestResult as R
from app.models.icfr import IcfrTestType as T
from app.models.icfr import derive_effectiveness, figures_problem
from app.schemas.control import ControlRead
from app.schemas.icfr import IcfrControlRead, IcfrTestCreate


def t(kind, result, day, n=0):
    return SimpleNamespace(test_type=kind, result=result, test_date=day,
                           created_at=datetime(2026, 1, 1, 0, n, tzinfo=timezone.utc))


def test_no_tests_keeps_the_hand_ratings():
    assert derive_effectiveness([], E.effective, E.partially_effective) == (
        E.effective, E.partially_effective, "manual", "manual")


def test_a_failed_operating_test_makes_the_control_ineffective():
    design, operating, db, ob = derive_effectiveness(
        [t(T.operating, R.failed, date(2026, 6, 1))], E.effective, E.effective)
    assert (design, operating, db, ob) == (E.effective, E.ineffective, "manual", "tests")


def test_the_latest_test_decides_not_the_worst():
    tests = [t(T.operating, R.failed, date(2026, 3, 1)), t(T.operating, R.passed, date(2026, 6, 1))]
    assert derive_effectiveness(tests, E.not_assessed, E.not_assessed)[1] == E.effective


def test_undated_tests_order_by_when_they_were_recorded():
    tests = [t(T.operating, R.passed, None, 1), t(T.operating, R.passed_with_exceptions, None, 2)]
    assert derive_effectiveness(tests, E.not_assessed, E.not_assessed)[1] == E.partially_effective


def test_not_tested_results_do_not_count():
    tests = [t(T.design, R.not_tested, date(2026, 6, 1))]
    assert derive_effectiveness(tests, E.partially_effective, E.not_assessed)[0] == E.partially_effective


def test_an_ineffective_design_caps_operating():
    tests = [t(T.design, R.failed, date(2026, 6, 1)), t(T.operating, R.passed, date(2026, 6, 2))]
    design, operating, _db, ob = derive_effectiveness(tests, E.effective, E.effective)
    assert (design, operating, ob) == (E.ineffective, E.ineffective, "design")


@pytest.mark.parametrize("sample,exceptions,result,ok", [
    (25, 0, R.passed, True),
    (25, 2, R.passed_with_exceptions, True),
    (25, 2, R.failed, True),
    (1, 5, R.failed, False),         # more exceptions than items tested
    (5, 1, R.passed, False),         # a test with exceptions did not simply pass
    (0, 0, R.not_tested, True),
])
def test_test_figures_must_agree(sample, exceptions, result, ok):
    assert (figures_problem(sample, exceptions, result) is None) is ok


def test_the_create_schema_applies_the_same_rule():
    with pytest.raises(ValidationError):
        IcfrTestCreate(sample_size=1, exceptions_found=5)
    IcfrTestCreate(sample_size=5, exceptions_found=1, result=R.failed)


def test_a_result_completes_the_test():
    data = {"result": R.failed, "status": "planned"}
    icfr_api._conclude(data)
    assert data["status"].value == "completed"
    untouched = {"result": R.not_tested, "status": "planned"}
    icfr_api._conclude(untouched)
    assert untouched["status"] == "planned"


def _control(**kw):
    base = dict(id=uuid.uuid4(), process_id=uuid.uuid4(), reference="CTL-001", title="Three-way match",
                test_count=0, latest_result=None, created_at=datetime.now(timezone.utc), tests=[],
                design_effectiveness=E.effective, operating_effectiveness=E.effective, control=None)
    base.update(kw)
    return SimpleNamespace(**base)


def test_the_read_model_shows_ratings_from_the_tests():
    test = SimpleNamespace(id=uuid.uuid4(), control_id=uuid.uuid4(), reference="TST-001",
                           created_at=datetime.now(timezone.utc), test_type=T.operating, period="",
                           tester="", sample_size=25, exceptions_found=3, test_date=date(2026, 6, 1),
                           result=R.failed, conclusion="", status="completed")
    read = IcfrControlRead.model_validate(_control(tests=[test], test_count=1))
    assert read.operating_effectiveness == E.ineffective and read.operating_basis == "tests"
    assert read.design_effectiveness == E.effective and read.design_basis == "manual"


def test_the_manual_rating_is_refused_once_a_test_decides_it():
    test = SimpleNamespace(test_type=T.operating, result=R.failed, test_date=date(2026, 6, 1),
                           created_at=None, reference="TST-9")
    ctl = _control(tests=[test], operating_effectiveness=E.ineffective)
    assert "TST-9" in icfr_api._manual_rating_refusal(ctl, {"operating_effectiveness": E.effective})
    assert icfr_api._manual_rating_refusal(ctl, {"design_effectiveness": E.partially_effective}) is None


def test_the_enterprise_control_link_is_a_relationship_both_ways():
    configure_mappers()
    from app.models.control import Control
    from app.models.icfr import IcfrControl

    assert IcfrControl.control.property.mapper.class_ is Control
    assert Control.icfr_controls.property.mapper.class_ is IcfrControl
    # The reverse leaves out lines of an archived ICFR process.
    assert "icfr_processes.deleted" in str(Control.icfr_controls.property.primaryjoin)
    assert "icfr_controls" in ControlRead.model_fields
