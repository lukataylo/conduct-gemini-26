import { useEffect, useRef, useState } from "react";
import type { AgentTurnOut, User } from "./api";
import { postAgentTurn, postLiveSession } from "./api";

type Mode = "idle" | "listening" | "thinking" | "speaking";
type Row = { kind: "you" | "gemini" | "tool"; text: string };

interface Props {
  viewer: User | undefined;
  focus?: User;
  page: string;
  onNavigateTimeline: (focusId: string) => void;
}

/** Dot-matrix face: two eyes that blink, glance, squint when speaking, and spin when thinking. */
function Face({ mode, small }: { mode: Mode; small?: boolean }) {
  const ref = useRef<HTMLCanvasElement>(null);
  useEffect(() => {
    const c = ref.current;
    if (!c) return;
    const ctx = c.getContext("2d");
    if (!ctx) return;
    const S = small ? 4 : 8, COLS = 20, ROWS = 8;
    c.width = COLS * S * 2; c.height = ROWS * S * 2; c.style.width = `${COLS * S}px`; c.style.height = `${ROWS * S}px`;
    ctx.scale(2, 2);
    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    let raf = 0, nextBlink = performance.now() + 2500, blinkUntil = 0, gaze = { x: 0, y: 0 }, gazeUntil = 0;
    const eyes = [3, 12]; // left column of each 5x5 eye
    const draw = (t: number) => {
      if (t > nextBlink) { blinkUntil = t + 130; nextBlink = t + 2500 + Math.random() * 3500; }
      if (t > gazeUntil) { gaze = { x: Math.round(Math.random() * 2 - 1), y: Math.round(Math.random() * 2 - 1) }; gazeUntil = t + 1200 + Math.random() * 2500; }
      const blinking = t < blinkUntil;
      const grid: number[][] = Array.from({ length: ROWS }, () => Array(COLS).fill(0));
      for (const ex of eyes) {
        if (mode === "thinking") {
          const k = Math.floor(t / 90) % 16; // dot running around the eye's border
          const ring = [[0,0],[0,1],[0,2],[0,3],[0,4],[1,4],[2,4],[3,4],[4,4],[4,3],[4,2],[4,1],[4,0],[3,0],[2,0],[1,0]];
          for (let i = 0; i < 16; i++) { const [r, cc] = ring[(k + i) % 16]; grid[1 + r][ex + cc] = i < 5 ? 2 : 1; }
          continue;
        }
        for (let r = 0; r < 5; r++) for (let cc = 0; cc < 5; cc++) {
          const y = 1 + r, x = ex + cc;
          if (blinking) { grid[3][x] = 1; continue; }
          if (mode === "speaking" && r > 2) continue; // squint = happy
          if (mode === "listening" || (r > 0 && r < 4 && cc > 0 && cc < 4) || r === 0 || r === 4 || cc === 0 || cc === 4) grid[y][x] = 1;
        }
        if (!blinking && mode !== "speaking") {
          const px = ex + 2 + (mode === "listening" ? 0 : gaze.x), py = 3 + (mode === "listening" ? 0 : gaze.y);
          for (let r = -1; r <= 0; r++) for (let cc = 0; cc <= 1; cc++) if (grid[py + r]?.[px + cc] !== undefined) grid[py + r][px + cc] = 2;
        }
      }
      ctx.clearRect(0, 0, COLS * S, ROWS * S);
      for (let y = 0; y < ROWS; y++) for (let x = 0; x < COLS; x++) {
        const v = grid[y][x];
        ctx.globalAlpha = v === 0 ? 0.08 : 1;
        ctx.fillStyle = v === 2 ? "#4285f4" : "#f4f4f4";
        ctx.beginPath(); ctx.arc(x * S + S / 2, y * S + S / 2, v ? S * 0.36 : S * 0.18, 0, Math.PI * 2); ctx.fill();
      }
      ctx.globalAlpha = 1;
      if (!reduce) raf = requestAnimationFrame(draw);
    };
    draw(performance.now());
    return () => cancelAnimationFrame(raf);
  }, [mode, small]);
  return <canvas ref={ref} className="face" aria-hidden="true" />;
}

