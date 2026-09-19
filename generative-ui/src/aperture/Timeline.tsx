import { useMemo } from "react";
import type { AuditEvent, EscalationCase, Grant } from "./api";
import { label } from "./api";

type Zoom = "session" | "project";
const MIN = 60e3, HOUR = 3600e3, DAY = 86400e3;
const STEPS = [MIN, 2 * MIN, 5 * MIN, 10 * MIN, 30 * MIN, HOUR, 6 * HOUR, DAY, 2 * DAY, 7 * DAY];

interface Props {
  grants: Grant[];
  cases: EscalationCase[];
  events: AuditEvent[];
  zoom: Zoom;
  now: number;
}

interface Bar {
  key: string;
  name: string;
  start: number;
  end: number;
  kind: "active" | "revoked" | "pending" | "denied";
  chip: string;
  sub?: string;
}

function dur(ms: number): string {
  if (ms >= DAY) return `${Math.round(ms / DAY)}d`;
  if (ms >= HOUR) return `${Math.round(ms / HOUR)}h`;
  return `${Math.max(1, Math.round(ms / MIN))}m`;
}

function fmtAxis(t: number, step: number): string {
  const d = new Date(t);
  if (step >= DAY) return d.toLocaleDateString([], { day: "numeric", month: "short" });
  return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", hour12: false });
}

export function Timeline({ grants, cases, events, zoom, now }: Props) {
  // Session zoom is a live window: from just before the first event to a little past now.
  const { t0, span } = useMemo(() => {
    const starts = [
      ...grants.map((g) => Date.parse(g.granted_at)),
      ...cases.map((c) => (c.opened_at ? Date.parse(c.opened_at) : NaN)).filter((n) => !Number.isNaN(n)),
      ...events.map((e) => Date.parse(e.timestamp)),
    ];
    const first = starts.length ? Math.min(...starts) : now;
    if (zoom === "project") return { t0: first - 6 * HOUR, span: 16 * DAY };
    const lead = 2 * MIN;
    const spanLive = Math.max(10 * MIN, now - first + lead + 4 * MIN);
    return { t0: first - lead, span: spanLive };
  }, [grants, cases, events, zoom, now]);

  const x = (t: number) => Math.max(0, Math.min(100, ((t - t0) / span) * 100));

  const bars: Bar[] = useMemo(() => {
    const out: Bar[] = [];
    for (const g of grants) {
      const start = Date.parse(g.granted_at);
      const expiry = Date.parse(g.expires_at);
      if (g.revoked && g.revoked_at) {
        const end = Date.parse(g.revoked_at);
        out.push({ key: g.id, name: label(g.resource_id), start, end, kind: "revoked", chip: `${dur(end - start)} of ${dur(expiry - start)}`, sub: g.revoked_reason ?? "revoked" });
      } else {
        out.push({ key: g.id, name: label(g.resource_id), start, end: expiry, kind: "active", chip: `${dur(expiry - now)} left` });
      }
    }
    for (const c of cases) {
      if (c.status !== "pending") continue;
      const start = c.opened_at ? Date.parse(c.opened_at) : now - MIN;
      const got = c.votes.filter((v) => v.approved).length;
      out.push({ key: c.id, name: label(c.resource_id), start, end: now, kind: "pending", chip: `${got} of ${c.required_approver_ids.length}`, sub: "waiting" });
    }
    for (const e of events) {
      if (e.type !== "request_denied") continue;
      const start = Date.parse(e.timestamp);
      out.push({ key: e.id, name: label(String(e.payload.resource_id ?? "")), start, end: start + 2 * MIN, kind: "denied", chip: "denied", sub: e.detail });
    }
    return out.sort((a, b) => a.start - b.start);
  }, [grants, cases, events, now]);

  const calls = events.filter((e) => e.type === "action_executed");

  const step = STEPS.find((s) => span / s <= 8) ?? STEPS[STEPS.length - 1];
  const ticks: number[] = [];
  for (let t = Math.ceil(t0 / step) * step; t <= t0 + span; t += step) ticks.push(t);

  const bodyHeight = bars.length * 56 + (calls.length ? 64 : 24) + 16;

  return (
    <div className="tl">
      <div className="tl-axis">
        {ticks.map((t) => (
          <span key={t} style={{ left: `${x(t)}%`, opacity: Math.abs(x(t) - x(now)) < 4 ? 0 : 1 }}>{fmtAxis(t, step)}</span>
        ))}
        <span className="tl-now-pill" style={{ left: `${x(now)}%` }}>Now</span>
      </div>
      <div className="tl-body" style={{ height: `${bodyHeight}px` }}>
        <div className="tl-now" style={{ left: `${x(now)}%` }} />
        {bars.map((b, i) => {
          const left = x(b.start);
          const right = x(b.end);
          const clipped = b.end > t0 + span;
          return (
            <div className="tl-lane" key={b.key} style={{ top: `${i * 56}px` }}>
              <div className={`pill ${b.kind} ${clipped ? "clipped" : ""}`} style={{ left: `${left}%`, width: `${Math.max(right - left, 0)}%` }} title={b.sub}>
                <span className="pill-name">{b.name}</span>
                <span className="pill-chip">{b.chip}</span>
              </div>
            </div>
          );
        })}
        {bars.length === 0 && <div className="tl-empty">No leases yet</div>}
        <div className="tl-calls" style={{ top: `${bars.length * 56 + 12}px` }}>
          {calls.map((e) => {
            const bounced = e.payload.status === "bounced";
            return (
              <span key={e.id} className={`tcall ${bounced ? "bounced" : ""}`} style={{ left: `${x(Date.parse(e.timestamp))}%` }} title={e.detail}>
                <i />
                <b>{String(e.payload.tool ?? e.detail.split(" ")[0])}</b>
              </span>
            );
          })}
        </div>
      </div>
    </div>
  );
}
