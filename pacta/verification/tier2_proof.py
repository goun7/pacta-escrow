"""
Pacta Verification Engine: Tier 2 (Cryptographic Execution & zkTLS Proofs)
Integrates Tamga-Protocol WASI Sandboxing and DECO TLSNotary Attestations.
Uses real cryptographic Keccak256 and ECDSA signature recovery when provided.
"""

import json
import hashlib
from typing import Any, Dict, Optional
from eth_account import Account
from eth_account.messages import encode_defunct
from web3 import Web3
from pacta.models import TamgaExecutionReceipt, ZkTLSCertificate


class Tier2VerificationResult:
    def __init__(self, is_valid: bool, reason: str, proof_type: str):
        self.is_valid = is_valid
        self.reason = reason
        self.proof_type = proof_type

    def __bool__(self) -> bool:
        return self.is_valid


class Tier2CryptographicValidator:
    """
    Validates mathematical and cryptographic proofs of work/data:
    - Tamga WASI execution receipts
    - zkTLS (DECO / TLSNotary) session attestations
    - ECDSA signature authentication
    """

    @staticmethod
    def compute_payload_hash(payload: Dict[str, Any]) -> str:
        """Computes deterministic SHA-256 hash of canonical JSON payload."""
        canonical_json = json.dumps(payload, sort_keys=True)
        return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()

    @classmethod
    def verify_tamga_receipt(
        cls,
        payload: Dict[str, Any],
        receipt: Optional[TamgaExecutionReceipt],
        expected_signer: Optional[str] = None
    ) -> Tier2VerificationResult:
        """
        Validates that the output payload matches the Tamga WASI execution receipt.
        Optionally verifies ECDSA signature if expected_signer is specified.
        """
        if receipt is None:
            return Tier2VerificationResult(
                is_valid=False,
                reason="Missing required Tamga execution receipt",
                proof_type="TAMGA_WASI"
            )

        if not receipt.verify_tamga_integrity():
            return Tier2VerificationResult(
                is_valid=False,
                reason="Tamga receipt fails structural integrity check",
                proof_type="TAMGA_WASI"
            )

        expected_hash = cls.compute_payload_hash(payload)
        if receipt.output_hash != expected_hash:
            return Tier2VerificationResult(
                is_valid=False,
                reason=f"Tamga receipt output_hash {receipt.output_hash} mismatch with payload hash {expected_hash}",
                proof_type="TAMGA_WASI"
            )

        # AT-149-güvenlik-düzeltmesi: expected_signer-verilmişse-ECDSA-ZORUNLU'dur.
        # Önceden-yalnızca-"0x"+132hex-ise-çalışırdı; başka-formatlarda-katman
        # SESSİCE-atlanıp-GREEN-verilirdi ( hash'i-doğru-herhangi-sahte-imza-
        # geçerdi). Artık-format-uyumsuzsa-reddederiz ( fail-closed).
        if expected_signer:
            sig = receipt.signature or ""
            if not (sig.startswith("0x") and len(sig) == 132):
                return Tier2VerificationResult(
                    is_valid=False,
                    reason="Tamga receipt signature must be 0x-prefixed 132-hex (65-byte) ECDSA "
                           "when expected_signer is required — signature layer not skipped",
                    proof_type="TAMGA_WASI"
                )
            try:
                signable_msg = encode_defunct(text=receipt.output_hash)
                recovered = Account.recover_message(signable_msg, signature=receipt.signature)
                if recovered.lower() != expected_signer.lower():
                    return Tier2VerificationResult(
                        is_valid=False,
                        reason=f"ECDSA signature recovered {recovered} does not match expected {expected_signer}",
                        proof_type="TAMGA_WASI"
                    )
            except Exception as e:
                return Tier2VerificationResult(
                    is_valid=False,
                    reason=f"ECDSA signature verification error: {str(e)}",
                    proof_type="TAMGA_WASI"
                )

        return Tier2VerificationResult(
            is_valid=True,
            reason=f"Tamga WASI receipt cryptographically verified (instructions: {receipt.instruction_count})",
            proof_type="TAMGA_WASI"
        )

    @classmethod
    def verify_zktls_certificate(
        cls,
        payload: Dict[str, Any],
        cert: Optional[ZkTLSCertificate]
    ) -> Tier2VerificationResult:
        """
        Validates zkTLS (DECO / TLSNotary) web response authenticity proof.
        """
        if cert is None:
            return Tier2VerificationResult(
                is_valid=False,
                reason="Missing required zkTLS certificate",
                proof_type="ZKTLS_DECO"
            )

        if not cert.verify_certificate():
            return Tier2VerificationResult(
                is_valid=False,
                reason="Invalid zkTLS certificate structure or snark proof length",
                proof_type="ZKTLS_DECO"
            )

        expected_hash = cls.compute_payload_hash(payload)
        if cert.data_hash != expected_hash:
            return Tier2VerificationResult(
                is_valid=False,
                reason=f"zkTLS cert data_hash {cert.data_hash} does not match payload hash {expected_hash}",
                proof_type="ZKTLS_DECO"
            )

        # AT-157-güvenlik-düzeltmesi: zk-SNARK-DOĞRULANMIYOR-DEĞİL. Önceden
        # bu-noktada-yalnızca-yapı-ve-data_hash-kontrolü-yapılıp-GERİ-DÖNÜLÜYORDU
        # ( 'certificate authentic from server'-mesajıyla). Ama-zk_proof_snark
        # ASLA-doğrulanmıyordu — 'A'*32-gibi-hiçbir-snark-olmayan-değer-bile
        # geçer-yapı-kontrolünü-geçti-ve-is_valid=True-verdi. Bu, AT-149/
        # AT-150-sınıfının-üst-sınıfıdır: kanıt-DOĞRULANMADIĞI-halde-doğrulu
        # iddia-ediliyordu. Doğru-davranış-fail-closed'dur: gerçek-snark-
        # doğrulaması ( DECO/TLSNotary-pairing-veya-circuit-check)-uygulanana
        # kadar-zkTLS-yolu-açıkça-KAPALIDIR.
        return Tier2VerificationResult(
            is_valid=False,
            reason="zkTLS snark proof verification is not implemented — the zk_proof_snark "
                   "field was never cryptographically verified (only length-checked), so a "
                   "forged certificate passed as authentic. This path is fail-closed until "
                   "real DECO/TLSNotary proof verification lands",
            proof_type="ZKTLS_DECO"
        )
