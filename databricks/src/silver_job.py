"""Stage 3: Bronze claims-system extract -> Silver Delta tables (Unity Catalog).

Runs on a Databricks job cluster, once per business day:

    silver_job.py --ingest-date 2026-10-19

For that day's files in abfss://bronze@.../claims_system/<table>/year=/month=/day=/

  customers        SCD1: latest version per customer; SIN replaced by a hash
  claims           SCD1: latest version per claim
  claim_payments   insert-only: a payment never changes, and a rerun adds nothing
  policies_history SCD2 (ADR-0004): every change is a new version with
                   valid_from / valid_to / is_current, done with one Delta MERGE

Every table run is idempotent: running the same day twice changes nothing.
Rows failing basic checks go to silver.quarantine, and each run writes its
counts (and any schema drift it saw) to silver._load_audit.
"""

from __future__ import annotations

import argparse
from datetime import date, datetime, timezone

from pyspark.sql import DataFrame, SparkSession, Window
from pyspark.sql import functions as F

BRONZE = "abfss://bronze@polaris599i8o.dfs.core.windows.net/claims_system"
SILVER = "polaris.silver"

# Expected columns and their types, per source table. Anything else in the
# file is schema drift: logged, not loaded, so a source release can't
# silently change a Silver table.
SCHEMAS = {
    "customers": {
        "customer_id": "string", "first_name": "string", "last_name": "string", "ssn": "string",
        "dob": "date", "email": "string", "phone": "string", "address_line1": "string",
        "city": "string", "province": "string", "postal_code": "string",
        "created_at": "timestamp", "updated_at": "timestamp",
    },
    "policies": {
        "policy_id": "string", "customer_id": "string", "product_type": "string",
        "effective_date": "date", "expiry_date": "date", "annual_premium": "decimal(18,2)",
        "coverage_limit": "decimal(18,2)", "status": "string",
        "created_at": "timestamp", "updated_at": "timestamp",
    },
    "claims": {
        "claim_id": "string", "claim_number": "string", "policy_id": "string",
        "customer_id": "string", "product_type": "string", "claim_type": "string",
        "loss_date": "date", "report_date": "date", "claim_amount": "decimal(18,2)",
        "status": "string", "is_fraud": "boolean", "fraud_score": "decimal(5,3)",
        "adjuster_id": "string", "created_at": "timestamp", "updated_at": "timestamp",
    },
    "claim_payments": {
        "payment_id": "string", "claim_id": "string", "payment_date": "date",
        "payment_amount": "decimal(18,2)", "payment_type": "string", "created_at": "timestamp",
    },
}
KEYS = {"customers": "customer_id", "policies": "policy_id", "claims": "claim_id",
        "claim_payments": "payment_id"}
# Rules a row must pass to enter Silver; failures go to quarantine with the reason
RULES = {
    "policies": "status IN ('ACTIVE','EXPIRED','CANCELLED') AND annual_premium IS NOT NULL",
    "claims": "status IN ('OPEN','CLOSED','PAID','DENIED') AND claim_amount >= 0",
    "claim_payments": "payment_amount IS NOT NULL AND payment_date IS NOT NULL",
    "customers": "customer_id IS NOT NULL",
}
# The columns whose change makes a new policy version (SCD2)
POLICY_TRACKED = ["customer_id", "product_type", "effective_date", "expiry_date",
                  "annual_premium", "coverage_limit", "status"]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ingest-date", type=date.fromisoformat, required=True)
    day = parser.parse_args().ingest_date
    spark = SparkSession.builder.getOrCreate()
    _create_tables(spark)

    for table in ["customers", "policies", "claims", "claim_payments"]:
        raw, drift = _read_day(spark, table, day)
        good, bad = _check(raw, table)
        _quarantine(bad, table, day)
        metrics = {
            "customers": _merge_scd1, "claims": _merge_scd1,
            "claim_payments": _insert_new, "policies": _merge_scd2,
        }[table](spark, good, table)
        _audit(spark, day, table, raw.count(), bad.count(), metrics, drift)
        print(f"[silver] {day} {table:<15} in={raw.count():>6} quarantined={bad.count():>3} "
              f"{metrics}" + (f"  SCHEMA DRIFT: {drift}" if drift else ""))


