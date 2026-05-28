#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = ["faker>=25.0"]
# ///
"""Synthetic P&C claims dataset generator for Polaris.

Outputs 4 CSVs to --out (default: data/raw/):
  customers.csv         ~3K rows  (with PII: SSN, DOB, address, phone)
  policies.csv          ~5K rows  (AUTO + PROPERTY lines of business)
  claims.csv            ~10K rows (with late-arriving FNOL + fraud signals)
  claim_payments.csv    ~18K rows (transaction-grain payouts)

Use --day 2 to simulate a daily refresh:
  - 5% of policies get an annual_premium bump (renewal)
  - 2% get coverage_limit changed
  - 1% flip to CANCELLED status
  - ~50 new claims with loss_date in the last 24h
  - A subset of OPEN claims close out with payments
This is what drives the dbt snapshot (SCD2) demo: re-run with --day 2,
re-load to Snowflake, dbt snapshot captures the change history.

Usage:
  uv run scripts/generate_polaris_data.py --day 1 --seed 42
  uv run scripts/generate_polaris_data.py --day 2 --seed 42
"""

from __future__ import annotations

import argparse
import csv
import random
from dataclasses import dataclass, fields
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from faker import Faker

# ── Volume knobs ──────────────────────────────────────────────────────────────
N_CUSTOMERS = 3_000
N_POLICIES = 5_000
N_CLAIMS = 10_000
N_ADJUSTERS = 50

# ── Realism knobs ─────────────────────────────────────────────────────────────
PCT_LATE_ARRIVING_FNOL = 0.05  # 5% of claims report > 7 days after loss
PCT_FRAUD = 0.03  # ~3% flagged fraudulent
PCT_AUTO = 0.60  # 60/40 auto/property split

# Day-2 update rates
PCT_POLICY_PREMIUM_BUMP = 0.05
PCT_POLICY_COVERAGE_CHANGE = 0.02
PCT_POLICY_CANCELLED = 0.01
N_NEW_CLAIMS_DAY2 = 50

# Thresholds (match dbt_project.yml vars where applicable)
DAY_BASELINE = 1
DAY_REFRESH = 2
FNOL_LATE_WINDOW_DAYS = 7
FRAUD_RECENT_POLICY_DAYS = 30

ONTARIO_CITIES = [
    "Toronto",
    "Mississauga",
    "Brampton",
    "Hamilton",
    "London",
    "Markham",
    "Vaughan",
    "Kitchener",
    "Windsor",
    "Richmond Hill",
    "Oakville",
    "Burlington",
    "Oshawa",
    "Barrie",
    "St. Catharines",
    "Cambridge",
    "Kingston",
    "Whitby",
    "Guelph",
    "Ajax",
    "Waterloo",
    "Niagara Falls",
    "Pickering",
    "Newmarket",
]

AUTO_CLAIM_TYPES = ["COLLISION", "COMPREHENSIVE", "LIABILITY", "INJURY"]
PROPERTY_CLAIM_TYPES = ["FIRE", "WATER", "THEFT", "LIABILITY", "WEATHER"]
CLAIM_STATUSES = ["OPEN", "CLOSED", "PAID", "DENIED"]
CLAIM_STATUS_WEIGHTS = [0.20, 0.40, 0.30, 0.10]
POLICY_STATUSES = ["ACTIVE", "EXPIRED", "CANCELLED"]
POLICY_STATUS_WEIGHTS = [0.85, 0.10, 0.05]
PAYMENT_TYPES = ["INDEMNITY", "EXPENSE", "RECOVERY"]
PAYMENT_TYPE_WEIGHTS = [0.80, 0.15, 0.05]


# ── Row shapes ────────────────────────────────────────────────────────────────
@dataclass
class Customer:
    customer_id: str
    first_name: str
    last_name: str
    ssn: str
    dob: date
    email: str
    phone: str
    address_line1: str
    city: str
    province: str
    postal_code: str
    created_at: datetime
    updated_at: datetime


@dataclass
class Policy:
    policy_id: str
    customer_id: str
    product_type: str
    effective_date: date
    expiry_date: date
    annual_premium: float
    coverage_limit: float
    status: str
    created_at: datetime
    updated_at: datetime


