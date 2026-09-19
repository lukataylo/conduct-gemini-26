import { useEffect, useMemo, useState } from "react";
import "./aperture.css";
import { ALL, toUsers, useSnapshot } from "./api";
import { Approvals } from "./Approvals";
import { DemoBar } from "./DemoBar";
import { Enact } from "./Enact";
import { Manager } from "./Manager";
import { Matrix } from "./Matrix";
import { Onboard } from "./Onboard";
import { Recorder } from "./Recorder";
import { Summary } from "./Summary";
import { Timeline } from "./Timeline";

type Screen = "onboard" | "me" | "manager" | "console";
const SCREENS: { id: Screen; name: string; who: string }[] = [
  { id: "onboard", name: "Onboard", who: "new hire" },
  { id: "me", name: "My access", who: "end user" },
  { id: "manager", name: "Manager", who: "approver" },
  { id: "console", name: "Timeline", who: "deep-dive" },
];

function initialUser(): string {
  return new URLSearchParams(window.location.search).get("user") ?? "u-newhire-1";
}
function initialScreen(): Screen {
  const s = new URLSearchParams(window.location.search).get("screen");
  return (SCREENS.some((x) => x.id === s) ? s : "onboard") as Screen;
}

export default function ApertureApp() {
  const snap = useSnapshot();
  const users = useMemo(() => toUsers(snap.people), [snap.people]);
  const [selected, setSelected] = useState<string>(initialUser);
  const [screen, setScreen] = useState<Screen>(initialScreen);
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
  const person = selected === ALL ? "u-newhire-1" : selected;

  return (
    <div className="ap" style={{ ["--accent" as string]: accent }}>
      <header className="hd">
        <span className="brand">APERTURE</span>
        <nav className="screens" aria-label="Screens">
          {SCREENS.map((s) => (
            <button key={s.id} className="scr" aria-pressed={screen === s.id} onClick={() => setScreen(s.id)}>
              <span>{s.name}</span><small>{s.who}</small>
            </button>
          ))}
        </nav>
        <div className="people" role="tablist" aria-label="Acting as">
          {screen === "console" && (
            <button className="person" aria-pressed={selected === ALL} onClick={() => setSelected(ALL)} style={{ ["--u" as string]: "#f4f4f4" }}>
              <i className="multi" /><span>Everyone</span>
            </button>
          )}
          {users.map((u) => (
            <button key={u.id} className="person" aria-pressed={selected === u.id} onClick={() => setSelected(u.id)} style={{ ["--u" as string]: u.color }}>
              <i /><span>{u.name}</span>
            </button>
          ))}
        </div>
        <span className="right">
          <span className={`dotst ${!snap.online ? "" : snap.verify?.ok ? "ok" : "bad"}`}>
            <i />
            {!snap.online ? "offline" : snap.verify?.ok ? `chain ok · ${snap.verify.length}` : `chain broken · ${snap.verify?.broken_at}`}
          </span>
          {screen === "console" && (
            <span className="seg" role="group" aria-label="Zoom">
              <button aria-pressed={zoom === "session"} onClick={() => setZoom("session")}>session</button>
              <button aria-pressed={zoom === "project"} onClick={() => setZoom("project")}>project</button>
            </span>
          )}
        </span>
      </header>

      {screen === "onboard" && (
        <Onboard users={users} resources={snap.resources} grants={snap.grants} cases={snap.cases} selected={person} online={snap.online} now={now} onOpenSummary={() => setScreen("me")} />
      )}

      {screen === "me" && (
        <Summary grants={snap.grants} cases={snap.cases} events={snap.events} resources={snap.resources} users={users} selected={person} now={now} />
      )}

      {screen === "manager" && (
        <Manager grants={snap.grants} cases={snap.cases} events={snap.events} resources={snap.resources} users={users} selected={person} now={now} onDeepDive={(uid) => { setSelected(uid); setScreen("console"); }} />
      )}

      {screen === "console" && (
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
          <Enact events={snap.events} grants={snap.grants} resources={snap.resources} users={users} selected={selected} preview={snap.preview} />
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
        </>
      )}

      <DemoBar grants={snap.grants} cases={snap.cases} users={users} selected={selected} online={snap.online} />
    </div>
  );
}
