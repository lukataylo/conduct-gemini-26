interface GrantCardProps {
  grant_id: string;
  resource_id: string;
  expires_at: string;
}

export function GrantCard(props: Record<string, unknown>) {
  const { grant_id, resource_id, expires_at } = props as unknown as GrantCardProps;
  return (
    <div className="card card-granted">
      <div className="card-title">{resource_id}</div>
      <div className="card-meta">expires {new Date(expires_at).toLocaleDateString()}</div>
      <div className="card-id">grant {grant_id.slice(0, 8)}</div>
    </div>
  );
}
