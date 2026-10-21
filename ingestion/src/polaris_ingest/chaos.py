"""Planned incidents for the production run (Stage 7).

Real production breaks in ways nobody schedules. To practise on-call, the
team lead keeps an incident calendar OUTSIDE the repo, so the engineer
doesn't know which day goes wrong:

    ~/.polaris/chaos.json    {"2026-10-21": ["vendor_bad_manifest"], ...}

The pipeline code is the same in every run. These hooks only change what the
"outside world" (the vendor, the claims app) does on a given day.

  vendor_bad_manifest  vendor's manifest claims one row more than it sent
  vendor_late          vendor sends nothing by the time the pipeline runs
  negative_payment     claims app books a payment reversal as a negative amount
  schema_change        claims app adds a column to the claims table
"""

from __future__ import annotations

import json
import os
from datetime import date
from pathlib import Path

CALENDAR = Path(os.environ.get("POLARIS_CHAOS_FILE", "~/.polaris/chaos.json")).expanduser()


def incidents(day: date) -> set[str]:
    """Incidents planned for `day`. No calendar file = no incidents."""
    if not CALENDAR.is_file():
        return set()
    return set(json.loads(CALENDAR.read_text()).get(day.isoformat(), []))


def apply_claims_app_incidents(conn, day: date) -> list[str]:
    """Run the claims-app side incidents for `day` against Postgres. Returns what ran."""
    planned = incidents(day)
    ran = []
    with conn.transaction(), conn.cursor() as cur:
        if "negative_payment" in planned:
            # A reversal on the newest paid claim, booked as a negative payment
            cur.execute(
                "SELECT claim_id FROM claims_system.claim_payments ORDER BY payment_id DESC LIMIT 1"
            )
            (claim_id,) = cur.fetchone()
            cur.execute("SELECT coalesce(max(substring(payment_id from 5)::int), 0) + 1 FROM claims_system.claim_payments")
            (n,) = cur.fetchone()
            cur.execute(
                "INSERT INTO claims_system.claim_payments VALUES (%s, %s, %s, %s, 'INDEMNITY', %s)",
                (f"PAY_{n:06d}", claim_id, day, -250.00, f"{day} 17:45:00"),
            )
            ran.append("negative_payment")
        if "schema_change" in planned:
            # The claims app ships a release that adds a column, without telling the data team
            cur.execute("ALTER TABLE claims_system.claims ADD COLUMN IF NOT EXISTS catastrophe_code TEXT")
            cur.execute(
                "UPDATE claims_system.claims SET catastrophe_code = 'CAT-2026-ON-STORM', "
                "updated_at = updated_at + interval '1 second' "
                "WHERE report_date = %s AND claim_type IN ('WEATHER', 'WATER')",
                (day,),
            )
            ran.append("schema_change")
    return ran
