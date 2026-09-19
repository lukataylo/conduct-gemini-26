import { useEffect, useState } from "react";
import type { AuditEvent, Company, EscalationCase, Grant, Resource, User } from "./api";
import { ATLAS, hasPlatform, isSapOnly, label, post } from "./api";
import { requestAs, requestSapAsk } from "./Menu";

interface Props {
  grants: Grant[];
  cases: EscalationCase[];
  events: AuditEvent[];
  resources: Resource[];
  users: User[];
  company: Company;
  now: number;
  online: boolean;
  onOpen: (userId: string) => void;
  onOpenAccess: (userId: string) => void;
}

interface Tool { name: string }
const MIN = 60e3, HOUR = 3600e3, DAY = 86400e3;
function left(ms: number) { return ms >= DAY ? `${Math.round(ms / DAY)}d` : ms >= HOUR ? `${Math.round(ms / HOUR)}h` : `${Math.max(1, Math.round(ms / MIN))}m`; }

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

/** Nothing-style dial: how much of the soonest-expiring lease is left. */
function Ring({ frac, color, text, sub }: { frac: number; color: string; text: string; sub: string }) {
  const r = 26, c = 2 * Math.PI * r;
  return (
    <div className="w w-ring">
      <svg viewBox="0 0 64 64" aria-hidden="true">
        <circle cx="32" cy="32" r={r} fill="none" stroke="#222" strokeWidth="6" />
        <circle cx="32" cy="32" r={r} fill="none" stroke={color} strokeWidth="6" strokeLinecap="round" strokeDasharray={`${c * Math.max(0, Math.min(1, frac))} ${c}`} transform="rotate(-90 32 32)" />
      </svg>
      <div className="w-ring-t"><b>{text}</b><small>{sub}</small></div>
    </div>
  );
}

/** Dot-matrix activity: one dot per 15-minute bucket over the last three hours. */
function Ticks({ times, now, color }: { times: number[]; now: number; color: string }) {
  const N = 12, B = 15 * MIN, start = now - N * B;
  const on = new Set(times.filter((t) => t >= start).map((t) => Math.min(N - 1, Math.floor((t - start) / B))));
  return <div className="w-ticks">{Array.from({ length: N }, (_, i) => <i key={i} style={on.has(i) ? { background: color, boxShadow: `0 0 6px ${color}` } : undefined} />)}</div>;
}

function AddPerson({ online }: { online: boolean }) {
  const [name, setName] = useState("");
  const [team, setTeam] = useState("data-platform");
  const [gcp, setGcp] = useState(true);
  const [sap, setSap] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const add = async () => {
    if (!name.trim()) return;
    setBusy(true); setErr(null);
    const platforms = [...(gcp ? ["gcp"] as const : []), ...(sap ? ["sap"] as const : [])];
    try {
      await post("/people", { name: name.trim(), team: team.trim() || "data-platform", platforms: platforms.length ? platforms : ["gcp"] });
      setName("");
      setGcp(true);
      setSap(false);
    }
    catch (e) { setErr(String(e).includes("409") ? "already here" : "failed"); }
    finally { setBusy(false); }
  };
  return (
    <div className="uc add">
      <div className="uc-head"><i /><div><b>Add a person</b><small>they get a card and an agent</small></div></div>
      <input id="add-name" value={name} onChange={(e) => setName(e.target.value)} onKeyDown={(e) => e.key === "Enter" && add()} placeholder="Name" />
      <input id="add-team" value={team} onChange={(e) => setTeam(e.target.value)} placeholder="Team" />
      <div className="uc-checks">
        <label><input type="checkbox" checked={gcp} onChange={(e) => setGcp(e.target.checked)} /> GCP</label>
        <label><input type="checkbox" checked={sap} onChange={(e) => setSap(e.target.checked)} /> SAP</label>
      </div>
      <div className="uc-actions">
        <button className="nb go" disabled={!online || busy || !name.trim()} onClick={add}>{busy ? "…" : "Add"}</button>
        {err && <span className="uc-err">{err}</span>}
      </div>
    </div>
  );
}

