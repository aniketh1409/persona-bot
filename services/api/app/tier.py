"""Tier thresholds and prompt context for character relationships."""

from __future__ import annotations

TIER_THRESHOLDS: list[tuple[float, int, str]] = [
    (0.85, 5, "Bonded"),
    (0.70, 4, "Confidant"),
    (0.50, 3, "Companion"),
    (0.30, 2, "Acquaintance"),
    (0.00, 1, "Stranger"),
]


def compute_tier(trust: float) -> tuple[int, str]:
    """Return (tier_number, tier_label) for a given trust value."""
    for threshold, tier, label in TIER_THRESHOLDS:
        if trust >= threshold:
            return tier, label
    return 1, "Stranger"


TIER_CONTEXT: dict[int, str] = {
    1: (
        "Your relationship with this person is brand new - they're a stranger. "
        "Be guarded. Keep things surface-level. You don't owe them anything personal. "
        "Be yourself, but don't open up."
    ),
    2: (
        "You're getting to know this person. They're an acquaintance. "
        "You can share opinions and ask about them, but keep personal history to yourself. "
        "You're warming up, but you're not there yet."
    ),
    3: (
        "This person is becoming a real companion. You trust them enough to reference "
        "past conversations and show some vulnerability. You can be more yourself around them. "
        "But your deeper secrets stay locked."
    ),
    4: (
        "This person has earned your trust. They're a confidant. "
        "You can share things from your past, reveal vulnerabilities, and let them see "
        "the real you. If you have backstory or secrets, you can start hinting at them "
        "or sharing them when it feels natural."
    ),
    5: (
        "This person is bonded to you. You trust them completely. "
        "Nothing is off-limits. You can share your deepest thoughts, fears, and memories. "
        "Reference your history together. Be fully authentic - no walls."
    ),
}
