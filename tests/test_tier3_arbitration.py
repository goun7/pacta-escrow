"""Unit tests for Tier 3 Schelling Point Arbitration Quorum and Slashing."""

import pytest
from pacta.models import ArbitrationVote
from pacta.verification.tier3_arbitration import Tier3ArbitrationEngine


def test_schelling_arbitration_buyer_wins():
    votes = [
        ArbitrationVote(arbitrator_address="0xA1", vote_favor_buyer=True, staked_amount_pacta=1000.0, rationale_hash="0x1"),
        ArbitrationVote(arbitrator_address="0xA2", vote_favor_buyer=True, staked_amount_pacta=1000.0, rationale_hash="0x2"),
        ArbitrationVote(arbitrator_address="0xA3_Rogue", vote_favor_buyer=False, staked_amount_pacta=1000.0, rationale_hash="0x3"),
    ]

    buyer_favored, rewards, slashes = Tier3ArbitrationEngine.calculate_schelling_outcome(
        votes=votes,
        dispute_bond_usdc=10.0,
        seller_collateral_usdc=50.0
    )

    assert buyer_favored is True
    assert "0xA1" in rewards and rewards["0xA1"] > 0
    assert "0xA2" in rewards and rewards["0xA2"] > 0
    assert "0xA3_Rogue" in slashes and slashes["0xA3_Rogue"] > 0


def test_schelling_arbitration_seller_wins():
    votes = [
        ArbitrationVote(arbitrator_address="0xA1", vote_favor_buyer=False, staked_amount_pacta=1000.0, rationale_hash="0x1"),
        ArbitrationVote(arbitrator_address="0xA2", vote_favor_buyer=False, staked_amount_pacta=1000.0, rationale_hash="0x2"),
        ArbitrationVote(arbitrator_address="0xA3_BadBuyer", vote_favor_buyer=True, staked_amount_pacta=1000.0, rationale_hash="0x3"),
    ]

    buyer_favored, rewards, slashes = Tier3ArbitrationEngine.calculate_schelling_outcome(
        votes=votes,
        dispute_bond_usdc=20.0,
        seller_collateral_usdc=50.0
    )

    assert buyer_favored is False
    assert rewards["0xA1"] > 0
    assert slashes["0xA3_BadBuyer"] > 0
