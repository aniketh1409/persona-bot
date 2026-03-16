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
  | { type: "meta"; user_id: string; session_id: string; character_id: string; persona_id: string; state: EmotionalState; tier: number; tier_label: string }
  | {
      type: "done";
      message: string;
      user_id: string;
      session_id: string;
      character_id: string;
      state: EmotionalState;
      tier: number;
      tier_label: string;
      latency_ms?: number;
      first_token_ms?: number;
      chunk_count?: number;
    }
  | { type: "token"; delta: string }
  | { type: "error"; message: string };

type CharacterOption = {
  id: string;
  name: string;
  archetype: string | null;
  description: string;
  temperature: number;
  is_default: boolean;
};

type SessionItem = {
  id: string;
  character_id: string | null;
  persona_id: string | null;
  message_count: number;
  created_at: string;
  last_active_at: string;
  preview: string;
};

const USER_ID_KEY = "personabot.user_id";
const SESSION_ID_KEY = "personabot.session_id";
const CHARACTER_ID_KEY = "personabot.character_id";
const THEME_KEY = "personabot.theme";
const MAX_RECONNECT_ATTEMPTS = 8;

const TIER_LABELS: Record<number, string> = {
  1: "Stranger",
  2: "Acquaintance",
  3: "Companion",
  4: "Confidant",
  5: "Bonded",
};

function makeId(): string {
  return `${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function resolveWsUrl(): string {
  return process.env.NEXT_PUBLIC_API_WS_URL || "ws://localhost:8000/ws/chat";
}

function resolveApiHttpBase(wsUrl: string): string {
  const explicit = process.env.NEXT_PUBLIC_API_HTTP_URL;
  if (explicit) return explicit;
  if (wsUrl.startsWith("wss://")) return `https://${wsUrl.slice(6).split("/")[0]}`;
  if (wsUrl.startsWith("ws://")) return `http://${wsUrl.slice(5).split("/")[0]}`;
  return "http://localhost:8000";
}

function splitIntoBubbles(text: string): string[] {
  if (!text) return [text];
  const parts = text.split(/\n{2,}/).map((p) => p.trim()).filter((p) => p.length > 0);
  return parts.length > 0 ? parts : [text];
}

function tierProgress(trust: number): number {
  return Math.min(100, Math.max(0, trust * 100));
}

// ============================================================================
// Main component
// ============================================================================

