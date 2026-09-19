import { useEffect, useState } from "react";

/**
 * The Policy tab: the Friday Finance Freeze, scenario by scenario, straight from
 * GET /demo/policy/final-story. Every outcome on this page is the engine's own output
 * on fixed inputs; the page adds no logic of its own beyond choosing what to show.
 */

interface Person { id: string; name: string; role: string; team: string; type: string; tenure_days: number }
interface Res { id: string; name: string; type: string; owning_team: string; sensitivity: string; capability: string; surface?: string | null; category?: string | null; metadata: Record<string, unknown> }
interface Decision {
  resource_id: string;
  decision: "auto_grant" | "auto_deny" | "escalate" | "step_up_auth_required" | "witness_required";
  reason: string;
  ttl_hours: number | null;
  required_approval_groups: string[];
  metadata: Record<string, unknown>;
}
interface Case {
  id: string; resource_id: string; required_approver_ids: string[]; requested_duration_days: number;
  human_summary?: string | null; routing_rationale?: string | null; peer_percentile?: string | null;
  risk_score?: string | null; policy_violation?: string | null; suggested_downgrade?: string | null;
  sla_due_at?: string | null; opened_at?: string; timeout_action: string;
}
interface DemoGrant { id: string; resource_id: string; capability: string | null; metadata: Record<string, unknown>; granted_at: string; expires_at: string; reclaimed: boolean; reclaim_reason: string | null }
interface ReaperState { label: string; jira: { status: string; summary?: string }; grants: DemoGrant[]; revocations: { grant_id: string; reason: string; metadata: Record<string, unknown> }[]; context_snapshot: Snapshot; toast: string | null }
interface Snapshot { location?: string | null; quiet_period?: boolean; snyk_score?: string | null }
interface Scenario {
  id: string; beat: number; kind: "request" | "reaper"; title: string; narrative: string;
  requester: Person; resources: Res[]; ticket: { ticket_id: string | null; incident_id: string | null; source: string | null; signal: Record<string, unknown> };
  context: { requester_location: Record<string, unknown>; company_calendar: Record<string, unknown> };
  context_snapshot?: Snapshot; compliance: string[];
  request?: { requested_duration_days: number; task_description: string; metadata: Record<string, unknown> };
  active_grants?: DemoGrant[]; decisions?: Decision[]; cases?: Case[];
  before?: ReaperState; after?: ReaperState; toast?: string;
}
interface Story {
  story: string; principle: string; demo_now: string; quiet_period: { start: string; end: string; label: string };
  engine: { module: string; entry_points: string[]; model_calls: number };
  people: Person[]; scenarios: Scenario[]; checks: { name: string; ok: boolean; detail: string }[]; all_pass: boolean;
}

const OUTCOME: Record<Decision["decision"], { label: string; cls: string }> = {
  auto_grant: { label: "granted", cls: "ok" },
  escalate: { label: "escalated", cls: "wait" },
  auto_deny: { label: "denied", cls: "no" },
  witness_required: { label: "witness", cls: "wait" },
  step_up_auth_required: { label: "step-up", cls: "wait" },
};

function outcomeOf(s: Scenario): { label: string; cls: string } {
  if (s.kind === "reaper") return { label: "reclaimed", cls: "no" };
  const kinds = (s.decisions ?? []).map((d) => d.decision);
  if (kinds.length > 1 && new Set(kinds).size > 1) return { label: kinds.map((k) => OUTCOME[k].label).join(" · "), cls: "mix" };
  return OUTCOME[kinds[0] ?? "auto_deny"];
}

const fmtT = (iso: string) => new Date(iso).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", timeZone: "UTC" }) + " UTC";
const hrs = (from: string, to: string) => Math.round((Date.parse(to) - Date.parse(from)) / 36e5);
const ttl = (h: number | null) => (h === null ? "" : h % 24 === 0 && h >= 48 ? `${h / 24}d` : `${h}h`);
const group = (g: string) => g.replace(/_/g, " ").toUpperCase();

