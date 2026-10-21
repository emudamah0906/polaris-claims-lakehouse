"""Stage 2c vendor drop: stable file, honest manifest, manifest written last."""

import hashlib
import json
from datetime import date

from polaris_ingest.cli import main
from polaris_ingest.landing.sinks import LocalSink
from polaris_ingest.sources import vendor

D1 = date(2026, 10, 16)


def test_same_day_same_file():
    assert vendor.gen_estimates(D1) == vendor.gen_estimates(D1)


def test_only_repairable_auto_claims_in_the_window():
    claims = {c.claim_id: c for c in vendor.generate(D1)["claims"]}
    for e in vendor.gen_estimates(D1):
        c = claims[e.claim_id]
        assert c.product_type == "AUTO" and c.claim_type in vendor.REPAIRABLE
        assert (D1 - c.report_date).days <= vendor.LOOKBACK_DAYS
        assert e.estimate_date <= D1
        assert round(e.parts_amount + e.labour_amount, 2) == e.total_amount


def test_manifest_matches_the_file(tmp_path):
    sink = LocalSink(tmp_path)
    m = vendor.drop(sink, D1)
    data = sink.read("autobody/2026-10-16/repair_estimates.csv")
    assert m["row_count"] == len(data.decode().splitlines()) - 1  # minus the header
    assert m["sha256"] == hashlib.sha256(data).hexdigest()
    assert json.loads(sink.read("autobody/2026-10-16/manifest.json")) == m


def test_bad_manifest_claims_one_extra_row(tmp_path):
    good = vendor.drop(LocalSink(tmp_path / "a"), D1)
    bad = vendor.drop(LocalSink(tmp_path / "b"), D1, bad_manifest=True)
    assert bad["row_count"] == good["row_count"] + 1


def test_manifest_written_last(tmp_path):
    order = []

    class OrderSink(LocalSink):
        def write(self, key, data):
            order.append(key)
            return super().write(key, data)

    vendor.drop(OrderSink(tmp_path), D1)
    assert order[-1].endswith("manifest.json")


def test_cli_drops_into_landing_by_default(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    main(["vendor-drop", "--ingest-date", "2026-10-16"])
    assert (tmp_path / "data/landing/autobody/2026-10-16/manifest.json").is_file()
