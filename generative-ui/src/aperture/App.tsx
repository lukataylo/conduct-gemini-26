import { useEffect, useMemo, useRef, useState } from "react";
import "./aperture.css";
import { ALL, toUsers, useSnapshot } from "./api";
import { Approvals } from "./Approvals";
import { Composer } from "./Composer";
import { Controls, seedDemo } from "./Controls";
import { Enact } from "./Enact";
import { Manager } from "./Manager";
import { Matrix } from "./Matrix";
import { Recorder } from "./Recorder";
import { Timeline } from "./Timeline";
import { UserScreen } from "./User";

type Mode = "user" | "manager" | "console";

function initialUser(): string {
  return new URLSearchParams(window.location.search).get("user") ?? "u-newhire-1";
}
function initialMode(): Mode {
  const m = new URLSearchParams(window.location.search).get("screen");
  return m === "manager" || m === "console" ? m : "user";
}

export default function ApertureApp() {
  const snap = useSnapshot();
  const users = useMemo(() => toUsers(snap.people), [snap.people]);
  const [selected, setSelected] = useState<string>(initialUser);
  const [mode, setMode] = useState<Mode>(initialMode);
  const [zoom, setZoom] = useState<"session" | "project">("session");
  const [now, setNow] = useState(Date.now());
  const seeded = useRef(false);

  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, []);

  // An empty store shows nothing; fill it once, through the real API, so every screen has data.
  useEffect(() => {
    if (seeded.current || !snap.online || users.length === 0) return;
    if (snap.grants.length > 0 || snap.events.length > 0) { seeded.current = true; return; }
    seeded.current = true;
    seedDemo(users).catch(console.error);
  }, [snap.online, snap.grants.length, snap.events.length, users]);

  const me = users.find((u) => u.id === selected);
  const person = selected === ALL ? "u-newhire-1" : selected;
  const accent = me?.color ?? "#f4f4f4";
  const mine = (uid: string) => selected === ALL || uid === selected;
  const active = snap.grants.filter((g) => !g.revoked && Date.parse(g.expires_at) > now && mine(g.requester_id));
  const pending = snap.cases.filter((c) => c.status === "pending" && mine(c.requester_id));
  const revoked = snap.grants.filter((g) => g.revoked && mine(g.requester_id));
  const bounced = snap.events.filter((e) => e.type === "action_executed" && e.payload.status === "bounced").length;

  return (
    <div className="ap" style={{ ["--accent" as string]: accent }}>
      <header className="hd">
        <span className="brand">APERTURE</span>
        <span className="seg" role="group" aria-label="Mode">
          <button aria-pressed={mode === "user"} onClick={() => { setMode("user"); if (selected === ALL) setSelected("u-newhire-1"); }}>User</button>
          <button aria-pressed={mode === "manager"} onClick={() => { setMode("manager"); if (selected === ALL) setSelected("u-manager-1"); }}>Manager</button>
        </span>
        <span className="right">
          {mode === "console" && (
            <span className="seg" role="group" aria-label="Zoom">
              <button aria-pressed={zoom === "session"} onClick={() => setZoom("session")}>session</button>
              <button aria-pressed={zoom === "project"} onClick={() => setZoom("project")}>project</button>
            </span>
          )}
          <span className={`dotst ${!snap.online ? "" : snap.verify?.ok ? "ok" : "bad"}`}><i />{!snap.online ? "offline" : snap.verify?.ok ? `chain ${snap.verify.length}` : "chain broken"}</span>
          <Controls users={users} selected={person} onSelect={setSelected} grants={snap.grants} cases={snap.cases} online={snap.online} />
        </span>
      </header>

      {mode === "user" && (
        <UserScreen grants={snap.grants} cases={snap.cases} events={snap.events} resources={snap.resources} users={users} selected={person} online={snap.online} now={now} />
      )}

      {mode === "manager" && (
        <Manager grants={snap.grants} cases={snap.cases} events={snap.events} resources={snap.resources} users={users} selected={person} now={now} onDeepDive={(uid) => { setSelected(uid); setMode("console"); }} />
      )}

      {mode === "console" && (
        <div className="console-body">
          <div className="console-main">
            <div className="sum">
              <button className="back" onClick={() => setMode("manager")}>← Manager</button>
              <div><span className="n" style={{ color: accent }}>{active.length}</span><span className="k">active</span></div>
              <div><span className="n amber">{pending.length}</span><span className="k">pending</span></div>
              <div><span className="n">{revoked.length}</span><span className="k">revoked</span></div>
              <div><span className={`n ${bounced ? "red" : ""}`}>{bounced}</span><span className="k">bounced</span></div>
            </div>
            <div className="grid2">
              <div>
                <div className="sec-h"><h2>Access</h2></div>
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
            <Enact events={snap.events} grants={snap.grants} resources={snap.resources} users={users} selected={selected} preview={snap.preview} />
          </div>
          <Composer key={selected} selected={selected} users={users} online={snap.online} />
        </div>
      )}
    </div>
  );
}
