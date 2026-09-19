#!/usr/bin/env bash
# Step 3: create the real demo resources behind the mock (see CLAUDE.md).
# Idempotent — safe to re-run. Usage: infra/gcp_setup.sh <project-id> [region]
set -euo pipefail

PROJECT="${1:?usage: $0 <project-id> [region]}"
REGION="${2:-us-central1}"
BUCKET="${PROJECT}-analytics-raw"
DATASET="project_x_finance"

gcloud config set project "$PROJECT" >/dev/null
echo "==> Enabling APIs"
gcloud services enable storage.googleapis.com bigquery.googleapis.com iam.googleapis.com \
  iamcredentials.googleapis.com generativelanguage.googleapis.com

echo "==> Bucket gs://$BUCKET"
gcloud storage buckets describe "gs://$BUCKET" >/dev/null 2>&1 || \
  gcloud storage buckets create "gs://$BUCKET" --location="$REGION" --uniform-bucket-level-access
tmp=$(mktemp -d)
for d in 2026-09-15 2026-09-16 2026-09-17; do
  printf 'event_id,user_id,event,ts\n1,u-101,page_view,%sT09:00:00Z\n2,u-102,signup,%sT09:05:00Z\n' "$d" "$d" \
    > "$tmp/events_$d.csv"
done
gcloud storage cp "$tmp"/*.csv "gs://$BUCKET/raw/events/" --quiet

echo "==> BigQuery dataset $PROJECT:$DATASET"
bq --location="$REGION" show "$PROJECT:$DATASET" >/dev/null 2>&1 || \
  bq --location="$REGION" mk --dataset --description "Project X finance (FAKE demo data)" "$PROJECT:$DATASET"
cat > "$tmp/revenue.csv" <<CSV
month,region,revenue_usd,cost_usd
2026-06,NA,1250000,810000
2026-06,EMEA,940000,655000
2026-07,NA,1310000,832000
2026-07,EMEA,975000,670000
2026-08,NA,1402000,861000
2026-08,EMEA,1020000,688000
CSV
bq --location="$REGION" load --replace --skip_leading_rows=1 --source_format=CSV \
  "$PROJECT:$DATASET.monthly_revenue" "$tmp/revenue.csv" \
  month:STRING,region:STRING,revenue_usd:INTEGER,cost_usd:INTEGER
rm -rf "$tmp"

echo
echo "Done. Add to .env:"
echo "  GCP_PROJECT_ID=$PROJECT"
echo "  GCS_BUCKET_ANALYTICS_RAW=$BUCKET"
echo "  BQ_DATASET_PROJECT_X_FINANCE=$DATASET"
