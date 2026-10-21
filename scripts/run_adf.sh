#!/usr/bin/env bash
# Start PL_Vendor_Autobody_To_Bronze for one day, wait for it, print each activity.
#
#   scripts/run_adf.sh 2026-10-16
#
# Exit code 0 if the pipeline succeeded, 1 if it failed. Airflow (Stage 7)
# does the same start-then-poll through its ADF operator.
set -euo pipefail

DAY=${1:?usage: scripts/run_adf.sh YYYY-MM-DD}
cd "$(dirname "$0")/.."
FACTORY=$(terraform -chdir=infra/terraform/azure output -raw data_factory_name)
SUB=$(az account show --query id -o tsv)
BASE="https://management.azure.com/subscriptions/$SUB/resourceGroups/polaris-rg/providers/Microsoft.DataFactory/factories/$FACTORY"
API="api-version=2018-06-01"

RUN=$(az rest --method post --uri "$BASE/pipelines/PL_Vendor_Autobody_To_Bronze/createRun?$API" \
  --body "{\"ingest_date\": \"$DAY\"}" --query runId -o tsv)
echo "run $RUN started for ingest_date=$DAY"

while :; do
  STATUS=$(az rest --method get --uri "$BASE/pipelineruns/$RUN?$API" --query status -o tsv)
  case $STATUS in Queued|InProgress|Canceling) sleep 10 ;; *) break ;; esac
done
echo "pipeline: $STATUS"

NOW=$(date -u +%Y-%m-%dT%H:%M:%SZ)
az rest --method post --uri "$BASE/pipelineruns/$RUN/queryActivityruns?$API" \
  --body "{\"lastUpdatedAfter\": \"2020-01-01T00:00:00Z\", \"lastUpdatedBefore\": \"$NOW\"}" \
  --query "sort_by(value, &activityRunStart)[].{activity:activityName, status:status, rowsCopied:output.rowsCopied, rowCount:output.firstRow.row_count, error:error.message}" -o table

[ "$STATUS" = "Succeeded" ]
