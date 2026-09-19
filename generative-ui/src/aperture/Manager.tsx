import type { AuditEvent, EscalationCase, Grant, PolicyRule, Resource, User } from "./api";
import { ALL } from "./api";
import { Approvals } from "./Approvals";

interface Props {
  grants: Grant[];
  cases: EscalationCase[];
  events: AuditEvent[];
  resources: Resource[];
  users: User[];
  policy: PolicyRule | null;
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

/** The manager's column: what needs deciding and the live GET /policy table. Gemini lives in the bubble. */
export function ManagerSide({ grants, cases, events, resources, users, policy }: Props) {
  const rows = policyRows(policy);
  return (
    <aside className="mgr-side">
      <Approvals cases={cases} grants={grants} events={events} resources={resources} users={users} selected={ALL} />
      <section className="mgr-settings">
        <div className="apv-h">Policy</div>
        <table className="pol">
          <thead><tr><th>tier</th><th>auto up to</th><th>approvals</th></tr></thead>
          <tbody>{rows.map((p) => <tr key={p.tier}><td>{p.tier}</td><td>{p.auto}</td><td>{p.approvals}</td></tr>)}</tbody>
        </table>
      </section>
    </aside>
  );
}
