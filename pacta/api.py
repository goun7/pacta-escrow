"""
Pacta Protocol REST API (Production-Ready FastAPI Microservice)
Provides HTTP/REST endpoints for autonomous agents to interact with Pacta.
"""

from typing import Any, Dict, Optional
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from pacta.config import settings
from pacta.client import PactaEscrowClient
from pacta.core.vault import PactaEscrowVault, EscrowNotFoundError, InvariantViolationError
from pacta.models import EscrowPolicy, VerificationTier, EscrowStatus
from pacta.verification.tier1_syntax import Tier1SyntacticValidator

app = FastAPI(
    title="Pacta Escrow & Autonomous Dispute Rail API",
    version="2026.1.0",
    description="Production M2M Delivery-versus-Payment Escrow API for AI Agents (x402 / AP2)"
)

# Shared in-process vault & client
shared_vault = PactaEscrowVault()
shared_client = PactaEscrowClient(vault=shared_vault)


class LockRequest(BaseModel):
    buyer_address: str
    seller_address: str
    amount_usdc: float = Field(gt=0, description="Amount in USDC")
    timeout_ms: int = Field(default=5000, gt=0)
    required_schema: Optional[Dict[str, Any]] = None


class SettleRequest(BaseModel):
    job_id: str


class SubmitRequest(BaseModel):
    job_id: str
    output_payload: Dict[str, Any]


class DisputeRequest(BaseModel):
    job_id: str
    claimant_address: str
    reason: str
    evidence_hash: str


class VerifyRequest(BaseModel):
    payload: Dict[str, Any]
    required_schema: Dict[str, Any]
    latency_ms: int = 100


@app.get("/healthz")
def health_check() -> Dict[str, Any]:
    """Healthcheck endpoint confirming vault solvency invariant."""
    is_solvent = shared_vault.check_solvency_invariant()
    return {
        "status": "healthy",
        "version": "2026.1.0",
        "network": settings.network,
        "vault_solvency_invariant": "PASS" if is_solvent else "FAIL",
    }


@app.get("/metrics")
def get_metrics() -> Dict[str, Any]:
    """Operational metrics: vault balances, locked escrows, dispute bonds."""
    stats = shared_vault.get_vault_stats()
    return {
        "network": settings.network,
        "vault_address": settings.vault_address,
        "stats": stats
    }


@app.post("/v1/escrow/lock")
def create_lock(req: LockRequest) -> Dict[str, Any]:
    """Locks USDC in smart escrow for atomic delivery-versus-payment."""
    policy = EscrowPolicy(
        timeout_ms=req.timeout_ms,
        required_schema=req.required_schema
    )
    job = shared_vault.create_and_lock_escrow(
        buyer_address=req.buyer_address,
        seller_address=req.seller_address,
        amount_usdc=req.amount_usdc,
        policy=policy
    )
    return {
        "job_id": job.job_id,
        "status": job.status.value,
        "amount_usdc": str(job.amount_usdc),
        # PACTA-VLT-4: fee_collected-settle'da-dolar; lock-anında-"0.000000"
        # göstermek-sessiz-sıfır-ücret-vaadiydi. Sözleşme-ücreti-politikadan
        # hesaplanır (gerçek-fee-settle_escrow'da-tahsil-edilir).
        "protocol_fee_usdc": str(job.calculate_fee()),
        "net_seller_usdc": str(job.net_seller_amount())
    }


@app.post("/v1/escrow/submit")
def submit_output(req: SubmitRequest) -> Dict[str, Any]:
    """Seller submits task output payload into active escrow."""
    try:
        job = shared_vault.submit_output(req.job_id, req.output_payload)
        return {
            "job_id": job.job_id,
            "status": job.status.value
        }
    except EscrowNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/v1/escrow/settle")
def settle_escrow(req: SettleRequest) -> Dict[str, Any]:
    """Settles escrow and releases net funds to seller."""
    try:
        if req.job_id not in shared_vault.jobs:
            raise HTTPException(status_code=404, detail=f"Job ID {req.job_id} not found.")
        job = shared_vault.jobs[req.job_id]
        if job.status == EscrowStatus.OUTPUT_SUBMITTED:
            tier1_res = Tier1SyntacticValidator.verify(
                payload=job.output_payload,
                policy=job.policy,
                latency_ms=100
            )
            if not tier1_res.is_valid:
                raise HTTPException(status_code=400, detail=f"Syntactic verification failed: {tier1_res.reason}")
            shared_vault.mark_verified_ok(job.job_id)

        job, tx = shared_vault.settle_escrow(req.job_id)
        return {
            "job_id": job.job_id,
            "status": job.status.value,
            "settlement_tx": tx,
            "net_seller_usdc": str(job.net_seller_amount())
        }
    except EscrowNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/v1/escrow/dispute")
def raise_dispute(req: DisputeRequest) -> Dict[str, Any]:
    """Raises dispute and locks anti-griefing bond."""
    try:
        dispute = shared_vault.raise_dispute(
            job_id=req.job_id,
            claimant_address=req.claimant_address,
            reason=req.reason,
            evidence_hash=req.evidence_hash
        )
        return {
            "dispute_id": dispute.dispute_id,
            "job_id": dispute.job_id,
            "bond_amount_usdc": str(dispute.bond_amount_usdc),
            "status": "ARBITRATION_IN_PROGRESS"
        }
    except EscrowNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/v1/verify")
def verify_tier1(req: VerifyRequest) -> Dict[str, Any]:
    """Runs Tier-1 syntactic JSON-Schema invariant validation."""
    policy = EscrowPolicy(required_schema=req.required_schema)
    res = Tier1SyntacticValidator.verify(
        payload=req.payload,
        policy=policy,
        latency_ms=req.latency_ms
    )
    return {
        "is_valid": res.is_valid,
        "reason": res.reason,
        "latency_ms": res.latency_ms
    }
