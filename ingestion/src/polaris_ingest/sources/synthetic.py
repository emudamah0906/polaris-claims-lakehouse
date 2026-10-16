"""Synthetic P&C claims data for Polaris.

Produces four tables for one day:
  customers        3,000 rows (with PII: SIN, date of birth, address, phone)
  policies         5,000 rows (AUTO 60% / PROPERTY 40%)
  claims          10,000 rows (5% late-arriving FNOL, ~3% fraud-flagged)
  claim_payments  1-3 payments per CLOSED or PAID claim

Day 2 replays day 1, then changes it the way a daily refresh would:
premium bumps, coverage changes, cancellations, ~50 new claims and some
claims closing with payments. Stage 3 uses that to demo SCD2 history.

Same seed + same ingest date = the same rows, every time. Two things make
that true:
  - Every date is worked out from the ingest date, never from the clock.
    Reading datetime.now() (or Faker's "-5y" style dates, which also read the
    clock) would change the data on every run, and a retry would land
    different bytes than the first attempt.
  - Each run gets its own seeded random generators instead of the shared
    module-level ones, so nothing else in the process can shift the sequence.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

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
N_CLAIMS_CLOSED_DAY2 = 100

# Thresholds (match dbt_project.yml vars where applicable)
FNOL_LATE_WINDOW_DAYS = 7
FRAUD_RECENT_POLICY_DAYS = 30

ONTARIO_CITIES = [
    "Toronto", "Mississauga", "Brampton", "Hamilton", "London", "Markham",
    "Vaughan", "Kitchener", "Windsor", "Richmond Hill", "Oakville", "Burlington",
    "Oshawa", "Barrie", "St. Catharines", "Cambridge", "Kingston", "Whitby",
    "Guelph", "Ajax", "Waterloo", "Niagara Falls", "Pickering", "Newmarket",
]  # fmt: skip

AUTO_CLAIM_TYPES = ["COLLISION", "COMPREHENSIVE", "LIABILITY", "INJURY"]
PROPERTY_CLAIM_TYPES = ["FIRE", "WATER", "THEFT", "LIABILITY", "WEATHER"]
CLAIM_STATUSES = ["OPEN", "CLOSED", "PAID", "DENIED"]
CLAIM_STATUS_WEIGHTS = [0.20, 0.40, 0.30, 0.10]
POLICY_STATUSES = ["ACTIVE", "EXPIRED", "CANCELLED"]
POLICY_STATUS_WEIGHTS = [0.85, 0.10, 0.05]
PAYMENT_TYPES = ["INDEMNITY", "EXPENSE", "RECOVERY"]
PAYMENT_TYPE_WEIGHTS = [0.80, 0.15, 0.05]


# ── Row shapes ────────────────────────────────────────────────────────────────
# Field order here is the column order in the CSV.
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
def years_ago(d: date, years: int) -> date:
    """Same calendar day `years` back. Feb 29 falls back to Feb 28."""
    try:
        return d.replace(year=d.year - years)
    except ValueError:
        return d.replace(year=d.year - years, day=28)


def canadian_sin(fake: Faker) -> str:
    """9-digit SIN-shaped string. Not a real SIN, synthetic PII only."""
    seg = fake.random_int
    return f"{seg(100, 999)}-{seg(100, 999)}-{seg(100, 999)}"


def canadian_postal(fake: Faker) -> str:
    letters = "ABCEGHJKLMNPRSTVWXYZ"
    digits = "0123456789"
    el = fake.random_element
    return f"{el(letters)}{el(digits)}{el(letters)} {el(digits)}{el(letters)}{el(digits)}"


# ── Day-1 tables ──────────────────────────────────────────────────────────────
def gen_customers(fake: Faker, rng: random.Random, as_of: datetime) -> list[Customer]:
    customers: list[Customer] = []
    for i in range(1, N_CUSTOMERS + 1):
        first = fake.first_name()
        last = fake.last_name()
        # Customer since: between 5 years and 30 days before as_of
        created = fake.date_time_between(
            start_date=as_of - timedelta(days=5 * 365), end_date=as_of - timedelta(days=30)
        )
        customers.append(
            Customer(
                customer_id=f"CUST_{i:05d}",
                first_name=first,
                last_name=last,
                ssn=canadian_sin(fake),
                # Aged 18 to 90 on as_of
                dob=fake.date_between(
                    start_date=years_ago(as_of.date(), 90), end_date=years_ago(as_of.date(), 18)
                ),
                email=f"{first.lower()}.{last.lower()}@example.com",
                phone=f"416-{fake.random_int(200, 999)}-{fake.random_int(1000, 9999)}",
                address_line1=fake.street_address(),
                city=rng.choice(ONTARIO_CITIES),
                province="ON",
                postal_code=canadian_postal(fake),
                created_at=created,
                updated_at=created,
            )
        )
    return customers


def gen_policies(
    fake: Faker, rng: random.Random, customers: list[Customer], as_of: datetime
) -> list[Policy]:
    policies: list[Policy] = []
    for i in range(1, N_POLICIES + 1):
        cust = rng.choice(customers)
        product_type = "AUTO" if rng.random() < PCT_AUTO else "PROPERTY"
        # Started between 3 years and 30 days before as_of, runs one year
        effective = fake.date_between(
            start_date=as_of.date() - timedelta(days=3 * 365),
            end_date=as_of.date() - timedelta(days=30),
        )
        expiry = effective + timedelta(days=365)
        if product_type == "AUTO":
            premium = round(rng.uniform(800, 3000), 2)
            coverage = float(rng.choice([25_000, 50_000, 100_000, 200_000]))
        else:
            premium = round(rng.uniform(1000, 4000), 2)
            coverage = float(rng.choice([200_000, 500_000, 750_000, 1_000_000]))
        status = rng.choices(POLICY_STATUSES, POLICY_STATUS_WEIGHTS, k=1)[0]
        created = datetime.combine(effective, time())
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


def gen_claims(
    fake: Faker, rng: random.Random, policies: list[Policy], as_of: datetime
) -> list[Claim]:
    claims: list[Claim] = []
    for i in range(1, N_CLAIMS + 1):
        pol = rng.choice(policies)
        # Loss happens while the policy is in force, and not after as_of
        loss_date = fake.date_between(
            start_date=pol.effective_date, end_date=min(pol.expiry_date, as_of.date())
        )

        # Late-arriving FNOL: 5% report more than 7 days after the loss
        if rng.random() < PCT_LATE_ARRIVING_FNOL:
            report_delay = rng.randint(8, 30)
        else:
            report_delay = rng.randint(0, 3)
        report_date = min(loss_date + timedelta(days=report_delay), as_of.date())

        if pol.product_type == "AUTO":
            claim_type = rng.choice(AUTO_CLAIM_TYPES)
            base_amount = rng.lognormvariate(7.5, 1.0)
        else:
            claim_type = rng.choice(PROPERTY_CLAIM_TYPES)
            base_amount = rng.lognormvariate(8.5, 1.2)
        claim_amount = min(round(base_amount * 100, 2), pol.coverage_limit)

        # Fraud signal: a big claim soon after the policy started
        days_since_policy_start = (loss_date - pol.effective_date).days
        is_fraud = rng.random() < PCT_FRAUD
        if is_fraud:
            fraud_score = round(rng.uniform(0.7, 0.99), 3)
            if days_since_policy_start < FRAUD_RECENT_POLICY_DAYS:
                claim_amount = round(pol.coverage_limit * rng.uniform(0.7, 0.95), 2)
        else:
            fraud_score = round(rng.uniform(0.0, 0.4), 3)

        status = rng.choices(CLAIM_STATUSES, CLAIM_STATUS_WEIGHTS, k=1)[0]
        created = datetime.combine(report_date, time())
        # Last touched up to 60 days after reporting, but never after as_of.
        # A future updated_at would push an incremental extract's watermark
        # past today, and it would silently skip tomorrow's real changes.
        updated = min(created + timedelta(days=rng.randint(0, 60)), as_of)

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
                adjuster_id=f"ADJ_{rng.randint(1, N_ADJUSTERS):03d}",
                created_at=created,
                updated_at=updated,
            )
        )
    return claims


def gen_payments(rng: random.Random, claims: list[Claim], as_of: datetime) -> list[ClaimPayment]:
    payments: list[ClaimPayment] = []
    pay_id = 1
    for c in claims:
        if c.status not in ("CLOSED", "PAID"):
            continue
        # 1 to 3 payments per closed or paid claim, adding up to the claim amount
        n_pay = rng.choices([1, 2, 3], [0.55, 0.30, 0.15], k=1)[0]
        remaining = c.claim_amount
        for k in range(n_pay):
            if k == n_pay - 1:
                amount = round(remaining, 2)
            else:
                amount = round(remaining * rng.uniform(0.3, 0.6), 2)
                remaining -= amount
            # 7 to 120 days after reporting, capped at as_of: no payments from the future
            payment_date = min(c.report_date + timedelta(days=rng.randint(7, 120)), as_of.date())
            payments.append(
                ClaimPayment(
                    payment_id=f"PAY_{pay_id:06d}",
                    claim_id=c.claim_id,
                    payment_date=payment_date,
                    payment_amount=amount,
                    payment_type=rng.choices(PAYMENT_TYPES, PAYMENT_TYPE_WEIGHTS, k=1)[0],
                    created_at=datetime.combine(payment_date, time()),
                )
            )
            pay_id += 1
    return payments


# ── Day-2 changes ─────────────────────────────────────────────────────────────
def apply_day2_changes(
    rng: random.Random,
    policies: list[Policy],
    claims: list[Claim],
    payments: list[ClaimPayment],
    stamp: datetime,
) -> None:
    """Change day-1 rows in place, the way a daily refresh would. `stamp` is day 2's date."""
    # 5% premium bumps
    for pol in rng.sample(policies, int(len(policies) * PCT_POLICY_PREMIUM_BUMP)):
        pol.annual_premium = round(pol.annual_premium * rng.uniform(1.03, 1.15), 2)
        pol.updated_at = stamp

    # 2% coverage changes
    for pol in rng.sample(policies, int(len(policies) * PCT_POLICY_COVERAGE_CHANGE)):
        pol.coverage_limit = round(pol.coverage_limit * rng.choice([0.5, 1.5, 2.0]), 2)
        pol.updated_at = stamp

    # 1% of active policies cancelled
    active = [p for p in policies if p.status == "ACTIVE"]
    for pol in rng.sample(active, max(1, int(len(active) * PCT_POLICY_CANCELLED))):
        pol.status = "CANCELLED"
        pol.updated_at = stamp

    # ~50 new claims, loss and report both on day 2
    next_idx = len(claims) + 1
    eligible = [p for p in policies if p.status == "ACTIVE"]
    for j in range(N_NEW_CLAIMS_DAY2):
        pol = rng.choice(eligible)
        loss = stamp.date()
        if pol.product_type == "AUTO":
            ctype = rng.choice(AUTO_CLAIM_TYPES)
            amount = round(rng.lognormvariate(7.5, 1.0) * 100, 2)
        else:
            ctype = rng.choice(PROPERTY_CLAIM_TYPES)
            amount = round(rng.lognormvariate(8.5, 1.2) * 100, 2)
        claims.append(
            Claim(
                claim_id=f"CLM_{next_idx + j:05d}",
                claim_number=f"CLM-{loss.year}-{next_idx + j:06d}",
                policy_id=pol.policy_id,
                customer_id=pol.customer_id,
                product_type=pol.product_type,
                claim_type=ctype,
                loss_date=loss,
                report_date=loss,
                claim_amount=min(amount, pol.coverage_limit),
                status="OPEN",
                is_fraud=False,
                fraud_score=round(rng.uniform(0.0, 0.4), 3),
                adjuster_id=f"ADJ_{rng.randint(1, N_ADJUSTERS):03d}",
                created_at=stamp,
                updated_at=stamp,
            )
        )

    # Close out up to 100 OPEN claims, each paid in full on day 2
    open_claims = [c for c in claims if c.status == "OPEN"]
    pay_id = len(payments) + 1
    for c in rng.sample(open_claims, min(N_CLAIMS_CLOSED_DAY2, len(open_claims))):
        c.status = "PAID"
        c.updated_at = stamp
        payments.append(
            ClaimPayment(
                payment_id=f"PAY_{pay_id:06d}",
                claim_id=c.claim_id,
                payment_date=stamp.date(),
                payment_amount=c.claim_amount,
                payment_type="INDEMNITY",
                created_at=stamp,
            )
        )
        pay_id += 1


