import { useEffect, useState } from "react";
import type { AuditEvent, EscalationCase, Grant, Resource, User } from "./api";
import { label } from "./api";

interface Props {
  grants: Grant[];
  cases: EscalationCase[];
  events: AuditEvent[];
  resources: Resource[];
  users: User[];
  selected: string;
  now: number;
}

interface Panel { id: string; component: string; props: Record<string, unknown> }
interface Spec { requester_id: string; panels: Panel[]; generated_at?: string }
interface Tool { name: string; description: string }

const DAY = 86400e3, HOUR = 3600e3;
function left(ms: number) { return ms >= DAY ? `${Math.round(ms / DAY)} days` : ms >= HOUR ? `${Math.round(ms / HOUR)} hours` : `${Math.max(1, Math.round(ms / 60e3))} minutes`; }

// How to use each resource type: a real command, the MCP tool name, and the real docs.
const GUIDE: Record<string, { what: string; cmd: (r: Resource) => string; docs: { title: string; url: string } }> = {
  gcs_bucket: {
    what: "Object storage bucket",
    cmd: (r) => `gcloud storage ls gs://atlas-${r.name}`,
    docs: { title: "Cloud Storage — listing objects", url: "https://cloud.google.com/storage/docs/listing-objects" },
  },
  bigquery_dataset: {
    what: "BigQuery dataset (read-only)",
    cmd: (r) => `bq query --use_legacy_sql=false 'SELECT COUNT(*) FROM ${r.name.replace(/-/g, "_")}.ledger'`,
    docs: { title: "BigQuery — running queries", url: "https://cloud.google.com/bigquery/docs/running-queries" },
  },
  github_repo: {
    what: "GitHub repository",
    cmd: (r) => `gh repo clone conduct/${r.name}`,
    docs: { title: "GitHub CLI — gh repo clone", url: "https://cli.github.com/manual/gh_repo_clone" },
  },
  cloud_sql_instance: {
    what: "Cloud SQL instance",
    cmd: (r) => `gcloud sql connect ${r.name}`,
    docs: { title: "Cloud SQL — connecting", url: "https://cloud.google.com/sql/docs/mysql/connect-overview" },
  },
  sap_business_partner: {
    what: "Customer Master · Business Partner display",
    cmd: (r) => `Fiori · Customer Master · BP ${String(r.metadata?.customer_id ?? "1710001")}`,
    docs: { title: "SAP S/4HANA — Business Partner", url: "https://help.sap.com/docs/SAP_S4HANA_CLOUD" },
  },
  sap_billing_document: {
    what: "Billing document display",
    cmd: (r) => `Fiori · Manage Billing Documents · ${r.name}`,
    docs: { title: "SAP S/4HANA — Billing Documents", url: "https://help.sap.com/docs/SAP_S4HANA_CLOUD" },
  },
  sap_sales_order: {
    what: "Sales order display",
    cmd: (r) => `Fiori · Manage Sales Orders · ${r.name}`,
    docs: { title: "SAP S/4HANA — Sales Orders", url: "https://help.sap.com/docs/SAP_S4HANA_CLOUD" },
  },
};

/** Deterministic composition used when the server has no Gemini composer. Same panel
 *  vocabulary the generated path is expected to emit. */
function compose(me: User, grants: Grant[], cases: EscalationCase[], events: AuditEvent[], resources: Resource[], now: number): Spec {
  const active = grants.filter((g) => g.requester_id === me.id && !g.revoked && Date.parse(g.expires_at) > now);
  const pending = cases.filter((c) => c.requester_id === me.id && c.status === "pending");
  const denied = events.filter((e) => e.type === "request_denied" && e.actor === me.id);
  const next = active.map((g) => Date.parse(g.expires_at)).sort((a, b) => a - b)[0];
  const panels: Panel[] = [
    { id: "headline", component: "AccessSummary", props: { name: me.name.split(" ")[0], count: active.length, pending: pending.length, until: next ? new Date(next).toLocaleDateString([], { day: "numeric", month: "long" }) : null } },
    ...active.map((g) => {
      const r = resources.find((x) => x.id === g.resource_id);
      const guide = r ? GUIDE[r.type] : undefined;
      return { id: `guide-${g.id}`, component: "ResourceGuide", props: { name: label(g.resource_id, resources), what: guide?.what ?? r?.type, tier: r?.sensitivity, team: r?.owning_team, cmd: r && guide ? guide.cmd(r) : "", docs: guide?.docs, expires: left(Date.parse(g.expires_at) - now), capability: r?.capability ?? "read" } };
    }),
    ...pending.map((c) => ({ id: `pending-${c.id}`, component: "PendingCard", props: { name: label(c.resource_id, resources), approvers: c.required_approver_ids, votes: c.votes.filter((v) => v.approved).map((v) => v.approver_id), reason: c.escalation_reason ?? "" } })),
    ...denied.map((e) => ({ id: `denied-${e.id}`, component: "DeniedCard", props: { name: label(String(e.payload.resource_id ?? ""), resources), reason: e.detail, alternative: "Ask for a read-only replica or a shorter window." } })),
  ];
  return { requester_id: me.id, panels, generated_at: new Date(now).toISOString() };
}

