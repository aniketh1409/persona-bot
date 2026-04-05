from datetime import datetime, timedelta, timezone

from app.character_service import CharacterService, compute_tier, TIER_CONTEXT


class _Rel:
    def __init__(self) -> None:
        self.trust = 0.8
        self.affection = 0.8
        self.energy = 0.8
        self.tier = 4
        self.last_active_at = datetime.now(timezone.utc) - timedelta(hours=24)


def test_compute_tier_stranger() -> None:
    tier, label = compute_tier(0.15)
    assert tier == 1
    assert label == "Stranger"


def test_compute_tier_acquaintance() -> None:
    tier, label = compute_tier(0.35)
    assert tier == 2
    assert label == "Acquaintance"


def test_compute_tier_companion() -> None:
    tier, label = compute_tier(0.55)
    assert tier == 3
    assert label == "Companion"


def test_compute_tier_confidant() -> None:
    tier, label = compute_tier(0.75)
    assert tier == 4
    assert label == "Confidant"


def test_compute_tier_bonded() -> None:
    tier, label = compute_tier(0.90)
    assert tier == 5
    assert label == "Bonded"


def test_tier_boundaries() -> None:
    assert compute_tier(0.00)[0] == 1
    assert compute_tier(0.30)[0] == 2
    assert compute_tier(0.50)[0] == 3
    assert compute_tier(0.70)[0] == 4
    assert compute_tier(0.85)[0] == 5
    assert compute_tier(1.00)[0] == 5


def test_tier_context_exists_for_all_tiers() -> None:
    for tier in range(1, 6):
        assert tier in TIER_CONTEXT
        assert len(TIER_CONTEXT[tier]) > 20


def test_relationship_decay_reduces_scores() -> None:
    service = CharacterService.__new__(CharacterService)
    service.decay_enabled = True
    service.energy_decay_per_hour = 0.01
    service.trust_decay_per_hour = 0.005
    service.affection_decay_per_hour = 0.002

    rel = _Rel()
    service._apply_decay(rel)

    assert rel.energy < 0.8
    assert rel.trust < 0.8
    assert rel.affection < 0.8
    assert 1 <= rel.tier <= 5


def test_relationship_decay_noop_when_disabled() -> None:
    service = CharacterService.__new__(CharacterService)
    service.decay_enabled = False
    service.energy_decay_per_hour = 0.01
    service.trust_decay_per_hour = 0.005
    service.affection_decay_per_hour = 0.002

    rel = _Rel()
    before = (rel.energy, rel.trust, rel.affection, rel.tier)
    service._apply_decay(rel)
    after = (rel.energy, rel.trust, rel.affection, rel.tier)
    assert before == after
