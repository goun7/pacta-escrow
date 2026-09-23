"""
Pacta Verification Engine: Tier 3 (Schelling Point Arbitration Quorum)
Decentralized focal-point arbitration with quadratic slashing for subjective disputes.
Strict Decimal precision.
"""

from decimal import Decimal, ROUND_HALF_UP
from typing import Dict, List, Tuple
from pacta.models import ArbitrationVote


class Tier3ArbitrationEngine:
    """
    Manages Schelling-point consensus among staked arbitrator nodes:
    - Calculates majority decision
    - Executes quadratic slashing against malicious or dissenting arbitrators
    - Computes payoff allocations from confiscated dispute bonds
    """

    @staticmethod
    def calculate_schelling_outcome(
        votes: List[ArbitrationVote],
        dispute_bond_usdc: Decimal,
        seller_collateral_usdc: Decimal
    ) -> Tuple[bool, Dict[str, Decimal], Dict[str, Decimal]]:
        """
        Calculates Schelling point decision, rewards majority nodes, and slashes minority nodes.
        
        Returns:
            (buyer_favored, arbitrator_rewards, arbitrator_slashes)
        """
        if not votes:
            raise ValueError("Cannot arbitrate without votes.")

        dispute_bond = Decimal(str(dispute_bond_usdc))
        seller_collateral = Decimal(str(seller_collateral_usdc))

        buyer_votes = [v for v in votes if v.vote_favor_buyer]
        seller_votes = [v for v in votes if not v.vote_favor_buyer]

        buyer_favored = len(buyer_votes) >= len(seller_votes)
        majority_votes = buyer_votes if buyer_favored else seller_votes
        minority_votes = seller_votes if buyer_favored else buyer_votes

        # Reward pool funded from 50% of the loser's forfeited bond/collateral
        if buyer_favored:
            reward_pool = (seller_collateral * Decimal("0.20")).quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)
        else:
            reward_pool = (dispute_bond * Decimal("0.50")).quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)

        rewards: Dict[str, Decimal] = {}
        slashes: Dict[str, Decimal] = {}

        maj_count = Decimal(str(max(1, len(majority_votes))))
        reward_per_winner = (reward_pool / maj_count).quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)
        for v in majority_votes:
            rewards[v.arbitrator_address] = reward_per_winner

        # Quadratic slashing for minority/collusive voters:
        # Penalty = (minority_count / total_votes)^2 * staked_amount * 0.1
        penalty_ratio = (Decimal(str(len(minority_votes))) / Decimal(str(len(votes)))) ** 2
        for v in minority_votes:
            slash_amount = (v.staked_amount_pacta * penalty_ratio * Decimal("0.1")).quantize(
                Decimal("0.000001"), rounding=ROUND_HALF_UP
            )
            slashes[v.arbitrator_address] = slash_amount

        return buyer_favored, rewards, slashes
