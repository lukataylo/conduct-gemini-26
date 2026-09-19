"""
Real GCP IAM behind the mock — only active when REAL_GCP=true (see root CLAUDE.md).

The mock grant store in main.py stays the source of truth. This module mirrors a grant
onto the real bucket/dataset, then reads the IAM policy back from Google so the audit
trail can show "Verified in GCP" — the dashboard looks the same either way, so the
read-back is what proves on stage that the access is real.

Every function returns a result dict and never raises: a GCP hiccup must not break the
demo, it just shows up in the audit trail.

Auth: Application Default Credentials (`gcloud auth application-default login` on the
demo laptop). Config comes from env vars, e.g. `uvicorn main:app --env-file ../.env`.
"""
from __future__ import annotations

import os

# mock resource id -> (kind, env var holding the real name)
REAL_RESOURCES = {
    "bucket-analytics-raw": ("gcs", "GCS_BUCKET_ANALYTICS_RAW"),
    "bq-project-x-finance": ("bq", "BQ_DATASET_PROJECT_X_FINANCE"),
}
# mock requester id -> env var holding the Google principal that receives the grant
REAL_PRINCIPALS = {
    "u-newhire-1": "ALEX_SA_EMAIL",
}

GCS_ROLE = "roles/storage.objectViewer"
BQ_ROLE = "READER"  # dataset access entry role == roles/bigquery.dataViewer


def enabled() -> bool:
    return os.environ.get("REAL_GCP", "false").strip().lower() in ("1", "true", "yes")


def is_real(resource_id: str, requester_id: str) -> bool:
    """True if this grant should be mirrored to GCP (flag on + mapped resource/requester)."""
    return enabled() and resource_id in REAL_RESOURCES and requester_id in REAL_PRINCIPALS


def grant(resource_id: str, requester_id: str) -> dict:
    return _apply(resource_id, requester_id, add=True)


def revoke(resource_id: str, requester_id: str) -> dict:
    return _apply(resource_id, requester_id, add=False)


def _apply(resource_id: str, requester_id: str, add: bool) -> dict:
    kind, name_var = REAL_RESOURCES[resource_id]
    name = os.environ.get(name_var, "")
    email = os.environ.get(REAL_PRINCIPALS[requester_id], "")
    project = os.environ.get("GCP_PROJECT_ID", "")
    result = {"ok": False, "verified": False, "resource": "", "principal": email, "action": "grant" if add else "revoke"}
    if not (name and email and project):
        result["error"] = f"missing env: need {name_var}, {REAL_PRINCIPALS[requester_id]}, GCP_PROJECT_ID"
        return result
    try:
        if kind == "gcs":
            result["resource"] = f"gs://{name}"
            has_access = _gcs(project, name, email, add)
        else:
            result["resource"] = f"{project}.{name}"
            has_access = _bq(project, name, email, add)
        result["ok"] = True
        result["verified"] = has_access == add  # read back from Google, not assumed
    except Exception as e:  # noqa: BLE001 — surface any GCP failure in the audit trail
        result["error"] = f"{type(e).__name__}: {e}"
    return result


def _gcs(project: str, bucket_name: str, email: str, add: bool) -> bool:
    from google.cloud import storage

    bucket = storage.Client(project=project).bucket(bucket_name)
    member = f"serviceAccount:{email}"
    policy = bucket.get_iam_policy(requested_policy_version=3)
    binding = next((b for b in policy.bindings if b["role"] == GCS_ROLE and not b.get("condition")), None)
    if add:
        if binding is None:
            policy.bindings.append({"role": GCS_ROLE, "members": {member}})
        else:
            binding["members"].add(member)
    elif binding is not None:
        binding["members"].discard(member)
        if not binding["members"]:
            policy.bindings.remove(binding)
    bucket.set_iam_policy(policy)

    after = bucket.get_iam_policy(requested_policy_version=3)
    return any(b["role"] == GCS_ROLE and member in b["members"] for b in after.bindings)


def _bq(project: str, dataset_name: str, email: str, add: bool) -> bool:
    from google.cloud import bigquery

    client = bigquery.Client(project=project)
    dataset = client.get_dataset(f"{project}.{dataset_name}")
    entries = [e for e in dataset.access_entries if not (e.entity_type == "userByEmail" and e.entity_id == email)]
    if add:
        entries.append(bigquery.AccessEntry(role=BQ_ROLE, entity_type="userByEmail", entity_id=email))
    dataset.access_entries = entries
    client.update_dataset(dataset, ["access_entries"])

    after = client.get_dataset(f"{project}.{dataset_name}")
    return any(e.entity_type == "userByEmail" and e.entity_id == email and e.role == BQ_ROLE for e in after.access_entries)
