import { useEffect, useMemo, useState } from "react";
import type { AuditEvent, CuFrame, CuGroup, CuPreview, CuSession, Grant, Resource, User } from "./api";
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

function liveSession(frames: CuFrame[], grantId: string | null | undefined): CuSession | null {
  if (!frames.length) return null;
  return {
    id: "live",
    label: "live",
    source: "live",
    grant_id: grantId ?? frames.find((f) => f.grant_id)?.grant_id ?? null,
    groups: [
      {
        id: "live",
        stem: "live",
        kind: "live",
        label: "live",
        frames,
        action_frames: [],
        recordings: [],
      },
    ],
  };
}

function fallbackSession(frames: CuFrame[], status: CuPreview["status"]): CuSession | null {
  if (!frames.length) return null;
  return {
    id: "replay",
    label: status === "replay" ? "last recorded run" : "session",
    source: "replay",
    grant_id: null,
    groups: [
      {
        id: "replay",
        stem: "replay",
        kind: "replay",
        label: "turns",
        frames,
        action_frames: [],
        recordings: [],
      },
    ],
  };
}

export function Enact({ events, grants, resources, users, selected, preview }: Props) {
  const byGrant = useMemo(() => new Map(grants.map((g) => [g.id, g])), [grants]);
  const liveFrames = useMemo(() => {
    const raw = fromEvents(events);
    if (selected === ALL) return raw;
    return raw.filter((f) => {
      if (!f.grant_id) return true;
      const g = byGrant.get(f.grant_id);
      return !g || g.requester_id === selected;
    });
  }, [events, selected, byGrant]);

  const sessions = useMemo(() => {
    const fromApi = preview.sessions ?? [];
    const replay = fromApi.filter((s) => s.source === "replay");
    const live = liveSession(liveFrames, preview.grant_id);
    if (live) return [live, ...replay];
    if (replay.length) return replay;
    const fallback = fallbackSession(preview.frames, preview.status);
    return fallback ? [fallback] : [];
  }, [liveFrames, preview]);

  const [sessionId, setSessionId] = useState<string | null>(null);
  const [groupId, setGroupId] = useState<string | null>(null);
  const [strip, setStrip] = useState<"turns" | "frames">("turns");
  const [pin, setPin] = useState<number | null>(null);
  const [recUrl, setRecUrl] = useState<string | null>(null);

  const session = sessions.find((s) => s.id === sessionId) ?? sessions[0];
  const group: CuGroup | undefined = session?.groups.find((g) => g.id === groupId) ?? session?.groups[0];
  const stills = strip === "frames" && group?.action_frames.length ? group.action_frames : group?.frames ?? [];
  const latest = stills.length ? stills.length - 1 : 0;
  const shown = pin !== null && pin < stills.length ? pin : latest;
  const current = stills[shown];

  const running = useMemo(() => {
    let open = false;
    for (const e of events) {
      const phase = e.payload.phase;
      if (phase === "started") open = true;
      else if (phase === "completed") open = false;
    }
    return open || preview.running;
  }, [events, preview.running]);

  useEffect(() => {
    if (!sessions.length) {
      setSessionId(null);
      setGroupId(null);
      return;
    }
    if (!sessionId || !sessions.some((s) => s.id === sessionId)) {
      setSessionId(sessions[0].id);
      setGroupId(sessions[0].groups[0]?.id ?? null);
      setPin(null);
      setRecUrl(null);
      setStrip("turns");
    }
  }, [sessions, sessionId]);

  useEffect(() => {
    if (running && session?.source === "live") {
      setPin(null);
      setRecUrl(null);
    }
  }, [running, stills.length, session?.source]);

  const status = !sessions.length ? "idle" : session?.source === "live" ? (running ? "live" : "enacted") : "replay";
  const grant = current?.grant_id ? byGrant.get(current.grant_id) : undefined;
  const who = grant ? users.find((u) => u.id === grant.requester_id) : undefined;
  const rec = group?.recordings.find((r) => r.url === recUrl);

  return (
    <section className="enact" aria-label="Computer-use enact">
      <div className="sec-h">
        <h2>Enact</h2>
        <span className={`enact-st ${status === "enacted" ? "live" : status}`}>
          <i />
          {status === "live" ? `live · turn ${String(current?.turn ?? 0).padStart(2, "0")}` : null}
          {status === "enacted" ? "enacted" : null}
          {status === "replay" ? session?.label ?? "recorded" : null}
          {status === "idle" ? "waiting for the agent" : null}
        </span>
      </div>

      {sessions.length > 0 ? (
        <div className="enact-sessions" role="tablist" aria-label="Sessions">
          {sessions.map((s) => (
            <button
              key={s.id}
              type="button"
              className="nb"
              role="tab"
              aria-selected={s.id === session?.id}
              onClick={() => {
                setSessionId(s.id);
                setGroupId(s.groups[0]?.id ?? null);
                setPin(null);
                setRecUrl(null);
                setStrip("turns");
              }}
            >
              {s.label}
              {s.groups.length > 1 ? ` · ${s.groups.length}` : ""}
            </button>
          ))}
        </div>
      ) : null}

      {session && session.groups.length > 1 ? (
        <div className="enact-sessions" role="tablist" aria-label="Groups">
          {session.groups.map((g) => (
            <button
              key={g.id}
              type="button"
              className="nb"
              role="tab"
              aria-selected={g.id === group?.id}
              onClick={() => {
                setGroupId(g.id);
                setPin(null);
                setRecUrl(null);
                setStrip("turns");
              }}
            >
              {g.label}
            </button>
          ))}
        </div>
      ) : null}

      <div className="enact-body">
        <div className="enact-stage">
          {rec ? (
            rec.type === "webm" || rec.type === "mp4" ? (
              <video key={rec.url} src={mediaUrl(rec.url)} controls playsInline />
            ) : (
              <img src={mediaUrl(rec.url)} alt={rec.name} />
            )
          ) : current ? (
            <img src={mediaUrl(current.url)} alt={current.action || `turn ${current.turn}`} />
          ) : (
            <div className="enact-empty">Grant issues → the agent is seen enacting it here.</div>
          )}
          {current && !rec ? (
            <div className="enact-cap">
              <b>{current.action || `turn ${current.turn}`}</b>
              {grant ? <span>{label(grant.resource_id, resources)}</span> : null}
              {who ? <span>{who.name}</span> : null}
              <span>{frameTime(current.timestamp)}</span>
            </div>
          ) : null}
          {rec ? (
            <div className="enact-cap">
              <b>{rec.type} recording</b>
              <span>{rec.name}</span>
            </div>
          ) : null}
        </div>
        <div className="enact-side">
          {group && group.action_frames.length > 0 ? (
            <div className="enact-sessions" role="group" aria-label="Stills">
              <button type="button" className="nb" aria-pressed={strip === "turns"} onClick={() => { setStrip("turns"); setPin(null); setRecUrl(null); }}>
                turns
              </button>
              <button type="button" className="nb" aria-pressed={strip === "frames"} onClick={() => { setStrip("frames"); setPin(null); setRecUrl(null); }}>
                frames
              </button>
            </div>
          ) : null}
          <div className="enact-strip" role="list">
            {stills.map((f, i) => (
              <button
                key={`${f.url}-${i}`}
                type="button"
                className="enact-thumb"
                role="listitem"
                aria-label={`turn ${String(f.turn).padStart(2, "0")}${f.action ? ` · ${f.action}` : ""}`}
                aria-pressed={!rec && i === shown}
                onClick={() => { setPin(i); setRecUrl(null); }}
              >
                <img src={mediaUrl(f.url)} alt="" />
                <span>{String(f.turn).padStart(2, "0")}</span>
              </button>
            ))}
          </div>
          {group && group.recordings.length > 0 ? (
            <div className="enact-recs" aria-label="Recordings">
              <div className="enact-recs-k">recordings</div>
              {group.recordings.map((r) => (
                <button
                  key={r.url}
                  type="button"
                  className="nb"
                  aria-pressed={recUrl === r.url}
                  onClick={() => setRecUrl(r.url)}
                >
                  {r.type}
                </button>
              ))}
            </div>
          ) : null}
        </div>
      </div>
    </section>
  );
}
