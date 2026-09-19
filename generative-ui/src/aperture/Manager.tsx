import { useMemo, useState } from "react";
import type { AuditEvent, EscalationCase, Grant, Resource, User } from "./api";
import { label, post } from "./api";
import { Approvals } from "./Approvals";

interface Props {
  grants: Grant[];
  cases: EscalationCase[];
  events: AuditEvent[];
  resources: Resource[];
  users: User[];
  selected: string;
  now: number;
  onDeepDive: (userId: string) => void;
}

const MIN = 60e3;

// Mirrors policy-engine DEFAULT_POLICY. Read-only until backend ships GET/PATCH /policy.
const POLICY = [
  { tier: "public", auto: "90d", approvals: 0 },
  { tier: "internal", auto: "30d", approvals: 1 },
  { tier: "restricted", auto: "7d", approvals: 1 },
  { tier: "critical", auto: "never", approvals: 2 },
];

function MiniTimeline({ grants, cases, user, t0, span, now }: { grants: Grant[]; cases: EscalationCase[]; user: User; t0: number; span: number; now: number }) {
  const x = (t: number) => Math.max(0, Math.min(100, ((t - t0) / span) * 100));
  const bars = [
    ...grants.filter((g) => g.requester_id === user.id).map((g) => {
      const s = Date.parse(g.granted_at);
      const e = g.revoked && g.revoked_at ? Date.parse(g.revoked_at) : Date.parse(g.expires_at);
      return { key: g.id, s, e, kind: g.revoked ? "revoked" : "active", name: g.resource_id };
    }),
    ...cases.filter((c) => c.requester_id === user.id && c.status === "pending").map((c) => ({ key: c.id, s: c.opened_at ? Date.parse(c.opened_at) : now - MIN, e: now, kind: "pending", name: c.resource_id })),
  ].sort((a, b) => a.s - b.s);
  return (
    <div className="mini" style={{ ["--u" as string]: user.color }}>
      <div className="mini-now" style={{ left: `${x(now)}%` }} />
      {bars.length === 0 && <span className="mini-empty">no leases</span>}
      {bars.map((b, i) => (
        <div key={b.key} className={`mini-bar ${b.kind}`} style={{ left: `${x(b.s)}%`, width: `${Math.max(x(b.e) - x(b.s), 1.5)}%`, top: `${6 + i * 12}px` }} title={b.name} />
      ))}
    </div>
  );
}

export function Manager({ grants, cases, events, resources, users, selected, now, onDeepDive }: Props) {
  const me = users.find((u) => u.id === selected);
  const [msg, setMsg] = useState("Who is waiting on me, and is anything risky?");
  const [chat, setChat] = useState<{ who: "you" | "gemini"; text: string }[]>([]);
  const [busy, setBusy] = useState(false);
  const [conv, setConv] = useState<string | null>(null);

  const { t0, span } = useMemo(() => {
    const starts = [...grants.map((g) => Date.parse(g.granted_at)), ...events.map((e) => Date.parse(e.timestamp))];
    const first = starts.length ? Math.min(...starts) : now;
    return { t0: first - 2 * MIN, span: Math.max(10 * MIN, now - first + 6 * MIN) };
  }, [grants, events, now]);

  const ask = async () => {
    if (!me || !msg.trim()) return;
    const text = msg.trim();
    setChat((c) => [...c, { who: "you", text }]);
    setMsg("");
    setBusy(true);
    try {
      const r = await post<{ reply: string; conversation_id: string }>("/agent/turn", { viewer_id: me.id, message: text, conversation_id: conv });
      setConv(r.conversation_id);
      setChat((c) => [...c, { who: "gemini", text: r.reply }]);
    } catch (e) {
      setChat((c) => [...c, { who: "gemini", text: `Not available here (${String(e).slice(0, 60)}). Track 2 hosts this turn; it answers from typed state only.` }]);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="mgr">
      <section className="mgr-people">
        <div className="sec-h"><h2>People · {users.length}</h2><span className="mgr-hint">click a row to open the full timeline</span></div>
        {users.map((u) => {
          const active = grants.filter((g) => g.requester_id === u.id && !g.revoked && Date.parse(g.expires_at) > now);
          const pending = cases.filter((c) => c.requester_id === u.id && c.status === "pending");
          const revoked = grants.filter((g) => g.requester_id === u.id && g.revoked);
          return (
            <button className="mgr-row" key={u.id} onClick={() => onDeepDive(u.id)} style={{ ["--u" as string]: u.color }}>
              <span className="mgr-who"><i /><b>{u.name}</b><small>{u.team} · {u.role}</small></span>
              <span className="mgr-counts"><b>{active.length}</b> active <em>·</em> <b className="amber">{pending.length}</b> pending <em>·</em> <b>{revoked.length}</b> revoked</span>
              <MiniTimeline grants={grants} cases={cases} user={u} t0={t0} span={span} now={now} />
              <span className="mgr-res">{active.map((g) => label(g.resource_id, resources)).join(", ") || "—"}</span>
              <span className="mgr-go">Open →</span>
            </button>
          );
        })}
      </section>

      <aside className="mgr-side">
        <Approvals cases={cases} grants={grants} events={events} resources={resources} users={users} selected={selected} />

        <section className="mgr-settings">
          <div className="apv-h">Settings · policy</div>
          <table className="pol">
            <thead><tr><th>tier</th><th>auto-grant up to</th><th>approvals</th></tr></thead>
            <tbody>{POLICY.map((p) => <tr key={p.tier}><td>{p.tier}</td><td>{p.auto}</td><td>{p.approvals}</td></tr>)}</tbody>
          </table>
          <div className="pol-note">Cross-team requests always escalate to the owning team. Read-only until <code>PATCH /policy</code> ships.</div>
        </section>

        <section className="mgr-live">
          <div className="apv-h">Gemini <span className="live-dot" /> discuss a permission</div>
          <div className="live-log">
            {chat.length === 0 && <div className="live-empty">Ask about anything on this screen. Gemini answers from typed state — it can explain and draft a request; it cannot vote or grant.</div>}
            {chat.map((m, i) => <div key={i} className={`live-msg ${m.who}`}><b>{m.who === "you" ? me?.short ?? "you" : "G"}</b><span>{m.text}</span></div>)}
            {busy && <div className="live-msg gemini"><b>G</b><span>…</span></div>}
          </div>
          <div className="live-in">
            <button className="nb mic" title="Voice via Gemini Live — hosted by track 2" disabled>●</button>
            <input id="live-text" value={msg} onChange={(e) => setMsg(e.target.value)} onKeyDown={(e) => e.key === "Enter" && ask()} placeholder="Ask Gemini…" />
            <button className="nb" onClick={ask} disabled={busy || !msg.trim()}>Send</button>
          </div>
        </section>
      </aside>
    </div>
  );
}
