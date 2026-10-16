#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = ["faker>=25.0"]
# ///
"""Write one day of synthetic Polaris data as flat CSVs in --out (default data/raw/).

The generator itself now lives in ingestion/src/polaris_ingest/sources/synthetic.py.
This script is kept for quick looks at the data. To land data in the Bronze
layout, use `uv run polaris-ingest run --ingest-date YYYY-MM-DD` instead.

Usage:
  uv run scripts/generate_polaris_data.py --day 1 --as-of 2026-10-16
  uv run scripts/generate_polaris_data.py --day 2 --as-of 2026-10-17
"""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

# Import the package straight from the repo, so this works without installing it
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "ingestion" / "src"))

from polaris_ingest.landing.bronze import rows_to_csv  # noqa: E402
from polaris_ingest.sources.synthetic import FNOL_LATE_WINDOW_DAYS, generate  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--day", type=int, choices=[1, 2], default=1)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--as-of", type=date.fromisoformat, default=date.today(),
                    help="Date the data is generated for, YYYY-MM-DD (default today)")
    ap.add_argument("--out", type=Path, default=Path("data/raw"))
    args = ap.parse_args()

    tables = generate(args.as_of, day=args.day, seed=args.seed)
    args.out.mkdir(parents=True, exist_ok=True)
    for table, rows in tables.items():
        path = args.out / f"{table}.csv"
        path.write_bytes(rows_to_csv(rows))
        print(f"  {table:<15} {len(rows):>6,} rows  ->  {path}")

    claims = tables["claims"]
    late = sum(1 for c in claims if (c.report_date - c.loss_date).days > FNOL_LATE_WINDOW_DAYS)
    fraud = sum(1 for c in claims if c.is_fraud)
    print(f"  late-arriving FNOL: {late:,} ({late / len(claims):.1%})")
    print(f"  fraud-flagged:      {fraud:,} ({fraud / len(claims):.1%})")


if __name__ == "__main__":
    main()
