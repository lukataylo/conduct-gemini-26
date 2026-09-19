import { useEffect, useRef, useState } from "react";
import type { AuditEvent, EscalationCase, Grant, Resource, User as Person } from "./api";
import { label, post, PROJECT } from "./api";
import { TICKET } from "./Menu";

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
interface Tool { name: string }

/** A dot-matrix iris: the opening grows with the number of active leases. */
function Iris({ open, max, color }: { open: number; max: number; color: string }) {
  const ref = useRef<HTMLCanvasElement>(null);
  useEffect(() => {
    const c = ref.current;
    if (!c) return;
    const ctx = c.getContext("2d");
    if (!ctx) return;
    const N = 23, S = 12, R = (N * S) / 2;
    c.width = N * S * 2; c.height = N * S * 2; c.style.width = `${N * S}px`; c.style.height = `${N * S}px`;
    ctx.scale(2, 2);
    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    let raf = 0, t0 = performance.now();
    const target = 2.5 + (max ? (open / max) * 6.5 : 0);
    const draw = (t: number) => {
      const pulse = reduce ? 0 : Math.sin((t - t0) / 900) * 0.35;
      const r = target + pulse;
      ctx.clearRect(0, 0, N * S, N * S);
      for (let y = 0; y < N; y++) for (let x = 0; x < N; x++) {
        const dx = x - (N - 1) / 2, dy = y - (N - 1) / 2;
        const d = Math.sqrt(dx * dx + dy * dy);
        const ring = Math.abs(d - r);
        let a = 0.08;
        if (d < r) a = 0.02;
        if (ring < 0.9) a = 1 - ring * 0.6;
        else if (ring < 2.2) a = 0.35 - (ring - 0.9) * 0.2;
        ctx.globalAlpha = Math.max(0.03, Math.min(1, a));
        ctx.fillStyle = ring < 2.2 ? color : "#ffffff";
        ctx.beginPath();
        ctx.arc(x * S + S / 2, y * S + S / 2, ring < 0.9 ? 3.2 : 2.2, 0, Math.PI * 2);
        ctx.fill();
      }
      ctx.globalAlpha = 1;
      if (!reduce) raf = requestAnimationFrame(draw);
    };
    draw(t0);
    return () => cancelAnimationFrame(raf);
  }, [open, max, color]);
  return <canvas ref={ref} className="iris" aria-label={`${open} of ${max} leases open`} />;
}

