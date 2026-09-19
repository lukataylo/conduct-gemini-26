import { useState } from "react";
import type { AuditEvent, EscalationCase, Grant, Resource, User } from "./api";
import { ALL, label, post } from "./api";

interface Props {
  cases: EscalationCase[];
  grants: Grant[];
  events: AuditEvent[];
  resources: Resource[];
  users: User[];
  selected: string; // a person, or ALL to show every open case and decide as its next approver
}

export function Approvals({ cases, grants, events, resources, users, selected }: Props) {
  const [busy, setBusy] = useState<string | null>(null);
  const byId = new Map(users.map((u) => [u.id, u]));
  const me = users.find((u) => u.id === selected);

  const open = cases.filter((c) => c.status === "pending" && (selected === ALL || c.required_approver_ids.includes(selected)));
  const waiting = selected === ALL ? [] : cases.filter((c) => c.status === "pending" && c.requester_id === selected);

  // Who decides on this card: the selected person, or the next required approver who hasn't voted.
  const decider = (c: EscalationCase) => me ?? byId.get(c.required_approver_ids.find((a) => !c.votes.some((v) => v.approver_id === a)) ?? "");

  const vote = async (c: EscalationCase, approved: boolean) => {
    const who = decider(c);
    if (!who) return;
    setBusy(c.id);
    try {
      await post(`/escalations/${c.id}/vote`, { escalation_id: c.id, approver_id: who.id, approved, comment: approved ? "Approved" : "Denied" });
    } catch (e) {
      console.error(e);
    } finally {
      setBusy(null);
    }
  };

  const reason = (c: EscalationCase) => c.escalation_reason ?? events.find((e) => e.type === "escalated" && e.escalation_id === c.id)?.detail ?? "escalated";
  const holders = (c: EscalationCase) =>
    grants.filter((g) => g.resource_id === c.resource_id && !g.revoked && g.requester_id !== c.requester_id).map((g) => byId.get(g.requester_id)?.name ?? g.requester_id);

  if (open.length === 0 && waiting.length === 0) {
    return <div className="apv"><div className="apv-h">Approvals</div><div className="apv-empty">Nothing to decide</div></div>;
  }

  return (
    <div className="apv">
      <div className="apv-h">Approvals{open.length ? <b>{open.length}</b> : null}</div>
      {open.map((c) => {
        const req = byId.get(c.requester_id);
        const res = resources.find((r) => r.id === c.resource_id);
        const who = decider(c);
        const voted = who ? c.votes.find((v) => v.approver_id === who.id) : undefined;
        const others = c.required_approver_ids.filter((a) => a !== who?.id).map((a) => ({ name: byId.get(a)?.name.split(" ")[0] ?? a, done: c.votes.some((v) => v.approver_id === a && v.approved) }));
        const hold = holders(c);
        return (
          <div className="apv-card" key={c.id} style={{ ["--u" as string]: who?.color ?? "#fff" }}>
            <div className="apv-top">
              <span className="apv-res">{label(c.resource_id, resources)}</span>
              <span className="apv-tier">{res?.sensitivity ?? ""} · {res?.owning_team ?? ""}</span>
            </div>
            <div className="apv-who"><i style={{ background: req?.color }} /><b>{req?.name ?? c.requester_id}</b><span>{c.requested_duration_days}d</span></div>
            <div className="apv-why">{reason(c)}</div>
            <div className="apv-facts">
              <span><span className="k">also held by</span>{hold.length ? hold.join(", ") : "nobody"}</span>
              <span><span className="k">approvers</span>{others.length ? others.map((o) => `${o.name}${o.done ? " ✓" : ""}`).join(", ") : "only you"}</span>
            </div>
            {voted || !who ? (
              <div className={`apv-done ${voted?.approved ? "ok" : "no"}`}>{voted?.approved ? "Approved" : "Denied"} · {c.votes.filter((v) => v.approved).length} of {c.required_approver_ids.length}</div>
            ) : (
              <div className="apv-btns">
                <button className="nb deny" disabled={busy === c.id} onClick={() => vote(c, false)}>Deny</button>
                <button className="nb go" disabled={busy === c.id} onClick={() => vote(c, true)}>{busy === c.id ? "…" : `Approve · ${who.name.split(" ")[0]}`}</button>
              </div>
            )}
          </div>
        );
      })}
      {waiting.map((c) => {
        const left = c.required_approver_ids.filter((a) => !c.votes.some((v) => v.approver_id === a)).map((a) => byId.get(a)?.name.split(" ")[0] ?? a);
        return <div className="apv-wait" key={c.id}><span className="apv-res">{label(c.resource_id, resources)}</span><span>waiting on <b>{left.join(", ") || "—"}</b></span></div>;
      })}
    </div>
  );
}
