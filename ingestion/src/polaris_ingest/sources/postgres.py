"""The claims system in Postgres (Stage 2b).

Two jobs:
  load()           write one generated day into Postgres, the way the claims app
                   would: new rows INSERTed, changed rows UPDATEd, unchanged
                   rows left alone (so their updated_at doesn't move)
  fetch_changes()  read only the rows whose change column falls in a window
"""

from __future__ import annotations

import os
from dataclasses import astuple, fields
from datetime import datetime

SCHEMA = "claims_system"

# Table -> (primary key, change column). Payments are insert-only, so
# created_at is the only timestamp that ever moves.
TABLES = {
    "customers": ("customer_id", "updated_at"),
    "policies": ("policy_id", "updated_at"),
    "claims": ("claim_id", "updated_at"),
    "claim_payments": ("payment_id", "created_at"),
}

# Local Docker container only (infra/docker/docker-compose.yml)
DEFAULT_DSN = "postgresql://polaris:polaris_local@localhost:5433/polaris"


def connect(dsn: str | None = None):
    import psycopg  # imported here so Stage 2 runs don't need it

    return psycopg.connect(dsn or os.environ.get("POLARIS_PG_DSN", DEFAULT_DSN))


def load(conn, tables: dict[str, list]) -> dict[str, tuple[int, int]]:
    """Upsert every table. Returns {table: (inserted, updated)}.

    Rows go into a temp table with COPY (fast), then one INSERT ... ON CONFLICT
    moves them in. The WHERE on the update skips rows that are identical, so
    only real changes get written. Tables load in order (customers first)
    because of the foreign keys.
    """
    counts = {}
    with conn.transaction(), conn.cursor() as cur:
        for table, rows in tables.items():
            if not rows:
                counts[table] = (0, 0)
                continue
            pk = TABLES[table][0]
            cols = [f.name for f in fields(rows[0])]
            col_list = ", ".join(cols)
            non_key = [c for c in cols if c != pk]

            cur.execute(f"CREATE TEMP TABLE tmp_{table} (LIKE {SCHEMA}.{table}) ON COMMIT DROP")
            with cur.copy(f"COPY tmp_{table} ({col_list}) FROM STDIN") as copy:
                for row in rows:
                    copy.write_row(astuple(row))

            # xmax = 0 is Postgres's tell for "this row was just inserted";
            # an updated row has a non-zero xmax.
            cur.execute(f"""
                INSERT INTO {SCHEMA}.{table} AS t ({col_list})
                SELECT {col_list} FROM tmp_{table}
                ON CONFLICT ({pk}) DO UPDATE
                    SET {", ".join(f"{c} = EXCLUDED.{c}" for c in non_key)}
                    WHERE ({", ".join(f"t.{c}" for c in non_key)})
                          IS DISTINCT FROM ({", ".join(f"EXCLUDED.{c}" for c in non_key)})
                RETURNING (xmax = 0) AS inserted
            """)
            results = [r[0] for r in cur.fetchall()]
            counts[table] = (sum(results), len(results) - sum(results))
    return counts


def max_change(conn, table: str) -> datetime | None:
    """Latest value of the table's change column right now."""
    ts_col = TABLES[table][1]
    with conn.cursor() as cur:
        cur.execute(f"SELECT max({ts_col}) FROM {SCHEMA}.{table}")
        return cur.fetchone()[0]


def fetch_changes(
    conn, table: str, after: datetime | None, up_to: datetime
) -> tuple[list[str], list[tuple]]:
    """Rows with after < change column <= up_to. after=None means from the start.

    Strictly greater than `after`: a row stamped exactly at the last watermark
    was already pulled by the run that set it.
    """
    pk, ts_col = TABLES[table]
    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT * FROM {SCHEMA}.{table}
            WHERE (%(after)s::timestamp IS NULL OR {ts_col} > %(after)s)
              AND {ts_col} <= %(up_to)s
            ORDER BY {pk}
            """,
            {"after": after, "up_to": up_to},
        )
        columns = [d.name for d in cur.description]
        return columns, cur.fetchall()
