"""Board packs, meeting decisions and declarations (client report, governance fixes).

Pins: a pack logo is judged by its bytes, not the content type the browser declared (a
text file named ``logo.png`` used to be accepted and silently left off every cover); a
failed or draft pack can be deleted and a failed one regenerated, while reviewed and
released packs stay; meeting decisions no longer share the "DEC" prefix with
declaration campaigns; declarations in a closed or archived campaign are frozen, and a
declaration recorded as submitted carries the day it was submitted. Pure — no database.
"""
import io
from datetime import date
from types import SimpleNamespace

import pytest
from PIL import Image

from app.api.v1 import declaration, governance
from app.models.declaration import CampaignStatus
from app.services import board_pack


def _png() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (40, 12), (10, 60, 200)).save(buf, "PNG")
    return buf.getvalue()


def _jpeg() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (40, 12), (10, 60, 200)).save(buf, "JPEG")
    return buf.getvalue()


# ------------------------------------------------------------------- logo bytes ---
def test_logo_format_reads_the_magic_number():
    assert governance.logo_format(_png()[:8]) == "png"
    assert governance.logo_format(_jpeg()[:8]) == "jpeg"
    assert governance.logo_format(b"not an image") is None
    assert governance.logo_format(b"%PDF-1.7\n") is None
    assert governance.logo_format(b"") is None


def test_logo_problem_accepts_a_real_image(tmp_path):
    path = tmp_path / "logo.png"
    path.write_bytes(_png())
    assert governance.logo_problem(path, "png") is None


def test_logo_problem_refuses_a_truncated_image(tmp_path):
    path = tmp_path / "logo.png"
    path.write_bytes(_png()[:40])
    assert "damaged or incomplete" in governance.logo_problem(path, "png")


def test_logo_problem_refuses_a_format_mismatch(tmp_path):
    # JPEG bytes that the magic-number sniff was told are PNG (cannot happen through the
    # endpoint, but the second check must not trust the first).
    path = tmp_path / "logo.png"
    path.write_bytes(_jpeg())
    assert governance.logo_problem(path, "png") == governance.LOGO_REFUSAL


# ------------------------------------------------------------- pack delete rules ---
@pytest.mark.parametrize("status,state,allowed", [
    (board_pack.FAILED, board_pack.DRAFT, True),
    (board_pack.FAILED, board_pack.RELEASED, True),  # a failed row has nothing to protect
    (board_pack.READY, board_pack.DRAFT, True),
    (board_pack.READY, board_pack.REVIEWED, False),
    (board_pack.READY, board_pack.RELEASED, False),
])
def test_pack_delete_refusal(status, state, allowed):
    refusal = governance.pack_delete_refusal(status, state)
    assert (refusal is None) is allowed
    if state == board_pack.REVIEWED and not allowed:
        assert "Return it to draft" in refusal


def test_pack_delete_and_regenerate_routes_exist():
    routes = {(r.path, m) for r in governance.router.routes for m in getattr(r, "methods", ())}
    assert ("/board-packs/{pack_id}", "DELETE") in routes
    assert ("/board-packs/{pack_id}/regenerate", "POST") in routes


# ---------------------------------------------------------------- prefixes ---
def test_meeting_decisions_have_their_own_prefix():
    # Declaration campaigns keep "DEC"; decisions minuted from now on are "MDC".
    assert governance.DECISION_PREFIX == "MDC"
    assert governance.DECISION_PREFIX != "DEC"


# ------------------------------------------------------------- declarations ---
def test_declarations_frozen_in_closed_or_archived_campaigns():
    open_c = SimpleNamespace(status=CampaignStatus.open, deleted=False)
    draft_c = SimpleNamespace(status=CampaignStatus.draft, deleted=False)
    closed_c = SimpleNamespace(status=CampaignStatus.closed, deleted=False)
    archived_c = SimpleNamespace(status=CampaignStatus.open, deleted=True)
    assert declaration.declaration_edit_refusal(open_c) is None
    assert declaration.declaration_edit_refusal(draft_c) is None
    assert "reopen" in declaration.declaration_edit_refusal(closed_c)
    assert "archived" in declaration.declaration_edit_refusal(archived_c)
    assert "archived" in declaration.declaration_edit_refusal(None)


def test_submitted_declaration_gets_a_submitted_date():
    data = {"status": "submitted", "submitted_date": None}
    declaration._stamp_submitted(data, None)
    assert data["submitted_date"] == date.today()


def test_pending_declaration_gets_no_submitted_date():
    data = {"status": "pending", "submitted_date": None}
    declaration._stamp_submitted(data, None)
    assert data["submitted_date"] is None


def test_submitted_date_given_or_already_on_record_is_kept():
    given = {"status": "cleared", "submitted_date": date(2026, 1, 5)}
    declaration._stamp_submitted(given, None)
    assert given["submitted_date"] == date(2026, 1, 5)
    on_record = {"status": "cleared"}
    declaration._stamp_submitted(on_record, SimpleNamespace(submitted_date=date(2026, 2, 1)))
    assert "submitted_date" not in on_record


def test_declaration_changes_compare_amounts_by_value():
    obj = SimpleNamespace(amount=1500, status="submitted", reviewer="")
    changes = declaration._changes(obj, {"amount": 1500.0, "status": "cleared", "reviewer": "CCO"})
    assert set(changes) == {"status", "reviewer"}