@dataclass
class Claim:
    claim_id: str
    claim_number: str
    policy_id: str
    customer_id: str
    product_type: str
    claim_type: str
    loss_date: date
    report_date: date
    claim_amount: float
    status: str
    is_fraud: bool
    fraud_score: float
    adjuster_id: str
    created_at: datetime
    updated_at: datetime


@dataclass
class ClaimPayment:
    payment_id: str
    claim_id: str
    payment_date: date
    payment_amount: float
    payment_type: str
    created_at: datetime


# ── Helpers ───────────────────────────────────────────────────────────────────
def canadian_sin(fake: Faker) -> str:
    """Return a 9-digit SIN-formatted string (not real, for synthetic PII)."""
    seg = fake.random_int
    return f"{seg(100, 999)}-{seg(100, 999)}-{seg(100, 999)}"


def canadian_postal(fake: Faker) -> str:
    letters = "ABCEGHJKLMNPRSTVWXYZ"
    digits = "0123456789"
    el = fake.random_element
    return f"{el(letters)}{el(digits)}{el(letters)} " f"{el(digits)}{el(letters)}{el(digits)}"


def write_csv(path: Path, rows: list[Any]) -> None:
    if not rows:
        return
    cols = [f.name for f in fields(rows[0])]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(cols)
        for r in rows:
            w.writerow([getattr(r, c) for c in cols])
    print(f"  wrote {len(rows):>6,} rows → {path}")


# ── Generators ────────────────────────────────────────────────────────────────
def gen_customers(fake: Faker, now: datetime) -> list[Customer]:
    customers: list[Customer] = []
    for i in range(1, N_CUSTOMERS + 1):
        first = fake.first_name()
        last = fake.last_name()
        created = fake.date_time_between(start_date="-5y", end_date="-30d")
        customers.append(
            Customer(
                customer_id=f"CUST_{i:05d}",
                first_name=first,
                last_name=last,
                ssn=canadian_sin(fake),
                dob=fake.date_of_birth(minimum_age=18, maximum_age=90),
                email=f"{first.lower()}.{last.lower()}@example.com",
                phone=f"416-{fake.random_int(200, 999)}-{fake.random_int(1000, 9999)}",
                address_line1=fake.street_address(),
                city=random.choice(ONTARIO_CITIES),
                province="ON",
                postal_code=canadian_postal(fake),
                created_at=created,
                updated_at=created,
            )
        )
    return customers


def gen_policies(fake: Faker, customers: list[Customer], now: datetime) -> list[Policy]:
    policies: list[Policy] = []
    for i in range(1, N_POLICIES + 1):
        cust = random.choice(customers)
        product_type = "AUTO" if random.random() < PCT_AUTO else "PROPERTY"
        effective = fake.date_between(start_date="-3y", end_date="-30d")
        expiry = effective + timedelta(days=365)
        if product_type == "AUTO":
            premium = round(random.uniform(800, 3000), 2)
            coverage = float(random.choice([25_000, 50_000, 100_000, 200_000]))
        else:
            premium = round(random.uniform(1000, 4000), 2)
            coverage = float(random.choice([200_000, 500_000, 750_000, 1_000_000]))
        status = random.choices(POLICY_STATUSES, POLICY_STATUS_WEIGHTS, k=1)[0]
        created = datetime.combine(effective, datetime.min.time())
        policies.append(
            Policy(
                policy_id=f"POL_{i:05d}",
                customer_id=cust.customer_id,
                product_type=product_type,
                effective_date=effective,
                expiry_date=expiry,
                annual_premium=premium,
                coverage_limit=coverage,
                status=status,
                created_at=created,
                updated_at=created,
            )
        )
    return policies


