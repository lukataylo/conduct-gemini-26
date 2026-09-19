import { useState } from "react";
import type { EscalationCase, Grant, User } from "./api";
import { ALL, post, PROJECT } from "./api";

interface Props {
  grants: Grant[];
  cases: EscalationCase[];
  users: User[];
  selected: string;
  online: boolean;
}

export function DemoBar({ grants, cases, users, selected, online }: Props) {
  const [busy, setBusy] = useState<string | null>(null);
  const run = async (name: string, fn: () => Promise<unknown>) => {
    setBusy(name);
    try {
      await fn();
    } catch (e) {
      console.error(e);
    } finally {
      setBusy(null);
    }
  };

  const me = users.find((u) => u.id === selected) ?? users[0];
  const active = grants.filter((g) => !g.revoked);
  const pending = cases.filter((c) => c.status === "pending");

  const seedPeers = async () => {
    const asks: Record<string, { resource_ids: string[]; days: number; text: string }> = {
      "u-manager-1": { resource_ids: ["bucket-analytics-raw"], days: 7, text: "Reviewing the Atlas ingestion output for the week." },
      "u-finance-owner-1": { resource_ids: ["bq-project-x-finance"], days: 30, text: "Month-end close on Project X." },
    };
    for (const u of users) {
      const ask = asks[u.id];
      if (!ask) continue;
      await post("/requests", {
        id: "client",
        requester: { id: u.id, name: u.name, role: u.role, team: u.team },
        task_description: ask.text,
        project: PROJECT,
        resource_ids: ask.resource_ids,
        requested_duration_days: ask.days,
        raw_text: ask.text,
      });
    }
  };

  const approveAll = async () => {
    for (const c of pending) for (const a of c.required_approver_ids) {
      if (c.votes.some((v) => v.approver_id === a)) continue;
      await post(`/escalations/${c.id}/vote`, { escalation_id: c.id, approver_id: a, approved: true, comment: "Approved (demo)" });
    }
  };

  const call = () => {
    const g = active.find((x) => x.requester_id === me?.id && x.resource_id === "bucket-analytics-raw") ?? active.find((x) => x.requester_id === me?.id);
    const tool = g?.resource_id.startsWith("bq") ? "bq_query" : "gcs_list_objects";
    return post("/audit", {
      id: "client",
      type: "action_executed",
      actor: "agent",
      detail: g ? `${tool} · 42 objects · 120ms` : `${tool} · bounced · no active grant`,
      request_id: g?.request_id ?? null,
      grant_id: g?.id ?? null,
      payload: { tool, status: g ? "ok" : "bounced", requester_id: me?.id },
    });
  };

  const close = () => post(`/projects/${PROJECT}/close`);

  const B = ({ name, onClick, disabled, danger }: { name: string; onClick: () => Promise<unknown>; disabled?: boolean; danger?: boolean }) => (
    <button className={`nb ${danger ? "danger" : ""}`} disabled={!online || disabled || busy !== null} onClick={() => run(name, onClick)}>
      {busy === name ? "…" : name}
    </button>
  );

  return (
    <div className="demo">
      <span className="demo-k">demo</span>
      <B name="Seed peers" onClick={seedPeers} />
      <B name="Approve all" onClick={approveAll} disabled={pending.length === 0} />
      <B name={`Call tool as ${me?.name.split(" ")[0] ?? "…"}`} onClick={call} disabled={selected === ALL} />
      <B name="Close project" onClick={close} disabled={active.length === 0} danger />
    </div>
  );
}