/** Dot-matrix waveform: live mic level while listening, synthetic while Gemini speaks, flat otherwise. */
function Wave({ mode, level }: { mode: Mode; level: React.MutableRefObject<number> }) {
  const ref = useRef<HTMLCanvasElement>(null);
  useEffect(() => {
    const c = ref.current;
    if (!c) return;
    const ctx = c.getContext("2d");
    if (!ctx) return;
    const S = 8, COLS = 40, ROWS = 7;
    c.width = COLS * S * 2; c.height = ROWS * S * 2; c.style.width = `${COLS * S}px`; c.style.height = `${ROWS * S}px`;
    ctx.scale(2, 2);
    const hist = new Array(COLS).fill(0);
    let raf = 0;
    const draw = (t: number) => {
      const amp = mode === "listening" ? level.current : mode === "speaking" ? 0.35 + 0.35 * Math.abs(Math.sin(t / 140)) * Math.abs(Math.sin(t / 530)) : mode === "thinking" ? 0.12 : 0;
      hist.push(amp); hist.shift();
      ctx.clearRect(0, 0, COLS * S, ROWS * S);
      for (let x = 0; x < COLS; x++) {
        const h = Math.round(hist[x] * ROWS);
        for (let y = 0; y < ROWS; y++) {
          const on = Math.abs(y - (ROWS - 1) / 2) < h / 2;
          ctx.globalAlpha = on ? 1 : 0.08;
          ctx.fillStyle = mode === "listening" ? "#f4f4f4" : "#4285f4";
          ctx.beginPath(); ctx.arc(x * S + S / 2, y * S + S / 2, on ? S * 0.34 : S * 0.16, 0, Math.PI * 2); ctx.fill();
        }
      }
      ctx.globalAlpha = 1;
      raf = requestAnimationFrame(draw);
    };
    raf = requestAnimationFrame(draw);
    return () => cancelAnimationFrame(raf);
  }, [mode, level]);
  return <canvas ref={ref} className="wave" aria-hidden="true" />;
}

