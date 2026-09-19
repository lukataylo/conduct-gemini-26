import { useEffect, useRef, useState } from "react";
import type { AgentTurnOut, User } from "./api";
import { liveWsUrl, postAgentTurn, postLiveSession } from "./api";
import { createPlayer, startMic } from "./liveAudio";

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

function rowKind(raw: string | undefined): Row["kind"] {
  if (raw === "you" || raw === "gemini" || raw === "tool") return raw;
  return "gemini";
}

function asMode(raw: string | undefined): Mode | null {
  if (raw === "idle" || raw === "listening" || raw === "thinking" || raw === "speaking") return raw;
  return null;
}

export function Live({ viewer, focus, page, onNavigateTimeline }: Props) {
  const [open, setOpen] = useState(false);
  const [mode, setMode] = useState<Mode>("idle");
  const [msg, setMsg] = useState("");
  const [rows, setRows] = useState<Row[]>([]);
  const [cid, setCid] = useState<string | null>(null);
  const [pending, setPending] = useState<AgentTurnOut | null>(null);
  const [voiceOffline, setVoiceOffline] = useState(false);
  const [micOn, setMicOn] = useState(false);
  const level = useRef(0);
  const logRef = useRef<HTMLDivElement>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const micRef = useRef<{ stop: () => void } | null>(null);
  const playerRef = useRef<ReturnType<typeof createPlayer> | null>(null);
  const cidRef = useRef<string | null>(null);
  const speakingRef = useRef(false);
  const sealRef = useRef(false);
  const viewerRef = useRef(viewer);
  const focusRef = useRef(focus);
  const pageRef = useRef(page);
  cidRef.current = cid;
  viewerRef.current = viewer;
  focusRef.current = focus;
  pageRef.current = page;

  const appendRow = (row: Row) => {
    if (!row.text) return;
    setRows((r) => {
      const last = r[r.length - 1];
      if (last && last.kind === row.kind && last.text === row.text) return r;
      return [...r, row];
    });
  };

  const joinTranscript = (prev: string, next: string) => {
    if (!prev) return next;
    if (!next) return prev;
    if (/^\s/.test(next) || /\s$/.test(prev)) return prev + next;
    if (/^[.,!?;:]/.test(next)) return prev + next;
    if (/[A-Za-z]$/.test(prev) && /^[A-Za-z]/.test(next)) return prev + next;
    return `${prev} ${next}`;
  };

  const mergeTranscript = (kind: Row["kind"], text: string) => {
    if (!text) return;
    const startNew = sealRef.current;
    sealRef.current = false;
    setRows((r) => {
      const last = r[r.length - 1];
      if (!startNew && last && last.kind === kind) {
        const joined = joinTranscript(last.text, text);
        if (joined === last.text) return r;
        return [...r.slice(0, -1), { kind, text: joined }];
      }
      return [...r, { kind, text }];
    });
  };

  const kickPlayer = () => {
    if (!playerRef.current) playerRef.current = createPlayer();
    playerRef.current.push(new ArrayBuffer(0));
  };

  const playBinary = (data: ArrayBuffer | Blob) => {
    if (data instanceof ArrayBuffer) {
      playerRef.current?.push(data);
      return;
    }
    void data.arrayBuffer().then((buf) => playerRef.current?.push(buf));
  };

  const handleWsMessage = (ev: MessageEvent) => {
    if (typeof ev.data !== "string") {
      playBinary(ev.data);
      return;
    }
    let payload: { type?: string; conversation_id?: string; role?: string; kind?: string; text?: string; mode?: string; message?: string };
    try { payload = JSON.parse(ev.data); } catch { return; }
    if (payload.type === "ready") {
      if (payload.conversation_id) setCid(payload.conversation_id);
      return;
    }
    if (payload.type === "transcript") {
      mergeTranscript(rowKind(payload.role ?? payload.kind), String(payload.text ?? ""));
      return;
    }
    if (payload.type === "mode") {
      const next = asMode(payload.mode);
      if (next) {
        speakingRef.current = next === "speaking";
        if (next === "listening") sealRef.current = true;
        setMode(next);
      }
      return;
    }
    if (payload.type === "error") {
      appendRow({ kind: "gemini", text: String(payload.message ?? "Live error") });
    }
  };

  const openLiveWs = (conversationId: string) => {
    const existing = wsRef.current;
    if (existing && (existing.readyState === WebSocket.OPEN || existing.readyState === WebSocket.CONNECTING)) return;
    if (!playerRef.current) playerRef.current = createPlayer();
    const ws = new WebSocket(liveWsUrl());
    ws.binaryType = "arraybuffer";
    wsRef.current = ws;
    ws.onopen = () => {
      if (wsRef.current !== ws) return;
      const actor = viewerRef.current;
      if (!actor) return;
      ws.send(JSON.stringify({
        type: "hello",
        viewer_id: actor.id,
        focus_id: focusRef.current?.id ?? "all",
        page: pageRef.current,
        conversation_id: cidRef.current ?? conversationId,
      }));
    };
    ws.onmessage = handleWsMessage;
    ws.onclose = () => {
      if (wsRef.current === ws) wsRef.current = null;
    };
  };

  const tearDownLive = () => {
    micRef.current?.stop();
    micRef.current = null;
    speakingRef.current = false;
    sealRef.current = false;
    setMicOn(false);
    playerRef.current?.close();
    playerRef.current = null;
    if (wsRef.current) {
      wsRef.current.close();
      wsRef.current = null;
    }
    level.current = 0;
    setMode("idle");
  };

  useEffect(() => { logRef.current?.scrollTo({ top: 1e6 }); }, [rows, pending, mode]);
  useEffect(() => {
    setRows([]);
    setCid(null);
    cidRef.current = null;
    setPending(null);
    setVoiceOffline(false);
    tearDownLive();
  }, [viewer?.id]);
  useEffect(() => {
    if (!open || !viewer) return;
    let cancelled = false;
    void postLiveSession({
      viewer_id: viewer.id,
      focus_id: focus?.id ?? "all",
      page,
      conversation_id: cidRef.current,
    }).then((session) => {
      if (cancelled) return;
      setCid((current) => current ?? session.conversation_id);
      if (!session.ok) {
        if (!wsRef.current) setVoiceOffline(true);
        return;
      }
      setVoiceOffline(false);
      openLiveWs(session.conversation_id);
    }).catch(() => {
      if (!cancelled && !wsRef.current) setVoiceOffline(true);
    });
    return () => { cancelled = true; };
  }, [open, viewer?.id, focus?.id, page]);

  const liveOpen = () => wsRef.current?.readyState === WebSocket.OPEN;

  const waitForLiveOpen = (ms = 8000) =>
    new Promise<void>((resolve, reject) => {
      const t0 = Date.now();
      const tick = () => {
        if (liveOpen()) return resolve();
        if (Date.now() - t0 > ms) return reject(new Error("live timeout"));
        window.setTimeout(tick, 40);
      };
      tick();
    });

  const startLiveConversation = async () => {
    if (!viewer) throw new Error("no viewer");
    if (liveOpen()) return;
    const session = await postLiveSession({
      viewer_id: viewer.id,
      focus_id: focus?.id ?? "all",
      page,
      conversation_id: cidRef.current,
    });
    setCid((current) => current ?? session.conversation_id);
    if (!session.ok) {
      setVoiceOffline(true);
      throw new Error("live offline");
    }
    setVoiceOffline(false);
    openLiveWs(session.conversation_id);
    await waitForLiveOpen();
  };

  const applyTurn = (turn: AgentTurnOut, skipReply = false) => {
    setCid(turn.conversation_id);
    for (const name of turn.tools_used) appendRow({ kind: "tool", text: name });
    if (turn.reply && !skipReply) appendRow({ kind: "gemini", text: turn.reply });
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
    const trimmed = text.trim();
    appendRow({ kind: "you", text: trimmed });
    setMsg("");
    kickPlayer();
    const ws = wsRef.current;
    const viaLive = ws?.readyState === WebSocket.OPEN;
    if (viaLive) {
      ws.send(JSON.stringify({ type: "text", text: trimmed }));
      setMode("thinking");
      return;
    }
    setMode("thinking");
    try {
      applyTurn(await postAgentTurn(payload(trimmed, { conversation_id: cid })));
    } catch (e) {
      appendRow({ kind: "gemini", text: `Offline (${String(e).slice(0, 40)})` });
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
      appendRow({ kind: "gemini", text: String(e) });
    } finally {
      setMode((m) => (m === "thinking" ? "idle" : m));
    }
  };

  const toggleMic = async () => {
    if (micRef.current) {
      micRef.current.stop();
      micRef.current = null;
      setMicOn(false);
      level.current = 0;
      setMode((m) => (m === "listening" ? "idle" : m));
      return;
    }
    setOpen(true);
    kickPlayer();
    setMode("thinking");
    try {
      await startLiveConversation();
      const handle = await startMic(
        (buf) => {
          if (speakingRef.current) return;
          if (wsRef.current?.readyState === WebSocket.OPEN) wsRef.current.send(buf);
        },
        (n) => { level.current = n; },
      );
      micRef.current = handle;
      setMicOn(true);
      setMode("listening");
    } catch (err) {
      const blocked = String(err).toLowerCase().includes("notallowed") || String(err).toLowerCase().includes("permission");
      appendRow({ kind: "gemini", text: blocked ? "Mic blocked — type instead." : "Live did not start — type instead." });
      setMode("idle");
    }
  };

  const preview = pending?.request_result?.preview;

  return (
    <>
      <button className={`live-bubble ${open ? "open" : ""}`} aria-expanded={open} aria-label="Gemini" onClick={() => { kickPlayer(); setOpen((o) => !o); }}>
        <Face mode={mode} small /><span>{open ? "Close" : voiceOffline ? "voice offline — use chat" : "Gemini"}</span>
      </button>
      {open && (
        <div className="live-panel" style={{ ["--u" as string]: viewer?.color ?? "#f4f4f4" }}>
          <div className="live-face"><Face mode={mode} /><div className="live-state"><b>{voiceOffline ? "voice offline — use chat" : mode}</b><small>helping {viewer?.name ?? "…"} · looking at {focus?.name ?? "everyone"}</small></div></div>
          <Wave mode={mode} level={level} />
          <div className="live-log" ref={logRef}>
            {rows.length === 0 && <div className="live-empty">Talk or type. I'm the assistant — I never grant.</div>}
            {rows.map((m, i) => m.kind === "tool"
              ? <div className="live-msg tool" key={i}><b>⚙</b><span>used {m.text}</span></div>
              : <div key={i} className={`live-msg ${m.kind}`}><b>{m.kind === "you" ? viewer?.short ?? "you" : "G"}</b><span>{m.text}</span></div>)}
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
            <button className={`nb mic ${micOn ? "on" : ""}`} title={micOn ? "Stop" : "Talk"} aria-label={micOn ? "Stop live conversation" : "Start live conversation"} aria-pressed={micOn} onClick={toggleMic}>●</button>
            <input id="live-text" autoFocus value={msg} onChange={(e) => setMsg(e.target.value)} onKeyDown={(e) => e.key === "Enter" && send(msg)} placeholder={micOn ? "Talk — I'll wait until you pause" : "Who is waiting on me?"} />
            <button className="nb" onClick={() => send(msg)} disabled={mode === "thinking" || !msg.trim()}>Send</button>
          </div>
        </div>
      )}
    </>
  );
}