def gen_claims(fake: Faker, policies: list[Policy], now: datetime) -> list[Claim]:
    claims: list[Claim] = []
    for i in range(1, N_CLAIMS + 1):
        pol = random.choice(policies)
        loss_date = fake.date_between(
            start_date=pol.effective_date, end_date=min(pol.expiry_date, now.date())
        )

        # Late-arriving FNOL: 5% report > 7 days after loss
        if random.random() < PCT_LATE_ARRIVING_FNOL:
            report_delay = random.randint(8, 30)
        else:
            report_delay = random.randint(0, 3)
        report_date = min(loss_date + timedelta(days=report_delay), now.date())

        if pol.product_type == "AUTO":
            claim_type = random.choice(AUTO_CLAIM_TYPES)
            base_amount = random.lognormvariate(7.5, 1.0)
            claim_amount = min(round(base_amount * 100, 2), pol.coverage_limit)
        else:
            claim_type = random.choice(PROPERTY_CLAIM_TYPES)
            base_amount = random.lognormvariate(8.5, 1.2)
            claim_amount = min(round(base_amount * 100, 2), pol.coverage_limit)

        # Fraud signals
        days_since_policy_start = (loss_date - pol.effective_date).days
        is_fraud = random.random() < PCT_FRAUD
        if is_fraud:
            # Suspicious patterns: claim very soon + high amount
            fraud_score = round(random.uniform(0.7, 0.99), 3)
            if days_since_policy_start < FRAUD_RECENT_POLICY_DAYS:
                claim_amount = round(pol.coverage_limit * random.uniform(0.7, 0.95), 2)
        else:
            fraud_score = round(random.uniform(0.0, 0.4), 3)

        status = random.choices(CLAIM_STATUSES, CLAIM_STATUS_WEIGHTS, k=1)[0]
        created = datetime.combine(report_date, datetime.min.time())
        updated = created + timedelta(days=random.randint(0, 60))

        claims.append(
            Claim(
                claim_id=f"CLM_{i:05d}",
                claim_number=f"CLM-{report_date.year}-{i:06d}",
                policy_id=pol.policy_id,
                customer_id=pol.customer_id,
                product_type=pol.product_type,
                claim_type=claim_type,
                loss_date=loss_date,
                report_date=report_date,
                claim_amount=claim_amount,
                status=status,
                is_fraud=is_fraud,
                fraud_score=fraud_score,
                adjuster_id=f"ADJ_{random.randint(1, N_ADJUSTERS):03d}",
                created_at=created,
                updated_at=updated,
            )
        )
    return claims


def gen_payments(claims: list[Claim]) -> list[ClaimPayment]:
    payments: list[ClaimPayment] = []
    pay_id = 1
    for c in claims:
        if c.status not in ("CLOSED", "PAID"):
            continue
        # 1-3 payments per closed/paid claim
        n_pay = random.choices([1, 2, 3], [0.55, 0.30, 0.15], k=1)[0]
        remaining = c.claim_amount
        for k in range(n_pay):
            if k == n_pay - 1:
                amount = round(remaining, 2)
            else:
                amount = round(remaining * random.uniform(0.3, 0.6), 2)
                remaining -= amount
            payment_date = c.report_date + timedelta(days=random.randint(7, 120))
            payments.append(
                ClaimPayment(
                    payment_id=f"PAY_{pay_id:06d}",
                    claim_id=c.claim_id,
                    payment_date=payment_date,
                    payment_amount=amount,
                    payment_type=random.choices(PAYMENT_TYPES, PAYMENT_TYPE_WEIGHTS, k=1)[0],
                    created_at=datetime.combine(payment_date, datetime.min.time()),
                )
            )
            pay_id += 1
    return payments


