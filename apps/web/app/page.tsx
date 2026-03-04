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
  | { type: "meta"; user_id: string; session_id: string; persona_id: string; state: EmotionalState }
  | {
      type: "done";
      message: string;
      user_id: string;
      session_id: string;
      persona_id: string;
      state: EmotionalState;
      latency_ms?: number;
      first_token_ms?: number;
      chunk_count?: number;
    }
  | { type: "token"; delta: string }
  | { type: "error"; message: string };

type PersonaOption = {
  id: string;
  name: string;
  description: string;
  is_default: boolean;
  temperature: number;
};

const USER_ID_KEY = "personabot.user_id";
const SESSION_ID_KEY = "personabot.session_id";
const PERSONA_ID_KEY = "personabot.persona_id";
const MAX_RECONNECT_ATTEMPTS = 8;

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

function resolveApiHttpBase(wsUrl: string): string {
  const explicit = process.env.NEXT_PUBLIC_API_HTTP_URL;
  if (explicit) {
    return explicit;
  }

  if (wsUrl.startsWith("wss://")) {
    const withoutProtocol = wsUrl.slice("wss://".length);
    const host = withoutProtocol.split("/")[0];
    return `https://${host}`;
  }
  if (wsUrl.startsWith("ws://")) {
    const withoutProtocol = wsUrl.slice("ws://".length);
    const host = withoutProtocol.split("/")[0];
    return `http://${host}`;
  }
  return "http://localhost:8000";
}

