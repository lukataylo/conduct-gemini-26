import { useEffect, useState } from "react";
import type { AgentTurnOut, User } from "./api";
import { ALL, postAgentTurn } from "./api";

type Row =
  | { kind: "user"; text: string }
  | { kind: "agent"; text: string }
  | { kind: "tool"; name: string };

interface Props {
  selected: string;
  users: User[];
  online: boolean;
}

export function Composer({ selected, users, online }: Props) {
  const me = users.find((u) => u.id === selected);
  const [text, setText] = useState("");
  const [rows, setRows] = useState<Row[]>([]);
  const [cid, setCid] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [pending, setPending] = useState<AgentTurnOut | null>(null);
  const locked = !online || busy || selected === ALL || !me;

  useEffect(() => {
    setText("");
    setRows([]);
    setCid(null);
    setPending(null);
  }, [selected]);

  const applyTurn = (turn: AgentTurnOut) => {
    setCid(turn.conversation_id);
    for (const name of turn.tools_used) {
      setRows((r) => [...r, { kind: "tool", name }]);
    }
    if (turn.reply) setRows((r) => [...r, { kind: "agent", text: turn.reply }]);
    if (turn.request_result?.status === "needs_confirmation") setPending(turn);
    else setPending(null);
  };

  const send = async () => {
    if (locked || !text.trim() || !me) return;
    const message = text.trim();
    setText("");
    setRows((r) => [...r, { kind: "user", text: message }]);
    setBusy(true);
    try {
      applyTurn(await postAgentTurn({ viewer_id: me.id, message, conversation_id: cid }));
    } catch (e) {
      setRows((r) => [...r, { kind: "agent", text: String(e) }]);
    } finally {
      setBusy(false);
    }
  };

  const confirm = async () => {
    if (!me || !pending) return;
    setBusy(true);
    try {
      applyTurn(
        await postAgentTurn({
          viewer_id: me.id,
          message: pending.request_result?.preview?.raw_text || "confirm",
          conversation_id: pending.conversation_id,
          confirm: true,
        }),
      );
    } catch (e) {
      setRows((r) => [...r, { kind: "agent", text: String(e) }]);
    } finally {
      setBusy(false);
    }
  };

  const preview = pending?.request_result?.preview;

  return (
    <aside className="dock" aria-label="Conversation">
      <div className="dock-h">
        <h2>Chat</h2>
        <span className="dock-sub">{me ? me.name : "Pick a person"}</span>
      </div>
      <div className="dock-log">
        {rows.length === 0 && (
          <div className="dock-empty">Ask for access, or what you already have.</div>
        )}
        {rows.map((row, i) =>
          row.kind === "tool" ? (
            <div className="dock-row tool" key={i}>
              agent used {row.name}
            </div>
          ) : (
            <div className={`dock-row ${row.kind}`} key={i}>
              <b>{row.kind === "user" ? "you" : "agent"}</b>
              <span>{row.text}</span>
            </div>
          ),
        )}
        {preview && (
          <div className="confirm-card" role="region" aria-label="Confirm access request">
            <div className="confirm-k">confirm request</div>
            <div><span className="k">resources</span> {preview.resource_ids.join(", ") || "—"}</div>
            <div><span className="k">duration</span> {preview.requested_duration_days}d</div>
            <div><span className="k">project</span> {preview.project}</div>
            <button className="nb go" disabled={locked} onClick={confirm}>
              {busy ? "…" : "Confirm"}
            </button>
          </div>
        )}
      </div>
      <div className="composer">
        <textarea
          rows={3}
          value={text}
          placeholder="Need read on analytics-raw for two weeks…"
          disabled={locked}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              void send();
            }
          }}
        />
        <button className="nb" disabled={locked || !text.trim()} onClick={() => void send()}>
          {busy ? "…" : "Send"}
        </button>
      </div>
    </aside>
  );
}
