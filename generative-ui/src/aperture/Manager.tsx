import { useEffect, useState } from "react";
import type { AuditEvent, Company, EscalationCase, Grant, PlatformId, PolicyRouteRow, PolicyRoutes, PolicyRule, Resource, User } from "./api";
import { ALL, ATLAS, fetchPolicyRoutes, hasPlatform, post } from "./api";
import { Approvals } from "./Approvals";

interface Props {
  grants: Grant[];
  cases: EscalationCase[];
  events: AuditEvent[];
  resources: Resource[];
  users: User[];
  company?: Company;
  policy: PolicyRule | null;
  online?: boolean;
}

const TIERS = ["public", "internal", "restricted", "critical"] as const;

function policyRows(policy: PolicyRule | null) {
  const days = policy?.max_auto_grant_duration_days ?? { public: 90, internal: 30, restricted: 7, critical: 0 };
  const approvals = policy?.required_approvals ?? { public: 0, internal: 1, restricted: 1, critical: 2 };
  const always = new Set((policy?.always_escalate_tiers ?? ["critical"]).map((t) => t.toLowerCase()));
  return TIERS.map((tier) => {
    const max = days[tier] ?? 0;
    return {
      tier,
      auto: always.has(tier) || max === 0 ? "never" : `${max}d`,
      approvals: approvals[tier] ?? 0,
    };
  });
}

function RouteTable({ title, rows, users }: { title: string; rows: PolicyRouteRow[]; users: User[] }) {
  const nameOf = (id: string) => users.find((u) => u.id === id)?.name.split(" ")[0] ?? id;
  return (
    <>
      <div className="pol-k">{title}</div>
      <table className="pol">
        <thead><tr><th>resource</th><th>approvers</th></tr></thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.id}><td>{r.name}</td><td>{r.approver_ids.map(nameOf).join(", ") || "—"}</td></tr>
          ))}
        </tbody>
      </table>
    </>
  );
}

/** The manager's column: what needs deciding and the live GET /policy table. Gemini lives in the bubble. */
export function ManagerSide({ grants, cases, events, resources, users, company = ATLAS, policy, online = true }: Props) {
  const rows = policyRows(policy);
  const plats = company.platforms.length ? company.platforms : ATLAS.platforms;
  const [busy, setBusy] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [routes, setRoutes] = useState<PolicyRoutes>({ gcp: [], sap: [] });
  useEffect(() => { fetchPolicyRoutes().then(setRoutes).catch(() => setRoutes({ gcp: [], sap: [] })); }, []);
  const setPlatform = async (u: User, platform: PlatformId, action: "grant" | "revoke") => {
    const key = `${u.id}:${platform}:${action}`;
    setBusy(key); setErr(null);
    try { await post(`/people/${u.id}/platforms`, { platform, action }); }
    catch (e) { console.error(e); setErr("platform update failed"); }
    finally { setBusy(null); }
  };
  return (
    <aside className="mgr-side">
      <Approvals cases={cases} grants={grants} events={events} resources={resources} users={users} selected={ALL} />
      <section className="mgr-settings">
        <div className="apv-h">Platforms</div>
        {plats.map((p) => (
          <div className="mgr-plat" key={p.id}>
            <div className="mgr-plat-h">{p.name}{p.home ? " · home" : ""}</div>
            {users.map((u) => {
              const on = hasPlatform(u, p.id);
              const key = `${u.id}:${p.id}:${on ? "revoke" : "grant"}`;
              return (
                <div className="mgr-plat-row" key={u.id} style={{ ["--u" as string]: u.color }}>
                  <span><i /><b>{u.name.split(" ")[0]}</b></span>
                  <button className="nb" disabled={!online || busy !== null} onClick={() => setPlatform(u, p.id, on ? "revoke" : "grant")}>
                    {busy === key ? "…" : on ? "Revoke" : "Grant"}
                  </button>
                </div>
              );
            })}
          </div>
        ))}
        {err && <div className="uc-err">{err}</div>}
      </section>
      <section className="mgr-settings">
        <div className="apv-h">Policy</div>
        <RouteTable title="GCP" rows={routes.gcp} users={users} />
        <RouteTable title="SAP" rows={routes.sap} users={users} />
        <div className="pol-k">tiers</div>
        <table className="pol">
          <thead><tr><th>tier</th><th>auto up to</th><th>approvals</th></tr></thead>
          <tbody>{rows.map((p) => <tr key={p.tier}><td>{p.tier}</td><td>{p.auto}</td><td>{p.approvals}</td></tr>)}</tbody>
        </table>
      </section>
    </aside>
  );
}
