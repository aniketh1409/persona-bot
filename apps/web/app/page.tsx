"use client";

import { FormEvent, useEffect, useMemo, useRef, useState } from "react";

type Role = "user" | "assistant" | "system";

type EmotionalState = {
  current_mood: string;
  trust: number;
  affection: number;
  energy: number;
};

type ChatUiMessage = {
  id: string;
  role: Role;
  text: string;
  streaming?: boolean;
  latencyMs?: number;
  firstTokenMs?: number;
  chunkCount?: number;
};

type ServerEvent =
  | { type: "system"; message: string }
  | { type: "meta"; user_id: string; session_id: string; state: EmotionalState }
  | {
      type: "done";
      message: string;
      user_id: string;
      session_id: string;
      state: EmotionalState;
      latency_ms?: number;
      first_token_ms?: number;
      chunk_count?: number;
    }
  | { type: "token"; delta: string }
  | { type: "error"; message: string };

const USER_ID_KEY = "personabot.user_id";
const SESSION_ID_KEY = "personabot.session_id";

function makeId(): string {
  return `${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function resolveWsUrl(): string {
  const explicit = process.env.NEXT_PUBLIC_API_WS_URL;
  if (explicit) {
    return explicit;
  }
  return "ws://localhost:8000/ws/chat";
}

export default function HomePage() {
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimerRef = useRef<number | null>(null);
  const activeAssistantIdRef = useRef<string | null>(null);
  const shouldReconnectRef = useRef(true);

  const wsUrl = useMemo(resolveWsUrl, []);

  const [messages, setMessages] = useState<ChatUiMessage[]>([]);
  const [input, setInput] = useState("");
  const [connected, setConnected] = useState(false);
  const [isAwaitingReply, setIsAwaitingReply] = useState(false);
  const [userId, setUserId] = useState<string | null>(null);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [state, setState] = useState<EmotionalState | null>(null);
  const [socketVersion, setSocketVersion] = useState(0);

  useEffect(() => {
    const savedUserId = window.localStorage.getItem(USER_ID_KEY);
    const savedSessionId = window.localStorage.getItem(SESSION_ID_KEY);
    if (savedUserId) {
      setUserId(savedUserId);
    }
    if (savedSessionId) {
      setSessionId(savedSessionId);
    }
  }, []);

  useEffect(() => {
    shouldReconnectRef.current = true;
    const socket = new WebSocket(wsUrl);
    wsRef.current = socket;

    socket.onopen = () => {
      setConnected(true);
      setMessages((prev) => [
        ...prev,
        { id: makeId(), role: "system", text: "Socket connected." }
      ]);
    };

    socket.onmessage = (event) => {
      let parsed: ServerEvent;
      try {
        parsed = JSON.parse(event.data) as ServerEvent;
      } catch {
        return;
      }

      if (parsed.type === "system") {
        setMessages((prev) => [...prev, { id: makeId(), role: "system", text: parsed.message }]);
        return;
      }

      if (parsed.type === "meta") {
        setUserId(parsed.user_id);
        setSessionId(parsed.session_id);
        setState(parsed.state);
        window.localStorage.setItem(USER_ID_KEY, parsed.user_id);
        window.localStorage.setItem(SESSION_ID_KEY, parsed.session_id);
        return;
      }

      if (parsed.type === "token") {
        const assistantId = activeAssistantIdRef.current;
        if (!assistantId) {
          return;
        }
        setMessages((prev) =>
          prev.map((item) =>
            item.id === assistantId ? { ...item, text: `${item.text}${parsed.delta}`, streaming: true } : item
          )
        );
        return;
      }

      if (parsed.type === "done") {
        setUserId(parsed.user_id);
        setSessionId(parsed.session_id);
        setState(parsed.state);
        window.localStorage.setItem(USER_ID_KEY, parsed.user_id);
        window.localStorage.setItem(SESSION_ID_KEY, parsed.session_id);

        const assistantId = activeAssistantIdRef.current;
        if (assistantId) {
          setMessages((prev) =>
            prev.map((item) =>
              item.id === assistantId
                ? {
                    ...item,
                    text: parsed.message,
                    streaming: false,
                    latencyMs: parsed.latency_ms,
                    firstTokenMs: parsed.first_token_ms,
                    chunkCount: parsed.chunk_count
                  }
                : item
            )
          );
        } else {
          setMessages((prev) => [
            ...prev,
            {
              id: makeId(),
              role: "assistant",
              text: parsed.message,
              latencyMs: parsed.latency_ms,
              firstTokenMs: parsed.first_token_ms,
              chunkCount: parsed.chunk_count
            }
          ]);
        }

        activeAssistantIdRef.current = null;
        setIsAwaitingReply(false);
        return;
      }

      if (parsed.type === "error") {
        setMessages((prev) => [...prev, { id: makeId(), role: "system", text: `Error: ${parsed.message}` }]);
        const assistantId = activeAssistantIdRef.current;
        if (assistantId) {
          setMessages((prev) =>
            prev.map((item) => (item.id === assistantId ? { ...item, streaming: false } : item))
          );
        }
        activeAssistantIdRef.current = null;
        setIsAwaitingReply(false);
      }
    };

    socket.onclose = () => {
      wsRef.current = null;
      setConnected(false);
      setIsAwaitingReply(false);
      setMessages((prev) => [...prev, { id: makeId(), role: "system", text: "Socket disconnected." }]);
      if (shouldReconnectRef.current) {
        reconnectTimerRef.current = window.setTimeout(() => {
          setSocketVersion((prev) => prev + 1);
        }, 1200);
      }
    };

    return () => {
      shouldReconnectRef.current = false;
      if (reconnectTimerRef.current) {
        window.clearTimeout(reconnectTimerRef.current);
      }
      socket.close();
    };
  }, [socketVersion, wsUrl]);

  function handleSend(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();

    const message = input.trim();
    if (!message || isAwaitingReply) {
      return;
    }

    const socket = wsRef.current;
    if (!socket || socket.readyState !== WebSocket.OPEN) {
      setMessages((prev) => [
        ...prev,
        { id: makeId(), role: "system", text: "No active connection to backend." }
      ]);
      return;
    }

    const assistantId = makeId();
    activeAssistantIdRef.current = assistantId;

    setMessages((prev) => [
      ...prev,
      { id: makeId(), role: "user", text: message },
      { id: assistantId, role: "assistant", text: "", streaming: true }
    ]);
    setIsAwaitingReply(true);
    setInput("");

    socket.send(
      JSON.stringify({
        message,
        user_id: userId ?? undefined,
        session_id: sessionId ?? undefined
      })
    );
  }

  return (
    <main className="page">
      <section className="shell">
        <header className="topbar">
          <div>
            <h1>PersonaBot</h1>
            <p className="subtext">Stateful streaming chat with memory context.</p>
          </div>
          <div className={`status ${connected ? "up" : "down"}`}>{connected ? "connected" : "offline"}</div>
        </header>

        <section className="meta">
          <p>
            <strong>user:</strong> {userId ?? "new"}
          </p>
          <p>
            <strong>session:</strong> {sessionId ?? "new"}
          </p>
          <p>
            <strong>mood:</strong> {state?.current_mood ?? "neutral"}
          </p>
        </section>

        <section className="timeline" aria-live="polite">
          {messages.length === 0 ? (
            <p className="placeholder">Send a message to start the stream.</p>
          ) : (
            messages.map((msg) => (
              <article key={msg.id} className={`bubble ${msg.role}`}>
                <p>{msg.text || (msg.streaming ? "..." : "")}</p>
                {msg.role === "assistant" && (msg.latencyMs || msg.firstTokenMs || msg.chunkCount) ? (
                  <small>
                    {msg.firstTokenMs ? `first token ${msg.firstTokenMs.toFixed(0)}ms` : "first token n/a"} |{" "}
                    {msg.latencyMs ? `done ${msg.latencyMs.toFixed(0)}ms` : "done n/a"} |{" "}
                    {msg.chunkCount ?? 0} chunks
                  </small>
                ) : null}
              </article>
            ))
          )}
          {isAwaitingReply ? <p className="typing">assistant is typing...</p> : null}
        </section>

        <form className="composer" onSubmit={handleSend}>
          <textarea
            value={input}
            onChange={(event) => setInput(event.target.value)}
            placeholder="Say something..."
            rows={3}
            disabled={!connected || isAwaitingReply}
          />
          <button type="submit" disabled={!connected || isAwaitingReply || !input.trim()}>
            {isAwaitingReply ? "waiting..." : "send"}
          </button>
        </form>
      </section>
    </main>
  );
}
