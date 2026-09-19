// Thin client over backend-api. Shapes mirror shared/schemas.py by hand.
import { useEffect, useState } from "react";

export interface Grant {
  id: string;
  request_id: string;
  resource_id: string;
  requester_id: string;
  granted_at: string;
  expires_at: string;
  revoked: boolean;
  revoked_at: string | null;
  revoked_reason: string | null;
}

export interface EscalationCase {
  id: string;
  request_id: string;
  resource_id: string;
  required_approver_ids: string[];
  requester_id: string;
  requested_duration_days: number;
  votes: { approver_id: string; approved: boolean }[];
  opened_at?: string;
  status: "pending" | "approved" | "denied";
}

export interface AuditEvent {
  id: string;
  type: string;
  actor: string;
  detail: string;
  request_id: string | null;
  grant_id: string | null;
  escalation_id: string | null;
  payload: Record<string, unknown>;
  prev_hash: string | null;
  timestamp: string;
}

export interface Snapshot {
  grants: Grant[];
  cases: EscalationCase[];
  events: AuditEvent[];
  verify: { ok: boolean; length?: number; broken_at?: number } | null;
  online: boolean;
}

export const REQUESTER_ID = "u-newhire-1";
export const PROJECT = "atlas-migration";

async function get<T>(path: string): Promise<T> {
  const r = await fetch(`/api${path}`);
  if (!r.ok) throw new Error(`${r.status} ${path}`);
  return r.json();
}

export async function post<T>(path: string, body?: unknown): Promise<T> {
  const r = await fetch(`/api${path}`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!r.ok) throw new Error(`${r.status} ${path}`);
  return r.json();
}

export async function fetchSnapshot(): Promise<Snapshot> {
  const [grants, cases, events, verify] = await Promise.all([
    get<Grant[]>(`/grants?requester_id=${REQUESTER_ID}&include_revoked=true`),
    get<EscalationCase[]>(`/escalations`),
    get<AuditEvent[]>(`/audit`),
    get<Snapshot["verify"]>(`/audit/verify`),
  ]);
  return { grants, cases: cases.filter((c) => c.requester_id === REQUESTER_ID), events, verify, online: true };
}

const EMPTY: Snapshot = { grants: [], cases: [], events: [], verify: null, online: false };

export function useSnapshot(intervalMs = 1500): Snapshot {
  const [snap, setSnap] = useState<Snapshot>(EMPTY);
  useEffect(() => {
    let alive = true;
    const tick = () =>
      fetchSnapshot()
        .then((s) => alive && setSnap(s))
        .catch(() => alive && setSnap((p) => ({ ...p, online: false })));
    tick();
    const id = setInterval(tick, intervalMs);
    return () => {
      alive = false;
      clearInterval(id);
    };
  }, [intervalMs]);
  return snap;
}

export const RESOURCE_LABEL: Record<string, string> = {
  "bucket-analytics-raw": "analytics-raw",
  "bq-project-x-finance": "project_x_finance",
  "sql-prod-primary": "prod-primary",
};

export function label(resourceId: string): string {
  return RESOURCE_LABEL[resourceId] ?? resourceId;
}
