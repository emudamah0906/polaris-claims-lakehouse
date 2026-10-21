#!/usr/bin/env bash
# Run any airflow command against Polaris's local Airflow.
#
#   orchestration/airflow.sh db migrate                  # once
#   orchestration/airflow.sh standalone                  # UI on http://localhost:8080
#   orchestration/airflow.sh dags list
#
# Airflow 2.10 in its own Python 3.12 venv (orchestration/.venv.nosync).
# State, logs and the SQLite metadata DB live in orchestration/airflow_home/
# (gitignored). Runs natively on the Mac rather than in Docker, so tasks can
# use the same az login, uv and snow as you do.
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
export AIRFLOW_HOME="$HERE/airflow_home"
export AIRFLOW__CORE__DAGS_FOLDER="$HERE/airflow/dags"
export AIRFLOW__CORE__LOAD_EXAMPLES=False
export AIRFLOW__CORE__DEFAULT_TIMEZONE=utc
export AIRFLOW__WEBSERVER__WEB_SERVER_PORT=8080
# The production run is compressed: business days ahead of today's real date
# are triggered now, one after another
export AIRFLOW__CORE__ALLOW_TRIGGER_IN_FUTURE=True
# macOS: forked task processes crash in some network libraries without these
export OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES
export no_proxy='*'

exec "$HERE/.venv/bin/airflow" "$@"
