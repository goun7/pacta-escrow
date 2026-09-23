"""
Pacta Finite State Machine (FSM)
Strict mathematical state transition verification for escrow lifecycles.
"""

from typing import Dict, Set
from pacta.models import EscrowStatus


class InvalidStateTransitionError(Exception):
    """Raised when an illegal or out-of-order state transition is attempted."""

    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(self.message)


class EscrowFSM:
    """
    Formally verifies and executes valid lifecycle transitions.
    Enforces delivery-versus-payment invariance.
    """

    ALLOWED_TRANSITIONS: Dict[EscrowStatus, Set[EscrowStatus]] = {
        EscrowStatus.INITIALIZED: {
            EscrowStatus.ESCROW_LOCKED
        },
        EscrowStatus.ESCROW_LOCKED: {
            EscrowStatus.OUTPUT_SUBMITTED,
            EscrowStatus.AUTO_REFUNDED_TIMEOUT
        },
        EscrowStatus.OUTPUT_SUBMITTED: {
            EscrowStatus.VERIFIED_OK,
            EscrowStatus.AUTO_REFUNDED_TIMEOUT,
            EscrowStatus.DISPUTED
        },
        EscrowStatus.VERIFIED_OK: {
            EscrowStatus.OPTIMISTIC_SETTLED,
            EscrowStatus.SETTLED,
            EscrowStatus.DISPUTED,
            # AT-165-BULGU-2: SLA-aşımı-settle-kapısında-reddedildiğinde-alıcının
            # iade-hakkı-kaybolmasın ( escrow-yine-de-zaman-aşımına-uğradıysa).
            # OUTPUT_SUBMITTED-ile-aynı-davranış ( additive; yeni-geçiş).
            EscrowStatus.AUTO_REFUNDED_TIMEOUT
        },
        EscrowStatus.OPTIMISTIC_SETTLED: {
            EscrowStatus.SETTLED,
            EscrowStatus.DISPUTED
        },
        EscrowStatus.DISPUTED: {
            EscrowStatus.ARBITRATION_IN_PROGRESS
        },
        EscrowStatus.ARBITRATION_IN_PROGRESS: {
            EscrowStatus.SLASHED_REFUNDED,
            EscrowStatus.SETTLED
        },
        EscrowStatus.SLASHED_REFUNDED: set(),      # Terminal state
        EscrowStatus.AUTO_REFUNDED_TIMEOUT: set(),  # Terminal state
        EscrowStatus.SETTLED: set()                # Terminal state
    }

    @classmethod
    def can_transition(cls, current: EscrowStatus, target: EscrowStatus) -> bool:
        """Checks if transition from current to target is mathematically legal."""
        return target in cls.ALLOWED_TRANSITIONS.get(current, set())

    @classmethod
    def transition(cls, current: EscrowStatus, target: EscrowStatus) -> EscrowStatus:
        """Executes state transition or raises InvalidStateTransitionError."""
        if not cls.can_transition(current, target):
            raise InvalidStateTransitionError(
                f"Illegal escrow state transition attempted: {current.value} -> {target.value}"
            )
        return target