export default function HomePage() {
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimerRef = useRef<number | null>(null);
  const activeAssistantIdRef = useRef<string | null>(null);
  const reconnectAttemptRef = useRef(0);
  const timelineRef = useRef<HTMLElement | null>(null);

  const wsUrl = useMemo(resolveWsUrl, []);
  const apiHttpBase = useMemo(() => resolveApiHttpBase(wsUrl), [wsUrl]);

  // -- State --
  const [messages, setMessages] = useState<ChatUiMessage[]>([]);
  const [input, setInput] = useState("");
  const [connected, setConnected] = useState(false);
  const [isAwaitingReply, setIsAwaitingReply] = useState(false);
  const [userId, setUserId] = useState<string | null>(null);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [characters, setCharacters] = useState<CharacterOption[]>([]);
  const [selectedCharacterId, setSelectedCharacterId] = useState<string | null>(null);
  const [state, setState] = useState<EmotionalState | null>(null);
  const [tier, setTier] = useState(1);
  const [tierLabel, setTierLabel] = useState("Stranger");
  const [socketVersion, setSocketVersion] = useState(0);
  const [retryLabel, setRetryLabel] = useState<string | null>(null);
  const [retryPaused, setRetryPaused] = useState(false);
  const [sessionList, setSessionList] = useState<SessionItem[]>([]);
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [theme, setTheme] = useState<"light" | "dark">("light");
  const [view, setView] = useState<"select" | "chat">("select");

  // -- Theme --
  useEffect(() => {
    const saved = window.localStorage.getItem(THEME_KEY);
    if (saved === "dark" || saved === "light") setTheme(saved);
    else if (window.matchMedia("(prefers-color-scheme: dark)").matches) setTheme("dark");
  }, []);

  useEffect(() => {
    document.documentElement.setAttribute("data-theme", theme);
    window.localStorage.setItem(THEME_KEY, theme);
  }, [theme]);

  // -- Scroll --
  useEffect(() => {
    const el = timelineRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [messages]);

  // -- Restore from localStorage --
  useEffect(() => {
    const savedUserId = window.localStorage.getItem(USER_ID_KEY);
    const savedSessionId = window.localStorage.getItem(SESSION_ID_KEY);
    const savedCharId = window.localStorage.getItem(CHARACTER_ID_KEY);
    if (savedUserId) setUserId(savedUserId);
    if (savedSessionId) setSessionId(savedSessionId);
    if (savedCharId) {
      setSelectedCharacterId(savedCharId);
      setView("chat");
    }
  }, []);

  // -- Load history --
  const loadSessionHistory = useCallback(async (sid: string) => {
    try {
      const response = await fetch(`${apiHttpBase}/history/${sid}?limit=50`);
      if (!response.ok) return;
      const events = (await response.json()) as { role: string; message: string }[];
      if (events.length === 0) return;
      setMessages(events.map((e) => ({ id: makeId(), role: e.role as Role, text: e.message })));
    } catch { /* best-effort */ }
  }, [apiHttpBase]);

  useEffect(() => {
    const sid = window.localStorage.getItem(SESSION_ID_KEY);
    if (sid) void loadSessionHistory(sid);
  }, [loadSessionHistory]);

  // -- Load characters --
  useEffect(() => {
    const controller = new AbortController();
    async function load() {
      try {
        const res = await fetch(`${apiHttpBase}/characters`, { signal: controller.signal });
        if (!res.ok) return;
        setCharacters((await res.json()) as CharacterOption[]);
      } catch { /* ignore */ }
    }
    void load();
    return () => controller.abort();
  }, [apiHttpBase]);

  // -- Load sessions --
  const loadSessionList = useCallback(async () => {
    const uid = userId || window.localStorage.getItem(USER_ID_KEY);
    if (!uid) return;
    try {
      const res = await fetch(`${apiHttpBase}/sessions/${uid}`);
      if (!res.ok) return;
      setSessionList((await res.json()) as SessionItem[]);
    } catch { /* */ }
  }, [apiHttpBase, userId]);

  useEffect(() => { void loadSessionList(); }, [loadSessionList]);

  // -- WebSocket --
  useEffect(() => {
    let active = true;
    if (reconnectTimerRef.current) { window.clearTimeout(reconnectTimerRef.current); reconnectTimerRef.current = null; }
    setRetryLabel("connecting...");
    const socket = new WebSocket(wsUrl);
    wsRef.current = socket;

    socket.onopen = () => {
      if (!active) return;
      reconnectAttemptRef.current = 0;
      setConnected(true); setRetryPaused(false); setRetryLabel(null);
      if (reconnectTimerRef.current) { window.clearTimeout(reconnectTimerRef.current); reconnectTimerRef.current = null; }
    };

    socket.onmessage = (event) => {
      if (!active) return;
      let parsed: ServerEvent;
      try { parsed = JSON.parse(event.data) as ServerEvent; } catch { return; }

      if (parsed.type === "system") return;

      if (parsed.type === "meta") {
        setUserId(parsed.user_id); setSessionId(parsed.session_id);
        setSelectedCharacterId(parsed.character_id);
        setState(parsed.state); setTier(parsed.tier); setTierLabel(parsed.tier_label);
        window.localStorage.setItem(USER_ID_KEY, parsed.user_id);
        window.localStorage.setItem(SESSION_ID_KEY, parsed.session_id);
        window.localStorage.setItem(CHARACTER_ID_KEY, parsed.character_id);
        return;
      }

      if (parsed.type === "token") {
        const aid = activeAssistantIdRef.current;
        if (!aid) return;
        setMessages((prev) => prev.map((m) => m.id === aid ? { ...m, text: `${m.text}${parsed.delta}`, streaming: true } : m));
        return;
      }

      if (parsed.type === "done") {
        setUserId(parsed.user_id); setSessionId(parsed.session_id);
        setSelectedCharacterId(parsed.character_id);
        setState(parsed.state); setTier(parsed.tier); setTierLabel(parsed.tier_label);
        window.localStorage.setItem(USER_ID_KEY, parsed.user_id);
        window.localStorage.setItem(SESSION_ID_KEY, parsed.session_id);
        window.localStorage.setItem(CHARACTER_ID_KEY, parsed.character_id);

        const aid = activeAssistantIdRef.current;
        if (aid) {
          setMessages((prev) => prev.map((m) => m.id === aid ? { ...m, text: parsed.message, streaming: false, latencyMs: parsed.latency_ms, firstTokenMs: parsed.first_token_ms, chunkCount: parsed.chunk_count } : m));
        }
        activeAssistantIdRef.current = null;
        setIsAwaitingReply(false);
        void loadSessionList();
        return;
      }

      if (parsed.type === "error") {
        setMessages((prev) => [...prev, { id: makeId(), role: "system", text: `Error: ${parsed.message}` }]);
        if (activeAssistantIdRef.current) {
          setMessages((prev) => prev.map((m) => m.id === activeAssistantIdRef.current ? { ...m, streaming: false } : m));
        }
        activeAssistantIdRef.current = null;
        setIsAwaitingReply(false);
      }
    };

    socket.onclose = () => {
      if (wsRef.current === socket) wsRef.current = null;
      if (!active) return;
      setConnected(false); setIsAwaitingReply(false);
      reconnectAttemptRef.current += 1;
      if (reconnectAttemptRef.current > MAX_RECONNECT_ATTEMPTS) { setRetryPaused(true); setRetryLabel("auto reconnect paused"); return; }
      const delay = Math.min(1000 * 2 ** (reconnectAttemptRef.current - 1), 10000);
      setRetryLabel(`retrying in ${(delay / 1000).toFixed(1)}s (${reconnectAttemptRef.current}/${MAX_RECONNECT_ATTEMPTS})`);
      reconnectTimerRef.current = window.setTimeout(() => { if (active) setSocketVersion((v) => v + 1); }, delay);
    };

    return () => {
      active = false;
      if (reconnectTimerRef.current) { window.clearTimeout(reconnectTimerRef.current); reconnectTimerRef.current = null; }
      if (wsRef.current === socket) wsRef.current = null;
      socket.close();
    };
  }, [socketVersion, wsUrl, loadSessionList]);

  // -- Handlers --
  function handleManualReconnect() {
    if (connected) return;
    if (reconnectTimerRef.current) window.clearTimeout(reconnectTimerRef.current);
    reconnectAttemptRef.current = 0; setRetryPaused(false); setRetryLabel("connecting...");
    setSocketVersion((v) => v + 1);
  }

  function handleSelectCharacter(charId: string) {
    setSelectedCharacterId(charId);
    setSessionId(null); setState(null); setMessages([]); setTier(1); setTierLabel("Stranger");
    window.localStorage.setItem(CHARACTER_ID_KEY, charId);
    window.localStorage.removeItem(SESSION_ID_KEY);
    setView("chat");
  }

  function handleNewChat() {
    setSessionId(null); setState(null); setMessages([]); setTier(1); setTierLabel("Stranger");
    setInput(""); setIsAwaitingReply(false); activeAssistantIdRef.current = null;
    window.localStorage.removeItem(SESSION_ID_KEY);
    setSidebarOpen(false);
  }

  function handleBackToSelect() {
    setView("select");
    setSelectedCharacterId(null); setSessionId(null); setState(null); setMessages([]);
    window.localStorage.removeItem(CHARACTER_ID_KEY);
    window.localStorage.removeItem(SESSION_ID_KEY);
  }

  async function handleSwitchSession(sid: string) {
    if (sid === sessionId) { setSidebarOpen(false); return; }
    setSessionId(sid); setState(null); setMessages([]); setInput("");
    setIsAwaitingReply(false); activeAssistantIdRef.current = null;
    window.localStorage.setItem(SESSION_ID_KEY, sid);
    setSidebarOpen(false);
    await loadSessionHistory(sid);
  }

  function handleKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      event.currentTarget.form?.requestSubmit();
    }
  }

  function handleSend(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const message = input.trim();
    if (!message || isAwaitingReply) return;
    const socket = wsRef.current;
    if (!socket || socket.readyState !== WebSocket.OPEN) return;

    const assistantId = makeId();
    activeAssistantIdRef.current = assistantId;
    setMessages((prev) => [
      ...prev,
      { id: makeId(), role: "user", text: message },
      { id: assistantId, role: "assistant", text: "", streaming: true },
    ]);
    setIsAwaitingReply(true); setInput("");

    socket.send(JSON.stringify({
      message,
      user_id: userId ?? undefined,
      session_id: sessionId ?? undefined,
      character_id: selectedCharacterId ?? undefined,
    }));
  }

  const selectedChar = characters.find((c) => c.id === selectedCharacterId);

  // ========================================================================
  // CHARACTER SELECT SCREEN
  // ========================================================================
  if (view === "select") {
    return (
      <main className="page">
        <section className="selectScreen">
          <header className="selectHeader">
            <div>
              <h1>PersonaBot RPG</h1>
              <p className="selectSubtext">Choose a character to begin.</p>
            </div>
            <div className="statusWrap">
              <button type="button" className="themeToggle" onClick={() => setTheme((t) => t === "light" ? "dark" : "light")} title="Toggle theme">
                {theme === "light" ? "\u263E" : "\u2600"}
              </button>
              <div className={`status ${connected ? "up" : "down"}`}>{connected ? "connected" : "offline"}</div>
              {!connected ? <button type="button" className="reconnectBtn" onClick={handleManualReconnect}>reconnect</button> : null}
            </div>
          </header>

          <div className="characterGrid">
            {characters.map((char) => (
              <button
                key={char.id}
                type="button"
                className="characterCard"
                onClick={() => handleSelectCharacter(char.id)}
                disabled={!connected}
              >
                <div className="charAvatar">{char.name[0]}</div>
                <h2 className="charName">{char.name}</h2>
                <p className="charArchetype">{char.archetype}</p>
                <p className="charDesc">{char.description}</p>
              </button>
            ))}
          </div>

          {!connected && retryLabel ? <p className="retryInfo">{retryLabel}</p> : null}
        </section>
      </main>
    );
  }

  // ========================================================================
  // CHAT VIEW
  // ========================================================================
  return (
    <main className="page">
      {sidebarOpen ? <div className="sidebarOverlay" onClick={() => setSidebarOpen(false)} /> : null}

      <aside className={`sidebar ${sidebarOpen ? "open" : ""}`}>
        <div className="sidebarHeader">
          <span className="sidebarTitle">Conversations</span>
          <button type="button" className="sidebarClose" onClick={() => setSidebarOpen(false)}>&times;</button>
        </div>
        <button type="button" className="sidebarNewChat" onClick={handleNewChat} disabled={!connected}>+ New chat</button>
        <div className="sessionList">
          {sessionList.filter((s) => s.character_id === selectedCharacterId).length === 0 ? (
            <p className="sessionEmpty">No conversations yet</p>
          ) : (
            sessionList.filter((s) => s.character_id === selectedCharacterId).map((s) => (
              <button key={s.id} type="button" className={`sessionItem ${s.id === sessionId ? "active" : ""}`} onClick={() => void handleSwitchSession(s.id)}>
                <span className="sessionPreview">{s.preview}</span>
                <span className="sessionMeta">{s.message_count} msgs</span>
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
            <button type="button" className="backBtn" onClick={handleBackToSelect}>&larr;</button>
            <div>
              <h1 className="charTitle">{selectedChar?.name ?? "Chat"}</h1>
              <span className="charArchLabel">{selectedChar?.archetype}</span>
            </div>
          </div>
          <div className="statusWrap">
            <button type="button" className="themeToggle" onClick={() => setTheme((t) => t === "light" ? "dark" : "light")} title="Toggle theme">
              {theme === "light" ? "\u263E" : "\u2600"}
            </button>
            <button type="button" className="newChatBtn" onClick={handleNewChat} disabled={!connected}>+ new</button>
            <div className={`status ${connected ? "up" : "down"}`}>{connected ? "connected" : "offline"}</div>
            {!connected ? <button type="button" className="reconnectBtn" onClick={handleManualReconnect}>reconnect</button> : null}
          </div>
        </header>

        {!connected && retryLabel ? <p className="retryInfo">{retryLabel}</p> : null}

        {/* Tier + stats bar */}
        <div className="tierBar">
          <div className="tierInfo">
            <span className="tierLabel">Tier {tier}: {tierLabel}</span>
            <span className="tierStats">
              trust {(state?.trust ?? 0.5).toFixed(2)} &middot; affection {(state?.affection ?? 0.5).toFixed(2)} &middot; energy {(state?.energy ?? 0.6).toFixed(2)} &middot; mood: {state?.current_mood ?? "neutral"}
            </span>
          </div>
          <div className="tierTrack">
            <div className="tierFill" style={{ width: `${tierProgress(state?.trust ?? 0.5)}%` }} />
          </div>
        </div>

        <section className="timeline" aria-live="polite" ref={timelineRef}>
          {messages.length === 0 ? (
            <p className="placeholder">Start talking to {selectedChar?.name ?? "this character"}.</p>
          ) : (
            messages.map((msg) => {
              if (msg.role === "assistant" && !msg.streaming && msg.text) {
                const parts = splitIntoBubbles(msg.text);
                if (parts.length > 1) {
                  return parts.map((part, i) => (
                    <article key={`${msg.id}-${i}`} className="bubble assistant">
                      <p>{part}</p>
                      {i === parts.length - 1 && (msg.latencyMs || msg.chunkCount) ? (
                        <small>{msg.latencyMs ? `${msg.latencyMs.toFixed(0)}ms` : ""} {msg.chunkCount ? `${msg.chunkCount} chunks` : ""}</small>
                      ) : null}
                    </article>
                  ));
                }
              }
              return (
                <article key={msg.id} className={`bubble ${msg.role}`}>
                  <p>{msg.text || (msg.streaming ? "..." : "")}</p>
                  {msg.role === "assistant" && !msg.streaming && (msg.latencyMs || msg.chunkCount) ? (
                    <small>{msg.latencyMs ? `${msg.latencyMs.toFixed(0)}ms` : ""} {msg.chunkCount ? `${msg.chunkCount} chunks` : ""}</small>
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
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder={`Message ${selectedChar?.name ?? "character"}...`}
            rows={1}
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
