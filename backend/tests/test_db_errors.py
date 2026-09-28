"""Constraint violations answer as 4xx with a sentence, and JSON columns accept the
values requests carry. Both were 500s in live verification (audit-trail changes holding
a date or id; a cleared required field; a duplicate audit plan)."""
import json
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy.exc import IntegrityError

from app.core.database import json_dumps
from app.core.db_errors import _describe
from app.models.enums import Criticality


class _PgError(Exception):
    def __init__(self, detail="", column_name=None, table_name=None, constraint_name=None):
        super().__init__(detail)
        self.detail, self.column_name, self.table_name = detail, column_name, table_name
        self.constraint_name = constraint_name


def _integrity(kind: str, **attrs) -> IntegrityError:
    cause = type(kind, (_PgError,), {})(**attrs)
    orig = Exception("wrapped")
    orig.__cause__ = cause
    return IntegrityError("stmt", {}, orig)


def test_not_null_names_the_field():
    status, msg = _describe(_integrity("NotNullViolationError", column_name="business_unit_id"))
    assert status == 422 and msg == "'business unit' is required and cannot be empty."


def test_unique_names_the_columns_without_tenant():
    exc = _integrity(
        "UniqueViolationError",
        detail="Key (tenant_id, year, title)=(abc, 2026, Annual plan) already exists.",
    )
    assert _describe(exc) == (409, "A record with this year and title already exists.")


def test_dangling_link_and_still_referenced():
    missing = _integrity(
        "ForeignKeyViolationError",
        detail='Key (control_id)=(123) is not present in table "controls".',
    )
    assert _describe(missing) == (422, "The selected control does not exist (it may have been deleted).")
    in_use = _integrity(
        "ForeignKeyViolationError",
        detail='Key (id)=(1) is still referenced from table "risks".',
        table_name="risk_controls",
    )
    status, msg = _describe(in_use)
    assert status == 409 and "still used" in msg


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (date(2026, 3, 1), "2026-03-01"),
        (datetime(2026, 3, 1, 9, 30, tzinfo=timezone.utc), "2026-03-01T09:30:00+00:00"),
        (uuid.UUID(int=1), str(uuid.UUID(int=1))),
        (Decimal("12.50"), "12.50"),
        (Criticality.high, "high"),
    ],
)
def test_json_columns_accept_request_values(value, expected):
    assert json.loads(json_dumps({"v": value})) == {"v": expected}


def test_json_still_rejects_unknown_objects():
    with pytest.raises(TypeError):
        json_dumps({"v": object()})


def test_rls_hides_the_key_so_the_constraint_name_is_used():
    dup = _integrity("UniqueViolationError", table_name="audit_plans",
                     constraint_name="uq_audit_plan_year_title")
    assert _describe(dup) == (409, "A record with this year and title already exists.")
    whole = _integrity("UniqueViolationError", table_name="asset_dependencies",
                       constraint_name="uq_asset_dependency")
    assert _describe(whole) == (409, "This record already exists.")
    fk = _integrity("ForeignKeyViolationError", table_name="icfr_controls",
                    constraint_name="icfr_controls_control_id_fkey")
    assert _describe(fk) == (422, "The selected control does not exist (it may have been deleted).")
