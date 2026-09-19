import { useState } from "react";
import type { EscalationCase, Grant } from "./api";
import { post, PROJECT, REQUESTER_ID } from "./api";

interface Props {
  grants: Grant[];
  cases: EscalationCase[];
  online: boolean;
}

const REQUEST_TEXT =
  "I need access to the analytics-raw GCS bucket and the project-x-finance BigQuery dataset to build the ingestion pipeline for Project Atlas, done by Nov 15.";

export function DemoBar({ grants, cases, online }: Props) {
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

  const active = grants.filter((g) => !g.revoked);
  const pending = cases.filter((c) => c.status === "pending");

  const request = () =>
    post("/requests", {
      id: "client",
      requester: { id: REQUESTER_ID, name: "Alex Chen", role: "Software Engineer", team: "data-platform" },
      task_description: REQUEST_TEXT,
      project: PROJECT,
      resource_ids: ["bucket-analytics-raw", "bq-project-x-finance"],
      requested_duration_days: 14,
      raw_text: REQUEST_TEXT,
    });

  const approve = async () => {
    for (const c of pending) {
      for (const a of c.required_approver_ids) {
        await post(`/escalations/${c.id}/vote`, { escalation_id: c.id, approver_id: a, approved: true, comment: "Atlas is on the roadmap" });
      }
    }
  };

  const call = () => {
    const g = active.find((x) => x.resource_id === "bucket-analytics-raw");
    const tool = "gcs_list_objects";
    return post("/audit", {
      id: "client",
      type: "action_executed",
      actor: "agent",
      detail: g ? `${tool} · 42 objects · 120ms` : `${tool} · bounced · no active grant`,
      request_id: g?.request_id ?? null,
      grant_id: g?.id ?? null,
      payload: { tool, status: g ? "ok" : "bounced" },
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
      <B name="Request" onClick={request} />
      <B name="Approve" onClick={approve} disabled={pending.length === 0} />
      <B name="Call tool" onClick={call} />
      <B name="Close project" onClick={close} disabled={active.length === 0} danger />
    </div>
  );
}