export function Live({ viewer, focus, page, onNavigateTimeline }: Props) {
  const [open, setOpen] = useState(false);
  const [mode, setMode] = useState<Mode>("idle");
  const [msg, setMsg] = useState("");
  const [rows, setRows] = useState<Row[]>([]);
  const [cid, setCid] = useState<string | null>(null);
  const [pending, setPending] = useState<AgentTurnOut | null>(null);
  const [voice, setVoice] = useState(false);
  const [voiceOffline, setVoiceOffline] = useState(false);
  const [interim, setInterim] = useState("");
  const level = useRef(0);
  const logRef = useRef<HTMLDivElement>(null);
  const recRef = useRef<any>(null);
  const audioRef = useRef<{ ctx: AudioContext; stream: MediaStream; raf: number } | null>(null);

  useEffect(() => { logRef.current?.scrollTo({ top: 1e6 }); }, [rows, pending, mode]);
  useEffect(() => { setRows([]); setCid(null); setPending(null); setVoiceOffline(false); }, [viewer?.id]);
  useEffect(() => {
    if (!open || !viewer) return;
    const hasSpeech = Boolean((window as any).SpeechRecognition || (window as any).webkitSpeechRecognition);
    void postLiveSession({
      viewer_id: viewer.id,
      focus_id: focus?.id ?? "all",
      page,
      conversation_id: cid,
    }).then((session) => {
      setCid((current) => current ?? session.conversation_id);
      if (!session.ok && !hasSpeech) setVoiceOffline(true);
    }).catch(() => {
      if (!hasSpeech) setVoiceOffline(true);
    });
  }, [open, viewer?.id, focus?.id, page]);

  const speak = (text: string) => {
    if (!voice || !("speechSynthesis" in window)) return;
    const u = new SpeechSynthesisUtterance(text);
    u.onstart = () => setMode("speaking");
    u.onend = () => setMode("idle");
    window.speechSynthesis.cancel();
    window.speechSynthesis.speak(u);
  };

  const applyTurn = (turn: AgentTurnOut) => {
    setCid(turn.conversation_id);
    for (const name of turn.tools_used) setRows((r) => [...r, { kind: "tool", text: name }]);
    if (turn.reply) { setRows((r) => [...r, { kind: "gemini", text: turn.reply }]); speak(turn.reply); }
    setPending(turn.request_result?.status === "needs_confirmation" ? turn : null);
    if (turn.navigate === "timeline") onNavigateTimeline(focus?.id ?? "all");
  };

  const payload = (message: string, extra?: { conversation_id?: string | null; confirm?: boolean }) => ({
    viewer_id: viewer!.id,
    focus_id: focus?.id ?? "all",
    page,
    message,
    ...extra,
  });

  const send = async (text: string) => {
    if (!viewer || !text.trim()) return;
    setRows((r) => [...r, { kind: "you", text: text.trim() }]);
    setMsg(""); setInterim("");
    setMode("thinking");
    try {
      applyTurn(await postAgentTurn(payload(text.trim(), { conversation_id: cid })));
    } catch (e) {
      setRows((r) => [...r, { kind: "gemini", text: `Offline (${String(e).slice(0, 40)})` }]);
    } finally {
      setMode((m) => (m === "thinking" ? "idle" : m));
    }
  };

  const confirm = async () => {
    if (!viewer || !pending) return;
    setMode("thinking");
    try {
      applyTurn(await postAgentTurn(payload(pending.request_result?.preview?.raw_text || "confirm", { conversation_id: pending.conversation_id, confirm: true })));
    } catch (e) {
      setRows((r) => [...r, { kind: "gemini", text: String(e) }]);
    } finally {
      setMode((m) => (m === "thinking" ? "idle" : m));
    }
  };

  const stopListening = () => {
    recRef.current?.stop?.(); recRef.current = null;
    if (audioRef.current) { cancelAnimationFrame(audioRef.current.raf); audioRef.current.stream.getTracks().forEach((t) => t.stop()); audioRef.current.ctx.close(); audioRef.current = null; }
    level.current = 0;
    setMode((m) => (m === "listening" ? "idle" : m));
  };

  const listen = async () => {
    if (mode === "listening") { stopListening(); return; }
    const SR = (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition;
    if (!SR) { setRows((r) => [...r, { kind: "gemini", text: "Voice needs Chrome or Safari here — type instead." }]); return; }
    setVoice(true);
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const ctx = new AudioContext(); const src = ctx.createMediaStreamSource(stream); const an = ctx.createAnalyser(); an.fftSize = 512; src.connect(an);
      const buf = new Uint8Array(an.fftSize);
      const tick = () => { an.getByteTimeDomainData(buf); let s = 0; for (const v of buf) { const d = (v - 128) / 128; s += d * d; } level.current = Math.min(1, Math.sqrt(s / buf.length) * 6); audioRef.current!.raf = requestAnimationFrame(tick); };
      audioRef.current = { ctx, stream, raf: 0 }; tick();
    } catch { /* no mic level; recognition can still run */ }
    const rec = new SR(); rec.lang = "en-GB"; rec.interimResults = true; rec.continuous = false;
    rec.onresult = (e: any) => {
      let finalText = "", partial = "";
      for (const res of e.results) (res.isFinal ? (finalText += res[0].transcript) : (partial += res[0].transcript));
      setInterim(partial);
      if (finalText) { stopListening(); void send(finalText); }
    };
    rec.onerror = () => stopListening();
    rec.onend = () => { if (recRef.current === rec) stopListening(); };
    recRef.current = rec; setMode("listening"); rec.start();
  };

  const preview = pending?.request_result?.preview;

  return (
    <>
      <button className={`live-bubble ${open ? "open" : ""}`} aria-expanded={open} aria-label="Gemini" onClick={() => setOpen((o) => !o)}>
        <Face mode={mode} small /><span>{open ? "Close" : voiceOffline ? "voice offline — use chat" : "Gemini"}</span>
      </button>
      {open && (
        <div className="live-panel" style={{ ["--u" as string]: viewer?.color ?? "#f4f4f4" }}>
          <div className="live-face"><Face mode={mode} /><div className="live-state"><b>{mode}</b><small>as {viewer?.name ?? "…"} · looking at {focus?.name ?? "everyone"}</small></div></div>
          <Wave mode={mode} level={level} />
          <div className="live-log" ref={logRef}>
            {rows.length === 0 && <div className="live-empty">Ask what's waiting, why something was refused, or ask for access. Gemini explains and drafts; it never grants.</div>}
            {rows.map((m, i) => m.kind === "tool"
              ? <div className="live-msg tool" key={i}><b>⚙</b><span>used {m.text}</span></div>
              : <div key={i} className={`live-msg ${m.kind}`}><b>{m.kind === "you" ? viewer?.short ?? "you" : "G"}</b><span>{m.text}</span></div>)}
            {interim && <div className="live-msg you dim"><b>{viewer?.short ?? "you"}</b><span>{interim}…</span></div>}
            {preview && (
              <div className="confirm-card">
                <div className="confirm-k">confirm request</div>
                <div><span className="k">resources</span> {preview.resource_ids.join(", ") || "—"}</div>
                <div><span className="k">duration</span> {preview.requested_duration_days}d</div>
                <button className="nb go" onClick={confirm} disabled={mode === "thinking"}>Confirm</button>
              </div>
            )}
          </div>
          <div className="live-in">
            <button className={`nb mic ${mode === "listening" ? "on" : ""}`} title={mode === "listening" ? "Stop" : "Talk"} onClick={listen}>●</button>
            <input id="live-text" autoFocus value={msg} onChange={(e) => setMsg(e.target.value)} onKeyDown={(e) => e.key === "Enter" && send(msg)} placeholder={mode === "listening" ? "Listening…" : "Who is waiting on me?"} />
            <button className="nb" onClick={() => send(msg)} disabled={mode === "thinking" || !msg.trim()}>Send</button>
          </div>
        </div>
      )}
    </>
  );
}