# ── Read ──────────────────────────────────────────────────────────────────────

def _read_day(spark: SparkSession, table: str, day: date) -> tuple[DataFrame, str]:
    path = f"{BRONZE}/{table}/year={day:%Y}/month={day:%m}/day={day:%d}/"
    df = spark.read.option("header", True).csv(path)  # every column arrives as a string
    expected = SCHEMAS[table]
    extra = sorted(set(df.columns) - set(expected))
    missing = sorted(set(expected) - set(df.columns))
    drift = "; ".join(filter(None, [f"new columns {extra}" if extra else "",
                                    f"missing columns {missing}" if missing else ""]))
    if missing:
        raise ValueError(f"{table} {day}: source dropped columns {missing}. Stop rather than load nulls.")
    typed = df.select([F.col(c).cast(t).alias(c) for c, t in expected.items()])
    return typed, drift


def _check(df: DataFrame, table: str) -> tuple[DataFrame, DataFrame]:
    ok = F.expr(f"{KEYS[table]} IS NOT NULL AND ({RULES[table]})")
    return df.where(ok), df.where(~ok | ok.isNull()).withColumn("_reason", F.lit(RULES[table]))


# ── Write ─────────────────────────────────────────────────────────────────────

def _merge_scd1(spark: SparkSession, src: DataFrame, table: str) -> dict:
    """Upsert the latest version. Only a NEWER updated_at replaces a row, so a
    late or replayed file can't roll a claim back to an older state."""
    key = KEYS[table]
    if table == "customers":
        # PII: Silver keeps a hash of the SIN (still joinable), never the SIN itself
        src = src.withColumn("ssn_hash", F.sha2(F.col("ssn"), 256)).drop("ssn")
    src.createOrReplaceTempView("src")
    cols = src.columns
    return _merge_metrics(spark.sql(f"""
        MERGE INTO {SILVER}.{table} t
        USING (SELECT * FROM src QUALIFY row_number() OVER (PARTITION BY {key} ORDER BY updated_at DESC) = 1) s
        ON t.{key} = s.{key}
        WHEN MATCHED AND s.updated_at > t.updated_at THEN UPDATE SET {", ".join(f"t.{c} = s.{c}" for c in cols)}
        WHEN NOT MATCHED THEN INSERT ({", ".join(cols)}) VALUES ({", ".join(f"s.{c}" for c in cols)})
    """))


def _insert_new(spark: SparkSession, src: DataFrame, table: str) -> dict:
    key = KEYS[table]
    src.dropDuplicates([key]).createOrReplaceTempView("src")
    cols = src.columns
    return _merge_metrics(spark.sql(f"""
        MERGE INTO {SILVER}.{table} t USING src s ON t.{key} = s.{key}
        WHEN NOT MATCHED THEN INSERT ({", ".join(cols)}) VALUES ({", ".join(f"s.{c}" for c in cols)})
    """))


def _merge_scd2(spark: SparkSession, src: DataFrame, table: str) -> dict:
    """SCD Type 2 in one MERGE (ADR-0004).

    The source is fed in twice:
      - keyed by policy_id: matches the current version. If the tracked columns
        changed, that version is closed (valid_to, is_current = false). A policy
        never seen before matches nothing and is inserted.
      - with a NULL key, only for changed policies: matches nothing, so it is
        inserted as the new current version.
    Unchanged policies match with the same hash and nothing happens, which is
    what makes a rerun safe. Older-than-current rows (late files) are ignored.
    """
    latest = (src.withColumn("row_hash", F.sha2(F.concat_ws("|", *[F.col(c).cast("string") for c in POLICY_TRACKED]), 256))
              .withColumn("_rn", F.row_number().over(
                  Window.partitionBy("policy_id").orderBy(F.col("updated_at").desc())))
              .where("_rn = 1").drop("_rn"))
    latest.createOrReplaceTempView("src")
    cols = latest.columns
    return _merge_metrics(spark.sql(f"""
        MERGE INTO {SILVER}.policies_history t
        USING (
            SELECT policy_id AS merge_key, * FROM src
            UNION ALL
            SELECT NULL AS merge_key, s.* FROM src s
            JOIN {SILVER}.policies_history c
              ON c.policy_id = s.policy_id AND c.is_current
             AND c.row_hash <> s.row_hash AND s.updated_at > c.valid_from
        ) s
        ON t.policy_id = s.merge_key AND t.is_current
        WHEN MATCHED AND t.row_hash <> s.row_hash AND s.updated_at > t.valid_from THEN
            UPDATE SET t.is_current = false, t.valid_to = s.updated_at
        WHEN NOT MATCHED THEN
            INSERT ({", ".join(cols)}, valid_from, valid_to, is_current)
            VALUES ({", ".join(f"s.{c}" for c in cols)}, s.updated_at, NULL, true)
    """))


