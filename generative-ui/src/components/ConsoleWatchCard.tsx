interface ConsoleWatchCardProps {
  grant_id: string;
  watch_url: string;
}

export function ConsoleWatchCard(props: Record<string, unknown>) {
  const { grant_id, watch_url } = props as unknown as ConsoleWatchCardProps;
  return (
    <div className="card card-watch">
      <div className="card-title">Console watch</div>
      <div className="card-meta">grant {grant_id.slice(0, 8)}</div>
      {watch_url ? (
        <a className="card-watch-link" href={watch_url} target="_blank" rel="noreferrer">
          Open live session
        </a>
      ) : (
        <div className="card-meta">No watch URL yet</div>
      )}
    </div>
  );
}
