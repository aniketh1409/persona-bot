# PersonaBot RPG: Design Document

> This document describes the transformation of PersonaBot from a persona-switching
> chatbot into an AI Companion RPG where the emotional state system drives narrative
> progression and character relationships.

---

## Core Concept

You enter a world with **distinct AI characters**, each with their own personality,
backstory, secrets, and relationship with you. How you talk to them matters — your
words shift their trust, affection, and energy. As the relationship deepens, they
reveal more about themselves, unlock new story arcs, and reference things you told
them weeks ago.

It's not a chatbot anymore. It's a **relationship simulation** with real memory and
real consequences.

---

## What Changes vs. What Stays

### Stays (reused as-is or with minor tweaks)
- **State engine** — trust/affection/energy/mood. This becomes the core RPG mechanic.
- **Memory service** — Qdrant vector memory. Characters remember what you said.
- **RAG context builder** — Assembles state + history + memory into the LLM prompt.
- **LLM service** — Ollama/OpenAI streaming. Characters speak through this.
- **Session service** — Session/user/event persistence.
- **Redis cache** — Emotional state caching.
- **WebSocket streaming** — Real-time token delivery.

### Changes
- **PersonaProfile** becomes **Character** — richer model with backstory, secrets, arc
  definitions.
- **RelationshipState** becomes **per-user-per-character** — not per-session. Your trust
  with a character persists across all conversations with them.
