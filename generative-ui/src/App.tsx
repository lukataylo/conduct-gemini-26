import { useEffect, useState } from "react";
import { PanelBoundary, resolveComponent } from "./registry";
import type { UISpec } from "./types";

// Matches usecase-demo/seed_data.py's REQUESTER.id — swap for real auth/selection later.
const DEMO_REQUESTER_ID = "u-newhire-1";

export default function App() {
  const [spec, setSpec] = useState<UISpec | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const load = () => {
      fetch(`/api/ui-spec/${DEMO_REQUESTER_ID}`)
        .then((res) => {
          if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
          return res.json();
        })
        .then(setSpec)
        .catch((err) => setError(String(err)));
    };
    load();
    const interval = setInterval(load, 3000); // poll for the demo; swap for websocket/SSE if there's time
    return () => clearInterval(interval);
  }, []);

  return (
    <main className="app">
      <h1>Access Scope Agent</h1>
      <p className="subtitle">Dashboard for {DEMO_REQUESTER_ID}</p>

      {error && <div className="error">Couldn't reach backend-api: {error}</div>}

      {!error && !spec && <div className="loading">Loading…</div>}

      <div className="panels">
        {spec?.panels.map((panel) => {
          const Panel = resolveComponent(panel.component);
          return (
            <PanelBoundary key={panel.id}>
              <Panel {...panel.props} />
            </PanelBoundary>
          );
        })}
      </div>

      {spec && spec.panels.length === 0 && (
        <div className="empty">No active grants or pending requests yet.</div>
      )}
    </main>
  );
}
