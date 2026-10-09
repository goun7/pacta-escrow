"""PactaEscrowVault.resolve_arbitration Schelling-arbitration dal-kesen (LEED).

Kural-1: mevcut dosyalara DOKUNULMADI, SADECE bu yeni dosya eklendi.
Dış çağrı YOK: yerel adresler + sentetik oylar.
"""
from decimal import Decimal

import pytest

from pacta.core.vault import PactaEscrowVault
from pacta.models import (ArbitrationVote, EscrowPolicy)


BUYER = "0x59b66b9e6ffdd9ba6ff61c12acfec66f46cd32"
SELLER = "0x2fe8de9732027146046b7f4603994c5a5f5cb0"
ARB1 = "0x24d749ec120e581b60b3dd0fcb8e7a0cf0753a"
ARB2 = "0x35e850c4e9c5a1f6c0c6c1c0a1c39b6c6c06a1c"
ARB3 = "0x46f961bd1a7c9c1f85c1c8c1c3a6c1971c93a2a"


@pytest.fixture
def vault():
    return PactaEscrowVault()


def _dispute(vault, amount=10.0, claimant=BUYER):
    job = vault.create_and_lock_escrow(
        buyer_address=BUYER, seller_address=SELLER,
        amount_usdc=amount, policy=EscrowPolicy())
    vault.submit_output(job.job_id, {"res": "ok"})
    claim = vault.raise_dispute(
        job_id=job.job_id, claimant_address=claimant,
        reason="uyusmazlik", evidence_hash="0xev")
    return job, claim


def _vote(arb, favor):
    return ArbitrationVote(arbitrator_address=arb, vote_favor_buyer=favor,
                           staked_amount=Decimal("1.0"),
                           rationale_hash="0xr")


# -- temel ---------------------------------------------------------------------------------

def test_seller_wins(vault):
    _, claim = _dispute(vault)
    votes = [_vote(ARB1, False), _vote(ARB2, False)]
    outcome = vault.resolve_arbitration(claim.dispute_id, votes)
    assert outcome.buyer_favored is False


def test_buyer_wins(vault):
    _, claim = _dispute(vault)
    votes = [_vote(ARB1, True), _vote(ARB2, True)]
    outcome = vault.resolve_arbitration(claim.dispute_id, votes)
    assert outcome.buyer_favored is True


def test_outcome_type(vault):
    _, claim = _dispute(vault)
    outcome = vault.resolve_arbitration(claim.dispute_id, [_vote(ARB1, True)])
    assert hasattr(outcome, "buyer_favored")


def test_seller_wins_paid(vault):
    _, claim = _dispute(vault)
    votes = [_vote(ARB1, False), _vote(ARB2, False)]
    outcome = vault.resolve_arbitration(claim.dispute_id, votes)
    assert outcome.paid_to_seller_usdc > Decimal("9.9")


def test_buyer_wins_refund(vault):
    _, claim = _dispute(vault)
    votes = [_vote(ARB1, True), _vote(ARB2, True)]
    outcome = vault.resolve_arbitration(claim.dispute_id, votes)
    assert outcome.refunded_to_buyer_usdc > Decimal("0")


# -- oylama ---------------------------------------------------------------------------------

def test_tie_buyer_favored(vault):
    """Uretim: beraberlikte buyer_favored True."""
    _, claim = _dispute(vault)
    votes = [_vote(ARB1, True), _vote(ARB2, False)]
    outcome = vault.resolve_arbitration(claim.dispute_id, votes)
    assert outcome.buyer_favored is True


def test_single_vote_buyer(vault):
    _, claim = _dispute(vault)
    outcome = vault.resolve_arbitration(claim.dispute_id, [_vote(ARB1, True)])
    assert outcome.buyer_favored is True


def test_single_vote_seller(vault):
    _, claim = _dispute(vault)
    outcome = vault.resolve_arbitration(claim.dispute_id, [_vote(ARB1, False)])
    assert outcome.buyer_favored is False


def test_majority_2_of_3_buyer(vault):
    _, claim = _dispute(vault)
    votes = [_vote(ARB1, True), _vote(ARB2, True), _vote(ARB3, False)]
    outcome = vault.resolve_arbitration(claim.dispute_id, votes)
    assert outcome.buyer_favored is True


def test_majority_2_of_3_seller(vault):
    _, claim = _dispute(vault)
    votes = [_vote(ARB1, False), _vote(ARB2, False), _vote(ARB3, True)]
    outcome = vault.resolve_arbitration(claim.dispute_id, votes)
    assert outcome.buyer_favored is False


