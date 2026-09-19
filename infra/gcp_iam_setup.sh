#!/usr/bin/env bash
# Step 4: identities for the demo (see CLAUDE.md "Identities").
# Idempotent. Usage: infra/gcp_iam_setup.sh <project-id>
#
# Only creates the service accounts. All data access for alex-chen-agent comes from
# task-scoped grants the backend makes on the bucket/dataset at runtime. The hackathon
# lab account can't set project-level IAM, create custom roles, or impersonate SAs, so
# nothing else is configured here.
set -euo pipefail

PROJECT="${1:?usage: $0 <project-id>}"
gcloud config set project "$PROJECT" >/dev/null

mk_sa() {  # name, display name, description
  gcloud iam service-accounts describe "$1@${PROJECT}.iam.gserviceaccount.com" >/dev/null 2>&1 || \
    gcloud iam service-accounts create "$1" --display-name="$2" --description="$3"
}
mk_sa alex-chen-agent "Alex Chen's coding agent" "Demo requester. Gets task-scoped, TTL'd grants only."
# Unused while the backend runs on the demo laptop; it's the identity for a Cloud Run deploy.
mk_sa access-granter "Access Scope Agent (granter)" "Backend identity. Can change IAM only on the demo resources."

echo "Add to .env:"
echo "  ALEX_SA_EMAIL=alex-chen-agent@${PROJECT}.iam.gserviceaccount.com"