# ── Day-2 mutations ───────────────────────────────────────────────────────────
def apply_day2_changes(
    fake: Faker,
    customers: list[Customer],
    policies: list[Policy],
    claims: list[Claim],
    payments: list[ClaimPayment],
    now: datetime,
) -> None:
    """Mutate in place to simulate a day-2 refresh — drives the SCD2 demo."""
    bumped_at = now

    # 5% premium bumps
    for pol in random.sample(policies, int(len(policies) * PCT_POLICY_PREMIUM_BUMP)):
        pol.annual_premium = round(pol.annual_premium * random.uniform(1.03, 1.15), 2)
        pol.updated_at = bumped_at

    # 2% coverage changes
    for pol in random.sample(policies, int(len(policies) * PCT_POLICY_COVERAGE_CHANGE)):
        pol.coverage_limit = round(pol.coverage_limit * random.choice([0.5, 1.5, 2.0]), 2)
        pol.updated_at = bumped_at

    # 1% cancelled
    active = [p for p in policies if p.status == "ACTIVE"]
    for pol in random.sample(active, max(1, int(len(active) * PCT_POLICY_CANCELLED))):
        pol.status = "CANCELLED"
        pol.updated_at = bumped_at

    # New claims (~50) with loss in last 24h
    next_idx = len(claims) + 1
    eligible = [p for p in policies if p.status == "ACTIVE"]
    for j in range(N_NEW_CLAIMS_DAY2):
        pol = random.choice(eligible)
        loss = now.date()
        report = loss
        if pol.product_type == "AUTO":
            ctype = random.choice(AUTO_CLAIM_TYPES)
            amount = round(random.lognormvariate(7.5, 1.0) * 100, 2)
        else:
            ctype = random.choice(PROPERTY_CLAIM_TYPES)
            amount = round(random.lognormvariate(8.5, 1.2) * 100, 2)
        amount = min(amount, pol.coverage_limit)
        claims.append(
            Claim(
                claim_id=f"CLM_{next_idx + j:05d}",
                claim_number=f"CLM-{loss.year}-{next_idx + j:06d}",
                policy_id=pol.policy_id,
                customer_id=pol.customer_id,
                product_type=pol.product_type,
                claim_type=ctype,
                loss_date=loss,
                report_date=report,
                claim_amount=amount,
                status="OPEN",
                is_fraud=False,
                fraud_score=round(random.uniform(0.0, 0.4), 3),
                adjuster_id=f"ADJ_{random.randint(1, N_ADJUSTERS):03d}",
                created_at=bumped_at,
                updated_at=bumped_at,
            )
        )

    # Close out some OPEN claims with payments
    open_claims = [c for c in claims if c.status == "OPEN"]
    closing = random.sample(open_claims, min(100, len(open_claims)))
    pay_id = len(payments) + 1
    for c in closing:
        c.status = "PAID"
        c.updated_at = bumped_at
        payments.append(
            ClaimPayment(
                payment_id=f"PAY_{pay_id:06d}",
                claim_id=c.claim_id,
                payment_date=now.date(),
                payment_amount=c.claim_amount,
                payment_type="INDEMNITY",
                created_at=bumped_at,
            )
        )
        pay_id += 1


# ── Main ──────────────────────────────────────────────────────────────────────
def main() -> None:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument(
        "--day", type=int, choices=[1, 2], default=1, help="Day 1 baseline or Day 2 refresh."
    )
    ap.add_argument("--seed", type=int, default=42, help="Deterministic seed.")
    ap.add_argument("--out", type=Path, default=Path("data/raw"), help="Output dir for CSVs.")
    args = ap.parse_args()

    random.seed(args.seed)
    fake = Faker("en_CA")
    Faker.seed(args.seed)
    now = datetime.now()

    print(f"\n[polaris-gen] day={args.day} seed={args.seed} out={args.out}")
    print("[polaris-gen] generating baseline (day 1)...")
    customers = gen_customers(fake, now)
    policies = gen_policies(fake, customers, now)
    claims = gen_claims(fake, policies, now)
    payments = gen_payments(claims)

    if args.day == DAY_REFRESH:
        print("[polaris-gen] applying day-2 mutations (SCD2 + new claims)...")
        apply_day2_changes(fake, customers, policies, claims, payments, now)

    print("[polaris-gen] writing CSVs...")
    write_csv(args.out / "customers.csv", customers)
    write_csv(args.out / "policies.csv", policies)
    write_csv(args.out / "claims.csv", claims)
    write_csv(args.out / "claim_payments.csv", payments)

    late = sum(1 for c in claims if (c.report_date - c.loss_date).days > FNOL_LATE_WINDOW_DAYS)
    fraud = sum(1 for c in claims if c.is_fraud)
    print("\n[polaris-gen] summary:")
    print(f"  customers       : {len(customers):>6,}")
    print(f"  policies        : {len(policies):>6,}")
    print(f"  claims          : {len(claims):>6,}")
    print(f"    late-arriving : {late:>6,}  ({late / len(claims):.1%})")
    print(f"    fraud-flagged : {fraud:>6,}  ({fraud / len(claims):.1%})")
    print(f"  claim_payments  : {len(payments):>6,}")
    print("\n[polaris-gen] done.\n")


if __name__ == "__main__":
    main()