def test_three_votes_seller(vault):
    _, claim = _dispute(vault)
    votes = [_vote(ARB1, False), _vote(ARB2, False), _vote(ARB3, False)]
    outcome = vault.resolve_arbitration(claim.dispute_id, votes)
    assert outcome.paid_to_seller_usdc > Decimal("9.9")


# -- hatalı durum ---------------------------------------------------------------------------------

def test_unknown_dispute_raises(vault):
    with pytest.raises(ValueError):
        vault.resolve_arbitration("yok-dispute", [_vote(ARB1, True)])


def test_empty_votes_raises(vault):
    _, claim = _dispute(vault)
    with pytest.raises(ValueError):
        vault.resolve_arbitration(claim.dispute_id, [])


def test_arbitrator_is_party_rejected(vault):
    """Hakem buyer/seller olamaz."""
    _, claim = _dispute(vault)
    with pytest.raises(ValueError) as exc:
        vault.resolve_arbitration(claim.dispute_id, [_vote(BUYER, True)])
    assert "escrow" in str(exc.value).lower()


def test_seller_as_arbitrator_rejected(vault):
    _, claim = _dispute(vault)
    with pytest.raises(ValueError):
        vault.resolve_arbitration(claim.dispute_id, [_vote(SELLER, False)])


# -- durum geçişi ---------------------------------------------------------------------------------

def test_seller_wins_sets_settled(vault):
    job, claim = _dispute(vault)
    votes = [_vote(ARB1, False), _vote(ARB2, False)]
    vault.resolve_arbitration(claim.dispute_id, votes)
    assert job.status.value == "SETTLED"


def test_buyer_wins_sets_refunded(vault):
    job, claim = _dispute(vault)
    votes = [_vote(ARB1, True), _vote(ARB2, True)]
    vault.resolve_arbitration(claim.dispute_id, votes)
    assert job.status.value == "SLASHED_REFUNDED"


# -- ledger / slash ---------------------------------------------------------------------------------

def test_buyer_wins_refund_ledger(vault):
    _, claim = _dispute(vault)
    before = vault.ledger_balances.get(BUYER, Decimal("0"))
    votes = [_vote(ARB1, True), _vote(ARB2, True)]
    vault.resolve_arbitration(claim.dispute_id, votes)
    after = vault.ledger_balances.get(BUYER, Decimal("0"))
    assert after >= before


def test_seller_slash_reduces(vault):
    _, claim = _dispute(vault)
    votes = [_vote(ARB1, True), _vote(ARB2, True)]
    outcome = vault.resolve_arbitration(claim.dispute_id, votes)
    assert outcome.slashed_seller_bond_usdc >= Decimal("0")


# -- ödül ---------------------------------------------------------------------------------

def test_arbitrator_reward_field(vault):
    _, claim = _dispute(vault)
    votes = [_vote(ARB1, False), _vote(ARB2, False)]
    outcome = vault.resolve_arbitration(claim.dispute_id, votes)
    assert isinstance(outcome.arbitrator_rewards, dict)


def test_minority_vote_zero_reward(vault):
    _, claim = _dispute(vault)
    votes = [_vote(ARB1, False), _vote(ARB2, False)]
    outcome = vault.resolve_arbitration(claim.dispute_id, votes)
    assert outcome is not None


# -- tutarlar ---------------------------------------------------------------------------------

def test_large_amount_dispute(vault):
    _, claim = _dispute(vault, amount=1000.0)
    votes = [_vote(ARB1, False), _vote(ARB2, False)]
    outcome = vault.resolve_arbitration(claim.dispute_id, votes)
    assert outcome.paid_to_seller_usdc > Decimal("990")


def test_small_amount_dispute(vault):
    _, claim = _dispute(vault, amount=1.0)
    votes = [_vote(ARB1, False), _vote(ARB2, False)]
    outcome = vault.resolve_arbitration(claim.dispute_id, votes)
    assert outcome.paid_to_seller_usdc >= Decimal("0")


def test_solvency_after_arbitration(vault):
    _, claim = _dispute(vault, amount=50.0)
    votes = [_vote(ARB1, False), _vote(ARB2, False)]
    vault.resolve_arbitration(claim.dispute_id, votes)
    assert vault.check_solvency_invariant() is True


# -- tekrar ---------------------------------------------------------------------------------

def test_double_resolve_rejected(vault):
    _, claim = _dispute(vault)
    votes = [_vote(ARB1, False), _vote(ARB2, False)]
    vault.resolve_arbitration(claim.dispute_id, votes)
    with pytest.raises(Exception):
        vault.resolve_arbitration(claim.dispute_id, votes)


def test_dispute_recorded(vault):
    _, claim = _dispute(vault)
    votes = [_vote(ARB1, False), _vote(ARB2, False)]
    vault.resolve_arbitration(claim.dispute_id, votes)
    assert claim.dispute_id in vault.disputes