- **New: Story arcs** — narrative threads that unlock based on relationship thresholds.
- **New: Milestones** — trackable achievements ("First time Kael trusted you enough to
  mention his past").
- **New: Lore fragments** — pieces of world-building that characters reveal when conditions
  are met.
- **Frontend overhaul** — character selection screen, relationship dashboard, milestone
  feed.

---

## Characters (Initial Set)

Three characters to start, each designed to reward different conversational approaches:

### 1. Kael — The Guarded Strategist
- **Archetype**: Reluctant mentor. Knows a lot, shares little.
- **Starting trust**: 0.30 (low — he doesn't trust easily)
- **Starting affection**: 0.20
- **Starting energy**: 0.70
- **Baseline mood**: guarded
- **What unlocks him**: Consistency, directness, proving you actually listen. He hates
  flattery and detects bullshit. Ask him real questions, reference things he said before,
  and he'll slowly open up.
- **Personality**: Dry wit, short sentences, strategic thinker. Won't give you the answer
  — will help you find it. Gets annoyed by vague questions.
- **Secret**: He failed someone he was mentoring before. That guilt drives his reluctance
  to get close. Unlocks at trust >= 0.75.
- **Voice sample**: "You're asking the wrong question. Think about what you actually need
  to know, then ask again."

### 2. Lyra — The Warm Idealist
- **Archetype**: Empathetic dreamer. Sees the best in people, sometimes naively.
- **Starting trust**: 0.55 (moderate — she's open but not naive)
- **Starting affection**: 0.50
- **Starting energy**: 0.80
- **Baseline mood**: playful
- **What unlocks her**: Emotional honesty, vulnerability, sharing real feelings. She
  responds poorly to cynicism or dismissiveness. Be genuine with her.
- **Personality**: Warm, curious, asks lots of follow-up questions. Uses metaphors.
  Sometimes rambles. Genuinely interested in how you're doing.
- **Secret**: She's hiding her own anxiety behind optimism. Unlocks at affection >= 0.80
  and trust >= 0.65.
- **Voice sample**: "that's actually really interesting — have you ever thought about
  why that matters to you? like, what's underneath it?"

### 3. Vex — The Chaotic Tinkerer
- **Archetype**: Hyperactive inventor. Says what they think, no filter.
- **Starting trust**: 0.45
- **Starting affection**: 0.35
- **Starting energy**: 0.90
- **Baseline mood**: playful
- **What unlocks them**: Humor, creativity, going along with their wild ideas. They
  get bored fast by serious-only conversations. Challenge them intellectually and they'll
  respect you.
- **Personality**: Fast talker, jumps between topics, makes obscure references, invents
  words. High energy. Occasionally drops something genuinely profound between the chaos.
- **Secret**: They use chaos as a defense mechanism — they're afraid of being seen as
  ordinary. Unlocks at trust >= 0.70 and energy stays above 0.50 for 10+ turns.
- **Voice sample**: "ok ok ok hear me out — what if gravity was optional but only on
  tuesdays. no wait that's stupid. OR IS IT."

---

## Relationship Model

### Per-User-Per-Character State

The current system tracks state per-session. The RPG model tracks state **per relationship**:

```
user_id + character_id = one RelationshipState
```

This means:
- Your trust with Kael persists across all conversations with him
- Starting a new chat with Kael doesn't reset your relationship
- Each character has different starting values

### State Thresholds and Tiers

| Tier | Trust Range | Label | Effect |
|------|-------------|-------|--------|
| 1 | 0.00 - 0.30 | Stranger | Surface-level conversation only. Character is guarded. |
| 2 | 0.30 - 0.50 | Acquaintance | Character shares opinions, asks about you. |
| 3 | 0.50 - 0.70 | Companion | Character references past conversations, shows vulnerability. |
| 4 | 0.70 - 0.85 | Confidant | Character reveals backstory/secrets. Story arcs unlock. |
| 5 | 0.85 - 1.00 | Bonded | Character's deepest lore. Unique dialogue. Rare milestones. |

The LLM system prompt changes based on the current tier. A Tier 1 Kael is curt and
dismissive. A Tier 4 Kael actually asks how you're doing.

### State Decay

If you don't talk to a character for a while, their energy decays slightly (they "drift").
Trust and affection decay very slowly — relationships don't reset, but they cool off.

```
hours_since_last_chat = now - last_active_at
energy_decay = min(0.15, hours_since_last_chat / 168)   # max 0.15 per week
trust_decay = min(0.05, hours_since_last_chat / 336)     # max 0.05 per 2 weeks
affection_decay = min(0.03, hours_since_last_chat / 336)
```

When you return after a long absence, the character notices: "Been a while. Thought
you'd moved on."

---

## Story Arcs

Arcs are narrative threads tied to relationship thresholds. They're not scripted
dialogue — they're **context injections** that tell the LLM what the character should
reveal or bring up when conditions are met.

### Arc Structure

```
Arc:
  id: "kael_past_failure"
  character_id: "kael"
  title: "The One He Couldn't Help"
  trigger: trust >= 0.75 AND message_count >= 30
  context_injection: |
    Kael is starting to trust the user enough to reveal something personal.
    He once mentored someone who was struggling, and he pushed too hard.
    They stopped coming to him. He still thinks about it.
    He won't dump this all at once — he'll hint at it first. Maybe mention
    "someone I used to talk to" or "a mistake I made." If the user asks
    follow-up questions with genuine interest, he'll share more.
  completed_when: character has fully revealed the backstory (tracked by milestone)
  milestone_on_complete: "kael_trust_breakthrough"
```

The `context_injection` is appended to the RAG context when the arc's conditions are
met. The LLM uses it naturally — it doesn't force the character to say anything specific,
but it gives them the material to draw from.

### Arc States
- **locked**: Conditions not met. Character has no awareness of this arc.
- **active**: Conditions met. Context injection is included in prompts. Character may
  begin hinting.
- **completed**: Milestone triggered. Context injection changes to reference the reveal
  as something that already happened.

---

## Milestones

Trackable moments in the relationship. Serve as both achievements and narrative markers.

### Examples
| Milestone | Character | Trigger |
|-----------|-----------|---------|
| First Impression | Any | Complete first conversation (5+ turns) |
| Kael Noticed You Listen | Kael | Reference something he said in a previous session |
| Lyra's Real Talk | Lyra | Affection >= 0.80, she reveals her anxiety |
| Vex Went Quiet | Vex | First time Vex drops the chaotic act and says something real |
| The Name He Won't Say | Kael | Trust >= 0.85, he names the person he failed |
| All Three Trust You | All | Trust >= 0.70 with all three characters |

Milestones are persisted and shown in the UI as a feed/log.

---

## Lore Fragments

Short pieces of world-building that characters drop when conditions are met. These build
out the setting without requiring a lore dump.

```
Fragment:
  id: "the_signal"
  character_id: "lyra"
  text: "There's a signal that started three months ago. No one talks about it,
         but everyone hears it. Lyra calls it 'the hum.'"
  unlocked_when: trust >= 0.60 AND user mentions anything about "sound" or "noise"
```

Lore fragments are collected in a "journal" UI element.

---

## Database Schema Changes

### New Tables

```sql
-- Characters replace PersonaProfile for RPG mode
CREATE TABLE characters (
    id          VARCHAR(64) PRIMARY KEY,
    name        VARCHAR(80) NOT NULL,
    archetype   VARCHAR(120),
    description TEXT,
    backstory   TEXT,          -- private, never shown to user directly
    system_prompt TEXT NOT NULL,
    style_prompt  TEXT NOT NULL,
    temperature FLOAT DEFAULT 0.7,
    starting_trust     FLOAT DEFAULT 0.5,
    starting_affection FLOAT DEFAULT 0.5,
    starting_energy    FLOAT DEFAULT 0.6,
    baseline_mood      VARCHAR(32) DEFAULT 'neutral',
    created_at  TIMESTAMPTZ DEFAULT now()
);

-- Per-user-per-character relationship (replaces per-session state)
CREATE TABLE character_relationships (
    id           VARCHAR(36) PRIMARY KEY,
    user_id      VARCHAR(36) REFERENCES users(id),
    character_id VARCHAR(64) REFERENCES characters(id),
    trust        FLOAT DEFAULT 0.5,
    affection    FLOAT DEFAULT 0.5,
    energy       FLOAT DEFAULT 0.6,
    current_mood VARCHAR(32) DEFAULT 'neutral',
    tier         INTEGER DEFAULT 1,
    message_count INTEGER DEFAULT 0,
    last_active_at TIMESTAMPTZ DEFAULT now(),
    created_at   TIMESTAMPTZ DEFAULT now(),
    UNIQUE(user_id, character_id)
);

-- Story arcs
CREATE TABLE story_arcs (
    id            VARCHAR(64) PRIMARY KEY,
    character_id  VARCHAR(64) REFERENCES characters(id),
    title         VARCHAR(200),
    description   TEXT,
    context_injection TEXT NOT NULL,  -- appended to prompt when active
    completed_injection TEXT,         -- replaces context_injection after completion
    trust_threshold    FLOAT DEFAULT 0.0,
    affection_threshold FLOAT DEFAULT 0.0,
    message_count_threshold INTEGER DEFAULT 0,
    sort_order    INTEGER DEFAULT 0,
    created_at    TIMESTAMPTZ DEFAULT now()
);

-- Per-user arc progress
CREATE TABLE user_arc_progress (
    id          VARCHAR(36) PRIMARY KEY,
    user_id     VARCHAR(36) REFERENCES users(id),
    arc_id      VARCHAR(64) REFERENCES story_arcs(id),
    status      VARCHAR(16) DEFAULT 'locked',  -- locked, active, completed
    activated_at  TIMESTAMPTZ,
    completed_at  TIMESTAMPTZ,
    UNIQUE(user_id, arc_id)
);

-- Milestones
CREATE TABLE milestones (
    id            VARCHAR(64) PRIMARY KEY,
    character_id  VARCHAR(64) REFERENCES characters(id),  -- NULL for global milestones
    title         VARCHAR(200),
    description   TEXT,
    icon          VARCHAR(8),  -- emoji for display
    created_at    TIMESTAMPTZ DEFAULT now()
);

-- Per-user milestone unlocks
CREATE TABLE user_milestones (
    id           VARCHAR(36) PRIMARY KEY,
    user_id      VARCHAR(36) REFERENCES users(id),
    milestone_id VARCHAR(64) REFERENCES milestones(id),
    unlocked_at  TIMESTAMPTZ DEFAULT now(),
    UNIQUE(user_id, milestone_id)
);

-- Lore fragments
CREATE TABLE lore_fragments (
    id            VARCHAR(64) PRIMARY KEY,
    character_id  VARCHAR(64) REFERENCES characters(id),
    title         VARCHAR(200),
    text          TEXT NOT NULL,
    trust_threshold    FLOAT DEFAULT 0.0,
    affection_threshold FLOAT DEFAULT 0.0,
    keyword_trigger    VARCHAR(200),  -- optional: unlock when user mentions this
    sort_order    INTEGER DEFAULT 0,
    created_at    TIMESTAMPTZ DEFAULT now()
);

-- Per-user lore unlocks
CREATE TABLE user_lore (
    id            VARCHAR(36) PRIMARY KEY,
    user_id       VARCHAR(36) REFERENCES users(id),
    fragment_id   VARCHAR(64) REFERENCES lore_fragments(id),
    unlocked_at   TIMESTAMPTZ DEFAULT now(),
    UNIQUE(user_id, fragment_id)
);
```

### Existing Tables — What Happens

| Table | Action |
|-------|--------|
| `users` | Keep as-is |
| `chat_sessions` | Keep. `persona_id` column becomes `character_id` FK. |
| `relationship_states` | **Deprecated** by `character_relationships`. Migrate data if needed, then drop. |
| `persona_profiles` | **Deprecated** by `characters`. Drop after migration. |
| `conversation_events` | Keep as-is |
| `chat_turn_metrics` | Keep as-is |

---

## System Prompt Architecture

The LLM prompt is constructed in layers:

```
Layer 1: Character identity (from characters.system_prompt)
  "You are Kael. You are a guarded strategist who..."

Layer 2: Relationship tier context (generated from tier)
  "Your relationship with this person is at the Companion level.
   You trust them somewhat. You can share opinions and reference
   past conversations, but you're not ready to reveal personal history."

Layer 3: Active arc injections (from story_arcs.context_injection)
  "You've been thinking about mentioning someone from your past..."

Layer 4: Style instructions (from characters.style_prompt)
  "Short sentences. Dry wit. Don't answer directly — guide them."

Layer 5: Memory + state context (existing RAG context)
  State summary + recent history + recalled memories

Layer 6: User message
```

This layered approach means the LLM naturally adjusts its behavior based on the
relationship state without us having to script dialogue.

---

## Frontend Changes

### Character Selection Screen
- Grid of character cards (portrait placeholder, name, archetype, current tier)
- Clicking a character opens a chat with them
- Visual indicator of relationship tier (1-5 dots or a progress bar)

### Chat View
- Same streaming chat, but header shows character name + current tier
- Sidebar shows relationship stats (trust/affection/energy bars)
- Milestone notifications pop up when earned

### Journal / Profile
- List of unlocked milestones with timestamps
- Collected lore fragments
- Relationship stats for all characters

---

## Implementation Phases

### Phase 1: Foundation (do first)
- [ ] Migration: `characters` table, `character_relationships` table
- [ ] Seed 3 characters (Kael, Lyra, Vex) with prompts
- [ ] `CharacterService` — resolve character, load/save relationship
- [ ] Update `main.py` WebSocket handler to use character relationships instead of personas
- [ ] Update state engine to use per-character starting values and tier thresholds
- [ ] Frontend: character selection, character-scoped sessions
- [ ] Basic tier display in chat header

### Phase 2: Narrative Layer
- [ ] Migration: `story_arcs`, `user_arc_progress` tables
- [ ] `ArcService` — evaluate triggers, activate/complete arcs
- [ ] Inject active arc context into LLM prompt
- [ ] Arc status check after each turn

### Phase 3: Milestones & Lore
- [ ] Migration: `milestones`, `user_milestones`, `lore_fragments`, `user_lore` tables
- [ ] `MilestoneService` — check and award milestones
- [ ] `LoreService` — unlock lore fragments
- [ ] Frontend: milestone notifications, journal/profile page
- [ ] Relationship decay on inactivity

### Phase 4: Polish
- [ ] Character portraits/art
- [ ] Sound effects for milestone unlocks
- [ ] Smoother animations
- [ ] Mobile-first responsive design
- [ ] CI/CD pipeline

---

## Open Questions

1. **Should relationship state be per-character globally, or per-character-per-session?**
   Recommendation: Per-character globally (user_id + character_id). Sessions are just
   conversation containers. Your trust with Kael shouldn't reset because you started a
   new chat.

2. **How to handle character-switching mid-session?**
   Don't allow it. Each session is tied to one character. Starting a chat with a different
   character creates a new session. The sidebar shows sessions grouped by character.

3. **Should characters know about each other?**
   Phase 1: No. Phase 2+: Maybe. Could add cross-character lore ("Lyra mentioned something
   about Kael..."). This is hard to do well and should wait.

4. **How to detect milestone completion?**
   Some milestones are threshold-based (easy — check after state update). Others require
   semantic detection ("user referenced something Kael said before"). For Phase 1, stick
   to threshold-based. Semantic milestones can use the memory service's recall score in
   Phase 3.
