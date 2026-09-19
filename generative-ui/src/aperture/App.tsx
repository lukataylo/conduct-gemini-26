import { useEffect, useState } from "react";
import "./aperture.css";
import { REQUESTER_ID, useSnapshot } from "./api";
import { DemoBar } from "./DemoBar";
import { Recorder } from "./Recorder";
import { Timeline } from "./Timeline";

export default function ApertureApp() {
  const snap = useSnapshot();
  const [zoom, setZoom] = useState<"session" | "project">("session");
  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, []);

  const active = snap.grants.filter((g) => !g.revoked && Date.parse(g.expires_at) > now);
  const revoked = snap.grants.filter((g) => g.revoked);
  const pending = snap.cases.filter((c) => c.status === "pending");
  const denied = snap.events.filter((e) => e.type === "request_denied").length;
  const bounced = snap.events.filter((e) => e.type === "action_executed" && e.payload.status === "bounced").length;
  const next = active.map((g) => Date.parse(g.expires_at)).sort((a, b) => a - b)[0];

  return (
    <div className="ap">
      <header className="hd">
        <span className="brand">APERTURE</span>
        <span className="who">
          <b>Alex Chen</b> data-platform <span className="id">{REQUESTER_ID}</span>
        </span>
        <span className="right">
          <span className={`dotst ${!snap.online ? "" : snap.verify?.ok ? "ok" : "bad"}`}>
            <i />
            {!snap.online ? "offline" : snap.verify?.ok ? `chain ok · ${snap.verify.length}` : `chain broken · ${snap.verify?.broken_at}`}
          </span>
          <span className="seg" role="group" aria-label="Zoom">
            <button aria-pressed={zoom === "session"} onClick={() => setZoom("session")}>session</button>
            <button aria-pressed={zoom === "project"} onClick={() => setZoom("project")}>project</button>
          </span>
        </span>
      </header>

      <div className="sum">
        <div><span className="n green">{active.length}</span><span className="k">active leases</span></div>
        <div><span className="n amber">{pending.length}</span><span className="k">pending</span></div>
        <div><span className="n">{revoked.length}</span><span className="k">revoked</span></div>
        <div><span className={`n ${denied ? "red" : ""}`}>{denied}</span><span className="k">denied</span></div>
        <div><span className={`n ${bounced ? "red" : ""}`}>{bounced}</span><span className="k">bounced</span></div>
        <div><span className="n">{next ? new Date(next).toLocaleDateString([], { day: "numeric", month: "short" }) : "—"}</span><span className="k">next expiry</span></div>
      </div>

      <main className="main">
        <div>
          <div className="sec-h"><h2>Leases</h2></div>
          <Timeline grants={snap.grants} cases={snap.cases} events={snap.events} zoom={zoom} now={now} />
        </div>
        <div>
          <div className="sec-h"><h2>Recorder</h2></div>
          <Recorder events={snap.events} grants={snap.grants} />
        </div>
      </main>

      <DemoBar grants={snap.grants} cases={snap.cases} online={snap.online} />
    </div>
  );
}
