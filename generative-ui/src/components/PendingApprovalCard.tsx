interface PendingApprovalCardProps {
  escalation_id: string;
  resource_id: string;
}

export function PendingApprovalCard(props: Record<string, unknown>) {
  const { escalation_id, resource_id } = props as unknown as PendingApprovalCardProps;
  return (
    <div className="card card-pending">
      <div className="card-title">{resource_id}</div>
      <div className="card-meta">pending approval</div>
      <div className="card-id">escalation {escalation_id.slice(0, 8)}</div>
    </div>
  );
}
