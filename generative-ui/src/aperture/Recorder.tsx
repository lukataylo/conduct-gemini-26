import type { AuditEvent, Grant } from "./api";
import { label } from "./api";

interface Props {
  events: AuditEvent[];
  grants: Grant[];
}

function t(ts: string): string {
  return new Date(ts).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
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

export function Recorder({ events, grants }: Props) {
  const byGrant = new Map(grants.map((g) => [g.id, g]));
  const rows = [...events].reverse();
  return (
    <div className="rec">
      {rows.length === 0 && <div className="rec-empty">Nothing recorded</div>}
      {rows.map((e) => {
        const isCall = e.type === "action_executed";
        const bounced = isCall && e.payload.status === "bounced";
        const g = e.grant_id ? byGrant.get(e.grant_id) : undefined;
        const cls = ["rec-row", isCall ? "call" : "", bounced ? "bounced" : "", e.type === "grant_issued" ? "grant" : "", e.type === "grant_revoked" || e.type === "project_closed" ? "revoke" : ""].join(" ");
        return (
          <div className={cls} key={e.id}>
            <span className="rec-t">{t(e.timestamp)}</span>
            <span className="rec-g">{bounced ? "◆" : GLYPH[e.type] ?? "·"}</span>
            <span className="rec-body">
              <b>{isCall ? String(e.payload.tool ?? e.detail) : e.type.replace(/_/g, " ")}</b>
              <span className="rec-d">{e.detail}</span>
              {isCall && (
                <span className="rec-auth">
                  {bounced ? "no active grant · re-checked at call time" : g ? `authorised by ${label(g.resource_id)} · ${e.grant_id?.slice(0, 8)}` : "authorised"}
                </span>
              )}
            </span>
            <span className="rec-h">{e.prev_hash ? e.prev_hash.slice(0, 6) : "genesis"}</span>
          </div>
        );
      })}
    </div>
  );
}
