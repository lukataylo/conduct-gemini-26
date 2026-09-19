import { useEffect, useMemo, useRef, useState } from "react";
import "./aperture.css";
import { ALL, toUsers, useSnapshot } from "./api";
import { Approvals } from "./Approvals";
import { Enact } from "./Enact";
import { Live } from "./Live";
import { ManagerSide } from "./Manager";
import { Matrix } from "./Matrix";
import { PersonMenu, roleOf, seedDemo, type Role } from "./Menu";
import { Recorder } from "./Recorder";
import { Summary } from "./Summary";
import { Timeline } from "./Timeline";
import { UserScreen } from "./User";
import { Users } from "./Users";

type Tab = "overview" | "timeline" | "onboard" | "access";
const TABS: Record<Role, { id: Tab; name: string }[]> = {
  manager: [{ id: "overview", name: "Overview" }, { id: "timeline", name: "Timeline" }],
  user: [{ id: "onboard", name: "Onboard" }, { id: "access", name: "Access" }, { id: "timeline", name: "Timeline" }],
};

function param(k: string): string | null {
  return new URLSearchParams(window.location.search).get(k);
}

export default function ApertureApp() {
  const snap = useSnapshot();
  const users = useMemo(() => toUsers(snap.people), [snap.people]);
  const [role, setRole] = useState<Role>(() => (param("role") === "user" ? "user" : "manager"));
  const [tab, setTab] = useState<Record<Role, Tab>>({ manager: "overview", user: "onboard" });
  const [actorId, setActorId] = useState<Record<Role, string | null>>({ manager: "u-manager-1", user: param("user") });
  const [scope, setScope] = useState<string>(ALL); // manager focus: cards + chips, default everyone
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

  // Manager dropdown is signed-in actor only (Priya + Jordan). Cards/chips set focus, not actor.
  const inRole = role === "manager" ? users.filter((u) => roleOf(u) === "manager") : users.filter((u) => roleOf(u) === "user");
  const actor = inRole.find((u) => u.id === actorId[role]) ?? (role === "manager" ? users.find((u) => u.id === "u-manager-1") ?? inRole[0] : inRole[0]);
  const current = tab[role];
  const accent = actor?.color ?? "#f4f4f4";
  const timelineFor = role === "manager" ? scope : actor?.id ?? ALL;
  const focus = role === "manager" ? (scope === ALL ? undefined : users.find((u) => u.id === scope)) : actor;

  const mine = (uid: string) => timelineFor === ALL || uid === timelineFor;
  const active = snap.grants.filter((g) => !g.revoked && Date.parse(g.expires_at) > now && mine(g.requester_id));
  const pending = snap.cases.filter((c) => c.status === "pending" && mine(c.requester_id));
  const revoked = snap.grants.filter((g) => g.revoked && mine(g.requester_id));
  const bounced = snap.events.filter((e) => e.type === "action_executed" && e.payload.status === "bounced" && (timelineFor === ALL || e.payload.requester_id === timelineFor)).length;

  const goTimeline = (uid: string) => { setScope(uid); setTab((t) => ({ ...t, manager: "timeline" })); };
  const goAccess = (uid: string) => { setRole("user"); setActorId((p) => ({ ...p, user: uid })); setTab((t) => ({ ...t, user: "access" })); };
  const onNavigateTimeline = (uid: string) => { setScope(uid); setTab((t) => ({ ...t, [role]: "timeline" })); };

  return (
    <div className="ap" style={{ ["--accent" as string]: accent }}>
      <header className="hd">
        <span className="brand-row">
          <span className="brand">APERTURE</span>
          <span className="who" aria-label="Company">
            <b>{snap.company.name}</b>
            {snap.company.platforms.map((p) => (
              <span key={p.id} className={`plat ${p.home ? "home" : ""}`} title={p.name}>{p.short}</span>
            ))}
          </span>
        </span>
        <nav className="tabs" aria-label="Screens">
          {TABS[role].map((t) => (
            <button key={t.id} className="tab" aria-pressed={current === t.id} onClick={() => setTab((s) => ({ ...s, [role]: t.id }))}>{t.name}</button>
          ))}
        </nav>
        <span className="right">
          <span className={`dotst ${!snap.online ? "" : snap.verify?.ok ? "ok" : "bad"}`}><i />{!snap.online ? "offline" : snap.verify?.ok ? `chain ${snap.verify.length}` : "chain broken"}</span>
          <span className="seg" role="group" aria-label="Role">
            <button aria-pressed={role === "user"} onClick={() => setRole("user")}>User</button>
            <button aria-pressed={role === "manager"} onClick={() => setRole("manager")}>Manager</button>
          </span>
          <PersonMenu role={role} users={inRole} selected={actor?.id ?? ""} onSelect={(id) => setActorId((p) => ({ ...p, [role]: id }))} grants={snap.grants} cases={snap.cases} online={snap.online} />
        </span>
      </header>

      {role === "manager" && current === "overview" && (
        <div className="mgr">
          <Users grants={snap.grants} cases={snap.cases} events={snap.events} resources={snap.resources} users={users} company={snap.company} now={now} online={snap.online} onOpen={goTimeline} onOpenAccess={goAccess} focusId={scope} onFocus={setScope} />
          <ManagerSide grants={snap.grants} cases={snap.cases} events={snap.events} resources={snap.resources} users={users} company={snap.company} policy={snap.policy} online={snap.online} />
        </div>
      )}

      {role === "user" && current === "onboard" && actor && (
        <UserScreen grants={snap.grants} cases={snap.cases} events={snap.events} resources={snap.resources} users={users} company={snap.company} selected={actor.id} online={snap.online} now={now} />
      )}

      {role === "user" && current === "access" && actor && (
        <Summary grants={snap.grants} cases={snap.cases} events={snap.events} resources={snap.resources} users={users} selected={actor.id} now={now} />
      )}

      {current === "timeline" && (
        <div className="console-body">
          <div className="console-main">
            <div className="sum">
              {role === "manager" && (
                <span className="people" role="tablist" aria-label="Scope">
                  <button className="person" aria-pressed={scope === ALL} onClick={() => setScope(ALL)} style={{ ["--u" as string]: "#f4f4f4" }}><i className="multi" /><span>Everyone</span></button>
                  {users.map((u) => (
                    <button key={u.id} className="person" aria-pressed={scope === u.id} onClick={() => setScope(u.id)} style={{ ["--u" as string]: u.color }}><i /><span>{u.name.split(" ")[0]}</span></button>
                  ))}
                </span>
              )}
              <div><span className="n" style={{ color: accent }}>{active.length}</span><span className="k">active</span></div>
              <div><span className="n amber">{pending.length}</span><span className="k">pending</span></div>
              <div><span className="n">{revoked.length}</span><span className="k">revoked</span></div>
              <div><span className={`n ${bounced ? "red" : ""}`}>{bounced}</span><span className="k">bounced</span></div>
            </div>
            <div className="grid2 single">
              <div>
                <div className="sec-h"><h2>Access</h2></div>
                <Matrix grants={snap.grants} cases={snap.cases} events={snap.events} resources={snap.resources} users={users} company={snap.company} selected={timelineFor} zoom="session" now={now} />
              </div>
            </div>
            <main className="main">
              <div>
                <div className="sec-h"><h2>Leases</h2></div>
                <Timeline grants={snap.grants} cases={snap.cases} events={snap.events} resources={snap.resources} users={users} selected={timelineFor} zoom="session" now={now} />
              </div>
              <div>
                <div className="sec-h"><h2>Recorder</h2></div>
                <Recorder events={snap.events} grants={snap.grants} resources={snap.resources} users={users} selected={timelineFor} />
              </div>
            </main>
            <Enact events={snap.events} grants={snap.grants} resources={snap.resources} users={users} selected={timelineFor} preview={snap.preview} />
          </div>
          <aside className="console-side">
            <Approvals cases={snap.cases} grants={snap.grants} events={snap.events} resources={snap.resources} users={users} selected={timelineFor} />
          </aside>
        </div>
      )}

      <Live viewer={actor} focus={focus} page={current} onNavigateTimeline={onNavigateTimeline} />
    </div>
  );
}
