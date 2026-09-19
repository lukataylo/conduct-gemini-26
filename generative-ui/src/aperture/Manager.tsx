import type { AuditEvent, EscalationCase, Grant, Resource, User } from "./api";
import { ALL } from "./api";
import { Approvals } from "./Approvals";

interface Props {
  grants: Grant[];
  cases: EscalationCase[];
  events: AuditEvent[];
  resources: Resource[];
  users: User[];
}

// Mirrors policy-engine DEFAULT_POLICY. Read-only until GET/PATCH /policy exists.
const POLICY = [
  { tier: "public", auto: "90d", approvals: 0 },
  { tier: "internal", auto: "30d", approvals: 1 },
  { tier: "restricted", auto: "7d", approvals: 1 },
  { tier: "critical", auto: "never", approvals: 2 },
];

/** The manager's column: what needs deciding and the policy in force. Gemini lives in the bubble. */
export function ManagerSide({ grants, cases, events, resources, users }: Props) {
  return (
    <aside className="mgr-side">
      <Approvals cases={cases} grants={grants} events={events} resources={resources} users={users} selected={ALL} />
      <section className="mgr-settings">
        <div className="apv-h">Policy</div>
        <table className="pol">
          <thead><tr><th>tier</th><th>auto up to</th><th>approvals</th></tr></thead>
          <tbody>{POLICY.map((p) => <tr key={p.tier}><td>{p.tier}</td><td>{p.auto}</td><td>{p.approvals}</td></tr>)}</tbody>
        </table>
      </section>
    </aside>
  );
}