# ── Entry point ───────────────────────────────────────────────────────────────
def generate(ingest_date: date, day: int = 1, seed: int = 42) -> dict[str, list]:
    """Build one day's tables. Returns {table name: rows}, in landing order.

    Day 1 is the baseline, generated as of `ingest_date`.
    Day 2 rebuilds that same baseline as of the day before, then applies the
    day-2 changes stamped with `ingest_date`. So for the SCD2 demo, land
    day 1 on D and day 2 on D+1: unchanged rows come out identical.
    """
    if day not in (1, 2):
        raise ValueError(f"day must be 1 or 2, got {day}")

    baseline_date = ingest_date - timedelta(days=day - 1)
    as_of = datetime.combine(baseline_date, time())

    rng = random.Random(seed)
    fake = Faker("en_CA")
    fake.seed_instance(seed)

    customers = gen_customers(fake, rng, as_of)
    policies = gen_policies(fake, rng, customers, as_of)
    claims = gen_claims(fake, rng, policies, as_of)
    payments = gen_payments(rng, claims, as_of)

    if day == 2:
        apply_day2_changes(rng, policies, claims, payments, datetime.combine(ingest_date, time()))

    return {
        "customers": customers,
        "policies": policies,
        "claims": claims,
        "claim_payments": payments,
    }
