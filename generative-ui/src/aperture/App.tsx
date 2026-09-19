import { useEffect, useMemo, useRef, useState } from "react";
import "./aperture.css";
import { ALL, toUsers, useSnapshot } from "./api";
import { Approvals } from "./Approvals";
import { Composer } from "./Composer";
import { Enact } from "./Enact";
import { ManagerSide } from "./Manager";
import { Matrix } from "./Matrix";
import { Menu, seedDemo, type Mode } from "./Menu";
import { Recorder } from "./Recorder";
import { Summary } from "./Summary";
import { Timeline } from "./Timeline";
import { UserScreen } from "./User";
import { Users } from "./Users";

function initialMode(): Mode {
  const m = new URLSearchParams(window.location.search).get("screen");
  return m === "console" || m === "onboard" || m === "me" ? m : "users";
}
function initialUser(): string {
  return new URLSearchParams(window.location.search).get("user") ?? ALL;
}

export default function ApertureApp() {
  const snap = useSnapshot();
  const users = useMemo(() => toUsers(snap.people), [snap.people]);
  const [mode, setMode] = useState<Mode>(initialMode);
  const [selected, setSelected] = useState<string>(initialUser); // only the Timeline deep-dive filters by person
  const zoom = "session" as const;
  const [now, setNow] = useState(Date.now());
  const seeded = useRef(false);

  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, []);

  // An empty store shows nothing; fill it once, through the real API.
  useEffect(() => {
    if (seeded.current || !snap.online || users.length === 0) return;
    seeded.current = true;
    if (snap.grants.length === 0 && snap.events.length === 0) seedDemo(users).catch(console.error);
  }, [snap.online, snap.grants.length, snap.events.length, users]);

  const me = users.find((u) => u.id === selected);
  const accent = me?.color ?? "#f4f4f4";
  const mine = (uid: string) => selected === ALL || uid === selected;
  const active = snap.grants.filter((g) => !g.revoked && Date.parse(g.expires_at) > now && mine(g.requester_id));
  const pending = snap.cases.filter((c) => c.status === "pending" && mine(c.requester_id));
  const revoked = snap.grants.filter((g) => g.revoked && mine(g.requester_id));
  const bounced = snap.events.filter((e) => e.type === "action_executed" && e.payload.status === "bounced").length;
  const openConsole = (uid: string) => { setSelected(uid); setMode("console"); };
  const openAccess = (uid: string) => { setSelected(uid); setMode("me"); };
  const person = selected === ALL ? "u-newhire-1" : selected;
  const personal = mode === "onboard" || mode === "me";

  return (
    <div className="ap" style={{ ["--accent" as string]: accent }}>
      <header className="hd">
        <span className="brand">APERTURE</span>
        <span className="right">
          {(mode === "console" || personal) && (
            <span className="people" role="tablist" aria-label="Person">
              {mode === "console" && <button className="person" aria-pressed={selected === ALL} onClick={() => setSelected(ALL)} style={{ ["--u" as string]: "#f4f4f4" }}><i className="multi" /><span>Everyone</span></button>}
              {users.map((u) => (
                <button key={u.id} className="person" aria-pressed={selected === u.id} onClick={() => setSelected(u.id)} style={{ ["--u" as string]: u.color }}><i /><span>{u.name.split(" ")[0]}</span></button>
              ))}
            </span>
          )}
          <span className={`dotst ${!snap.online ? "" : snap.verify?.ok ? "ok" : "bad"}`}><i />{!snap.online ? "offline" : snap.verify?.ok ? `chain ${snap.verify.length}` : "chain broken"}</span>
          <Menu mode={mode} onMode={setMode} users={users} grants={snap.grants} cases={snap.cases} online={snap.online} />
        </span>
      </header>

      {mode === "users" && (
        <div className="mgr">
          <Users grants={snap.grants} cases={snap.cases} events={snap.events} resources={snap.resources} users={users} now={now} online={snap.online} onOpen={openConsole} onOpenAccess={openAccess} />
          <ManagerSide grants={snap.grants} cases={snap.cases} events={snap.events} resources={snap.resources} users={users} />
        </div>
      )}

      {mode === "onboard" && (
        <UserScreen grants={snap.grants} cases={snap.cases} events={snap.events} resources={snap.resources} users={users} selected={person} online={snap.online} now={now} />
      )}

      {mode === "me" && (
        <Summary grants={snap.grants} cases={snap.cases} events={snap.events} resources={snap.resources} users={users} selected={person} now={now} />
      )}

      {mode === "console" && (
        <div className="console-body">
          <div className="console-main">
            <div className="sum">
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
          <Composer key={selected} selected={selected === ALL ? "u-newhire-1" : selected} users={users} online={snap.online} />
        </div>
      )}
    </div>
  );
}
