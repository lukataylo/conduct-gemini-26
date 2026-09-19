import { useMemo } from "react";
import type { AuditEvent, EscalationCase, Grant, Resource, User } from "./api";
import { ALL } from "./api";

const COLS = 36;
const MIN = 60e3, HOUR = 3600e3, DAY = 86400e3;

interface Props {
  grants: Grant[];
  cases: EscalationCase[];
  events: AuditEvent[];
  resources: Resource[];
  users: User[];
  selected: string; // user id or ALL
  zoom: "session" | "project";
  now: number;
}

type Cell = { fills: { color: string; a: number }[]; pending?: string; red?: boolean };

export function Matrix({ grants, cases, events, resources, users, selected, zoom, now }: Props) {
  const byId = useMemo(() => new Map(users.map((u) => [u.id, u])), [users]);
  const visible = selected === ALL ? users : users.filter((u) => u.id === selected);
  const visibleIds = new Set(visible.map((u) => u.id));

  const { t0, span } = useMemo(() => {
    const starts = [...grants.map((g) => Date.parse(g.granted_at)), ...events.map((e) => Date.parse(e.timestamp))];
    const first = starts.length ? Math.min(...starts) : now;
    if (zoom === "project") return { t0: first - 6 * HOUR, span: 16 * DAY };
    return { t0: first - 2 * MIN, span: Math.max(10 * MIN, now - first + 6 * MIN) };
  }, [grants, events, zoom, now]);
  const bucket = span / COLS;
  const col = (t: number) => Math.floor((t - t0) / bucket);

  const rows = useMemo(() => {
    const rowIds = resources.map((r) => r.id);
    const grid: Record<string, Cell[]> = {};
    const blank = () => Array.from({ length: COLS }, () => ({ fills: [] as { color: string; a: number }[] }));
    for (const id of rowIds) grid[id] = blank();
    grid.__calls = blank();
    grid.__denied = blank();

    for (const g of grants) {
      if (!visibleIds.has(g.requester_id) || !grid[g.resource_id]) continue;
      const u = byId.get(g.requester_id);
      if (!u) continue;
      const s = Date.parse(g.granted_at);
      const e = g.revoked && g.revoked_at ? Date.parse(g.revoked_at) : Math.min(Date.parse(g.expires_at), now);
      for (let c = Math.max(0, col(s)); c <= Math.min(COLS - 1, col(e)); c++) {
        const bs = t0 + c * bucket, be = bs + bucket;
        const cover = (Math.min(e, be) - Math.max(s, bs)) / bucket;
        if (cover > 0) grid[g.resource_id][c].fills.push({ color: u.color, a: 0.35 + 0.65 * Math.min(1, cover) });
      }
    }
    for (const c of cases) {
      if (c.status !== "pending" || !visibleIds.has(c.requester_id) || !grid[c.resource_id]) continue;
      const u = byId.get(c.requester_id);
      const s = c.opened_at ? Date.parse(c.opened_at) : now;
      for (let k = Math.max(0, col(s)); k <= Math.min(COLS - 1, col(now)); k++) grid[c.resource_id][k].pending = u?.color;
    }
    for (const e of events) {
      if (!visibleIds.has(e.actor) && e.type !== "action_executed") continue;
      const k = col(Date.parse(e.timestamp));
      if (k < 0 || k >= COLS) continue;
      if (e.type === "action_executed") {
        const bounced = e.payload.status === "bounced";
        const g = grants.find((x) => x.id === e.grant_id);
        const uid = g?.requester_id ?? (visible[0]?.id ?? "");
        if (!visibleIds.has(uid)) continue;
        const u = byId.get(uid);
        if (bounced) grid.__denied[k].red = true;
        else if (u) grid.__calls[k].fills.push({ color: u.color, a: 1 });
      }
      if (e.type === "request_denied") grid.__denied[k].red = true;
    }
    return grid;
  }, [grants, cases, events, resources, byId, visibleIds, t0, bucket, now]);

  const ticks = Array.from({ length: 6 }, (_, i) => t0 + (span * i) / 6);
  const fmt = (t: number) =>
    zoom === "project"
      ? new Date(t).toLocaleDateString([], { day: "numeric", month: "short" })
      : new Date(t).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", hour12: false });

  const rowList = [
    ...resources.map((r) => ({ id: r.id, name: r.name, sub: `${r.sensitivity} · ${r.owning_team}` })),
    { id: "__calls", name: "calls", sub: "tool calls" },
    { id: "__denied", name: "refused", sub: "denied · bounced" },
  ];

  return (
    <div className="mx">
      <div className="mx-axis">
        <span className="mx-label" />
        <div className="mx-ticks">{ticks.map((t) => <span key={t}>{fmt(t)}</span>)}</div>
      </div>
      {rowList.map((r) => (
        <div className="mx-row" key={r.id}>
          <span className="mx-label"><b>{r.name}</b><small>{r.sub}</small></span>
          <div className="mx-cells">
            {rows[r.id].map((cell, i) => {
              const k = col(now);
              const future = i > k;
              if (cell.red) return <i key={i} className="mx-cell red" />;
              if (cell.fills.length === 0 && cell.pending) return <i key={i} className="mx-cell pend" style={{ borderColor: cell.pending }} />;
              if (cell.fills.length === 0) return <i key={i} className={`mx-cell ${future ? "future" : ""}`} />;
              if (cell.fills.length === 1) return <i key={i} className="mx-cell" style={{ background: cell.fills[0].color, opacity: cell.fills[0].a }} />;
              const stops = cell.fills.map((f, j) => `${f.color} ${(j / cell.fills.length) * 100}% ${((j + 1) / cell.fills.length) * 100}%`).join(", ");
              return <i key={i} className="mx-cell" style={{ background: `linear-gradient(135deg, ${stops})` }} />;
            })}
          </div>
        </div>
      ))}
      <div className="mx-legend">
        {visible.map((u) => (
          <span key={u.id}><i style={{ background: u.color }} />{u.name}</span>
        ))}
        <span><i className="pend" />pending</span>
        <span><i className="red" />refused</span>
      </div>
    </div>
  );
}
