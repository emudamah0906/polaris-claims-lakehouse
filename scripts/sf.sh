#!/usr/bin/env bash
# Run Snowflake SQL as the pipeline user POLARIS_SVC (key pair, no password).
#
#   scripts/sf.sh <role> <warehouse> -q "select 1"
#   scripts/sf.sh <role> <warehouse> -f file.sql -D day=19
#
# Account and key path come from .env (gitignored). The role is chosen per
# call, so a load runs as the loader and nothing runs as ACCOUNTADMIN.
set -euo pipefail

cd "$(dirname "$0")/.."
set -a; . ./.env; set +a
ROLE=${1:?role}; WH=${2:?warehouse}; shift 2

exec snow sql -x --account "$SNOWFLAKE_ACCOUNT" --user "$SNOWFLAKE_USER" \
  --authenticator SNOWFLAKE_JWT --private-key-file "$SNOWFLAKE_PRIVATE_KEY_PATH" \
  --role "$ROLE" --warehouse "$WH" --database POLARIS --schema RAW "$@"
