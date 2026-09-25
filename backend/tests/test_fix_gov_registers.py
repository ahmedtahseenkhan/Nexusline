"""Awareness, access reviews, projects and the organisation registers (client report).

Pins: a completed access review is frozen until it is reopened, and cannot be marked
completed by a plain edit; the org registers share one four-eyes rule for archiving
(business units, processes and now the legal register), with a refusal that says what
to do; business units and processes show their risks and controls, and projects their
goals. Pure — no database.
"""
import uuid
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy.orm import configure_mappers

import app.models  # noqa: F401 - registers every mapper
from app.api.v1 import access_reviews, awareness, organization, projects
from app.models.enums import AccessReviewStatus
from app.schemas.organization import BusinessUnitRead, ProcessRead
from app.schemas.project import ProjectRead
from app.services import dual_control


def test_a_completed_review_is_frozen():
    with pytest.raises(HTTPException) as exc:
        access_reviews._open_or_409(SimpleNamespace(status=AccessReviewStatus.completed))
    assert exc.value.status_code == 409 and "in progress" in exc.value.detail
    access_reviews._open_or_409(SimpleNamespace(status=AccessReviewStatus.in_progress))
    access_reviews._open_or_409(SimpleNamespace(status=AccessReviewStatus.draft))


@pytest.mark.parametrize("module", [access_reviews, awareness, projects])
def test_change_diffs_only_name_what_changed(module):
    obj = SimpleNamespace(name="A", status=AccessReviewStatus.draft, due_date=None)
    changes = module._changes(obj, {"name": "A", "status": AccessReviewStatus.in_progress, "due_date": None})
    assert changes == {"status": {"from": "draft", "to": "in_progress"}}


def test_every_mutation_of_these_registers_is_audited():
    # Each write route takes the acting user, which is what the trail records.
    for module in (access_reviews, awareness, projects):
        for route in module.router.routes:
            if set(getattr(route, "methods", ())) & {"POST", "PATCH", "PUT", "DELETE"}:
                assert "user" in route.endpoint.__code__.co_varnames, (module.__name__, route.path)


def test_org_registers_share_the_archive_rule():
    for et in ("business_unit", "process", "legal"):
        assert dual_control.is_enforced_key(et, "delete")


def test_org_delete_refusal_says_what_to_do():
    text = organization._org_delete_refusal("business unit", "business units", "Archiving a business unit")
    assert "colleague" in text and "administrator" in text and "Archiving a business unit" in text


def test_reads_carry_the_reverse_links():
    assert {"risks", "controls"} <= set(BusinessUnitRead.model_fields)
    assert {"risks", "controls"} <= set(ProcessRead.model_fields)
    assert "goals" in ProjectRead.model_fields


def test_project_goals_is_a_read_only_relationship():
    configure_mappers()
    from app.models.goal import Goal
    from app.models.project import Project

    prop = Project.goals.property
    assert prop.mapper.class_ is Goal and prop.viewonly
    assert "goals.deleted" in str(prop.secondaryjoin)


def test_project_links_are_labelled_for_the_trail():
    items = [SimpleNamespace(id=uuid.uuid4(), reference="R-2", title="b"),
             SimpleNamespace(id=uuid.uuid4(), reference="", title="a", name="")]
    assert projects._link_labels(items) == ["R-2", "a"]