export function Policy() {
  const [story, setStory] = useState<Story | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [sel, setSel] = useState(0);
  const [done, setDone] = useState(false); // reaper: has the presenter marked ATLAS-101 DONE

  useEffect(() => {
    let alive = true;
    fetch("/api/demo/policy/final-story")
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`${r.status}`))))
      .then((s: Story) => alive && setStory(s))
      .catch((e) => alive && setErr(String(e)));
    return () => { alive = false; };
  }, []);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (!story || (e.target as HTMLElement)?.tagName === "TEXTAREA") return;
      if (e.key === "ArrowRight" || e.key === "ArrowDown") setSel((i) => Math.min(story.scenarios.length - 1, i + 1));
      if (e.key === "ArrowLeft" || e.key === "ArrowUp") setSel((i) => Math.max(0, i - 1));
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [story]);

  if (err) return <div className="pol"><div className="offline">policy story unavailable · {err}</div></div>;
  if (!story) return <div className="pol"><div className="offline">running the engine…</div></div>;

  const s = story.scenarios[sel];
  const people = new Map(story.people.map((p) => [p.id, p]));
  const passed = story.checks.filter((c) => c.ok).length;

  return (
    <div className="pol">
      <section className="pol-hero">
        <div>
          <div className="ob-eyebrow">policy · {story.story}</div>
          <h1>AI can parse.<br /><span>Deterministic policy decides.</span></h1>
          <p>Eight beats, one engine, zero model calls on the decision path. Every outcome below is the engine's own output on fixed inputs: the same rules that gate every request in this console.</p>
        </div>
        <div className="pol-checks" aria-label="Success criteria">
          <div className="pol-checks-h"><b className={passed === story.checks.length ? "ok" : "no"}>{passed}/{story.checks.length}</b><span>success criteria, checked against the engine's output</span></div>
          {story.checks.map((c) => <div key={c.name} className={`pol-check ${c.ok ? "ok" : "no"}`} title={c.detail}><i /><span>{c.name}</span></div>)}
        </div>
      </section>

      <div className="pol-body">
        <nav className="pol-list" aria-label="Scenarios">
          {story.scenarios.map((x, i) => {
            const o = outcomeOf(x);
            return (
              <button key={x.id} className="pol-item" aria-pressed={i === sel} onClick={() => setSel(i)}>
                <b>{String(x.beat).padStart(2, "0")}</b>
                <span className="pol-item-t">{x.title}</span>
                <span className={`pol-pill ${o.cls}`}>{o.label}</span>
              </button>
            );
          })}
          <div className="pol-engine">
            <span className="k">engine</span><code>{story.engine.module}</code>
            <span className="k">entry points</span><code>{story.engine.entry_points.join(" · ")}</code>
            <span className="k">model calls</span><code>{story.engine.model_calls}</code>
            <span className="k">clock</span><code>{story.demo_now.replace("T", " ").replace("+00:00", "Z")}</code>
          </div>
        </nav>

        <main className="pol-main" key={s.id}>
          <div className="pol-head">
            <div className="ob-eyebrow">beat {s.beat} of {story.scenarios.length}</div>
            <h2>{s.title}</h2>
            <p>{s.narrative}</p>
          </div>

          <div className="pol-facts">
            <div className="pol-fact">
              <span className="k">requester</span>
              <b>{s.requester.name}</b>
              <small>{s.requester.role} · {s.requester.team}{s.requester.type !== "EMPLOYEE" ? ` · ${s.requester.type.toLowerCase().replace("_", " ")}` : ""}</small>
            </div>
            <div className="pol-fact">
              <span className="k">resource{s.resources.length > 1 ? "s" : ""}</span>
              {s.resources.map((r) => <b key={r.id} className="mono">{r.name}</b>)}
              <small>{[...new Set(s.resources.map((r) => `${r.type.replace(/_/g, " ")} · ${r.sensitivity} · ${r.owning_team}`))].join(" / ")}</small>
            </div>
            <div className="pol-fact">
              <span className="k">capability</span>
              {s.resources.map((r) => {
                const d = s.decisions?.find((x) => x.resource_id === r.id);
                const down = d?.metadata.downgraded_capability as string | undefined;
                const lease = s.before?.grants.find((g) => g.resource_id === r.id); // reaper: the lease's capability, not the resource's
                return <b key={r.id} className="mono">{lease?.capability ?? r.capability}{down ? <em> → {down}</em> : null}{lease?.metadata.restriction ? <em> · {String(lease.metadata.restriction)}</em> : null}</b>;
              })}
              <small>{s.request ? `${s.request.requested_duration_days}d requested` : "held under approval"}</small>
            </div>
            <div className="pol-fact">
              <span className="k">business context</span>
              <b className="mono">{s.ticket.ticket_id ?? s.ticket.incident_id ?? "none"}</b>
              <small>{s.ticket.source ?? "no ticket"}{s.ticket.signal?.status ? ` · ${String(s.ticket.signal.status).toLowerCase().replace("_", " ")}` : ""}{s.ticket.signal?.requester_email ? ` · from ${s.ticket.signal.requester_email}` : ""}{s.ticket.signal?.summary ? ` · ${s.ticket.signal.summary}` : ""}</small>
            </div>
          </div>

          {s.kind === "request" && (
            <>
              {s.active_grants && s.active_grants.length > 0 && (
                <div className="pol-sec">
                  <div className="ob-eyebrow">already held</div>
                  <div className="pol-leases">
                    {s.active_grants.map((g) => (
                      <div key={g.id} className="pol-lease held">
                        <span className="pol-lease-st">open</span>
                        <span className="mono">{s.resources.find((r) => r.id === g.resource_id)?.name ?? g.resource_id}</span>
                        <span className="pol-lease-why">granted {Math.round((Date.parse(story.demo_now) - Date.parse(g.granted_at)) / 6e4)} min ago · {String(g.metadata.ticket_id)}</span>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              <div className="pol-sec">
                <div className="ob-eyebrow">decision</div>
                <div className="pol-decisions">
                  {(s.decisions ?? []).map((d) => {
                    const o = OUTCOME[d.decision];
                    const r = s.resources.find((x) => x.id === d.resource_id);
                    return (
                      <div key={d.resource_id} className={`pol-dec ${o.cls}`}>
                        <div className="pol-dec-top">
                          <span className="pol-dec-st">{o.label}</span>
                          <span className="mono">{r?.name ?? d.resource_id}</span>
                          <span className="pol-dec-meta">
                            {d.ttl_hours !== null ? `TTL ${ttl(d.ttl_hours)}` : d.required_approval_groups.length ? `to ${d.required_approval_groups.map(group).join(", ")}` : "no grant minted"}
                            {d.metadata.restriction ? ` · ${String(d.metadata.restriction)}` : ""}
                            {d.metadata.anomaly_alarm ? " · ANOMALY ALARM" : ""}
                          </span>
                        </div>
                        <div className="pol-reason"><span className="k">exact policy reason</span><code>{d.reason}</code></div>
                      </div>
                    );
                  })}
                </div>
              </div>

              {(s.cases ?? []).map((c) => {
                const d = s.decisions?.find((x) => x.resource_id === c.resource_id);
                const r = s.resources.find((x) => x.id === c.resource_id);
                return (
                  <div className="pol-sec" key={c.id}>
                    <div className="ob-eyebrow">what the approver sees</div>
                    <div className="pol-card">
                      <div className="pol-card-top"><span className="mono">{r?.name}</span><span className={`pol-risk ${c.risk_score ?? ""}`}>risk {c.risk_score ?? "—"}</span></div>
                      <div className="pol-card-grid">
                        <div><span className="k">policy violation</span><b>{c.policy_violation ?? "—"}</b></div>
                        <div><span className="k">peer signal</span><b>{c.peer_percentile ?? "unavailable"}{d?.metadata.peer_warning ? <em> · {String(d.metadata.peer_warning)}</em> : null}</b></div>
                        <div><span className="k">suggested downgrade</span><b>{c.suggested_downgrade ?? (d?.metadata.downgraded_capability ? `${r?.capability} → ${String(d.metadata.downgraded_capability)}` : "none")}</b></div>
                        <div><span className="k">required approvers</span><b>{c.required_approver_ids.map((id) => people.get(id)?.name ?? id).join(", ")}{d?.required_approval_groups.length ? <em> · {d.required_approval_groups.map(group).join(", ")}</em> : null}</b></div>
                        <div><span className="k">SLA</span><b>{c.sla_due_at && c.opened_at ? `${hrs(c.opened_at, c.sla_due_at)}h · due ${fmtT(c.sla_due_at)}` : "—"}<em> · on timeout {c.timeout_action.replace("_", " ")}</em></b></div>
                        <div><span className="k">asked for</span><b>{c.requested_duration_days}d</b></div>
                      </div>
                      {c.human_summary && <div className="pol-summary">{c.human_summary}</div>}
                      {c.routing_rationale && <div className="pol-route">{c.routing_rationale}</div>}
                      <div className="pol-card-btns"><span className="nb deny" aria-disabled="true">Deny</span><span className="nb go" aria-disabled="true">Approve</span><small>static chrome · never generated</small></div>
                    </div>
                  </div>
                );
              })}
            </>
          )}

          {s.kind === "reaper" && s.before && s.after && (() => {
            const st = done ? s.after : s.before;
            return (
              <div className="pol-sec">
                <div className="pol-reaper-bar">
                  <div className="ob-eyebrow">reaper loop · live grants vs business signals</div>
                  <span className={`pol-pill ${done ? "no" : "wait"}`}>ATLAS-101 · {st.jira.status.toLowerCase().replace("_", " ")}</span>
                  <button className={`nb ${done ? "" : "go"}`} onClick={() => setDone((d) => !d)}>{done ? "Reopen ATLAS-101" : "Mark ATLAS-101 DONE"}</button>
                </div>
                {st.toast && <div className="pol-toast" role="status"><i />{st.toast}</div>}
                <div className="pol-leases">
                  {st.grants.map((g) => {
                    const r = s.resources.find((x) => x.id === g.resource_id);
                    const left = hrs(story.demo_now, g.expires_at);
                    return (
                      <div key={g.id} className={`pol-lease ${g.reclaimed ? "reclaimed" : "held"}`}>
                        <span className="pol-lease-st">{g.reclaimed ? "reclaimed" : "open"}</span>
                        <span className="mono">{r?.name ?? g.resource_id}<em> · {g.capability}{g.metadata.restriction ? ` · ${String(g.metadata.restriction)}` : ""}</em></span>
                        <span className="pol-lease-why">{g.reclaimed ? g.reclaim_reason : `${String(g.metadata.ticket_id)} · ${left}h left of TTL${g.metadata.approved_by ? ` · approved by ${people.get(String(g.metadata.approved_by))?.name ?? g.metadata.approved_by}` : ""}`}</span>
                        <span className="pol-lease-track"><i style={{ width: `${Math.max(4, Math.min(100, (left / hrs(g.granted_at, g.expires_at)) * 100))}%` }} /></span>
                      </div>
                    );
                  })}
                </div>
                {st.revocations.map((rv) => (
                  <div className="pol-reason" key={rv.grant_id}><span className="k">RevocationAction · {String(rv.metadata.reaper_trigger)}</span><code>{rv.reason}</code></div>
                ))}
                {!done && <p className="pol-hint">The read-only lease the CFO approved is live with 22 h left. Mark the ticket done and watch the engine reclaim it before the TTL, leaving the ATLAS-118 lease alone.</p>}
              </div>
            );
          })()}

          <div className="pol-foot">
            <div className="pol-crumbs">
              <span className="k">compliance</span>
              {s.compliance.length ? s.compliance.map((c, i) => <span key={c}><code>{c}</code>{i < s.compliance.length - 1 ? <em>›</em> : null}</span>) : <code>none triggered</code>}
            </div>
            <div className="pol-snap">
              <span className="k">context snapshot</span>
              {Object.entries((s.kind === "reaper" ? (done ? s.after : s.before)?.context_snapshot : s.context_snapshot) ?? {}).map(([k, v]) => (
                <span key={k} className={`pol-snap-kv ${v === true ? "on" : ""}`}><b>{k.replace("_", " ")}</b>{v === null || v === undefined ? "—" : String(v)}</span>
              ))}
              <span className="pol-snap-kv"><b>hr</b>active</span>
              {s.context.requester_location?.label ? <span className="pol-snap-kv on"><b>at</b>{String(s.context.requester_location.label)}</span> : null}
            </div>
          </div>
        </main>
      </div>
    </div>
  );
}
