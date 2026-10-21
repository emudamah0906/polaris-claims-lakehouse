"""polaris_daily: one business day through the whole platform.

    simulate_claims_app ──► extract_claims_system ──► load_claims_system ──┐
            │                                                              ├──► dbt_build
            └──► vendor_drop ──► adf_vendor_to_bronze ──► load_vendor ─────┘

  simulate_claims_app    the claims app's business day in Postgres (stands in
                         for real users; a real platform has no such task)
  extract_claims_system  rows changed since the last watermark → ADLS Bronze
  vendor_drop            the body-shop vendor drops its file + manifest in landing
                         (also stands in for the outside world)
  adf_vendor_to_bronze   ADF copies it to Bronze and checks the row count
  load_*                 COPY INTO Snowflake RAW, as the loader role
  dbt_build              staging + marts + 60-odd tests, as the dbt role

Every task takes the business day from {{ ds }}, never from the clock, so a
rerun of Tuesday loads Tuesday. A failed task (after its retry) opens a GitHub
issue: polaris_alerts.open_incident.
"""

from __future__ import annotations

import os
from datetime import timedelta

import pendulum
from airflow import DAG
from airflow.operators.bash import BashOperator
from polaris_alerts import open_incident

REPO = "/Users/maheshshettynani/Desktop/Career-Hub/Projects/polaris-claims-lakehouse"
ENV = {
    # Tasks get a bare environment; these are where uv, az, snow and terraform live
    "PATH": "/Users/maheshshettynani/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin",
    "HOME": "/Users/maheshshettynani",
}
# Every task starts in the repo with .env loaded (Snowflake account, ADLS account)
PREFIX = f"cd {REPO} && set -a && . ./.env && set +a && "
YMD = "-D year={{ macros.ds_format(ds, '%Y-%m-%d', '%Y') }} " \
      "-D month={{ macros.ds_format(ds, '%Y-%m-%d', '%m') }} " \
      "-D day={{ macros.ds_format(ds, '%Y-%m-%d', '%d') }}"

# A scheduled DAG never starts a run before its logical date, even one you
# trigger by hand. To run future business days back to back (compressed
# time), the DAG has no schedule and the runs are triggered instead.
SCHEDULE = None if os.environ.get("POLARIS_COMPRESSED_TIME") == "1" else "@daily"

default_args = {
    "owner": "data-platform",
    "retries": 1,
    "retry_delay": timedelta(minutes=1),
    "on_failure_callback": open_incident,
}

with DAG(
    dag_id="polaris_daily",
    description="Claims system + vendor feed → Bronze → Snowflake RAW → dbt marts",
    start_date=pendulum.datetime(2026, 10, 19, tz="UTC"),
    schedule=SCHEDULE,
    catchup=False,
    max_active_runs=1,          # business days run in order, one at a time
    default_args=default_args,
    tags=["polaris", "production"],
) as dag:

    simulate_claims_app = BashOperator(
        task_id="simulate_claims_app",
        bash_command=PREFIX + "uv run polaris-ingest simulate-day --date {{ ds }}",
        env=ENV,
    )

    # depends_on_past: the watermark only moves forward, so day N's extract
    # must not run before day N-1's has succeeded
    extract_claims_system = BashOperator(
        task_id="extract_claims_system",
        bash_command=PREFIX + "uv run polaris-ingest extract --ingest-date {{ ds }} "
                              "--backend azure --account $ADLS_ACCOUNT_NAME",
        env=ENV,
        depends_on_past=True,
    )

    load_claims_system = BashOperator(
        task_id="load_claims_system",
        bash_command=PREFIX + "scripts/sf.sh POLARIS_LOADER_ROLE POLARIS_WH_LOAD "
                              "-f ingestion/snowflake/load_claims_system.sql " + YMD,
        env=ENV,
    )

    vendor_drop = BashOperator(
        task_id="vendor_drop",
        bash_command=PREFIX + "uv run polaris-ingest vendor-drop --ingest-date {{ ds }} "
                              "--source postgres --backend azure --account $ADLS_ACCOUNT_NAME",
        env=ENV,
    )

    adf_vendor_to_bronze = BashOperator(
        task_id="adf_vendor_to_bronze",
        bash_command=PREFIX + "scripts/run_adf.sh {{ ds }}",
        env=ENV,
        retries=0,  # a failed row-count check is a data problem; retrying won't fix it
    )

    load_vendor = BashOperator(
        task_id="load_vendor",
        bash_command=PREFIX + "scripts/sf.sh POLARIS_LOADER_ROLE POLARIS_WH_LOAD "
                              "-f ingestion/snowflake/load_vendor.sql " + YMD,
        env=ENV,
    )

    # all_done: refresh the marts with whatever did arrive. A failed source
    # already has its own incident; holding back dbt would hide good data too.
    dbt_build = BashOperator(
        task_id="dbt_build",
        bash_command=PREFIX + "make dbt-build",
        env=ENV,
        trigger_rule="all_done",
        retries=0,  # a failed dbt test is a data problem, not a blip
    )

    simulate_claims_app >> extract_claims_system >> load_claims_system >> dbt_build
    simulate_claims_app >> vendor_drop >> adf_vendor_to_bronze >> load_vendor >> dbt_build