export function Summary({ grants, cases, events, resources, users, selected, now }: Props) {
  const me = users.find((u) => u.id === selected) ?? users[0];
  const [server, setServer] = useState<Spec | null>(null);
  const [tools, setTools] = useState<Tool[]>([]);
  const [tick, setTick] = useState(0);

  useEffect(() => {
    if (!me) return;
    let alive = true;
    fetch(`/api/ui-spec/${me.id}`).then((r) => r.json()).then((s: Spec) => alive && setServer(s)).catch(() => {});
    fetch(`/api/tools?requester_id=${me.id}`).then((r) => r.json()).then((t) => alive && setTools(t)).catch(() => {});
    return () => { alive = false; };
  }, [me?.id, tick, grants.length, cases.length]);

  if (!me) return null;
  const byId = new Map(users.map((u) => [u.id, u]));
  // Use the server's spec only if a composer produced something beyond the two scaffold cards.
  const rich = server?.panels.some((p) => !["GrantCard", "PendingApprovalCard"].includes(p.component));
  const spec = rich && server ? server : compose(me, grants, cases, events, resources, now);
  const source = rich ? "gemini" : "fallback composer";

  return (
    <div className="sm" style={{ ["--u" as string]: me.color }}>
      <div className="sm-prov"><span>composed for <b>{me.id}</b> · {source} · {new Date(spec.generated_at ?? now).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", hour12: false })}</span><button className="nb" onClick={() => setTick((t) => t + 1)}>Refresh</button></div>
      <div className="sm-grid">
        {spec.panels.map((p) => {
          const pr = p.props as Record<string, any>;
          switch (p.component) {
            case "AccessSummary":
              return (
                <div className="sm-head" key={p.id}>
                  <h1>{pr.name}, you can use <b>{pr.count}</b> thing{pr.count === 1 ? "" : "s"}{pr.until ? <> until <b>{pr.until}</b></> : null}.</h1>
                  <p>{pr.pending ? `${pr.pending} waiting on a human. ` : ""}All of it expires on its own.</p>
                </div>
              );
            case "ResourceGuide":
              return (
                <div className="sm-card guide" key={p.id}>
                  <div className="sm-top"><span className="sm-name">{pr.name}</span><span className="sm-exp">{pr.expires} left</span></div>
                  <div className="sm-meta">{pr.what} · {pr.capability} · {pr.tier} · owned by {pr.team}</div>
                  <div className="sm-k">how to use it</div>
                  <pre>{pr.cmd}</pre>
                  {pr.docs && <a className="sm-doc" href={pr.docs.url} target="_blank" rel="noreferrer">{pr.docs.title} ↗</a>}
                </div>
              );
            case "PendingCard":
              return (
                <div className="sm-card pending" key={p.id}>
                  <div className="sm-top"><span className="sm-name">{pr.name}</span><span className="sm-exp amber">waiting</span></div>
                  <div className="sm-meta">{pr.reason}</div>
                  <div className="sm-k">deciding</div>
                  <div className="sm-people">{(pr.approvers as string[]).map((a) => <span key={a} style={{ ["--u" as string]: byId.get(a)?.color }}><i />{byId.get(a)?.name ?? a}{(pr.votes as string[]).includes(a) ? " ✓" : ""}</span>)}</div>
                </div>
              );
            case "DeniedCard":
              return (
                <div className="sm-card denied" key={p.id}>
                  <div className="sm-top"><span className="sm-name">{pr.name}</span><span className="sm-exp red">refused</span></div>
                  <div className="sm-meta">{pr.reason}</div>
                  <div className="sm-k">instead</div>
                  <div className="sm-meta">{pr.alternative}</div>
                </div>
              );
            case "GrantCard":
            case "PendingApprovalCard":
              return null;
            default:
              return <div className="sm-card unknown" key={p.id}><div className="sm-name">{p.component}</div><div className="sm-meta">not in this page's catalog — shown as a placeholder</div></div>;
          }
        })}
        <div className="sm-card tools">
          <div className="sm-top"><span className="sm-name">your agent's tools</span><span className="sm-exp">live</span></div>
          <div className="sm-tools">
            <span>request_access</span><span>my_access</span>
            {tools.map((t) => <span className="live" key={t.name}>{t.name}</span>)}
          </div>
        </div>
      </div>
    </div>
  );
}
