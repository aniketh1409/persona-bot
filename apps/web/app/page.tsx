"use client";

import { FormEvent, KeyboardEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";

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

type SessionItem = {
  id: string;
  persona_id: string;
  message_count: number;
  created_at: string;
  last_active_at: string;
  preview: string;
};

const USER_ID_KEY = "personabot.user_id";
const SESSION_ID_KEY = "personabot.session_id";
const PERSONA_ID_KEY = "personabot.persona_id";
const THEME_KEY = "personabot.theme";
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

/** Split a message into paragraph-level segments for multi-bubble rendering. */
function splitIntoBubbles(text: string): string[] {
  if (!text) return [text];
  const parts = text.split(/\n{2,}/);
  const result = parts.map((p) => p.trim()).filter((p) => p.length > 0);
  return result.length > 0 ? result : [text];
}

export default function HomePage() {
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimerRef = useRef<number | null>(null);
  const activeAssistantIdRef = useRef<string | null>(null);
  const reconnectAttemptRef = useRef(0);
  const timelineRef = useRef<HTMLElement | null>(null);

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
  const [sessionList, setSessionList] = useState<SessionItem[]>([]);
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [theme, setTheme] = useState<"light" | "dark">("light");

  // --- Theme ---
  useEffect(() => {
    const saved = window.localStorage.getItem(THEME_KEY);
    if (saved === "dark" || saved === "light") {
      setTheme(saved);
    } else if (window.matchMedia("(prefers-color-scheme: dark)").matches) {
      setTheme("dark");
    }
  }, []);

  useEffect(() => {
    document.documentElement.setAttribute("data-theme", theme);
    window.localStorage.setItem(THEME_KEY, theme);
  }, [theme]);

  function toggleTheme() {
    setTheme((prev) => (prev === "light" ? "dark" : "light"));
  }

  // --- Scroll to bottom ---
  useEffect(() => {
    const el = timelineRef.current;
    if (el) {
      el.scrollTop = el.scrollHeight;
    }
  }, [messages]);

  // --- Restore IDs from localStorage ---
  useEffect(() => {
    const savedUserId = window.localStorage.getItem(USER_ID_KEY);
    const savedSessionId = window.localStorage.getItem(SESSION_ID_KEY);
    const savedPersonaId = window.localStorage.getItem(PERSONA_ID_KEY);
    if (savedUserId) setUserId(savedUserId);
    if (savedSessionId) setSessionId(savedSessionId);
    if (savedPersonaId) setSelectedPersonaId(savedPersonaId);
  }, []);

  // --- Load history for current session ---
  const loadSessionHistory = useCallback(
    async (sid: string) => {
      try {
        const response = await fetch(`${apiHttpBase}/history/${sid}?limit=50`);
        if (!response.ok) return;
        const events = (await response.json()) as { role: string; message: string; created_at: string }[];
        if (events.length === 0) return;
        const restored: ChatUiMessage[] = events.map((event) => ({
          id: makeId(),
          role: event.role as Role,
          text: event.message,
        }));
        setMessages(restored);
      } catch {
        // best-effort
      }
    },
    [apiHttpBase],
  );

  // --- Load history on mount ---
  useEffect(() => {
    const savedSessionId = window.localStorage.getItem(SESSION_ID_KEY);
    if (!savedSessionId) return;
    void loadSessionHistory(savedSessionId);
  }, [loadSessionHistory]);

  // --- Load personas ---
  useEffect(() => {
    const controller = new AbortController();
    async function loadPersonas() {
      try {
        setPersonaLoadError(null);
        const response = await fetch(`${apiHttpBase}/personas`, { signal: controller.signal });
        if (!response.ok) throw new Error(`request failed (${response.status})`);
        const payload = (await response.json()) as PersonaOption[];
        setPersonas(payload);

        const savedPersonaId = window.localStorage.getItem(PERSONA_ID_KEY);
        const hasSaved = savedPersonaId && payload.some((p) => p.id === savedPersonaId);
        if (hasSaved) {
          setSelectedPersonaId(savedPersonaId as string);
          return;
        }

        const defaultPersona = payload.find((p) => p.is_default) ?? payload[0];
        if (defaultPersona) {
          setSelectedPersonaId(defaultPersona.id);
          window.localStorage.setItem(PERSONA_ID_KEY, defaultPersona.id);
        }
      } catch {
        if (!controller.signal.aborted) setPersonaLoadError("could not load personas");
      }
    }
    void loadPersonas();
    return () => controller.abort();
  }, [apiHttpBase]);

  // --- Persist persona selection ---
  useEffect(() => {
    window.localStorage.setItem(PERSONA_ID_KEY, selectedPersonaId);
  }, [selectedPersonaId]);

  // --- Load session list ---
  const loadSessionList = useCallback(async () => {
    const uid = userId || window.localStorage.getItem(USER_ID_KEY);
    if (!uid) return;
    try {
      const response = await fetch(`${apiHttpBase}/sessions/${uid}`);
      if (!response.ok) return;
      const payload = (await response.json()) as SessionItem[];
      setSessionList(payload);
    } catch {
      // best-effort
    }
  }, [apiHttpBase, userId]);

  useEffect(() => {
    void loadSessionList();
  }, [loadSessionList]);

  // --- WebSocket lifecycle ---
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
      if (!effectActive) return;
      reconnectAttemptRef.current = 0;
      setConnected(true);
      setRetryPaused(false);
      setRetryLabel(null);
      if (reconnectTimerRef.current) {
        window.clearTimeout(reconnectTimerRef.current);
        reconnectTimerRef.current = null;
      }
    };

    socket.onmessage = (event) => {
      if (!effectActive) return;
      let parsed: ServerEvent;
      try {
        parsed = JSON.parse(event.data) as ServerEvent;
      } catch {
        return;
      }

      if (parsed.type === "system") {
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
        if (!assistantId) return;
        setMessages((prev) =>
          prev.map((item) =>
            item.id === assistantId ? { ...item, text: `${item.text}${parsed.delta}`, streaming: true } : item,
          ),
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
                    chunkCount: parsed.chunk_count,
                  }
                : item,
            ),
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
              chunkCount: parsed.chunk_count,
            },
          ]);
        }

        activeAssistantIdRef.current = null;
        setIsAwaitingReply(false);
        // refresh session list after a reply completes
        void loadSessionList();
        return;
      }

      if (parsed.type === "error") {
        setMessages((prev) => [...prev, { id: makeId(), role: "system", text: `Error: ${parsed.message}` }]);
        const assistantId = activeAssistantIdRef.current;
        if (assistantId) {
          setMessages((prev) =>
            prev.map((item) => (item.id === assistantId ? { ...item, streaming: false } : item)),
          );
        }
        activeAssistantIdRef.current = null;
        setIsAwaitingReply(false);
      }
    };

    socket.onclose = () => {
      if (wsRef.current === socket) wsRef.current = null;
      if (!effectActive) return;

      setConnected(false);
      setIsAwaitingReply(false);
      reconnectAttemptRef.current += 1;
      if (reconnectAttemptRef.current > MAX_RECONNECT_ATTEMPTS) {
        setRetryPaused(true);
        setRetryLabel("auto reconnect paused");
        return;
      }

      const delayMs = Math.min(1000 * 2 ** (reconnectAttemptRef.current - 1), 10000);
      setRetryLabel(
        `retrying in ${(delayMs / 1000).toFixed(1)}s (${reconnectAttemptRef.current}/${MAX_RECONNECT_ATTEMPTS})`,
      );
      reconnectTimerRef.current = window.setTimeout(() => {
        if (!effectActive) return;
        setSocketVersion((prev) => prev + 1);
      }, delayMs);
    };

    return () => {
      effectActive = false;
      if (reconnectTimerRef.current) {
        window.clearTimeout(reconnectTimerRef.current);
        reconnectTimerRef.current = null;
      }
      if (wsRef.current === socket) wsRef.current = null;
      socket.close();
    };
  }, [socketVersion, wsUrl, loadSessionList]);

  function handleManualReconnect() {
    if (connected) return;
    if (reconnectTimerRef.current) window.clearTimeout(reconnectTimerRef.current);
    reconnectAttemptRef.current = 0;
    setRetryPaused(false);
    setRetryLabel("connecting...");
    setSocketVersion((prev) => prev + 1);
  }

  function handleNewChat() {
    setSessionId(null);
    setState(null);
    setMessages([]);
    setInput("");
    setIsAwaitingReply(false);
    activeAssistantIdRef.current = null;
    window.localStorage.removeItem(SESSION_ID_KEY);
    setSidebarOpen(false);
  }

  async function handleSwitchSession(sid: string) {
    if (sid === sessionId) {
      setSidebarOpen(false);
      return;
    }
    setSessionId(sid);
    setState(null);
    setMessages([]);
    setInput("");
    setIsAwaitingReply(false);
    activeAssistantIdRef.current = null;
    window.localStorage.setItem(SESSION_ID_KEY, sid);
    setSidebarOpen(false);
    await loadSessionHistory(sid);
  }

  function handleKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      const form = event.currentTarget.form;
      if (form) form.requestSubmit();
    }
  }

  function handleSend(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();

    const message = input.trim();
    if (!message || isAwaitingReply) return;

    const socket = wsRef.current;
    if (!socket || socket.readyState !== WebSocket.OPEN) {
      setMessages((prev) => [
        ...prev,
        { id: makeId(), role: "system", text: "No active connection to backend." },
      ]);
      return;
    }

    const assistantId = makeId();
    activeAssistantIdRef.current = assistantId;

    setMessages((prev) => [
      ...prev,
      { id: makeId(), role: "user", text: message },
      { id: assistantId, role: "assistant", text: "", streaming: true },
    ]);
    setIsAwaitingReply(true);
    setInput("");

    socket.send(
      JSON.stringify({
        message,
        user_id: userId ?? undefined,
        session_id: sessionId ?? undefined,
        persona_id: selectedPersonaId,
      }),
    );
  }

  const selectedPersona =
    personas.find((p) => p.id === selectedPersonaId) ??
    ({ id: selectedPersonaId, name: selectedPersonaId, description: "", is_default: false, temperature: 0.6 } as PersonaOption);

  return (
    <main className="page">
      {/* Sidebar overlay */}
      {sidebarOpen ? <div className="sidebarOverlay" onClick={() => setSidebarOpen(false)} /> : null}

      {/* Session sidebar */}
      <aside className={`sidebar ${sidebarOpen ? "open" : ""}`}>
        <div className="sidebarHeader">
          <span className="sidebarTitle">Conversations</span>
          <button type="button" className="sidebarClose" onClick={() => setSidebarOpen(false)}>
            &times;
          </button>
        </div>
        <button type="button" className="sidebarNewChat" onClick={handleNewChat} disabled={!connected}>
          + New chat
        </button>
        <div className="sessionList">
          {sessionList.length === 0 ? (
            <p className="sessionEmpty">No conversations yet</p>
          ) : (
            sessionList.map((s) => (
              <button
                key={s.id}
                type="button"
                className={`sessionItem ${s.id === sessionId ? "active" : ""}`}
                onClick={() => void handleSwitchSession(s.id)}
              >
                <span className="sessionPreview">{s.preview}</span>
                <span className="sessionMeta">
                  {s.message_count} msgs &middot; {new Date(s.last_active_at).toLocaleDateString()}
                </span>
              </button>
            ))
          )}
        </div>
      </aside>

      <section className="shell">
        <header className="topbar">
          <div className="topbarLeft">
            <button type="button" className="menuBtn" onClick={() => { void loadSessionList(); setSidebarOpen(true); }}>
              <span className="menuIcon">&#9776;</span>
            </button>
            <div>
              <h1>PersonaBot</h1>
            </div>
          </div>
          <div className="statusWrap">
            <button type="button" className="themeToggle" onClick={toggleTheme} title="Toggle dark mode">
              {theme === "light" ? "\u263E" : "\u2600"}
            </button>
            <button type="button" className="newChatBtn" onClick={handleNewChat} disabled={!connected}>
              + new chat
            </button>
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

        <section className="controlsRow">
          <div className="personaBar">
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
          </div>
          <div className="metaBar">
            <span>mood: {state?.current_mood ?? "neutral"}</span>
            <span>trust: {state?.trust?.toFixed(2) ?? "0.50"}</span>
            <span>energy: {state?.energy?.toFixed(2) ?? "0.60"}</span>
          </div>
        </section>

        <section className="timeline" aria-live="polite" ref={timelineRef}>
          {messages.length === 0 ? (
            <p className="placeholder">Send a message to start a conversation.</p>
          ) : (
            messages.map((msg) => {
              // Split assistant messages into multiple bubbles
              if (msg.role === "assistant" && !msg.streaming && msg.text) {
                const parts = splitIntoBubbles(msg.text);
                if (parts.length > 1) {
                  return parts.map((part, i) => (
                    <article key={`${msg.id}-${i}`} className="bubble assistant">
                      <p>{part}</p>
                      {i === parts.length - 1 && (msg.latencyMs || msg.firstTokenMs || msg.chunkCount) ? (
                        <small>
                          {msg.firstTokenMs ? `${msg.firstTokenMs.toFixed(0)}ms first` : ""}{" "}
                          {msg.latencyMs ? `${msg.latencyMs.toFixed(0)}ms total` : ""}{" "}
                          {msg.chunkCount ? `${msg.chunkCount} chunks` : ""}
                        </small>
                      ) : null}
                    </article>
                  ));
                }
              }

              return (
                <article key={msg.id} className={`bubble ${msg.role}`}>
                  <p>{msg.text || (msg.streaming ? "..." : "")}</p>
                  {msg.role === "assistant" && !msg.streaming && (msg.latencyMs || msg.firstTokenMs || msg.chunkCount) ? (
                    <small>
                      {msg.firstTokenMs ? `${msg.firstTokenMs.toFixed(0)}ms first` : ""}{" "}
                      {msg.latencyMs ? `${msg.latencyMs.toFixed(0)}ms total` : ""}{" "}
                      {msg.chunkCount ? `${msg.chunkCount} chunks` : ""}
                    </small>
                  ) : null}
                </article>
              );
            })
          )}
          {isAwaitingReply ? <p className="typing">typing...</p> : null}
        </section>

        <form className="composer" onSubmit={handleSend}>
          <textarea
            value={input}
            onChange={(event) => setInput(event.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Say something... (Enter to send, Shift+Enter for new line)"
            rows={2}
            disabled={!connected || isAwaitingReply}
          />
          <button type="submit" disabled={!connected || isAwaitingReply || !input.trim()}>
            {isAwaitingReply ? "..." : "send"}
          </button>
        </form>
      </section>
    </main>
  );
}
