import { useState } from "react";
import type { AuditEvent, EscalationCase, Grant, Resource, User } from "./api";
import { ALL, label, post } from "./api";

interface Props {
  cases: EscalationCase[];
  grants: Grant[];
  events: AuditEvent[];
  resources: Resource[];
  users: User[];
  selected: string;
}

export function Approvals({ cases, grants, events, resources, users, selected }: Props) {
  const [busy, setBusy] = useState<string | null>(null);
  const me = users.find((u) => u.id === selected);
  const byId = new Map(users.map((u) => [u.id, u]));

  const mine = cases.filter((c) => c.status === "pending" && (selected === ALL || c.required_approver_ids.includes(selected)));
  const waiting = cases.filter((c) => c.status === "pending" && c.requester_id === selected);

  const vote = async (c: EscalationCase, approved: boolean) => {
    if (!me) return;
    setBusy(c.id);
    try {
      await post(`/escalations/${c.id}/vote`, { escalation_id: c.id, approver_id: me.id, approved, comment: approved ? "Approved from the console" : "Denied from the console" });
    } catch (e) {
      console.error(e);
    } finally {
      setBusy(null);
    }
  };

  const reason = (c: EscalationCase) => c.escalation_reason ?? events.find((e) => e.type === "escalated" && e.escalation_id === c.id)?.detail ?? "escalated by policy";
  const holders = (c: EscalationCase) =>
    grants
      .filter((g) => g.resource_id === c.resource_id && !g.revoked && g.requester_id !== c.requester_id)
      .map((g) => byId.get(g.requester_id)?.name ?? g.requester_id);

  if (mine.length === 0 && waiting.length === 0) {
    return (
      <div className="apv">
        <div className="apv-h">Approvals</div>
        <div className="apv-empty">{me ? `Nothing needs ${me.name.split(" ")[0]}` : "Nothing pending"}</div>
      </div>
    );
  }

  return (
    <div className="apv">
      <div className="apv-h">Approvals{mine.length ? <b>{mine.length}</b> : null}</div>
      {mine.map((c) => {
        const req = byId.get(c.requester_id);
        const res = resources.find((r) => r.id === c.resource_id);
        const voted = me ? c.votes.find((v) => v.approver_id === me.id) : undefined;
        const others = c.required_approver_ids.filter((a) => a !== me?.id).map((a) => ({ id: a, name: byId.get(a)?.name ?? a, done: c.votes.some((v) => v.approver_id === a && v.approved) }));
        const hold = holders(c);
        return (
          <div className="apv-card" key={c.id} style={{ ["--u" as string]: me?.color ?? "#fff" }}>
            <div className="apv-top">
              <span className="apv-res">{label(c.resource_id, resources)}</span>
              <span className="apv-tier">{res?.sensitivity ?? "restricted"} · {res?.owning_team ?? ""}</span>
            </div>
            <div className="apv-who">
              <i style={{ background: req?.color }} /><b>{req?.name ?? c.requester_id}</b><span>{req?.team}</span><span>· {c.requested_duration_days} days</span>
            </div>
            <div className="apv-why"><span className="k">why</span>{reason(c)}</div>
            <div className="apv-facts">
              <span><span className="k">also held by</span>{hold.length ? hold.join(", ") : "nobody"}</span>
              <span><span className="k">with you</span>{others.length ? others.map((o) => `${o.name.split(" ")[0]}${o.done ? " ✓" : ""}`).join(", ") : "only you"}</span>
            </div>
            {voted ? (
              <div className={`apv-done ${voted.approved ? "ok" : "no"}`}>{voted.approved ? "Approved" : "Denied"} · {c.votes.filter((v) => v.approved).length} of {c.required_approver_ids.length}</div>
            ) : selected === ALL ? (
              <div className="apv-done">Pick a person to decide</div>
            ) : (
              <div className="apv-btns">
                <button className="nb deny" disabled={busy === c.id} onClick={() => vote(c, false)}>Deny</button>
                <button className="nb go" disabled={busy === c.id} onClick={() => vote(c, true)}>{busy === c.id ? "…" : "Approve"}</button>
              </div>
            )}
          </div>
        );
      })}
      {waiting.map((c) => {
        const got = c.votes.filter((v) => v.approved).map((v) => byId.get(v.approver_id)?.name.split(" ")[0] ?? v.approver_id);
        const left = c.required_approver_ids.filter((a) => !c.votes.some((v) => v.approver_id === a)).map((a) => byId.get(a)?.name.split(" ")[0] ?? a);
        return (
          <div className="apv-wait" key={c.id}>
            <span className="apv-res">{label(c.resource_id, resources)}</span>
            <span>waiting on <b>{left.join(", ") || "—"}</b>{got.length ? ` · ${got.join(", ")} ✓` : ""}</span>
          </div>
        );
      })}
    </div>
  );
}
