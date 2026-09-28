"""Basel III SMA operational-risk capital (CRE25): buckets, ILM and currency.

Client report: BI 1bn with an average annual loss of 200m came out at ILM 2.7 and ORC
324m instead of 120m; ORC was computed from an ILM rounded to 2 dp; and the bucket edges
were hard-coded PKR figures (8bn / 240bn) applied to records in any currency.

Pinned here:

* a bucket-1 bank uses ILM = 1 (CRE25.9), so BI 1bn / losses 200m gives ORC 120m;
* ORC uses the unrounded ILM;
* the edges are Basel's EUR 1bn / EUR 30bn, used as-is for an EUR record and converted
  at the organisation's rates for any other currency; with no rate the capital is not
  computed and the read names the missing rate.
"""
from __future__ import annotations

import math
import uuid
from datetime import date, datetime, timezone
from types import SimpleNamespace

import pytest

from app.api.v1 import scenario as api
from app.models.scenario import BASEL_BI_BUCKET_1, BASEL_BI_BUCKET_2, CapitalStatus, sma_capital
from app.services.fx import RateBook

EUR_PKR = 310.5
PKR_1 = BASEL_BI_BUCKET_1 * EUR_PKR
PKR_2 = BASEL_BI_BUCKET_2 * EUR_PKR


def test_bucket_one_uses_an_ilm_of_one():
    r = sma_capital(1e9, 2e8, PKR_1, PKR_2)
    assert (r.bucket, r.ilm) == (1, 1.0)
    assert r.bic == pytest.approx(120e6) and r.orc == pytest.approx(120e6)


def test_bucket_edges_and_marginal_coefficients():
    assert sma_capital(PKR_1, 0, PKR_1, PKR_2).bucket == 1  # the edge itself is bucket 1
    two = sma_capital(2 * PKR_1, 0, PKR_1, PKR_2)
    assert two.bucket == 2 and two.bic == pytest.approx(0.12 * PKR_1 + 0.15 * PKR_1)
    three = sma_capital(PKR_2 + 1e9, 0, PKR_1, PKR_2)
    expected = 0.12 * PKR_1 + 0.15 * (PKR_2 - PKR_1) + 0.18 * 1e9
    assert three.bucket == 3 and three.bic == pytest.approx(expected)


def test_orc_uses_the_unrounded_ilm():
    r = sma_capital(2e9, 5e8, 1e9, 30e9)  # EUR record
    bic = 0.12 * 1e9 + 0.15 * 1e9
    ilm = math.log(math.e - 1 + (15 * 5e8 / bic) ** 0.8)
    assert r.ilm == pytest.approx(ilm, rel=1e-12)
    assert r.orc == pytest.approx(bic * ilm, rel=1e-12)
    assert r.orc != pytest.approx(bic * round(ilm, 2), rel=1e-6)


def test_zero_bi_is_zero_capital():
    r = sma_capital(0, 1e9, 1e9, 30e9)
    assert (r.bic, r.orc, r.ilm) == (0.0, 0.0, 1.0)


# ------------------------------------------------------------------ thresholds
def _book(*rates, reporting="PKR"):
    return RateBook(reporting, [(c, date(2026, 1, 1), r) for c, r in rates])


def test_eur_records_use_the_basel_edges_as_they_are():
    edges = api.sma_thresholds(_book(), "EUR")
    assert (edges.bucket_1, edges.bucket_2) == (BASEL_BI_BUCKET_1, BASEL_BI_BUCKET_2)


def test_reporting_currency_records_convert_at_the_eur_rate():
    edges = api.sma_thresholds(_book(("EUR", EUR_PKR)), "PKR")
    assert edges.bucket_1 == pytest.approx(PKR_1) and edges.bucket_2 == pytest.approx(PKR_2)
    assert "1 EUR = 310.5000 PKR" in edges.basis and "2026-01-01" in edges.basis


def test_a_third_currency_converts_through_the_reporting_currency():
    # USD record, PKR reporting: EUR 1bn = 1bn × 310.5 / 280 USD.
    edges = api.sma_thresholds(_book(("EUR", EUR_PKR), ("USD", 280)), "USD")
    assert edges.bucket_1 == pytest.approx(BASEL_BI_BUCKET_1 * EUR_PKR / 280)


def test_a_missing_rate_is_named_not_guessed():
    note = api.sma_thresholds(_book(), "PKR")
    assert isinstance(note, str) and "No EUR → PKR exchange rate" in note
    note = api.sma_thresholds(_book(("EUR", EUR_PKR)), "USD")
    assert isinstance(note, str) and "No USD → PKR" in note


def test_the_read_carries_figures_and_the_edges_used():
    obj = SimpleNamespace(
        id=uuid.uuid4(), reference="CAP-001", period="FY2026", business_indicator=1e9,
        avg_annual_loss=2e8, currency="PKR", notes="", status=CapitalStatus.draft,
        workflow_status="draft", created_at=datetime(2026, 9, 1, tzinfo=timezone.utc),
    )
    read = api._capital_read(obj, _book(("EUR", EUR_PKR)))
    assert (read.bucket, read.ilm, read.orc) == (1, 1.0, 120e6)
    assert read.bucket_1_threshold == pytest.approx(PKR_1) and read.threshold_note == ""
    blank = api._capital_read(obj, _book())
    assert (blank.bic, blank.ilm, blank.orc) == (None, None, None)
    assert blank.loss_component == 3e9 and "Exchange rates" in blank.threshold_note
