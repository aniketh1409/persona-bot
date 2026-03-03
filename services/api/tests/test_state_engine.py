from app.schemas import EmotionalState
from app.state_engine import update_emotional_state


def test_positive_message_improves_trust_and_affection() -> None:
    initial = EmotionalState()
    result = update_emotional_state(initial, "thanks this is awesome and helpful", 1)

    assert result.state.trust > initial.trust
    assert result.state.affection > initial.affection
    assert result.sentiment_score > 0


def test_negative_message_lowers_trust_and_affection() -> None:
    initial = EmotionalState()
    result = update_emotional_state(initial, "this is bad and annoying", 1)

    assert result.state.trust < initial.trust
    assert result.state.affection < initial.affection
    assert result.sentiment_score < 0
