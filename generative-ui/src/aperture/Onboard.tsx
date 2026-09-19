import { useState } from "react";
import type { EscalationCase, Grant, Resource, User } from "./api";
import { label, post, PROJECT } from "./api";

interface Props {
  users: User[];
  resources: Resource[];
  grants: Grant[];
  cases: EscalationCase[];
  selected: string;
  online: boolean;
  now: number;
  onOpenSummary: () => void;
}

interface Result { resource_id: string; status: string; reason?: string; grant_id?: string }

const DEFAULT_TEXT =
  "I need the analytics-raw bucket and the project-x-finance dataset to build the Atlas ingestion pipeline, done by Nov 15.";

export function Onboard({ users, resources, grants, cases, selected, online, now, onOpenSummary }: Props) {
  const me = users.find((u) => u.id === selected) ?? users[0];
  const [text, setText] = useState(DEFAULT_TEXT);
  const [busy, setBusy] = useState(false);
  const [results, setResults] = useState<Result[] | null>(null);
  const [ms, setMs] = useState<number | null>(null);
  const [copied, setCopied] = useState(false);

  const byId = new Map(users.map((u) => [u.id, u]));
  const active = me ? grants.filter((g) => g.requester_id === me.id && !g.revoked && Date.parse(g.expires_at) > now) : [];
  const pending = me ? cases.filter((c) => c.requester_id === me.id && c.status === "pending") : [];

  const send = async () => {
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

  const cmd = `claude mcp add aperture -e APERTURE_REQUESTER=${me?.id ?? "u-newhire-1"} -e APERTURE_BACKEND=http://127.0.0.1:8000 -- python agent-runtime/mcp_serve.py`;
  const copy = () => { navigator.clipboard?.writeText(cmd).then(() => { setCopied(true); setTimeout(() => setCopied(false), 1500); }); };

  return (
    <div className="ob" style={{ ["--u" as string]: me?.color ?? "#f4f4f4" }}>
      <div className="ob-hero">
        <div className="ob-eyebrow">welcome · {me?.team} · {PROJECT}</div>
        <h1>Hi {me?.name.split(" ")[0]}.<br />Plug in your agent. Ask for what the task needs.</h1>
        <p>You get exactly that access, for exactly as long as the task takes. Low-risk access is granted in seconds; anything sensitive goes to {byId.get(users.find((u) => u.id === me?.id)?.id ?? "")?.name === me?.name ? "your manager" : "a human"}. Nothing is standing.</p>
      </div>

      <div className="ob-steps">
        <section className="ob-step">
          <div className="ob-n">1</div>
          <div className="ob-body">
            <h2>One line for your agent</h2>
            <p>Paste this into your terminal. Your agent gets a <code>request_access</code> tool, and every tool it's granted appears — and disappears — on its own.</p>
            <div className="ob-cmd"><code>{cmd}</code><button className="nb" onClick={copy}>{copied ? "Copied" : "Copy"}</button></div>
          </div>
        </section>

        <section className="ob-step">
          <div className="ob-n">2</div>
          <div className="ob-body">
            <h2>Or ask here</h2>
            <p>Same thing your agent would say. Gemini turns it into a typed request; a policy engine — not a model — decides.</p>
            <textarea id="ob-text" value={text} onChange={(e) => setText(e.target.value)} rows={3} />
            <div className="ob-row">
              <button className="nb go" disabled={!online || busy || !text.trim()} onClick={send}>{busy ? "Deciding…" : "Ask"}</button>
              {ms !== null && <span className="ob-ms">decided in <b>{ms} ms</b></span>}
            </div>
            {results && (
              <div className="ob-results">
                {results.map((r, i) => (
                  <div className={`ob-res ${r.status}`} key={i}>
                    <span className="ob-res-st">{r.status}</span>
                    <span className="ob-res-name">{label(r.resource_id, resources)}</span>
                    <span className="ob-res-why">
                      {r.status === "granted" && "yours now · expires with the task"}
                      {r.status === "escalated" && "a human is deciding — you'll see it below"}
                      {r.status !== "granted" && r.status !== "escalated" && (r.reason ?? "")}
                    </span>
                  </div>
                ))}
              </div>
            )}
          </div>
        </section>

        <section className="ob-step">
          <div className="ob-n">3</div>
          <div className="ob-body">
            <h2>Where you stand</h2>
            <div className="ob-status">
              {active.map((g) => <div className="ob-res granted" key={g.id}><span className="ob-res-st">active</span><span className="ob-res-name">{label(g.resource_id, resources)}</span><span className="ob-res-why">until {new Date(g.expires_at).toLocaleDateString([], { day: "numeric", month: "short" })}</span></div>)}
              {pending.map((c) => <div className="ob-res escalated" key={c.id}><span className="ob-res-st">waiting</span><span className="ob-res-name">{label(c.resource_id, resources)}</span><span className="ob-res-why">on {c.required_approver_ids.filter((a) => !c.votes.some((v) => v.approver_id === a)).map((a) => byId.get(a)?.name.split(" ")[0] ?? a).join(", ") || "—"}</span></div>)}
              {active.length === 0 && pending.length === 0 && <div className="ob-tool none"><b>—</b><span>nothing yet — ask above</span></div>}
            </div>
            <div className="ob-row"><button className="nb" onClick={onOpenSummary}>Open my access page →</button></div>
          </div>
        </section>
      </div>

      <div className="ob-why">
        <div className="ob-eyebrow">why it works this way</div>
        <div className="ob-cards">
          <div className="ob-card"><b>Google's own Vertex AI Agent Engine shipped an over-privileged default service account.</b><span>Unit 42 · confirmed</span><em>Here: no standing privilege. Every grant is task-scoped and expires.</em></div>
          <div className="ob-card"><b>Replit's agent deleted a production database during an explicit code freeze.</b><span>confirmed</span><em>Here: production is critical tier — always a human, and a closed project revokes everything.</em></div>
          <div className="ob-card"><b>Real MCP CVEs exist for exactly this attack surface.</b><span>confirmed</span><em>Here: the tool list is derived from grants and every call is re-checked and recorded.</em></div>
        </div>
      </div>
    </div>
  );
}