export function UserScreen({ grants, cases, events, resources, users, selected, online, now }: Props) {
  const me = users.find((u) => u.id === selected) ?? users[0];
  const [text, setText] = useState("I need the atlas-ingestion repo and the analytics-raw bucket for the Atlas pipeline, until Nov 15.");
  const [busy, setBusy] = useState(false);
  const [results, setResults] = useState<Result[] | null>(null);
  const [ms, setMs] = useState<number | null>(null);
  const [copied, setCopied] = useState(false);
  const [tools, setTools] = useState<Tool[]>([]);

  const byId = new Map(users.map((u) => [u.id, u]));
  const mine = me ? grants.filter((g) => g.requester_id === me.id && !g.revoked && Date.parse(g.expires_at) > now) : [];
  const waiting = me ? cases.filter((c) => c.requester_id === me.id && c.status === "pending") : [];
  const calls = me ? events.filter((e) => e.type === "action_executed" && e.payload.requester_id === me.id).length : 0;
  const next = mine.map((g) => Date.parse(g.expires_at)).sort((a, b) => a - b)[0];

  useEffect(() => {
    if (!me) return;
    let alive = true;
    fetch(`/api/tools?requester_id=${me.id}`).then((r) => r.json()).then((t) => alive && setTools(t)).catch(() => {});
    return () => { alive = false; };
  }, [me?.id, grants.length]);

  const ask = async () => {
    if (!me) return;
    setBusy(true); setResults(null); setMs(null);
    const t0 = performance.now();
    try {
      let body: { results: Result[] };
      try {
        body = await post("/requests", { raw_text: text, requester_id: me.id, context: { active_jira_ticket: TICKET } });
      } catch {
        const ids = resources.filter((r) => text.toLowerCase().replace(/[_-]/g, " ").includes(r.name.replace(/[_-]/g, " ").split(" ")[0].toLowerCase())).map((r) => r.id);
        body = await post("/requests", { id: "ui", requester: { id: me.id, name: me.name, role: me.role, team: me.team }, task_description: text, project: PROJECT, resource_ids: ids, requested_duration_days: 14, raw_text: text, context: { active_jira_ticket: TICKET } });
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
  const color = me?.color ?? "#f4f4f4";

  return (
    <div className="ob" style={{ ["--u" as string]: color }}>
      <section className="ob-hero2">
        <div className="ob-hero-text">
          <div className="ob-eyebrow">welcome · {me?.team} · {PROJECT}</div>
          <h1>Hi {me?.name.split(" ")[0]}.</h1>
          <p className="ob-tag">Exactly the access the task needs.<br />For exactly as long as it takes.</p>
          <div className="ob-stats">
            <div><span className="n" style={{ color }}>{mine.length}</span><span className="k">open</span></div>
            <div><span className="n amber">{waiting.length}</span><span className="k">waiting</span></div>
            <div><span className="n">{calls}</span><span className="k">calls</span></div>
            <div><span className="n">{next ? new Date(next).toLocaleDateString([], { day: "numeric", month: "short" }) : "—"}</span><span className="k">until</span></div>
          </div>
        </div>
        <Iris open={mine.length} max={Math.max(3, resources.length)} color={color} />
      </section>

      <div className="ob-steps">
        <section className="ob-step">
          <div className="ob-n">1</div>
          <div className="ob-body">
            <h2>Connect your agent</h2>
            <div className="ob-cmd"><code>{cmd}</code><button className="nb" onClick={copy}>{copied ? "Copied" : "Copy"}</button></div>
          </div>
        </section>

        <section className="ob-step">
          <div className="ob-n">2</div>
          <div className="ob-body">
            <h2>Say what the task is</h2>
            <textarea id="ob-text" value={text} onChange={(e) => setText(e.target.value)} rows={2} />
            <div className="ob-row">
              <button className="nb go" disabled={!online || busy || !text.trim()} onClick={ask}>{busy ? "…" : "Ask"}</button>
              {ms !== null && <span className="ob-ms">decided in <b>{ms} ms</b></span>}
            </div>
            {results && (
              <div className="ob-results">
                {results.map((r, i) => (
                  <div className={`ob-res ${r.status}`} key={i}>
                    <span className="ob-res-st">{r.status}</span>
                    <span className="ob-res-name">{label(r.resource_id, resources)}</span>
                    <span className="ob-res-why">{r.status === "granted" ? "yours now · expires with the task" : r.status === "escalated" ? "a human is deciding" : r.reason ?? ""}</span>
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
            <div className="ob-status">
              {mine.map((g) => <div className="ob-res granted" key={g.id}><span className="ob-res-st">open</span><span className="ob-res-name">{label(g.resource_id, resources)}</span><span className="ob-res-why">until {new Date(g.expires_at).toLocaleDateString([], { day: "numeric", month: "short" })}</span></div>)}
              {waiting.map((c) => <div className="ob-res escalated" key={c.id}><span className="ob-res-st">waiting</span><span className="ob-res-name">{label(c.resource_id, resources)}</span><span className="ob-res-why">on {c.required_approver_ids.filter((a) => !c.votes.some((v) => v.approver_id === a)).map((a) => byId.get(a)?.name.split(" ")[0] ?? a).join(", ") || "—"}</span></div>)}
              {mine.length === 0 && waiting.length === 0 && <div className="ob-tool none"><b>—</b><span>nothing yet</span></div>}
            </div>
            <div className="ob-tools-row">
              <span>request_access</span><span>my_access</span>
              {tools.map((t) => <span className="live" key={t.name}>{t.name}</span>)}
            </div>
          </div>
        </section>
      </div>

      <div className="ob-why">
        <div className="ob-eyebrow">why it works this way</div>
        <div className="ob-cards">
          <div className="ob-card"><b>Google's own Vertex AI Agent Engine shipped an over-privileged default service account.</b><span>Unit 42 · confirmed</span><em>No standing privilege here. Every grant is task-scoped and expires.</em></div>
          <div className="ob-card"><b>Replit's agent deleted a production database during an explicit code freeze.</b><span>confirmed</span><em>Production is critical tier — always a human, and a closed project revokes everything.</em></div>
          <div className="ob-card"><b>Real MCP CVEs exist for exactly this attack surface.</b><span>confirmed</span><em>The tool list is derived from grants; every call is re-checked and recorded.</em></div>
        </div>
      </div>
    </div>
  );
}
