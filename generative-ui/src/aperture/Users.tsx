import { useEffect, useState } from "react";
import type { AuditEvent, EscalationCase, Grant, Resource, User } from "./api";
import { label } from "./api";
import { requestAs } from "./Menu";

interface Props {
  grants: Grant[];
  cases: EscalationCase[];
  events: AuditEvent[];
  resources: Resource[];
  users: User[];
  now: number;
  online: boolean;
  onOpen: (userId: string) => void;
  onOpenAccess: (userId: string) => void;
}

interface Tool { name: string }
const DAY = 86400e3, HOUR = 3600e3;
function left(ms: number) { return ms >= DAY ? `${Math.round(ms / DAY)}d` : ms >= HOUR ? `${Math.round(ms / HOUR)}h` : `${Math.max(1, Math.round(ms / 60e3))}m`; }

function useTools(userIds: string[], tick: number): Record<string, Tool[]> {
  const [tools, setTools] = useState<Record<string, Tool[]>>({});
  useEffect(() => {
    let alive = true;
    Promise.all(userIds.map((id) => fetch(`/api/tools?requester_id=${id}`).then((r) => r.json()).then((t: Tool[]) => [id, t] as const).catch(() => [id, []] as const)))
      .then((pairs) => alive && setTools(Object.fromEntries(pairs)));
    return () => { alive = false; };
  }, [userIds.join(","), tick]);
  return tools;
}

export function Users({ grants, cases, events, resources, users, now, online, onOpen, onOpenAccess }: Props) {
  const tools = useTools(users.map((u) => u.id), grants.length);
  const [busy, setBusy] = useState<string | null>(null);
  const byId = new Map(users.map((u) => [u.id, u]));

  const ask = async (u: User) => {
    setBusy(u.id);
    try { await requestAs(u); } catch (e) { console.error(e); } finally { setBusy(null); }
  };

  return (
    <div className="uc-grid">
      {users.map((u) => {
        const active = grants.filter((g) => g.requester_id === u.id && !g.revoked && Date.parse(g.expires_at) > now);
        const pending = cases.filter((c) => c.requester_id === u.id && c.status === "pending");
        const denied = events.filter((e) => e.type === "request_denied" && e.actor === u.id);
        const next = active.map((g) => Date.parse(g.expires_at)).sort((a, b) => a - b)[0];
        return (
          <div className="uc" key={u.id} style={{ ["--u" as string]: u.color }}>
            <div className="uc-head">
              <i /><div><b>{u.name}</b><small>{u.team}</small></div>
              <span className="uc-n">{active.length}</span>
            </div>
            <div className="uc-line">{active.length ? <>until <b>{new Date(next).toLocaleDateString([], { day: "numeric", month: "short" })}</b></> : "nothing yet"}{pending.length ? <> · <em>{pending.length} waiting</em></> : null}</div>

            <div className="uc-rows">
              {active.map((g) => (
                <div className="uc-row on" key={g.id}><span>{label(g.resource_id, resources)}</span><small>{left(Date.parse(g.expires_at) - now)} left</small></div>
              ))}
              {pending.map((c) => {
                const on = c.required_approver_ids.filter((a) => !c.votes.some((v) => v.approver_id === a)).map((a) => byId.get(a)?.name.split(" ")[0] ?? a);
                return <div className="uc-row wait" key={c.id}><span>{label(c.resource_id, resources)}</span><small>{on.join(", ")}</small></div>;
              })}
              {denied.map((e) => (
                <div className="uc-row no" key={e.id}><span>{label(String(e.payload.resource_id ?? ""), resources)}</span><small>refused</small></div>
              ))}
            </div>

            <div className="uc-tools">
              <span>request_access</span>
              {(tools[u.id] ?? []).map((t) => <span className="live" key={t.name}>{t.name}</span>)}
            </div>

            <div className="uc-actions">
              <button className="nb go" disabled={!online || busy === u.id} onClick={() => ask(u)}>{busy === u.id ? "…" : "Ask"}</button>
              <button className="nb" onClick={() => onOpenAccess(u.id)}>Access →</button>
              <button className="nb" onClick={() => onOpen(u.id)}>Timeline →</button>
            </div>
          </div>
        );
      })}
    </div>
  );
}
