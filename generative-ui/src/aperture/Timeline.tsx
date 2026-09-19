import { useMemo } from "react";
import type { AuditEvent, EscalationCase, Grant } from "./api";
import { label } from "./api";

type Zoom = "session" | "project";
const SPAN: Record<Zoom, number> = { session: 6 * 3600e3, project: 16 * 86400e3 };

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

function days(ms: number): string {
  const d = ms / 86400e3;
  if (d >= 1) return `${Math.round(d)}d`;
  const h = ms / 3600e3;
  if (h >= 1) return `${Math.round(h)}h`;
  return `${Math.max(1, Math.round(ms / 60e3))}m`;
}

function fmtAxis(t: number, zoom: Zoom): string {
  const d = new Date(t);
  if (zoom === "session") return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  return d.toLocaleDateString([], { day: "numeric", month: "short" });
}

export function Timeline({ grants, cases, events, zoom, now }: Props) {
  const t0 = useMemo(() => {
    const firsts = [
      ...grants.map((g) => Date.parse(g.granted_at)),
      ...cases.map((c) => (c.opened_at ? Date.parse(c.opened_at) : NaN)).filter((n) => !Number.isNaN(n)),
      ...events.map((e) => Date.parse(e.timestamp)),
    ];
    const first = firsts.length ? Math.min(...firsts) : now;
    return first - (zoom === "session" ? 10 * 60e3 : 6 * 3600e3);
  }, [grants, cases, events, zoom, now]);

  const span = SPAN[zoom];
  const x = (t: number) => Math.max(0, Math.min(100, ((t - t0) / span) * 100));

  const bars: Bar[] = useMemo(() => {
    const out: Bar[] = [];
    for (const g of grants) {
      const start = Date.parse(g.granted_at);
      const expiry = Date.parse(g.expires_at);
      if (g.revoked && g.revoked_at) {
        const end = Date.parse(g.revoked_at);
        out.push({ key: g.id, name: label(g.resource_id), start, end, kind: "revoked", chip: `${days(end - start)} used of ${days(expiry - start)}`, sub: g.revoked_reason ?? "revoked" });
      } else {
        out.push({ key: g.id, name: label(g.resource_id), start, end: expiry, kind: "active", chip: `${days(expiry - now)} left` });
      }
    }
    for (const c of cases) {
      if (c.status !== "pending") continue;
      const start = c.opened_at ? Date.parse(c.opened_at) : now - 60e3;
      const got = c.votes.filter((v) => v.approved).length;
      out.push({ key: c.id, name: label(c.resource_id), start, end: now, kind: "pending", chip: `${got} of ${c.required_approver_ids.length}`, sub: "waiting" });
    }
    for (const e of events) {
      if (e.type !== "request_denied") continue;
      const start = Date.parse(e.timestamp);
      out.push({ key: e.id, name: label(String(e.payload.resource_id ?? "")), start, end: start + 15 * 60e3, kind: "denied", chip: "denied", sub: e.detail });
    }
    return out.sort((a, b) => a.start - b.start);
  }, [grants, cases, events, now]);

  const calls = events.filter((e) => e.type === "action_executed");

  const ticks: number[] = [];
  const step = zoom === "session" ? 3600e3 : 2 * 86400e3;
  for (let t = Math.ceil(t0 / step) * step; t <= t0 + span; t += step) ticks.push(t);

  return (
    <div className="tl">
      <div className="tl-axis">
        {ticks.map((t) => (
          <span key={t} style={{ left: `${x(t)}%` }}>{fmtAxis(t, zoom)}</span>
        ))}
        <span className="tl-now-pill" style={{ left: `${x(now)}%` }}>Now</span>
      </div>
      <div className="tl-body">
        <div className="tl-now" style={{ left: `${x(now)}%` }} />
        {bars.map((b, i) => {
          const left = x(b.start);
          const right = x(b.end);
          const clipped = b.end > t0 + span;
          return (
            <div className="tl-lane" key={b.key} style={{ top: `${i * 56}px` }}>
              <div
                className={`pill ${b.kind} ${clipped ? "clipped" : ""}`}
                style={{ left: `${left}%`, width: `${Math.max(right - left, 3.2)}%` }}
                title={b.sub}
              >
                <span className="pill-name">{b.name}</span>
                <span className="pill-chip">{b.chip}</span>
              </div>
            </div>
          );
        })}
        {bars.length === 0 && <div className="tl-empty">No leases yet</div>}
        <div className="tl-calls" style={{ top: `${bars.length * 56 + 8}px` }}>
          {calls.map((e) => {
            const bounced = e.payload.status === "bounced";
            return (
              <span key={e.id} className={`call ${bounced ? "bounced" : ""}`} style={{ left: `${x(Date.parse(e.timestamp))}%` }} title={e.detail}>
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
