import type { AuditEvent, Grant, Resource, User } from "./api";
import { ALL, label, mediaUrl } from "./api";

interface Props {
  events: AuditEvent[];
  grants: Grant[];
  resources: Resource[];
  users: User[];
  selected: string;
}

function t(ts: string): string {
  return new Date(ts).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false });
}

const GLYPH: Record<string, string> = {
  request_received: "○",
  policy_evaluated: "·",
  grant_issued: "●",
  escalated: "◐",
  approval_vote_cast: "✓",
  request_denied: "◍",
  grant_revoked: "◌",
  project_closed: "▬",
  action_executed: "→",
};

export function Recorder({ events, grants, resources, users, selected }: Props) {
  const byGrant = new Map(grants.map((g) => [g.id, g]));
  const byUser = new Map(users.map((u) => [u.id, u]));
  const myRequests = new Set(grants.filter((g) => g.requester_id === selected).map((g) => g.request_id));
  const rows = [...events].reverse().filter((e) => {
    if (selected === ALL) return true;
    if (e.actor === selected) return true;
    if (e.request_id && myRequests.has(e.request_id)) return true;
    const g = e.grant_id ? byGrant.get(e.grant_id) : undefined;
    return g?.requester_id === selected;
  });

  return (
    <div className="rec">
      {rows.length === 0 && <div className="rec-empty">Nothing recorded</div>}
      {rows.map((e) => {
        const isCall = e.type === "action_executed";
        const bounced = isCall && e.payload.status === "bounced";
        const g = e.grant_id ? byGrant.get(e.grant_id) : undefined;
        const actor = byUser.get(e.actor) ?? (g ? byUser.get(g.requester_id) : undefined);
        const shot = typeof e.payload.screenshot_url === "string" ? e.payload.screenshot_url : null;
        const cls = ["rec-row", isCall ? "call" : "", bounced ? "bounced" : "", e.type === "grant_issued" ? "grant" : "", e.type === "grant_revoked" || e.type === "project_closed" ? "revoke" : ""].join(" ");
        return (
          <div className={cls} key={e.id} style={{ ["--u" as string]: actor?.color ?? "#5c5c5c" }}>
            <span className="rec-t">{t(e.timestamp)}</span>
            <span className="rec-g">{bounced ? "◆" : GLYPH[e.type] ?? "·"}</span>
            <span className="rec-body">
              {actor ? <span className="rec-who"><i />{actor.short}</span> : null}
              <b>{isCall ? String(e.payload.tool ?? e.detail) : e.type.replace(/_/g, " ")}</b>
              <span className="rec-d">{e.detail}</span>
              {isCall && (
                <span className="rec-auth">
                  {bounced ? "no active grant · re-checked at call time" : g ? `authorised by ${label(g.resource_id, resources)} · ${e.grant_id?.slice(0, 8)}` : "authorised"}
                </span>
              )}
              {shot ? <img className="rec-shot" src={mediaUrl(shot)} alt="" /> : null}
            </span>
            <span className="rec-h">{e.prev_hash ? e.prev_hash.slice(0, 6) : "genesis"}</span>
          </div>
        );
      })}
    </div>
  );
}
