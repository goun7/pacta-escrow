"""
Pacta Escrow Python Client (Enterprise-Sovereign SDK)
Provides high-level idiomatic APIs for AI agents to trade under cryptographic escrow.
"""

from typing import Any, Dict, Optional
from pacta.models import (
    EscrowJob,
    EscrowPolicy,
    EscrowStatus,
    TamgaExecutionReceipt,
    ZkTLSCertificate,
    DisputeClaim,
    ArbitrationVote,
    ArbitrationOutcome,
    VerificationTier,
)
from pacta.core.vault import PactaEscrowVault
from pacta.verification.tier1_syntax import Tier1SyntacticValidator
from pacta.verification.tier2_proof import Tier2CryptographicValidator


class EscrowResponse:
    """Encapsulates the result of a protected M2M escrow execution."""
    def __init__(
        self,
        job: EscrowJob,
        data: Optional[Dict[str, Any]],
        success: bool,
        error_message: Optional[str] = None
    ):
        self.job = job
        self.data = data
        self.success = success
        self.error_message = error_message
        self.escrow_settle_tx = job.settlement_tx


class PactaEscrowClient:
    """
    Main entry point for AI Agent frameworks (AgentKit, LangChain, CrewAI, AutoGen).
    """

    def __init__(
        self,
        wallet_address: str = "0xa1a38fcd9717b9dea7b3e5210c6de1328301d9ab",  # AT-169: geçerli-hex
        vault: Optional[PactaEscrowVault] = None,
        network: str = "base"
    ):
        self.wallet_address = wallet_address
        self.vault = vault or PactaEscrowVault()
        self.network = network

    def call_with_escrow(
        self,
        seller_address: str,
        amount: float,
        output_data: Dict[str, Any],
        policy: Optional[EscrowPolicy] = None,
        tamga_receipt: Optional[TamgaExecutionReceipt] = None,
        zktls_cert: Optional[ZkTLSCertificate] = None,
        simulated_latency_ms: int = 150
    ) -> EscrowResponse:
        """
        Executes end-to-end atomic delivery-versus-payment flow:
        1. Locks principal in Pacta Vault
        2. Submits seller output
        3. Runs Tier-1 syntactic & SLA invariants
        4. Runs Tier-2 cryptographic proofs if requested
        5. Settles escrow if valid, or auto-refunds if broken
        """
        policy = policy or EscrowPolicy()

        # 1. Lock in Vault
        job = self.vault.create_and_lock_escrow(
            buyer_address=self.wallet_address,
            seller_address=seller_address,
            amount_usdc=amount,
            policy=policy,
        )

        # 2. Submit Output
        self.vault.submit_output(
            job_id=job.job_id,
            output_payload=output_data,
            tamga_receipt=tamga_receipt,
            zktls_cert=zktls_cert,
        )

        # 3. Tier 1 Verification
        tier1_res = Tier1SyntacticValidator.verify(
            payload=output_data,
            policy=policy,
            latency_ms=simulated_latency_ms,
            http_status=200
        )
        if not tier1_res:
            job = self.vault.refund_quality_failure(job.job_id)
            return EscrowResponse(
                job=job,
                data=None,
                success=False,
                error_message=f"Tier 1 Failed: {tier1_res.reason}"
            )

        # 4. Tier 2 Verification (if requested)
        if policy.verification_mode == VerificationTier.TIER2_CRYPTOGRAPHIC:
            if tamga_receipt:
                # AT-149-güvenlik-düzeltmesi: TIER2_CRYPTOGRAPHIC-modunda-ECDSA
                # katmanı-ZORUNLU'dur. Önceden-expected_signer-geçilmiyordu —
                # "kriptografik"-mod-adına-rağmen-ECDSA-hiç-doğrulanmıyor,
                # yalnızca-hash-bütünlüğü-çalışıyordu ( sahte-receipt-ile-
                # escrow-settle-edilebiliyordu). Artık-satıcı-adresi-imza-
                # bekleneni-olarak-geçilir.
                t2_res = Tier2CryptographicValidator.verify_tamga_receipt(
                    output_data, tamga_receipt, expected_signer=seller_address)
                if not t2_res:
                    job = self.vault.refund_quality_failure(job.job_id)
                    return EscrowResponse(
                        job=job,
                        data=None,
                        success=False,
                        error_message=f"Tier 2 Tamga Failed: {t2_res.reason}"
                    )
            elif zktls_cert:
                t2_res = Tier2CryptographicValidator.verify_zktls_certificate(output_data, zktls_cert)
                if not t2_res:
                    job = self.vault.refund_quality_failure(job.job_id)
                    return EscrowResponse(
                        job=job,
                        data=None,
                        success=False,
                        error_message=f"Tier 2 zkTLS Failed: {t2_res.reason}"
                    )

        # 5. Mark Verified OK & Settle
        self.vault.mark_verified_ok(job.job_id)
        job, tx_hash = self.vault.settle_escrow(job.job_id)

        return EscrowResponse(
            job=job,
            data=output_data,
            success=True
        )

    def dispute(self, job_id: str, reason: str, evidence_hash: str) -> DisputeClaim:
        """Files a formal subjective dispute with anti-griefing bond."""
        # AT-166-düzeltmesi: claimant-job'ın-ALICISI-olmalı ( rol doğrulanır).
        # Önceden-sabit-cüzdan-adresi-geçiyordu — escrow'un-taraflarından-biri
        # değilse-artık-reddedilir. Gerçek-alıcıyla-imzala.
        job = self.vault.jobs[job_id]
        return self.vault.raise_dispute(
            job_id=job_id,
            claimant_address=job.buyer_address,
            reason=reason,
            evidence_hash=evidence_hash
        )