export function Users({ grants, cases, events, resources, users, company, now, online, onOpen, onOpenAccess }: Props) {
  const tools = useTools(users.map((u) => u.id), grants.length);
  const [busy, setBusy] = useState<string | null>(null);
  const byId = new Map(users.map((u) => [u.id, u]));
  const plats = company.platforms.length ? company.platforms : ATLAS.platforms;
  const ask = async (u: User) => { setBusy(u.id); try { await requestAs(u); } catch (e) { console.error(e); } finally { setBusy(null); } };
  const askSap = async (u: User) => { setBusy(u.id); try { await requestSapAsk(u); } catch (e) { console.error(e); } finally { setBusy(null); } };

  return (
    <div className="uc-grid">
      {users.map((u) => {
        const active = grants.filter((g) => g.requester_id === u.id && !g.revoked && Date.parse(g.expires_at) > now);
        const pending = cases.filter((c) => c.requester_id === u.id && c.status === "pending");
        const refused = events.filter((e) => (e.type === "request_denied" && e.actor === u.id) || (e.type === "action_executed" && e.payload.status === "bounced" && e.payload.requester_id === u.id));
        const ended = grants.filter((g) => g.requester_id === u.id && (g.revoked || Date.parse(g.expires_at) <= now)).slice(-1);
        const calls = events.filter((e) => e.type === "action_executed" && e.payload.requester_id === u.id).map((e) => Date.parse(e.timestamp));
        const soonest = [...active].sort((a, b) => Date.parse(a.expires_at) - Date.parse(b.expires_at))[0];
        const frac = soonest ? (Date.parse(soonest.expires_at) - now) / (Date.parse(soonest.expires_at) - Date.parse(soonest.granted_at)) : 0;
        const waitingOn = [...new Set(pending.flatMap((c) => c.required_approver_ids.filter((a) => !c.votes.some((v) => v.approver_id === a))))].map((a) => byId.get(a)?.name.split(" ")[0] ?? a);
        return (
          <div className="uc" key={u.id} style={{ ["--u" as string]: u.color }}>
            <div className="uc-head"><i /><div><b>{u.name}</b><small>{u.team} · {u.role}</small></div>
              <span className="plats">
                {plats.map((p) => (
                  <span key={p.id} className={`plat ${p.home ? "home" : ""} ${hasPlatform(u, p.id) ? "on" : "off"}`} title={p.name}>{p.short}</span>
                ))}
              </span>
            </div>

            <div className="w-grid">
              <div className={`w w-big ${active.length ? "" : "zero"}`}><b>{active.length}</b><small>open</small></div>
              <Ring frac={frac} color={u.color} text={soonest ? left(Date.parse(soonest.expires_at) - now) : "—"} sub={soonest ? "left" : "no lease"} />
              <div className={`w w-until ${soonest ? "" : "zero"}`}><b>{soonest ? new Date(soonest.expires_at).toLocaleDateString([], { day: "numeric", month: "short" }) : "—"}</b><small>until</small></div>
              <div className={`w w-wait ${pending.length ? "on" : "zero"}`}><b>{pending.length}</b><small>{pending.length ? `waiting on ${waitingOn.join(", ")}` : "waiting"}</small></div>
              <div className={`w w-ref ${refused.length ? "on" : "zero"}`}><b>{refused.length}</b><small>refused</small></div>
              <div className={`w w-calls ${calls.length ? "" : "zero"}`}><Ticks times={calls} now={now} color={u.color} /><small>{calls.length} calls · 3h</small></div>
            </div>

            <div className="uc-rows">
              {active.map((g) => <div className="uc-row on" key={g.id}><span>{label(g.resource_id, resources)}</span><small>{left(Date.parse(g.expires_at) - now)} left</small></div>)}
              {pending.map((c) => <div className="uc-row wait" key={c.id}><span>{label(c.resource_id, resources)}</span><small>{c.required_approver_ids.filter((a) => !c.votes.some((v) => v.approver_id === a)).map((a) => byId.get(a)?.name.split(" ")[0] ?? a).join(", ")}</small></div>)}
              {ended.map((g) => <div className="uc-row off" key={g.id}><span>{label(g.resource_id, resources)}</span><small>{g.revoked ? "ended" : "expired"}</small></div>)}
              {active.length === 0 && pending.length === 0 && ended.length === 0 && <div className="uc-row off"><span>nothing yet</span><small>ask</small></div>}
            </div>

            <div className="uc-tools">
              <span>request_access</span>
              {(tools[u.id] ?? []).map((t) => <span className="live" key={t.name}>{t.name}</span>)}
            </div>

            <div className="uc-actions">
              <button className="nb go" disabled={!online || busy === u.id} onClick={() => ask(u)}>{busy === u.id ? "…" : "Ask"}</button>
              {!isSapOnly(u) && <button className="nb" disabled={!online || busy === u.id} onClick={() => askSap(u)}>{busy === u.id ? "…" : "Ask SAP"}</button>}
              <button className="nb" onClick={() => onOpenAccess(u.id)}>Access →</button>
              <button className="nb" onClick={() => onOpen(u.id)}>Timeline →</button>
            </div>
          </div>
        );
      })}
      <AddPerson online={online} />
    </div>
  );
}
