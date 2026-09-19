import { useEffect, useRef, useState } from "react";
import type { AuditEvent, EscalationCase, Grant, Resource, User as Person } from "./api";
import { label, PROJECT } from "./api";

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

interface Tool { name: string }

/** A dot-matrix iris: the opening grows with the number of active leases. */
function Iris({ open, max, color }: { open: number; max: number; color: string }) {
  const ref = useRef<HTMLCanvasElement>(null);
  useEffect(() => {
    const c = ref.current;
    if (!c) return;
    const ctx = c.getContext("2d");
    if (!ctx) return;
    const N = 23, S = 12;
    c.width = N * S * 2; c.height = N * S * 2; c.style.width = `${N * S}px`; c.style.height = `${N * S}px`;
    ctx.scale(2, 2);
    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    let raf = 0, t0 = performance.now();
    const target = 2.5 + (max ? (open / max) * 6.5 : 0);
    const draw = (t: number) => {
      const r = target + (reduce ? 0 : Math.sin((t - t0) / 900) * 0.35);
      ctx.clearRect(0, 0, N * S, N * S);
      for (let y = 0; y < N; y++) for (let x = 0; x < N; x++) {
        const dx = x - (N - 1) / 2, dy = y - (N - 1) / 2, d = Math.sqrt(dx * dx + dy * dy), ring = Math.abs(d - r);
        let a = d < r ? 0.02 : 0.08;
        if (ring < 0.9) a = 1 - ring * 0.6; else if (ring < 2.2) a = 0.35 - (ring - 0.9) * 0.2;
        ctx.globalAlpha = Math.max(0.03, Math.min(1, a));
        ctx.fillStyle = ring < 2.2 ? color : "#ffffff";
        ctx.beginPath(); ctx.arc(x * S + S / 2, y * S + S / 2, ring < 0.9 ? 3.2 : 2.2, 0, Math.PI * 2); ctx.fill();
      }
      ctx.globalAlpha = 1;
      if (!reduce) raf = requestAnimationFrame(draw);
    };
    draw(t0);
    return () => cancelAnimationFrame(raf);
  }, [open, max, color]);
  return <canvas ref={ref} className="iris" aria-label={`${open} of ${max} leases open`} />;
}

/** Dot-matrix glyphs for the five stages, 7×7. */
const GLYPHS: Record<string, string[]> = {
  ask:     ["..###..", ".#...#.", "....#..", "...#...", "...#...", ".......", "...#..."],
  decide:  [".......", "#.....#", ".#...#.", "..#.#..", "...#...", "...#...", "...#..."],
  approve: [".......", "......#", ".....#.", "#...#..", ".#.#...", "..#....", "......."],
  use:     ["..###..", ".#...#.", "#..#..#", "#..##.#", "#.....#", ".#...#.", "..###.."],
  expire:  ["..###..", ".#...#.", "#..#..#", "#..#..#", "#.....#", ".#...#.", "..###.."],
};

function Glyph({ name, on, color }: { name: string; on: boolean; color: string }) {
  return (
    <div className="fl-glyph" aria-hidden="true">
      {GLYPHS[name].map((row, y) => row.split("").map((ch, x) => <i key={`${y}${x}`} style={ch === "#" ? { background: on ? color : "#f4f4f4", opacity: on ? 1 : 0.55 } : undefined} />))}
    </div>
  );
}