def _merge_metrics(result: DataFrame) -> dict:
    row = result.collect()[0].asDict()
    return {k.replace("num_", "").replace("_rows", ""): v for k, v in row.items()
            if k in ("num_inserted_rows", "num_updated_rows")}


def _quarantine(bad: DataFrame, table: str, day: date) -> None:
    if bad.isEmpty():
        return
    (bad.select(F.lit(table).alias("source_table"), F.lit(day).alias("ingest_date"),
                F.to_json(F.struct(*[c for c in bad.columns if c != "_reason"])).alias("record"),
                F.col("_reason").alias("reason"), F.current_timestamp().alias("quarantined_at"))
        .write.mode("append").saveAsTable(f"{SILVER}.quarantine"))


def _audit(spark, day, table, rows_in, quarantined, metrics, drift) -> None:
    spark.createDataFrame(
        [(day, table, rows_in, quarantined, metrics.get("inserted", 0), metrics.get("updated", 0),
          drift or None, datetime.now(timezone.utc))],
        "ingest_date date, source_table string, rows_in long, quarantined long, inserted long, "
        "updated long, schema_drift string, loaded_at timestamp",
    ).write.mode("append").saveAsTable(f"{SILVER}._load_audit")


# ── Tables ────────────────────────────────────────────────────────────────────

def _create_tables(spark: SparkSession) -> None:
    def ddl(cols: dict) -> str:
        return ", ".join(f"{c} {t.upper()}" for c, t in cols.items())

    customers = {k: v for k, v in SCHEMAS["customers"].items() if k != "ssn"} | {"ssn_hash": "string"}
    spark.sql(f"CREATE TABLE IF NOT EXISTS {SILVER}.customers ({ddl(customers)}) "
              "COMMENT 'Latest version per customer (SCD1). SIN kept only as a SHA-256 hash.'")
    spark.sql(f"CREATE TABLE IF NOT EXISTS {SILVER}.claims ({ddl(SCHEMAS['claims'])}) "
              "COMMENT 'Latest version per claim (SCD1).'")
    spark.sql(f"CREATE TABLE IF NOT EXISTS {SILVER}.claim_payments ({ddl(SCHEMAS['claim_payments'])}) "
              "COMMENT 'Insert-only payments.'")
    history = SCHEMAS["policies"] | {"row_hash": "string", "valid_from": "timestamp",
                                     "valid_to": "timestamp", "is_current": "boolean"}
    spark.sql(f"CREATE TABLE IF NOT EXISTS {SILVER}.policies_history ({ddl(history)}) "
              "COMMENT 'Every version of every policy (SCD2): valid_from, valid_to, is_current.'")
    spark.sql(f"CREATE TABLE IF NOT EXISTS {SILVER}.quarantine (source_table STRING, ingest_date DATE, "
              "record STRING, reason STRING, quarantined_at TIMESTAMP)")
    spark.sql(f"CREATE TABLE IF NOT EXISTS {SILVER}._load_audit (ingest_date DATE, source_table STRING, "
              "rows_in BIGINT, quarantined BIGINT, inserted BIGINT, updated BIGINT, "
              "schema_drift STRING, loaded_at TIMESTAMP)")


if __name__ == "__main__":
    main()
