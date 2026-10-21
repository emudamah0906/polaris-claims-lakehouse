"""One business day in the claims system (Stage 7).

Stage 2b only knew two days. For a production run the claims system has to
keep living: every business day the claims app

  - signs up a few customers and writes new policies
  - reprices a few renewals and cancels a few policies
  - takes in new claims (FNOL), a few of them reported late
  - closes some older open claims: most paid (with payments), some denied

Every change is stamped inside that day's business hours (08:00-18:00 UTC),
so the next extract picks up exactly that day. The same date gives the same
changes, and a day already applied is skipped (claims_system.sim_days), so a
retry can't apply a day twice.

Claim amounts here are realistic (no x100), unlike the Stage 2 baseline.
"""

from __future__ import annotations

import random
from datetime import date, datetime, time, timedelta

from faker import Faker

from polaris_ingest.sources.postgres import SCHEMA
from polaris_ingest.sources.synthetic import (
    AUTO_CLAIM_TYPES,
    N_ADJUSTERS,
    ONTARIO_CITIES,
    PROPERTY_CLAIM_TYPES,
    canadian_postal,
    canadian_sin,
    years_ago,
)

# Volume per business day
NEW_CUSTOMERS = (5, 15)
NEW_POLICIES = (10, 25)
REPRICED = (8, 15)
CANCELLED = (3, 8)
NEW_CLAIMS = (40, 70)
PCT_LATE_FNOL = 0.05
PCT_FRAUD = 0.03
PCT_OPEN_CLOSED_PER_DAY = 0.08  # of open claims reported 3+ days ago
PCT_CLOSED_AS_DENIED = 0.25


