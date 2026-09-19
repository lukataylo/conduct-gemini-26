import { useEffect, useMemo, useState } from "react";
import type { AuditEvent, CuFrame, CuPreview, Grant, Resource, User } from "./api";
import { ALL, label, mediaUrl } from "./api";

interface Props {
  events: AuditEvent[];
  grants: Grant[];
  resources: Resource[];
  users: User[];
  selected: string;
  preview: CuPreview;
}

function frameTime(ts?: string | null): string {
  if (!ts) return "";
  return new Date(ts).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false });
}

function fromEvents(events: AuditEvent[]): CuFrame[] {
  return events
    .filter((e) => e.type === "action_executed" && typeof e.payload.screenshot_url === "string")
    .map((e) => ({
      url: String(e.payload.screenshot_url),
      turn: Number(e.payload.turn) || 0,
      action: (e.payload.action as string | undefined) ?? e.detail,
      timestamp: e.timestamp,
      grant_id: e.grant_id,
      source: "live" as const,
    }));
}

export function Enact({ events, grants, resources, users, selected, preview }: Props) {
  const byGrant = useMemo(() => new Map(grants.map((g) => [g.id, g])), [grants]);
  const liveFrames = useMemo(() => fromEvents(events), [events]);
  const frames = useMemo(() => {
    const pool = liveFrames.length ? liveFrames : preview.frames;
    if (selected === ALL) return pool;
    return pool.filter((f) => {
      if (!f.grant_id) return true;
      const g = byGrant.get(f.grant_id);
      return !g || g.requester_id === selected;
    });
  }, [liveFrames, preview.frames, selected, byGrant]);

  const running = useMemo(() => {
    let open = false;
    for (const e of events) {
      const phase = e.payload.phase;
      if (phase === "started") open = true;
      else if (phase === "completed") open = false;
    }
    return open || preview.running;
  }, [events, preview.running]);

  const status = frames.length === 0 ? "idle" : running || liveFrames.length ? "live" : preview.status;
  const [pin, setPin] = useState<number | null>(null);
  const latest = frames.length ? frames.length - 1 : 0;
  const shown = pin !== null && pin < frames.length ? pin : latest;

  useEffect(() => {
    if (running) setPin(null);
  }, [running, frames.length]);

  const current = frames[shown];
  const grant = current?.grant_id ? byGrant.get(current.grant_id) : undefined;
  const who = grant ? users.find((u) => u.id === grant.requester_id) : undefined;

  return (
    <section className="enact" aria-label="Computer-use enact">
      <div className="sec-h">
        <h2>Enact</h2>
        <span className={`enact-st ${status}`}>
          <i />
          {status === "live" && running ? `live · turn ${String(current?.turn ?? 0).padStart(2, "0")}` : null}
          {status === "live" && !running ? "enacted" : null}
          {status === "replay" ? "last recorded run" : null}
          {status === "idle" ? "waiting for the agent" : null}
        </span>
      </div>
      <div className="enact-body">
        <div className="enact-stage">
          {current ? (
            <img src={mediaUrl(current.url)} alt={current.action || `turn ${current.turn}`} />
          ) : (
            <div className="enact-empty">Grant issues → the agent is seen enacting it here.</div>
          )}
          {current ? (
            <div className="enact-cap">
              <b>{current.action || `turn ${current.turn}`}</b>
              {grant ? <span>{label(grant.resource_id, resources)}</span> : null}
              {who ? <span>{who.name}</span> : null}
              <span>{frameTime(current.timestamp)}</span>
            </div>
          ) : null}
        </div>
        <div className="enact-strip" role="list">
          {frames.map((f, i) => (
            <button
              key={`${f.url}-${i}`}
              type="button"
              className="enact-thumb"
              role="listitem"
              aria-label={`turn ${String(f.turn).padStart(2, "0")}${f.action ? ` · ${f.action}` : ""}`}
              aria-pressed={i === shown}
              onClick={() => setPin(i)}
            >
              <img src={mediaUrl(f.url)} alt="" />
              <span>{String(f.turn).padStart(2, "0")}</span>
            </button>
          ))}
        </div>
      </div>
    </section>
  );
}
