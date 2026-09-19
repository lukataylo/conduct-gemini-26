import { useEffect, useMemo, useState } from "react";
import "./aperture.css";
import { ALL, toUsers, useSnapshot } from "./api";
import { Approvals } from "./Approvals";
import { DemoBar } from "./DemoBar";
import { Matrix } from "./Matrix";
import { Onboard } from "./Onboard";
import { Recorder } from "./Recorder";
import { Timeline } from "./Timeline";

function initialUser(): string {
  const q = new URLSearchParams(window.location.search).get("user");
  return q ?? "u-newhire-1";
}

function initialView(): "console" | "onboard" {
  return new URLSearchParams(window.location.search).get("view") === "onboard" ? "onboard" : "console";
}

export default function ApertureApp() {
  const snap = useSnapshot();
  const users = useMemo(() => toUsers(snap.people), [snap.people]);
  const [selected, setSelected] = useState<string>(initialUser);
  const [view, setView] = useState<"console" | "onboard">(initialView);
  const [zoom, setZoom] = useState<"session" | "project">("session");
  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, []);

  const me = users.find((u) => u.id === selected);
  const mine = (uid: string) => selected === ALL || uid === selected;
  const active = snap.grants.filter((g) => !g.revoked && Date.parse(g.expires_at) > now && mine(g.requester_id));
  const revoked = snap.grants.filter((g) => g.revoked && mine(g.requester_id));
  const pending = snap.cases.filter((c) => c.status === "pending" && mine(c.requester_id));
  const needsMe = snap.cases.filter((c) =>
    c.status === "pending" && (selected === ALL ? true : me !== undefined && c.required_approver_ids.includes(me.id) && !c.votes.some((v) => v.approver_id === me.id)),
  ).length;
  const bounced = snap.events.filter((e) => e.type === "action_executed" && e.payload.status === "bounced").length;
  const next = active.map((g) => Date.parse(g.expires_at)).sort((a, b) => a - b)[0];
  const accent = me?.color ?? "#f4f4f4";

  return (
    <div className="ap" style={{ ["--accent" as string]: accent }}>
      <header className="hd">
        <span className="brand">APERTURE</span>
        <div className="people" role="tablist" aria-label="People">
          <button className="person" aria-pressed={selected === ALL} onClick={() => setSelected(ALL)} style={{ ["--u" as string]: "#f4f4f4" }}>
            <i className="multi" /><span>Everyone</span>
          </button>
          {users.map((u) => (
            <button key={u.id} className="person" aria-pressed={selected === u.id} onClick={() => setSelected(u.id)} style={{ ["--u" as string]: u.color }}>
              <i /><span>{u.name}</span><small>{u.team}</small>
            </button>
          ))}
        </div>
        <span className="right">
          <span className={`dotst ${!snap.online ? "" : snap.verify?.ok ? "ok" : "bad"}`}>
            <i />
            {!snap.online ? "offline" : snap.verify?.ok ? `chain ok · ${snap.verify.length}` : `chain broken · ${snap.verify?.broken_at}`}
          </span>
          <span className="seg" role="group" aria-label="Zoom">
            <button aria-pressed={zoom === "session"} onClick={() => setZoom("session")}>session</button>
            <button aria-pressed={zoom === "project"} onClick={() => setZoom("project")}>project</button>
          </span>
          <span className="seg" role="group" aria-label="View">
            <button aria-pressed={view === "console"} onClick={() => setView("console")}>console</button>
            <button aria-pressed={view === "onboard"} onClick={() => setView("onboard")}>onboard</button>
          </span>
        </span>
      </header>

      {view === "onboard" ? (
        <>
          <Onboard users={users} resources={snap.resources} selected={selected === ALL ? "u-newhire-1" : selected} online={snap.online} />
          <DemoBar grants={snap.grants} cases={snap.cases} users={users} selected={selected} online={snap.online} />
        </>
      ) : (
      <>
      <div className="sum">
        <div><span className="n" style={{ color: accent }}>{active.length}</span><span className="k">active leases</span></div>
        <div><span className="n amber">{pending.length}</span><span className="k">pending</span></div>
        <div><span className={`n ${needsMe ? "hot" : ""}`}>{needsMe}</span><span className="k">needs {me ? me.name.split(" ")[0] : "a decision"}</span></div>
        <div><span className="n">{revoked.length}</span><span className="k">revoked</span></div>
        <div><span className={`n ${bounced ? "red" : ""}`}>{bounced}</span><span className="k">bounced</span></div>
        <div><span className="n">{next ? new Date(next).toLocaleDateString([], { day: "numeric", month: "short" }) : "—"}</span><span className="k">next expiry</span></div>
      </div>

      <div className="grid2">
        <div>
          <div className="sec-h"><h2>Access · {me ? me.name : "everyone"}</h2></div>
          <Matrix grants={snap.grants} cases={snap.cases} events={snap.events} resources={snap.resources} users={users} selected={selected} zoom={zoom} now={now} />
        </div>
        <Approvals cases={snap.cases} grants={snap.grants} events={snap.events} resources={snap.resources} users={users} selected={selected} />
      </div>

      <main className="main">
        <div>
          <div className="sec-h"><h2>Leases</h2></div>
          <Timeline grants={snap.grants} cases={snap.cases} events={snap.events} resources={snap.resources} users={users} selected={selected} zoom={zoom} now={now} />
        </div>
        <div>
          <div className="sec-h"><h2>Recorder</h2></div>
          <Recorder events={snap.events} grants={snap.grants} resources={snap.resources} users={users} selected={selected} />
        </div>
      </main>

      <DemoBar grants={snap.grants} cases={snap.cases} users={users} selected={selected} online={snap.online} />
      </>
      )}
    </div>
  );
}