export default function HomePage() {
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimerRef = useRef<number | null>(null);
  const activeAssistantIdRef = useRef<string | null>(null);
  const reconnectAttemptRef = useRef(0);

  const wsUrl = useMemo(resolveWsUrl, []);
  const apiHttpBase = useMemo(() => resolveApiHttpBase(wsUrl), [wsUrl]);

  const [messages, setMessages] = useState<ChatUiMessage[]>([]);
  const [input, setInput] = useState("");
  const [connected, setConnected] = useState(false);
  const [isAwaitingReply, setIsAwaitingReply] = useState(false);
  const [userId, setUserId] = useState<string | null>(null);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [personas, setPersonas] = useState<PersonaOption[]>([]);
  const [selectedPersonaId, setSelectedPersonaId] = useState("balanced");
  const [personaLoadError, setPersonaLoadError] = useState<string | null>(null);
  const [state, setState] = useState<EmotionalState | null>(null);
  const [socketVersion, setSocketVersion] = useState(0);
  const [retryLabel, setRetryLabel] = useState<string | null>(null);
  const [retryPaused, setRetryPaused] = useState(false);

  useEffect(() => {
    const savedUserId = window.localStorage.getItem(USER_ID_KEY);
    const savedSessionId = window.localStorage.getItem(SESSION_ID_KEY);
    const savedPersonaId = window.localStorage.getItem(PERSONA_ID_KEY);
    if (savedUserId) {
      setUserId(savedUserId);
    }
    if (savedSessionId) {
      setSessionId(savedSessionId);
    }
    if (savedPersonaId) {
      setSelectedPersonaId(savedPersonaId);
    }
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    async function loadPersonas() {
      try {
        setPersonaLoadError(null);
        const response = await fetch(`${apiHttpBase}/personas`, { signal: controller.signal });
        if (!response.ok) {
          throw new Error(`request failed (${response.status})`);
        }
        const payload = (await response.json()) as PersonaOption[];
        setPersonas(payload);

        const savedPersonaId = window.localStorage.getItem(PERSONA_ID_KEY);
        const hasSaved = savedPersonaId && payload.some((persona) => persona.id === savedPersonaId);
        if (hasSaved) {
          setSelectedPersonaId(savedPersonaId as string);
          return;
        }

        const defaultPersona = payload.find((persona) => persona.is_default) ?? payload[0];
        if (defaultPersona) {
          setSelectedPersonaId(defaultPersona.id);
          window.localStorage.setItem(PERSONA_ID_KEY, defaultPersona.id);
        }
      } catch {
        if (!controller.signal.aborted) {
          setPersonaLoadError("could not load personas");
        }
      }
    }

    void loadPersonas();
    return () => controller.abort();
  }, [apiHttpBase]);

  useEffect(() => {
    window.localStorage.setItem(PERSONA_ID_KEY, selectedPersonaId);
  }, [selectedPersonaId]);

  useEffect(() => {
    let effectActive = true;
    if (reconnectTimerRef.current) {
      window.clearTimeout(reconnectTimerRef.current);
      reconnectTimerRef.current = null;
    }

    setRetryLabel("connecting...");
    const socket = new WebSocket(wsUrl);
    wsRef.current = socket;

    socket.onopen = () => {
      if (!effectActive) {
        return;
      }
      reconnectAttemptRef.current = 0;
      setConnected(true);
      setRetryPaused(false);
      setRetryLabel(null);
      if (reconnectTimerRef.current) {
        window.clearTimeout(reconnectTimerRef.current);
        reconnectTimerRef.current = null;
      }
      setMessages((prev) => [
        ...prev,
        { id: makeId(), role: "system", text: "Socket connected." }
      ]);
    };

    socket.onmessage = (event) => {
      if (!effectActive) {
        return;
      }
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
        setSelectedPersonaId(parsed.persona_id);
        setState(parsed.state);
        window.localStorage.setItem(USER_ID_KEY, parsed.user_id);
        window.localStorage.setItem(SESSION_ID_KEY, parsed.session_id);
        window.localStorage.setItem(PERSONA_ID_KEY, parsed.persona_id);
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
        setSelectedPersonaId(parsed.persona_id);
        setState(parsed.state);
        window.localStorage.setItem(USER_ID_KEY, parsed.user_id);
        window.localStorage.setItem(SESSION_ID_KEY, parsed.session_id);
        window.localStorage.setItem(PERSONA_ID_KEY, parsed.persona_id);

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
      if (wsRef.current === socket) {
        wsRef.current = null;
      }
      if (!effectActive) {
        return;
      }

      setConnected(false);
      setIsAwaitingReply(false);
      setMessages((prev) => [...prev, { id: makeId(), role: "system", text: "Socket disconnected." }]);
      reconnectAttemptRef.current += 1;
      if (reconnectAttemptRef.current > MAX_RECONNECT_ATTEMPTS) {
        setRetryPaused(true);
        setRetryLabel("auto reconnect paused");
        setMessages((prev) => [
          ...prev,
          {
            id: makeId(),
            role: "system",
            text: "Backend still offline. Click reconnect after your API server is running."
          }
        ]);
        return;
      }

      const delayMs = Math.min(1000 * 2 ** (reconnectAttemptRef.current - 1), 10000);
      setRetryLabel(
        `retrying in ${(delayMs / 1000).toFixed(1)}s (${reconnectAttemptRef.current}/${MAX_RECONNECT_ATTEMPTS})`
      );
      reconnectTimerRef.current = window.setTimeout(() => {
        if (!effectActive) {
          return;
        }
        setSocketVersion((prev) => prev + 1);
      }, delayMs);
    };

    return () => {
      effectActive = false;
      if (reconnectTimerRef.current) {
        window.clearTimeout(reconnectTimerRef.current);
        reconnectTimerRef.current = null;
      }
      if (wsRef.current === socket) {
        wsRef.current = null;
      }
      socket.close();
    };
  }, [socketVersion, wsUrl]);

  function handleManualReconnect() {
    if (connected) {
      return;
    }
    if (reconnectTimerRef.current) {
      window.clearTimeout(reconnectTimerRef.current);
    }
    reconnectAttemptRef.current = 0;
    setRetryPaused(false);
    setRetryLabel("connecting...");
    setSocketVersion((prev) => prev + 1);
  }

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
        session_id: sessionId ?? undefined,
        persona_id: selectedPersonaId
      })
    );
  }

  const selectedPersona =
    personas.find((persona) => persona.id === selectedPersonaId) ??
    ({ id: selectedPersonaId, name: selectedPersonaId, description: "", is_default: false, temperature: 0.6 } as PersonaOption);

  return (
    <main className="page">
      <section className="shell">
        <header className="topbar">
          <div>
            <h1>PersonaBot</h1>
            <p className="subtext">Stateful streaming chat with memory context.</p>
          </div>
          <div className="statusWrap">
            <div className={`status ${connected ? "up" : "down"}`}>{connected ? "connected" : "offline"}</div>
            {!connected ? (
              <button type="button" className="reconnectBtn" onClick={handleManualReconnect}>
                reconnect
              </button>
            ) : null}
          </div>
        </header>
        {!connected && retryLabel ? (
          <p className="retryInfo">
            {retryLabel}
            {retryPaused ? "." : ""}
          </p>
        ) : null}

        <section className="personaBar">
          <label htmlFor="persona-select">persona</label>
          <select
            id="persona-select"
            value={selectedPersonaId}
            onChange={(event) => setSelectedPersonaId(event.target.value)}
          >
            {personas.length === 0 ? <option value={selectedPersonaId}>{selectedPersona.name}</option> : null}
            {personas.map((persona) => (
              <option key={persona.id} value={persona.id}>
                {persona.name}
              </option>
            ))}
          </select>
          <p className="personaHint">
            {personaLoadError ? personaLoadError : selectedPersona.description || "persona controls style and tone"}
          </p>
        </section>

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
          <p>
            <strong>persona:</strong> {selectedPersona.name}
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