export function UserScreen({ grants, cases, events, resources, users, selected, now }: Props) {
  const me = users.find((u) => u.id === selected) ?? users[0];
  const [copied, setCopied] = useState(false);
  const [tools, setTools] = useState<Tool[]>([]);
  const [stage, setStage] = useState(0);

  const byId = new Map(users.map((u) => [u.id, u]));
  const mine = me ? grants.filter((g) => g.requester_id === me.id && !g.revoked && Date.parse(g.expires_at) > now) : [];
  const waiting = me ? cases.filter((c) => c.requester_id === me.id && c.status === "pending") : [];
  const myRequests = new Set([...grants, ...cases].filter((x) => x.requester_id === me?.id).map((x) => x.request_id));
  const myEvents = me ? events.filter((e) => e.actor === me.id || e.payload.requester_id === me.id || (e.request_id !== null && myRequests.has(e.request_id))) : [];
  const asked = myEvents.filter((e) => e.type === "request_received").length;
  const granted = myEvents.filter((e) => e.type === "grant_issued").length;
  const escalated = myEvents.filter((e) => e.type === "escalated").length;
  const approvedBy = [...new Set(cases.filter((c) => c.requester_id === me?.id).flatMap((c) => c.votes.filter((v) => v.approved).map((v) => byId.get(v.approver_id)?.name.split(" ")[0] ?? v.approver_id)))];
  const calls = myEvents.filter((e) => e.type === "action_executed").length;
  const ended = me ? grants.filter((g) => g.requester_id === me.id && (g.revoked || Date.parse(g.expires_at) <= now)).length : 0;
  const next = mine.map((g) => Date.parse(g.expires_at)).sort((a, b) => a - b)[0];

  useEffect(() => {
    if (!me) return;
    let alive = true;
    fetch(`/api/tools?requester_id=${me.id}`).then((r) => r.json()).then((t) => alive && setTools(t)).catch(() => {});
    return () => { alive = false; };
  }, [me?.id, grants.length]);

  useEffect(() => {
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    const id = setInterval(() => setStage((s) => (s + 1) % 5), 1600);
    return () => clearInterval(id);
  }, []);

  const cmd = `claude mcp add aperture -e APERTURE_REQUESTER=${me?.id ?? "u-newhire-1"} -- python agent-runtime/mcp_serve.py`;
  const copy = () => navigator.clipboard?.writeText(cmd).then(() => { setCopied(true); setTimeout(() => setCopied(false), 1200); });
  const color = me?.color ?? "#f4f4f4";
  const fmtDay = (t: number) => new Date(t).toLocaleDateString([], { day: "numeric", month: "short" });

  const stages = [
    { id: "ask", title: "Your agent asks", n: String(asked), sub: asked ? "requests, in plain language" : "nothing asked yet" },
    { id: "decide", title: "The engine decides", n: `${granted}·${escalated}`, sub: "granted · escalated, in milliseconds" },
    { id: "approve", title: "A human only if needed", n: String(approvedBy.length), sub: approvedBy.length ? `approved by ${approvedBy.join(", ")}` : "no one needed yet" },
    { id: "use", title: "Tools appear", n: String(calls), sub: calls ? "calls, each re-checked" : "no calls yet" },
    { id: "expire", title: "Then they vanish", n: next ? fmtDay(next) : String(ended), sub: next ? "next expiry — or when the project closes" : `${ended} already ended` },
  ];

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
            <div><span className="n">{next ? fmtDay(next) : "—"}</span><span className="k">until</span></div>
          </div>
        </div>
        <Iris open={mine.length} max={Math.max(3, resources.length)} color={color} />
      </section>

      <div className="ob-steps">
        <section className="ob-step">
          <div className="ob-n">1</div>
          <div className="ob-body">
            <h2>Connect your agent</h2>
            <p>One line. Your agent gets <code>request_access</code>; every tool it's granted appears — and disappears — on its own.</p>
            <div className="ob-cmd"><code>{cmd}</code><button className="nb" onClick={copy}>{copied ? "Copied" : "Copy"}</button></div>
          </div>
        </section>

        <section className="ob-step">
          <div className="ob-n">2</div>
          <div className="ob-body wide">
            <h2>How it works</h2>
            <div className="fl">
              {stages.map((s, i) => (
                <div className={`fl-stage ${stage === i ? "on" : ""}`} key={s.id} onMouseEnter={() => setStage(i)}>
                  <Glyph name={s.id} on={stage === i} color={color} />
                  <b>{s.n}</b>
                  <span className="fl-t">{s.title}</span>
                  <small>{s.sub}</small>
                </div>
              ))}
            </div>
          </div>
        </section>

        <section className="ob-step">
          <div className="ob-n">3</div>
          <div className="ob-body">
            <h2>Where you stand</h2>
            <div className="ob-status">
              {mine.map((g) => <div className="ob-res granted" key={g.id}><span className="ob-res-st">open</span><span className="ob-res-name">{label(g.resource_id, resources)}</span><span className="ob-res-why">until {fmtDay(Date.parse(g.expires_at))}</span></div>)}
              {waiting.map((c) => <div className="ob-res escalated" key={c.id}><span className="ob-res-st">waiting</span><span className="ob-res-name">{label(c.resource_id, resources)}</span><span className="ob-res-why">on {c.required_approver_ids.filter((a) => !c.votes.some((v) => v.approver_id === a)).map((a) => byId.get(a)?.name.split(" ")[0] ?? a).join(", ") || "—"}</span></div>)}
              {mine.length === 0 && waiting.length === 0 && <div className="ob-tool none"><b>—</b><span>nothing yet — ask through your agent, or the Gemini bubble</span></div>}
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
