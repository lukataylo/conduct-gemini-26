import { useEffect, useState } from "react";
import type { Resource, User } from "./api";
import { label, post, PROJECT } from "./api";

interface Props {
  users: User[];
  resources: Resource[];
  selected: string;
  online: boolean;
}

interface Tool { name: string; description: string; grant_id: string; resource_id: string }
interface Result { resource_id: string; status: string; reason?: string; grant_id?: string }

const DEFAULT_TEXT =
  "I need the analytics-raw bucket and the project-x-finance dataset to build the Atlas ingestion pipeline, done by Nov 15.";

export function Onboard({ users, resources, selected, online }: Props) {
  const me = users.find((u) => u.id === selected) ?? users[0];
  const [text, setText] = useState(DEFAULT_TEXT);
  const [busy, setBusy] = useState(false);
  const [results, setResults] = useState<Result[] | null>(null);
  const [ms, setMs] = useState<number | null>(null);
  const [how, setHow] = useState<string>("");
  const [tools, setTools] = useState<Tool[]>([]);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    if (!me) return;
    let alive = true;
    const tick = () => fetch(`/api/tools?requester_id=${me.id}`).then((r) => r.json()).then((t) => alive && setTools(t)).catch(() => {});
    tick();
    const id = setInterval(tick, 1500);
    return () => { alive = false; clearInterval(id); };
  }, [me?.id]);

  const send = async () => {
    if (!me) return;
    setBusy(true); setResults(null); setMs(null);
    const t0 = performance.now();
    try {
      let body: { results: Result[] };
      try {
        body = await post("/requests", { raw_text: text, requester_id: me.id });
        setHow("parsed by Gemini");
      } catch {
        const ids = resources.filter((r) => text.toLowerCase().replace(/[_-]/g, " ").includes(r.name.replace(/[_-]/g, " ").split(" ")[0].toLowerCase())).map((r) => r.id);
        body = await post("/requests", { id: "ui", requester: { id: me.id, name: me.name, role: me.role, team: me.team }, task_description: text, project: PROJECT, resource_ids: ids, requested_duration_days: 14, raw_text: text });
        setHow("parsed locally · no Gemini key on this machine");
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
        <div className="ob-eyebrow">agent onboarding</div>
        <h1>Exactly the access the task needs.<br />For exactly as long as it takes.</h1>
        <p>A coding agent describes its task and gets a scoped, expiring grant in seconds — not a week-long ticket. Anything sensitive goes to a human. Everything is recorded.</p>
      </div>

      <div className="ob-steps">
        <section className="ob-step">
          <div className="ob-n">1</div>
          <div className="ob-body">
            <h2>Connect the agent</h2>
            <p>One MCP server. Its tool list is derived from live grants, so the agent only ever sees what it may use.</p>
            <div className="ob-cmd"><code>{cmd}</code><button className="nb" onClick={copy}>{copied ? "Copied" : "Copy"}</button></div>
          </div>
        </section>

        <section className="ob-step">
          <div className="ob-n">2</div>
          <div className="ob-body">
            <h2>Say what the task is</h2>
            <p>The agent calls <code>request_access</code>, or you type it here as <b style={{ color: me?.color }}>{me?.name}</b>. Gemini turns it into a typed request; the policy engine decides.</p>
            <textarea id="ob-text" value={text} onChange={(e) => setText(e.target.value)} rows={3} />
            <div className="ob-row">
              <button className="nb go" disabled={!online || busy || !text.trim()} onClick={send}>{busy ? "Deciding…" : `Request as ${me?.name.split(" ")[0]}`}</button>
              {ms !== null && <span className="ob-ms">decided in <b>{ms} ms</b> · {how}</span>}
            </div>
            {results && (
              <div className="ob-results">
                {results.map((r, i) => (
                  <div className={`ob-res ${r.status}`} key={i}>
                    <span className="ob-res-st">{r.status}</span>
                    <span className="ob-res-name">{label(r.resource_id, resources)}</span>
                    <span className="ob-res-why">
                      {r.status === "granted" && "scoped · expires with the task"}
                      {r.status === "escalated" && "needs a human — see Approvals"}
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
            <h2>Use it — then lose it</h2>
            <p>This is the agent's <code>tools/list</code> right now. Approve a request and a tool appears; close the project and it vanishes mid-session.</p>
            <div className="ob-tools">
              <div className="ob-tool base"><b>request_access</b><span>always available</span></div>
              <div className="ob-tool base"><b>my_access</b><span>always available</span></div>
              {tools.map((t) => (
                <div className="ob-tool live" key={t.name}><b>{t.name}</b><span>{t.description}</span></div>
              ))}
              {tools.length === 0 && <div className="ob-tool none"><b>—</b><span>no grant-derived tools yet</span></div>}
            </div>
          </div>
        </section>
      </div>

      <div className="ob-why">
        <div className="ob-eyebrow">why this exists</div>
        <div className="ob-cards">
          <div className="ob-card"><b>Google's own Vertex AI Agent Engine shipped an over-privileged default service account.</b><span>Unit 42 · confirmed</span><em>Aperture: no standing privilege. Every grant is task-scoped and expires.</em></div>
          <div className="ob-card"><b>Replit's agent deleted a production database during an explicit code freeze.</b><span>confirmed</span><em>Aperture: production is critical tier — it always goes to a human, and a closed project revokes everything.</em></div>
          <div className="ob-card"><b>Real MCP CVEs exist for exactly this attack surface.</b><span>confirmed</span><em>Aperture: the tool list is derived from grants and every call is re-checked and recorded — a bounce is evidence, not a bug.</em></div>
        </div>
      </div>
    </div>
  );
}
