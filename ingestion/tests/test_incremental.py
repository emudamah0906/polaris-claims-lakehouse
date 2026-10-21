"""Stage 2b watermark rules, with an in-memory source instead of Postgres."""

import json
from datetime import date, datetime

import pytest
from polaris_ingest.landing.incremental import (
    WATERMARK_KEY,
    extract_key,
    extract_marker_key,
    land_extract,
    plan_window,
    read_state,
)
from polaris_ingest.landing.sinks import LocalSink, Sink

D1, D2, D3 = date(2026, 10, 16), date(2026, 10, 17), date(2026, 10, 18)
T1, T2 = datetime(2026, 10, 16), datetime(2026, 10, 17)


class FakeSource:
    """One table, rows of (id, changed_at). Mirrors postgres.fetch_changes."""

    def __init__(self, rows):
        self.rows = list(rows)

    def current_max(self, table):
        return max((ts for _, ts in self.rows), default=None)

    def fetch(self, table, after, up_to):
        picked = [
            (i, ts) for i, ts in self.rows
            if up_to is not None and (after is None or ts > after) and ts <= up_to
        ]
        return ["id", "changed_at"], sorted(picked)


def csv_rows(sink, table, day):
    return sink.read(extract_key(table, day)).decode().splitlines()[1:]


# ── plan_window ───────────────────────────────────────────────────────────────

def test_first_run_takes_everything():
    assert plan_window({}, D1, T1) == (None, T1)


def test_next_day_starts_where_the_last_stopped():
    runs = {"2026-10-16": {"after": None, "up_to": T1.isoformat()}}
    assert plan_window(runs, D2, T2) == (T1, T2)


def test_rerun_reuses_the_saved_window():
    runs = {"2026-10-16": {"after": None, "up_to": T1.isoformat()}}
    # Even though newer rows exist now, a retry of D1 reads D1's window
    assert plan_window(runs, D1, T2) == (None, T1)


def test_nothing_new_gives_an_empty_window():
    runs = {"2026-10-16": {"after": None, "up_to": T1.isoformat()}}
    assert plan_window(runs, D2, T1) == (T1, T1)


def test_backfill_before_a_later_run_is_refused():
    runs = {"2026-10-17": {"after": None, "up_to": T2.isoformat()}}
    with pytest.raises(ValueError, match="Backfills"):
        plan_window(runs, D1, T2)


# ── land_extract ──────────────────────────────────────────────────────────────

def test_day_two_pulls_only_changes(tmp_path):
    sink = LocalSink(tmp_path)
    src = FakeSource([("a", T1), ("b", T1), ("c", datetime(2026, 9, 1))])
    land_extract(sink, ["t"], D1, src.current_max, src.fetch)
    assert len(csv_rows(sink, "t", D1)) == 3

    src.rows += [("d", T2)]                      # one new row
    src.rows[0] = ("a", T2)                      # one changed row
    land_extract(sink, ["t"], D2, src.current_max, src.fetch)
    # "b" shares the old watermark exactly; strictly-greater keeps it out
    assert csv_rows(sink, "t", D2) == ["a,2026-10-17 00:00:00", "d,2026-10-17 00:00:00"]


def test_rerun_lands_the_same_file(tmp_path):
    sink = LocalSink(tmp_path)
    src = FakeSource([("a", T1)])
    land_extract(sink, ["t"], D1, src.current_max, src.fetch)
    first = sink.read(extract_key("t", D1))
    src.rows.append(("b", T2))                   # a change arrives before the retry
    land_extract(sink, ["t"], D1, src.current_max, src.fetch)
    assert sink.read(extract_key("t", D1)) == first


def test_quiet_day_writes_header_only(tmp_path):
    sink = LocalSink(tmp_path)
    src = FakeSource([("a", T1)])
    land_extract(sink, ["t"], D1, src.current_max, src.fetch)
    land_extract(sink, ["t"], D2, src.current_max, src.fetch)
    assert sink.read(extract_key("t", D2)) == b"id,changed_at\n"
    assert read_state(sink)["t"]["2026-10-17"] == {"after": T1.isoformat(), "up_to": T1.isoformat()}


class OrderSink(LocalSink):
    """Records the order of writes; can fail on one key."""

    def __init__(self, root, fail_on=None):
        super().__init__(root)
        self.order, self.fail_on = [], fail_on

    def write(self, key, data):
        if key == self.fail_on:
            raise OSError("disk full")
        self.order.append(key)
        return super().write(key, data)


def test_marker_then_watermark_last(tmp_path):
    sink = OrderSink(tmp_path)
    src = FakeSource([("a", T1)])
    land_extract(sink, ["t", "u"], D1, src.current_max, src.fetch)
    assert sink.order[-2:] == [extract_marker_key(D1), WATERMARK_KEY]


def test_failed_run_leaves_the_watermark_alone(tmp_path):
    sink = OrderSink(tmp_path)
    src = FakeSource([("a", T1)])
    land_extract(sink, ["t"], D1, src.current_max, src.fetch)
    before = sink.read(WATERMARK_KEY)

    src.rows.append(("b", T2))
    sink.fail_on = extract_key("t", D2)
    with pytest.raises(OSError):
        land_extract(sink, ["t"], D2, src.current_max, src.fetch)
    # Watermark unchanged, so the next try starts from T1 and still gets "b"
    assert sink.read(WATERMARK_KEY) == before
    assert "2026-10-17" not in json.loads(before)["t"]


def test_sink_interface_has_read():
    assert "read" in Sink.__abstractmethods__
