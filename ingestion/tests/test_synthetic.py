"""The generator's promises: fixed sizes, and same inputs give the same rows."""

from datetime import date, timedelta

import pytest

from polaris_ingest.sources import synthetic
from polaris_ingest.sources.synthetic import generate

D1 = date(2026, 10, 16)


@pytest.fixture(scope="module")
def day1():
    return generate(D1, day=1, seed=42)


def test_table_sizes(day1):
    assert len(day1["customers"]) == synthetic.N_CUSTOMERS
    assert len(day1["policies"]) == synthetic.N_POLICIES
    assert len(day1["claims"]) == synthetic.N_CLAIMS
    assert len(day1["claim_payments"]) > 0


def test_same_inputs_same_rows(day1):
    # The whole idempotency story rests on this
    assert generate(D1, day=1, seed=42) == day1


def test_different_seed_different_rows(day1):
    assert generate(D1, day=1, seed=7)["claims"] != day1["claims"]


def test_no_dates_after_ingest_date(day1):
    # Proves the clock is pinned: nothing can come from "today"
    assert max(c.report_date for c in day1["claims"]) <= D1
    assert max(c.loss_date for c in day1["claims"]) <= D1
    assert max(p.created_at.date() for p in day1["policies"]) <= D1


def test_day2_replays_day1_then_changes_it(day1):
    day2 = generate(D1 + timedelta(days=1), day=2, seed=42)
    # Customers aren't touched by the refresh, so they match day 1 exactly
    assert day2["customers"] == day1["customers"]
    # Same policies, some of them updated on day 2
    assert len(day2["policies"]) == len(day1["policies"])
    changed = [p for p in day2["policies"] if p.updated_at.date() == D1 + timedelta(days=1)]
    assert changed
    # 50 new claims on top of day 1's
    assert len(day2["claims"]) == len(day1["claims"]) + synthetic.N_NEW_CLAIMS_DAY2


def test_bad_day_rejected():
    with pytest.raises(ValueError):
        generate(D1, day=3)
