from dataclasses import dataclass

from app.schemas import EmotionalState

POSITIVE_TOKENS = {"thanks", "thank you", "great", "awesome", "love", "nice", "good", "helpful", "appreciate"}
NEGATIVE_TOKENS = {
    "hate",
    "bad",
    "angry",
    "annoyed",
    "stupid",
    "terrible",
    "upset",
    "sad",
    "frustrated",
    "tired",
    "drained",
    "lonely",
    "unloveable",
    "unlovable",
    "unloved",
}


@dataclass(frozen=True)
class StateUpdateResult:
    state: EmotionalState
    sentiment_score: float


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def _sentiment_score(message: str) -> float:
    lowered = message.lower()
    pos_hits = sum(1 for token in POSITIVE_TOKENS if token in lowered)
    neg_hits = sum(1 for token in NEGATIVE_TOKENS if token in lowered)

    if pos_hits == 0 and neg_hits == 0:
        return 0.0
    total = pos_hits + neg_hits
    return (pos_hits - neg_hits) / total


def update_emotional_state(previous: EmotionalState, message: str, message_count: int) -> StateUpdateResult:
    score = _sentiment_score(message)

    trust_delta = 0.08 * score
    affection_delta = 0.10 * score
    energy_delta = -0.02 + (0.03 * score)

    if len(message) > 240:
        energy_delta -= 0.01
    if message_count > 20:
        energy_delta -= 0.01

    trust = _clamp(previous.trust + trust_delta)
    affection = _clamp(previous.affection + affection_delta)
    energy = _clamp(previous.energy + energy_delta)

    if score > 0.25:
        mood = "playful"
    elif score < -0.25:
        mood = "guarded"
    elif energy < 0.25:
        mood = "calm"
    else:
        mood = previous.baseline_mood

    new_state = EmotionalState(
        baseline_mood=previous.baseline_mood,
        current_mood=mood,
        affection=affection,
        trust=trust,
        energy=energy,
    )
    return StateUpdateResult(state=new_state, sentiment_score=score)