def simulate_day(conn, day: date, seed: int = 42) -> dict[str, int]:
    """Apply one business day. Returns counts of what changed, or {} if already applied."""
    rng = random.Random(seed * 1_000_000 + day.toordinal())
    fake = Faker("en_CA")
    fake.seed_instance(seed * 1_000_000 + day.toordinal())

    def stamp() -> datetime:
        # A moment inside business hours on `day`
        return datetime.combine(day, time(8)) + timedelta(seconds=rng.randint(0, 10 * 3600))

    counts = dict.fromkeys(
        ["customers", "policies", "repriced", "cancelled", "claims", "paid", "denied", "payments"], 0
    )
    with conn.transaction(), conn.cursor() as cur:
        cur.execute(f"CREATE TABLE IF NOT EXISTS {SCHEMA}.sim_days (day DATE PRIMARY KEY, applied_at TIMESTAMP NOT NULL DEFAULT now())")
        cur.execute(f"INSERT INTO {SCHEMA}.sim_days (day) VALUES (%s) ON CONFLICT DO NOTHING", (day,))
        if cur.rowcount == 0:
            return {}

        next_id = _next_ids(cur)

        # ── New customers ────────────────────────────────────────────────────
        new_customers = []
        for _ in range(rng.randint(*NEW_CUSTOMERS)):
            first, last, ts = fake.first_name(), fake.last_name(), stamp()
            cid = f"CUST_{next_id['customers']:05d}"
            next_id["customers"] += 1
            new_customers.append(cid)
            cur.execute(
                f"INSERT INTO {SCHEMA}.customers VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (cid, first, last, canadian_sin(fake),
                 fake.date_between(start_date=years_ago(day, 80), end_date=years_ago(day, 18)),
                 f"{first.lower()}.{last.lower()}@example.com",
                 f"416-{rng.randint(200, 999)}-{rng.randint(1000, 9999)}",
                 fake.street_address(), rng.choice(ONTARIO_CITIES), "ON", canadian_postal(fake),
                 ts, ts),
            )
        counts["customers"] = len(new_customers)

        # ── New policies, starting today ─────────────────────────────────────
        cur.execute(f"SELECT customer_id FROM {SCHEMA}.customers ORDER BY customer_id")
        all_customers = [r[0] for r in cur.fetchall()]
        for i in range(rng.randint(*NEW_POLICIES)):
            # Every new customer gets a policy; the rest go to existing customers
            cust = new_customers[i] if i < len(new_customers) else rng.choice(all_customers)
            product = "AUTO" if rng.random() < 0.6 else "PROPERTY"
            premium = round(rng.uniform(800, 3000) if product == "AUTO" else rng.uniform(1000, 4000), 2)
            coverage = float(rng.choice([25_000, 50_000, 100_000, 200_000] if product == "AUTO"
                                        else [200_000, 500_000, 750_000, 1_000_000]))
            ts = stamp()
            cur.execute(
                f"INSERT INTO {SCHEMA}.policies VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (f"POL_{next_id['policies']:05d}", cust, product, day, day + timedelta(days=365),
                 premium, coverage, "ACTIVE", ts, ts),
            )
            next_id["policies"] += 1
            counts["policies"] += 1

        # ── Renewals repriced, policies cancelled ────────────────────────────
        cur.execute(f"SELECT policy_id FROM {SCHEMA}.policies WHERE status = 'ACTIVE' AND effective_date < %s ORDER BY policy_id", (day,))
        active = [r[0] for r in cur.fetchall()]
        for pid in rng.sample(active, rng.randint(*REPRICED)):
            cur.execute(
                f"UPDATE {SCHEMA}.policies SET annual_premium = round(annual_premium * %s::numeric, 2), updated_at = %s WHERE policy_id = %s",
                (round(rng.uniform(1.02, 1.12), 4), stamp(), pid),
            )
            counts["repriced"] += 1
        for pid in rng.sample(active, rng.randint(*CANCELLED)):
            cur.execute(
                f"UPDATE {SCHEMA}.policies SET status = 'CANCELLED', updated_at = %s WHERE policy_id = %s",
                (stamp(), pid),
            )
            counts["cancelled"] += 1

        # ── New claims (FNOL) on policies in force ───────────────────────────
        cur.execute(
            f"SELECT policy_id, customer_id, product_type, effective_date, coverage_limit FROM {SCHEMA}.policies "
            f"WHERE status = 'ACTIVE' AND effective_date <= %s ORDER BY policy_id", (day,)
        )
        in_force = cur.fetchall()
        for _ in range(rng.randint(*NEW_CLAIMS)):
            pid, cust, product, effective, coverage = rng.choice(in_force)
            delay = rng.randint(8, 30) if rng.random() < PCT_LATE_FNOL else rng.randint(0, 3)
            loss = max(day - timedelta(days=delay), effective)
            if product == "AUTO":
                ctype, amount = rng.choice(AUTO_CLAIM_TYPES), rng.lognormvariate(7.5, 1.0)
            else:
                ctype, amount = rng.choice(PROPERTY_CLAIM_TYPES), rng.lognormvariate(8.5, 1.2)
            is_fraud = rng.random() < PCT_FRAUD
            ts = stamp()
            n = next_id["claims"]
            cur.execute(
                f"INSERT INTO {SCHEMA}.claims VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (f"CLM_{n:05d}", f"CLM-{day.year}-{n:06d}", pid, cust, product, ctype, loss, day,
                 min(round(amount, 2), float(coverage)), "OPEN", is_fraud,
                 round(rng.uniform(0.7, 0.99) if is_fraud else rng.uniform(0.0, 0.4), 3),
                 f"ADJ_{rng.randint(1, N_ADJUSTERS):03d}", ts, ts),
            )
            next_id["claims"] += 1
            counts["claims"] += 1

        # ── Older open claims close: paid (with payments) or denied ──────────
        cur.execute(
            f"SELECT claim_id, claim_amount FROM {SCHEMA}.claims "
            f"WHERE status = 'OPEN' AND report_date <= %s ORDER BY claim_id", (day - timedelta(days=3),)
        )
        open_claims = cur.fetchall()
        for cid, amount in rng.sample(open_claims, int(len(open_claims) * PCT_OPEN_CLOSED_PER_DAY)):
            ts = stamp()
            if rng.random() < PCT_CLOSED_AS_DENIED:
                cur.execute(f"UPDATE {SCHEMA}.claims SET status = 'DENIED', updated_at = %s WHERE claim_id = %s", (ts, cid))
                counts["denied"] += 1
                continue
            cur.execute(f"UPDATE {SCHEMA}.claims SET status = 'PAID', updated_at = %s WHERE claim_id = %s", (ts, cid))
            counts["paid"] += 1
            # Paid in full: indemnity, plus an expense share on some claims
            parts = [float(amount)] if rng.random() < 0.6 else _split(rng, float(amount))
            for part, ptype in zip(parts, ["INDEMNITY", "EXPENSE"]):
                cur.execute(
                    f"INSERT INTO {SCHEMA}.claim_payments VALUES (%s,%s,%s,%s,%s,%s)",
                    (f"PAY_{next_id['payments']:06d}", cid, day, part, ptype, ts),
                )
                next_id["payments"] += 1
                counts["payments"] += 1
    return counts


def _split(rng: random.Random, amount: float) -> list[float]:
    indemnity = round(amount * rng.uniform(0.75, 0.9), 2)
    return [indemnity, round(amount - indemnity, 2)]


def _next_ids(cur) -> dict[str, int]:
    """Next free number for each table's ID, e.g. CLM_10051 -> 10052."""
    ids = {}
    for table, col, prefix_len in [
        ("customers", "customer_id", 5), ("policies", "policy_id", 4),
        ("claims", "claim_id", 4), ("payments", "payment_id", 4),
    ]:
        name = "claim_payments" if table == "payments" else table
        cur.execute(f"SELECT coalesce(max(substring({col} from {prefix_len + 1})::int), 0) + 1 FROM {SCHEMA}.{name}")
        ids[table] = cur.fetchone()[0]
    return ids
