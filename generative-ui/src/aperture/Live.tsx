import { useEffect, useRef, useState } from "react";
import type { User } from "./api";
import { post } from "./api";

interface Props {
  viewer: User | undefined;
}

/** Gemini bubble: one chat, available on every screen. Text now; the mic is the Gemini
 *  Live slot (track 2). It can explain and draft a request; it cannot vote or grant. */
export function Live({ viewer }: Props) {
  const [open, setOpen] = useState(false);
  const [msg, setMsg] = useState("");
  const [chat, setChat] = useState<{ who: "you" | "gemini"; text: string }[]>([]);
  const [busy, setBusy] = useState(false);
  const [conv, setConv] = useState<string | null>(null);
  const logRef = useRef<HTMLDivElement>(null);

  useEffect(() => { logRef.current?.scrollTo({ top: 1e6 }); }, [chat, busy]);

  const ask = async () => {
    if (!viewer || !msg.trim()) return;
    const text = msg.trim();
    setChat((c) => [...c, { who: "you", text }]);
    setMsg("");
    setBusy(true);
    try {
      const r = await post<{ reply: string; conversation_id: string }>("/agent/turn", { viewer_id: viewer.id, message: text, conversation_id: conv });
      setConv(r.conversation_id);
      setChat((c) => [...c, { who: "gemini", text: r.reply }]);
    } catch {
      setChat((c) => [...c, { who: "gemini", text: "Offline." }]);
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <button className={`live-bubble ${open ? "open" : ""}`} aria-expanded={open} aria-label="Gemini" onClick={() => setOpen((o) => !o)}>
        <i /><span>{open ? "Close" : "Gemini"}</span>
      </button>
      {open && (
        <div className="live-panel" style={{ ["--u" as string]: viewer?.color ?? "#f4f4f4" }}>
          <div className="live-head"><span className="apv-h">Gemini <span className="live-dot" /></span><small>as {viewer?.name ?? "…"}</small></div>
          <div className="live-log" ref={logRef}>
            {chat.length === 0 && <div className="live-empty">Ask what's waiting, why something was refused, or draft a request. Gemini explains; it never grants.</div>}
            {chat.map((m, i) => <div key={i} className={`live-msg ${m.who}`}><b>{m.who === "you" ? viewer?.short ?? "you" : "G"}</b><span>{m.text}</span></div>)}
            {busy && <div className="live-msg gemini"><b>G</b><span>…</span></div>}
          </div>
          <div className="live-in">
            <button className="nb mic" title="Voice — Gemini Live, coming" disabled>●</button>
            <input id="live-text" autoFocus value={msg} onChange={(e) => setMsg(e.target.value)} onKeyDown={(e) => e.key === "Enter" && ask()} placeholder="Who is waiting on me?" />
            <button className="nb" onClick={ask} disabled={busy || !msg.trim()}>Send</button>
          </div>
        </div>
      )}
    </>
  );
}
