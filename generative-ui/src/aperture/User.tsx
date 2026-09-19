import { useState } from "react";
import type { AuditEvent, EscalationCase, Grant, Resource, User as Person } from "./api";
import { label, post, PROJECT } from "./api";

interface Props {
  grants: Grant[];
  cases: EscalationCase[];
  events: AuditEvent[];
  resources: Resource[];
  users: Person[];
  selected: string;
  online: boolean;
  now: number;
}

interface Result { resource_id: string; status: string; reason?: string }

export function UserScreen({ grants, cases, events, resources, users, selected, online, now }: Props) {
  const me = users.find((u) => u.id === selected) ?? users[0];
  const [text, setText] = useState("I need the analytics-raw bucket and the project-x-finance dataset for the Atlas pipeline, until Nov 15.");
  const [busy, setBusy] = useState(false);
  const [results, setResults] = useState<Result[] | null>(null);
  const [ms, setMs] = useState<number | null>(null);
  const [copied, setCopied] = useState(false);

  const mine = me ? grants.filter((g) => g.requester_id === me.id && !g.revoked && Date.parse(g.expires_at) > now) : [];
  const waiting = me ? cases.filter((c) => c.requester_id === me.id && c.status === "pending") : [];
  const fresh = mine.length === 0 && waiting.length === 0;

  const ask = async () => {
    if (!me) return;
    setBusy(true); setResults(null); setMs(null);
    const t0 = performance.now();
    try {
      let body: { results: Result[] };
      try {
        body = await post("/requests", { raw_text: text, requester_id: me.id });
      } catch {
        const ids = resources.filter((r) => text.toLowerCase().replace(/[_-]/g, " ").includes(r.name.replace(/[_-]/g, " ").split(" ")[0].toLowerCase())).map((r) => r.id);
        body = await post("/requests", { id: "ui", requester: { id: me.id, name: me.name, role: me.role, team: me.team }, task_description: text, project: PROJECT, resource_ids: ids, requested_duration_days: 14, raw_text: text });
      }
      setMs(Math.round(performance.now() - t0));
      setResults(body.results);
    } catch (e) {
      setResults([{ resource_id: "request", status: "failed", reason: String(e) }]);
    } finally {
      setBusy(false);
    }
  };

  const cmd = `claude mcp add aperture -e APERTURE_REQUESTER=${me?.id ?? "u-newhire-1"} -- python agent-runtime/mcp_serve.py`;
  const copy = () => navigator.clipboard?.writeText(cmd).then(() => { setCopied(true); setTimeout(() => setCopied(false), 1200); });

  return (
    <div className="us" style={{ ["--u" as string]: me?.color ?? "#f4f4f4" }}>
      <div className="us-hero">
        <h1>Hi {me?.name.split(" ")[0]}.</h1>
        <p>{fresh ? "Plug in your agent, or ask below." : "Your agent is connected. Ask for more below."}</p>
        <div className="ob-cmd"><code>{cmd}</code><button className="nb" onClick={copy}>{copied ? "Copied" : "Copy"}</button></div>
      </div>

      <div className="us-ask">
        <textarea id="us-text" value={text} onChange={(e) => setText(e.target.value)} rows={2} />
        <div className="us-row">
          <button className="nb go" disabled={!online || busy || !text.trim()} onClick={ask}>{busy ? "…" : "Ask"}</button>
          {ms !== null && <span className="ob-ms">{ms} ms</span>}
          {results?.map((r, i) => (
            <span className={`us-res ${r.status}`} key={i}>{r.status} · {label(r.resource_id, resources)}</span>
          ))}
        </div>
      </div>

      {!fresh && (
        <div className="us-status">
          {mine.map((g) => <span className="us-res granted" key={g.id}>{label(g.resource_id, resources)} · until {new Date(g.expires_at).toLocaleDateString([], { day: "numeric", month: "short" })}</span>)}
          {waiting.map((c) => <span className="us-res escalated" key={c.id}>{label(c.resource_id, resources)} · waiting</span>)}
        </div>
      )}
    </div>
  );
}
