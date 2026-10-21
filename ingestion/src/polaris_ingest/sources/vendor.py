"""A vendor feed for Stage 2c: repair estimates from a body-shop network.

Each day the vendor drops two files into the landing container:

    autobody/YYYY-MM-DD/repair_estimates.csv   one estimate per repairable auto claim
    autobody/YYYY-MM-DD/manifest.json          {"row_count": N, "sha256": ..., ...}

The manifest is the vendor's promise of what they sent. ADF copies the CSV to
Bronze and fails the run if the rows it copied don't match row_count. The
manifest is written last, so its presence means the drop is complete.

Same seed + same ingest date = the same file, like the Stage 2 generator.
"""

from __future__ import annotations

import hashlib
import json
import random
from dataclasses import dataclass
from datetime import date, timedelta

from polaris_ingest.landing.bronze import rows_to_csv
from polaris_ingest.landing.sinks import Sink
from polaris_ingest.sources.synthetic import generate

VENDOR = "autobody"
REPAIRABLE = ("COLLISION", "COMPREHENSIVE")  # the auto claims a body shop quotes on
LOOKBACK_DAYS = 7  # estimates for claims reported in the week before the drop
N_SHOPS = 40


@dataclass
class RepairEstimate:
    estimate_id: str
    claim_id: str
    shop_id: str
    estimate_date: date
    parts_amount: float
    labour_amount: float
    total_amount: float
    currency: str


def drop_folder(ingest_date: date) -> str:
    return f"{VENDOR}/{ingest_date:%Y-%m-%d}"


def gen_estimates(ingest_date: date, seed: int = 42) -> list[RepairEstimate]:
    claims = generate(ingest_date, day=1, seed=seed)["claims"]
    window_start = ingest_date - timedelta(days=LOOKBACK_DAYS)
    # Own generator, seeded by the date, so each day's file is stable on its own
    rng = random.Random(seed * 100_000 + ingest_date.toordinal())
    estimates = []
    for c in claims:
        if c.product_type != "AUTO" or c.claim_type not in REPAIRABLE:
            continue
        if not (window_start <= c.report_date < ingest_date):
            continue
        parts = round(rng.uniform(500, 8_000), 2)
        labour = round(rng.uniform(300, 4_000), 2)
        estimates.append(
            RepairEstimate(
                estimate_id=f"EST_{c.claim_id}",
                claim_id=c.claim_id,
                shop_id=f"SHOP_{rng.randint(1, N_SHOPS):03d}",
                estimate_date=min(c.report_date + timedelta(days=rng.randint(1, 3)), ingest_date),
                parts_amount=parts,
                labour_amount=labour,
                total_amount=round(parts + labour, 2),
                currency="CAD",
            )
        )
    return estimates


def drop(sink: Sink, ingest_date: date, seed: int = 42, bad_manifest: bool = False) -> dict:
    """Write the CSV, then the manifest. Returns the manifest.

    bad_manifest=True claims one row more than was sent, to test that the ADF
    pipeline's row-count check fails the run.
    """
    rows = gen_estimates(ingest_date, seed)
    data = rows_to_csv(rows)
    folder = drop_folder(ingest_date)
    sink.write(f"{folder}/repair_estimates.csv", data)
    manifest = {
        "vendor": VENDOR,
        "file": "repair_estimates.csv",
        "ingest_date": ingest_date.isoformat(),
        "row_count": len(rows) + (1 if bad_manifest else 0),
        "sha256": hashlib.sha256(data).hexdigest(),
    }
    sink.write(f"{folder}/manifest.json", json.dumps(manifest, indent=2).encode("utf-8"))
    return manifest
