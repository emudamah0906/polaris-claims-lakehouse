"""Bronze landing: layout, marker order, and safe re-runs."""

import hashlib
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import pytest

from polaris_ingest.cli import main
from polaris_ingest.landing.bronze import land_day, marker_key, partition_key, rows_to_csv
from polaris_ingest.landing.sinks import LocalSink, Sink

D1 = date(2026, 10, 16)


@dataclass
class Row:
    id: str
    amount: float


def test_keys():
    assert partition_key("claims", D1) == "claims/year=2026/month=10/day=16/part-00000.csv"
    assert marker_key(D1) == "_markers/ingest_date=2026-10-16/_SUCCESS"


def test_rows_to_csv():
    assert rows_to_csv([Row("a", 1.5), Row("b", 2.0)]) == b"id,amount\na,1.5\nb,2.0\n"
    assert rows_to_csv([]) == b""


class RecordingSink(Sink):
    """Remembers every call in order. Can be told to fail on one key."""

    def __init__(self, fail_on: str | None = None):
        self.calls: list[tuple[str, str]] = []
        self.fail_on = fail_on

    def write(self, key, data):
        if key == self.fail_on:
            raise OSError("disk full")
        self.calls.append(("write", key))
        return key

    def delete(self, key):
        self.calls.append(("delete", key))


def test_marker_deleted_first_and_written_last():
    sink = RecordingSink()
    land_day(sink, {"a": [Row("x", 1.0)], "b": [Row("y", 2.0)]}, D1)
    assert sink.calls[0] == ("delete", marker_key(D1))
    assert sink.calls[-1] == ("write", marker_key(D1))


def test_failed_table_means_no_marker():
    sink = RecordingSink(fail_on=partition_key("b", D1))
    with pytest.raises(OSError):
        land_day(sink, {"a": [Row("x", 1.0)], "b": [Row("y", 2.0)]}, D1)
    assert ("write", marker_key(D1)) not in sink.calls


def test_local_sink_overwrites_and_deletes(tmp_path):
    sink = LocalSink(tmp_path)
    sink.write("t/f.csv", b"old")
    sink.write("t/f.csv", b"new")
    assert (tmp_path / "t/f.csv").read_bytes() == b"new"
    sink.delete("t/f.csv")
    sink.delete("t/f.csv")  # deleting twice is fine
    assert not (tmp_path / "t/f.csv").exists()
    assert not list((tmp_path / "t").glob(".tmp-*"))  # no temp files left over


def _hashes(root: Path) -> dict[str, str]:
    return {
        str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(root.rglob("*"))
        if p.is_file()
    }


def test_cli_rerun_lands_identical_bytes(tmp_path):
    # Step 7's idempotency check, as a test: same day twice, same files
    args = ["run", "--ingest-date", "2026-10-16", "--root", str(tmp_path)]
    main(args)
    first = _hashes(tmp_path)
    main(args)
    assert _hashes(tmp_path) == first
    assert set(first) == {
        "customers/year=2026/month=10/day=16/part-00000.csv",
        "policies/year=2026/month=10/day=16/part-00000.csv",
        "claims/year=2026/month=10/day=16/part-00000.csv",
        "claim_payments/year=2026/month=10/day=16/part-00000.csv",
        "_markers/ingest_date=2026-10-16/_SUCCESS",
    }


# ── AdlsSink, with a fake Azure client so no network is needed ────────────────
from azure.core.exceptions import ResourceNotFoundError  # noqa: E402

from polaris_ingest.landing.sinks import AdlsSink, make_sink  # noqa: E402


class FakeFile:
    def __init__(self, store, key):
        self.store, self.key = store, key

    def upload_data(self, data, overwrite):
        assert overwrite is True  # a retry must replace, not fail on "exists"
        if len(data) == 0:
            return  # same as the real SDK: 0 bytes creates nothing
        self.store[self.key] = data

    def create_file(self):
        self.store[self.key] = b""

    def delete_file(self):
        if self.key not in self.store:
            raise ResourceNotFoundError("not found")
        del self.store[self.key]


class FakeFileSystem:
    def __init__(self):
        self.store: dict[str, bytes] = {}

    def get_file_client(self, key):
        return FakeFile(self.store, key)


def test_adls_sink_write_delete():
    fs = FakeFileSystem()
    sink = AdlsSink("polarisabc123", "bronze", file_system_client=fs)
    loc = sink.write("claims/x.csv", b"data")
    assert loc == "abfss://bronze@polarisabc123.dfs.core.windows.net/claims/x.csv"
    assert fs.store == {"claims/x.csv": b"data"}
    sink.delete("claims/x.csv")
    sink.delete("claims/x.csv")  # missing file is fine
    assert fs.store == {}


def test_adls_sink_writes_empty_marker():
    # Regression: the _SUCCESS marker is 0 bytes and never reached Azure
    fs = FakeFileSystem()
    AdlsSink("acct", "bronze", file_system_client=fs).write("_markers/x/_SUCCESS", b"")
    assert fs.store == {"_markers/x/_SUCCESS": b""}


def test_land_day_on_adls_matches_local(tmp_path):
    # Same day through both sinks gives the same keys and the same bytes
    from polaris_ingest.sources.synthetic import generate

    tables = generate(D1)
    fs = FakeFileSystem()
    land_day(AdlsSink("acct", "bronze", file_system_client=fs), tables, D1)
    land_day(LocalSink(tmp_path), tables, D1)
    local = {str(p.relative_to(tmp_path)): p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    assert fs.store == local


def test_azure_backend_needs_account():
    with pytest.raises(ValueError, match="ADLS_ACCOUNT_NAME"):
        make_sink("azure", account=None)
