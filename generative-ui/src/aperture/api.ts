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
  votes: { approver_id: string; approved: boolean; comment?: string | null }[];
  escalation_reason?: string | null;
  human_summary?: string | null;
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

export interface Resource {
  id: string;
  name: string;
  type: string;
  owning_team: string;
  sensitivity: string;
  capability?: string;
}

export interface Person {
  id: string;
  name: string;
  role: string;
  team: string;
}

export interface User extends Person {
  color: string;
  short: string;
}

export interface CuFrame {
  url: string;
  turn: number;
  action?: string | null;
  timestamp?: string | null;
  grant_id?: string | null;
  source: "live" | "replay";
}

export interface CuRecording {
  url: string;
  name: string;
  type: string;
}

export interface CuGroup {
  id: string;
  stem: string;
  kind: string;
  label: string;
  frames: CuFrame[];
  action_frames: CuFrame[];
  recordings: CuRecording[];
}

export interface CuSession {
  id: string;
  label: string;
  source: "live" | "replay";
  grant_id?: string | null;
  groups: CuGroup[];
}

export interface CuPreview {
  status: "live" | "replay" | "idle";
  grant_id?: string | null;
  running: boolean;
  frames: CuFrame[];
  sessions?: CuSession[];
}

export interface Snapshot {
  grants: Grant[];
  cases: EscalationCase[];
  events: AuditEvent[];
  resources: Resource[];
  people: Person[];
  verify: { ok: boolean; length?: number; broken_at?: number } | null;
  preview: CuPreview;
  online: boolean;
}

export const PROJECT = "atlas-migration";
export const ALL = "all";

// One colour per person. Red is reserved for deny / bounce and never used for a user.
const PALETTE = ["#22c55e", "#a78bfa", "#fb923c", "#38bdf8", "#f472b6", "#facc15"];

export function toUsers(people: Person[]): User[] {
  return people.map((p, i) => ({
    ...p,
    color: PALETTE[i % PALETTE.length],
    short: p.name.split(" ").map((s) => s[0]).join("").toUpperCase(),
  }));
}

async function get<T>(path: string): Promise<T> {
  const r = await fetch(`/api${path}`);
  if (!r.ok) throw new Error(`${r.status} ${path}`);
  return r.json();
}

// Sent on every write when the hub runs with DEMO_KEY set (see backend-api demo_key_guard).
const DEMO_KEY: string = (import.meta as any).env?.VITE_DEMO_KEY ?? "";

export async function post<T>(path: string, body?: unknown): Promise<T> {
  const r = await fetch(`/api${path}`, {
    method: "POST",
    headers: { "content-type": "application/json", ...(DEMO_KEY ? { "x-demo-key": DEMO_KEY } : {}) },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!r.ok) throw new Error(`${r.status} ${path}`);
  return r.json();
}

const IDLE_PREVIEW: CuPreview = { status: "idle", grant_id: null, running: false, frames: [], sessions: [] };

export function mediaUrl(path: string): string {
  if (path.startsWith("http://") || path.startsWith("https://") || path.startsWith("data:")) return path;
  return `/api${path.startsWith("/") ? path : `/${path}`}`;
}

export async function fetchSnapshot(): Promise<Snapshot> {
  const [grants, cases, events, resources, people, verify, preview] = await Promise.all([
    get<Grant[]>(`/grants?include_revoked=true`),
    get<EscalationCase[]>(`/escalations`),
    get<AuditEvent[]>(`/audit`),
    get<Resource[]>(`/resources`),
    get<Person[]>(`/people`),
    get<Snapshot["verify"]>(`/audit/verify`),
    get<CuPreview>(`/cu/preview`).catch(() => IDLE_PREVIEW),
  ]);
  return { grants, cases, events, resources, people, verify, preview, online: true };
}

const EMPTY: Snapshot = { grants: [], cases: [], events: [], resources: [], people: [], verify: null, preview: IDLE_PREVIEW, online: false };

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

export function label(resourceId: string, resources?: Resource[]): string {
  const r = resources?.find((x) => x.id === resourceId);
  return r ? r.name : resourceId.replace(/^(bucket|bq|sql)-/, "");
}

export interface AgentTurnPreview {
  resource_ids: string[];
  requested_duration_days: number;
  project: string;
  raw_text?: string | null;
}

export interface AgentTurnResult {
  status: string;
  preview?: AgentTurnPreview;
  request_id?: string;
  results?: { resource_id: string; status: string; reason?: string }[];
}

export interface AgentTurnOut {
  reply: string;
  tools_used: string[];
  request_result: AgentTurnResult | null;
  conversation_id: string;
}

export function postAgentTurn(body: {
  viewer_id: string;
  message: string;
  conversation_id?: string | null;
  confirm?: boolean;
}): Promise<AgentTurnOut> {
  return post<AgentTurnOut>("/agent/turn", body);
}
