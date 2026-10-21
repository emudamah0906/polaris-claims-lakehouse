#!/usr/bin/env bash
# Deploy adf/ to the Data Factory: the JSON in git is the source of truth.
#
#   scripts/deploy_adf.sh            # from the repo root, after `az login`
#
# Order matters: a dataset can't point at a linked service that doesn't exist
# yet, and a pipeline can't point at a dataset that doesn't exist yet.
# PUT is create-or-replace, so running this twice changes nothing.
set -euo pipefail

cd "$(dirname "$0")/.."
TF=infra/terraform/azure
FACTORY=$(terraform -chdir=$TF output -raw data_factory_name)
SUB=$(az account show --query id -o tsv)
BASE="https://management.azure.com/subscriptions/$SUB/resourceGroups/polaris-rg/providers/Microsoft.DataFactory/factories/$FACTORY"
API="api-version=2018-06-01"

for kind in linkedService dataset pipeline trigger; do
  [ -d "adf/$kind" ] || continue
  for file in adf/$kind/*.json; do
    name=$(basename "$file" .json)
    az rest --method put --uri "$BASE/${kind}s/$name?$API" --body "@$file" --output none
    echo "deployed  $kind  $name"
  done
done
