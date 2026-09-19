import { useState } from "react";
import type { AuditEvent, EscalationCase, Grant, Resource, User } from "./api";
import { ALL, post } from "./api";
import { Approvals } from "./Approvals";

interface Props {
  grants: Grant[];
  cases: EscalationCase[];
  events: AuditEvent[];
  resources: Resource[];
  users: User[];
}

// Mirrors policy-engine DEFAULT_POLICY. Read-only until GET/PATCH /policy exists.
const POLICY = [
  { tier: "public", auto: "90d", approvals: 0 },
  { tier: "internal", auto: "30d", approvals: 1 },
  { tier: "restricted", auto: "7d", approvals: 1 },
  { tier: "critical", auto: "never", approvals: 2 },
];

/** The manager's column: what needs deciding, the policy in force, and Gemini. */
export function ManagerSide({ grants, cases, events, resources, users }: Props) {
  const me = users.find((u) => u.id === "u-manager-1") ?? users[0];
  const [msg, setMsg] = useState("");
  const [chat, setChat] = useState<{ who: "you" | "gemini"; text: string }[]>([]);
  const [busy, setBusy] = useState(false);
  const [conv, setConv] = useState<string | null>(null);

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
    } catch {
      setChat((c) => [...c, { who: "gemini", text: "Offline." }]);
    } finally {
      setBusy(false);
    }
  };

  return (
    <aside className="mgr-side">
      <Approvals cases={cases} grants={grants} events={events} resources={resources} users={users} selected={ALL} />

      <section className="mgr-settings">
        <div className="apv-h">Policy</div>
        <table className="pol">
          <thead><tr><th>tier</th><th>auto up to</th><th>approvals</th></tr></thead>
          <tbody>{POLICY.map((p) => <tr key={p.tier}><td>{p.tier}</td><td>{p.auto}</td><td>{p.approvals}</td></tr>)}</tbody>
        </table>
      </section>

      <section className="mgr-live">
        <div className="apv-h">Gemini <span className="live-dot" /></div>
        <div className="live-log">
          {chat.length === 0 && <div className="live-empty">Ask about anyone here.</div>}
          {chat.map((m, i) => <div key={i} className={`live-msg ${m.who}`}><b>{m.who === "you" ? me?.short ?? "you" : "G"}</b><span>{m.text}</span></div>)}
          {busy && <div className="live-msg gemini"><b>G</b><span>…</span></div>}
        </div>
        <div className="live-in">
          <button className="nb mic" title="Voice — soon" disabled>●</button>
          <input id="live-text" value={msg} onChange={(e) => setMsg(e.target.value)} onKeyDown={(e) => e.key === "Enter" && ask()} placeholder="Who is waiting on me?" />
          <button className="nb" onClick={ask} disabled={busy || !msg.trim()}>Send</button>
        </div>
      </section>
    </aside>
  );
}
