// Placeholder — intended to render GET /audit for the request currently in view.
// TODO(contributor 1): fetch and render the AuditEvent[] timeline (see shared/schemas.py).
export function AuditTimeline(props: Record<string, unknown>) {
  const requestId = props.request_id as string | undefined;
  return (
    <div className="card card-audit">
      <div className="card-title">Audit trail</div>
      <div className="card-meta">TODO: fetch /audit?request_id={requestId}</div>
    </div>
  );
}
