import { useEffect, useRef, useState } from "react";
import type { EscalationCase, Grant, User } from "./api";
import { post, PROJECT } from "./api";

export type Role = "user" | "manager";

/** Managers and resource owners decide; everyone else is a user. */
export function roleOf(u: User): Role {
  return /manager|owner|lead|head/i.test(u.role) ? "manager" : "user";
}

// The policy engine refuses requests with no business context (JIT-Evidence-01).
export const TICKET = "ATLAS-142";

const ASKS: Record<string, { resource_ids: string[]; days: number; text: string }> = {
  "u-newhire-1": { resource_ids: ["repo-atlas-ingestion", "bucket-analytics-raw", "bq-project-x-finance"], days: 14, text: "I need the atlas-ingestion repo, the analytics-raw bucket and the project-x-finance dataset to build the Atlas ingestion pipeline, done by Nov 15." },
  "u-manager-1": { resource_ids: ["bucket-analytics-raw", "repo-atlas-ingestion"], days: 7, text: "Reviewing the Atlas ingestion output this week." },
  "u-finance-owner-1": { resource_ids: ["bq-project-x-finance", "repo-finance-ledger"], days: 3, text: "Month-end close on Project X." },
};

export function requestAs(u: User) {
  const ask = ASKS[u.id] ?? { resource_ids: ["bucket-analytics-raw"], days: 7, text: `Need analytics-raw for ${PROJECT}.` };
  return post("/requests", {
    id: "ui",
    requester: { id: u.id, name: u.name, role: u.role, team: u.team },
    task_description: ask.text,
    project: PROJECT,
    resource_ids: ask.resource_ids,
    requested_duration_days: ask.days,
    raw_text: ask.text,
    context: { active_jira_ticket: TICKET },
  });
}

export async function approveAll(cases: EscalationCase[]) {
  for (const c of cases.filter((x) => x.status === "pending")) {
    for (const a of c.required_approver_ids) {
      if (c.votes.some((v) => v.approver_id === a)) continue;
      await post(`/escalations/${c.id}/vote`, { escalation_id: c.id, approver_id: a, approved: true, comment: "Approved" });
    }
  }
}

export function useTool(u: User, grants: Grant[]) {
  const g = grants.find((x) => x.requester_id === u.id && !x.revoked && x.resource_id === "bucket-analytics-raw") ?? grants.find((x) => x.requester_id === u.id && !x.revoked);
  const tool = g?.resource_id.startsWith("bq") ? "bq_query_project_x_finance" : g?.resource_id.startsWith("repo") ? "gh_push_atlas_ingestion" : "gcs_list_analytics_raw";
  return post("/audit", {
    id: "ui",
    type: "action_executed",
    actor: "agent",
    detail: g ? `${tool} · 2 objects` : `${tool} · bounced`,
    request_id: g?.request_id ?? null,
    grant_id: g?.id ?? null,
    payload: { tool, status: g ? "ok" : "bounced", requester_id: u.id },
  });
}

/** Reset the store and replay the demo morning with real timestamps (POST /demo/seed). */
export function seedDemo(_users: User[]) {
  return post("/demo/seed");
}

interface Props {
  role: Role;
  users: User[]; // already filtered to the role
  selected: string;
  onSelect: (id: string) => void;
  grants: Grant[];
  cases: EscalationCase[];
  online: boolean;
}

export function PersonMenu({ role, users, selected, onSelect, grants, cases, online }: Props) {
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const ref = useRef<HTMLDivElement>(null);
  const me = users.find((u) => u.id === selected) ?? users[0];

  useEffect(() => {
    if (!open) return;
    const close = (e: MouseEvent) => { if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false); };
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, [open]);

  const run = async (name: string, fn: () => Promise<unknown>) => {
    setBusy(name);
    try { await fn(); } catch (e) { console.error(e); } finally { setBusy(null); }
  };

  const active = grants.filter((g) => !g.revoked);
  const pending = cases.filter((c) => c.status === "pending");
  const A = ({ name, fn, off }: { name: string; fn: () => Promise<unknown>; off?: boolean }) => (
    <button className="ctl-act" disabled={!online || off || busy !== null} onClick={() => run(name, fn)}>{busy === name ? "…" : name}</button>
  );

  return (
    <div className="ctl" ref={ref}>
      <button className="ctl-btn" aria-expanded={open} onClick={() => setOpen((o) => !o)} style={{ ["--u" as string]: me?.color ?? "#f4f4f4" }}>
        <i /><span>{me?.name ?? "…"}</span><b>▾</b>
      </button>
      {open && (
        <div className="ctl-menu">
          <div className="ctl-k">{role === "manager" ? "people" : "users"}</div>
          {users.map((u) => (
            <button key={u.id} className="ctl-person" aria-pressed={u.id === selected} onClick={() => { onSelect(u.id); setOpen(false); }} style={{ ["--u" as string]: u.color }}>
              <i /><span>{u.name}</span><small>{u.team}</small>
            </button>
          ))}
          <div className="ctl-k">demo</div>
          <A name="Reset demo" fn={() => seedDemo(users)} />
          <A name="Approve all" fn={() => approveAll(cases)} off={pending.length === 0} />
          <A name={`${me?.name.split(" ")[0] ?? "Someone"} uses a tool`} fn={() => (me ? useTool(me, grants) : Promise.resolve())} />
          <A name="Close project" fn={() => post(`/projects/${PROJECT}/close`)} off={active.length === 0} />
        </div>
      )}
    </div>
  );
}
