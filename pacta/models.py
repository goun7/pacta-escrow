"""
Pacta Core Models & Schemas (Pydantic v2)
Zero-tolerance financial precision: Strictly uses Decimal for all currency, balances, and fees.
Compliant with x402, AP2, and UCC Article 12 CER Standards.
"""

from __future__ import annotations

import time
import uuid
import hashlib
from decimal import Decimal, ROUND_HALF_UP
from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field, field_validator


class EscrowStatus(str, Enum):
    """Lifecycle states of a Pacta Escrow Contract."""
    INITIALIZED = "INITIALIZED"
    ESCROW_LOCKED = "ESCROW_LOCKED"
    OUTPUT_SUBMITTED = "OUTPUT_SUBMITTED"
    VERIFIED_OK = "VERIFIED_OK"
    OPTIMISTIC_SETTLED = "OPTIMISTIC_SETTLED"
    DISPUTED = "DISPUTED"
    ARBITRATION_IN_PROGRESS = "ARBITRATION_IN_PROGRESS"
    SLASHED_REFUNDED = "SLASHED_REFUNDED"
    AUTO_REFUNDED_TIMEOUT = "AUTO_REFUNDED_TIMEOUT"
    SETTLED = "SETTLED"


class VerificationTier(str, Enum):
    """Three-Tier Verification Modes."""
    TIER1_SYNTACTIC = "TIER1_SYNTACTIC"        # Schema, status codes, latency invariant (zero-gas)
    TIER2_CRYPTOGRAPHIC = "TIER2_CRYPTOGRAPHIC"  # Tamga WASI trace + zkTLS DECO proof
    TIER3_SCHELLING = "TIER3_SCHELLING"          # Bonded decentralized arbitration quorum


class EscrowPolicy(BaseModel):
    """Configurable conditions and SLA parameters governing the escrow."""
    timeout_ms: int = Field(default=5000, ge=1, description="Max execution window before automatic refund.")
    required_schema: Optional[Dict[str, Any]] = Field(default=None, description="JSON-Schema for validation.")
    required_schema_hash: Optional[str] = Field(default=None, description="SHA-256 hash of required schema.")
    verification_mode: VerificationTier = Field(
        default=VerificationTier.TIER1_SYNTACTIC,
        description="Verification level enforced."
    )
    max_latency_ms: int = Field(default=5000, ge=0, description="Max allowable roundtrip latency in ms.")
    dispute_window_sec: int = Field(default=60, ge=0, description="Window in seconds for raising subjective dispute.")
    # AT-175-BULGU-1-düzeltmesi: aralık-doğrulama-YOKTU — 5.0-bond-oranı
    # 500-USDC-bond-açar ( anti-griefing-bozuk); negatif-fee-geri-para-akışı;
    # negatif-timeout/latency-geçerliydi. Şimdi-aralık-zorunlu ( VerificationTier-
    # ve-syntropion-tier'in-doğru-modeli-gibi).
    dispute_bond_ratio: Decimal = Field(
        default=Decimal("0.20"),
        description="Ratio of escrow value buyer must post to file dispute (anti-griefing).",
        ge=Decimal("0.0"), le=Decimal("1.0")
    )
    fee_rate_basis_points: int = Field(
        default=75,
        description="Protocol fee in basis points (75 bps = 0.75%).",
        ge=0, le=10000
    )

    def compute_schema_hash(self) -> Optional[str]:
        if not self.required_schema:
            return None
        import json
        serialized = json.dumps(self.required_schema, sort_keys=True)
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


class TamgaExecutionReceipt(BaseModel):
    """Cryptographic execution receipt produced by Tamga-Protocol WASI Sandbox."""
    job_id: str
    program_hash: str
    input_commitment: str
    output_hash: str
    wasi_trace_root: str
    instruction_count: int
    timestamp_epoch: int
    signature: str

    def verify_tamga_integrity(self) -> bool:
        """Verifies that the receipt is self-consistent and well-formed."""
        if not (self.program_hash and self.input_commitment and self.output_hash and self.signature):
            return False
        if self.instruction_count <= 0:
            return False
        return True


class ZkTLSCertificate(BaseModel):
    """DECO / TLSNotary zero-knowledge proof of authentic web/API response."""
    session_id: str
    server_name: str
    data_hash: str
    tls_version: str = "TLS1.3"
    zk_proof_snark: str
    attestation_key: str

    def verify_certificate(self) -> bool:
        """Verifies structure of zkTLS certificate."""
        return bool(self.session_id and self.server_name and self.data_hash and len(self.zk_proof_snark) >= 32)


class ChainAnchor(BaseModel):
    """Gerçek-EVM-zincirine-bağlanmış-bağ ( chain-anchoring).

    Bir settlement/dispute/arbitration-kararının **gerçek-bir-zincirde** gerçek-
    bir-transaction-ile-sabitleştirildiğini kanıtlar ( anvil, yerel-JSON-RPC
    veya in-memory py-evm). Bağ, zincirden-bağımsız-olarak-yeniden-
    doğrulanabilir: ``verify_against_chain``-ile-alıcı-üçüncü-bir-taraf
    transaction-receipt'ini-fetch-edip-calldata'daki-keccak-bağını-teyit-edebilir.

    Dürüst-not: değer-transferi-İÇERMEZ ( 0-wei). Pacta'nın-fon-akışı-yine-de
    ledger-içindedir; zincir-bağı **kararın-taahhüdünü** ( commitment) sabitler
    — bu-dürüst-bir-kapanıştır, "zincir-simülasyonu-değil"-sınırının-kapanması.
    """
    chain_id: int = Field(gt=0, description="Canlı zincir kimliği ( anvil=1337/31337).")
    tx_hash: str = Field(description="0x-önekli-gerçek-transaction-hash.")
    block_number: int = Field(ge=0)
    gas_used: int = Field(ge=0)
    anchor_kind: str = Field(description="settlement | dispute | arbitration | refund")
    job_id: str
    commitment_keccak: str = Field(description="0x-önekli-keccak256-bağı.")
    anchored_at_epoch_ms: int
    from_address: str
    to_address: str
    rpc_url: str = ""
    backend: str = Field(description="anvil | in-memory-pyevm | json-rpc")
    tx_status: int = Field(default=1, description="1 = EVM-başarılı ( SLOAD-çasıtlamak).")

    def verify_against_chain(self, w3: Any) -> bool:
        """Zincirden-bağımsız-yeniden-doğrulama: receipt-fetch + calldata-teyiti.

        Üçüncü-bir-taraf ( alıcı, denetçi) Pacta'ya-güvenmeden-bağı-teyit-eder:
        transaction-gerçekten-zincirde-var-olmalı-ve-calldata-bağı-eşleşmeli.
        """
        try:
            receipt = w3.eth.get_transaction_receipt(self.tx_hash)
        except Exception:
            return False
        if int(receipt.get("status", 0)) != 1:
            return False
        if int(receipt.get("blockNumber", -1)) != self.block_number:
            return False
        try:
            tx = w3.eth.get_transaction(self.tx_hash)
        except Exception:
            return False
        data = tx.get("input") or tx.get("data") or b""
        if isinstance(data, str):
            data = bytes.fromhex(data[2:] if data.startswith("0x") else data)
        return data == bytes.fromhex(
            self.commitment_keccak[2:] if self.commitment_keccak.startswith("0x")
            else self.commitment_keccak)


class EscrowJob(BaseModel):
    """Core Pacta Escrow Job Record with Decimal accounting."""
    job_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    buyer_address: str
    seller_address: str
    amount_usdc: Decimal = Field(gt=Decimal(0), description="Principal escrow amount in USDC (Decimal).")
    deposit_token: str = Field(
        default="0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
        description="Base L2 Native USDC Address."
    )
    policy: EscrowPolicy = Field(default_factory=EscrowPolicy)
    status: EscrowStatus = Field(default=EscrowStatus.INITIALIZED)
    created_at_epoch_ms: int = Field(default_factory=lambda: int(time.time() * 1000))
    locked_at_epoch_ms: Optional[int] = None
    submitted_at_epoch_ms: Optional[int] = None
    settled_at_epoch_ms: Optional[int] = None

    output_payload: Optional[Dict[str, Any]] = None
    tamga_receipt: Optional[TamgaExecutionReceipt] = None
    zktls_cert: Optional[ZkTLSCertificate] = None
    settlement_tx: Optional[str] = None
    # AT-194-chain-anchoring: gerçek-zincir-bağı ( None = zincir-kullanılmıyor)
    chain_anchor: Optional[ChainAnchor] = None
    # AT-195: RFC-010 cross-artifact settlement binding — settlement-kararının
    # Tamga-D5-hash-chain'ine-sabitlenmiş-hali ( None = D5-ledger-yapılandırılmadı;
    # eski-davranış). charge = escrow-tarafı-kayıt, claim = alıcı-tarafı-yetki,
    # delivery_hash = kanıtlanan-teslimatın-özeti.
    settlement_binding: Optional[Dict[str, Any]] = None
    # PACTA-VLT-4-DUZELTME: None = fee-henüz-TAHSİL-EDİLMEDİ ( settle-öncesi).
    # Eski-varsayılan ``0.000000``-idi: settle-öncesi-işlerde-"tahsil-edilmiş-
    # fee=0"gibi-GÖRÜNÜP-zincir-bağı-terms'inde-sessiz-sıfır-ücret-
    # sabitliyordu. Gerçek-değer-settle_escrow'da-yazılır.
    fee_collected_usdc: Optional[Decimal] = Field(default=None)

    @field_validator("amount_usdc", mode="before")
    def convert_amount_to_decimal(cls, v: Any) -> Decimal:
        d = Decimal(str(v))
        if d <= Decimal(0):
            raise ValueError("Escrow amount must be strictly positive.")
        return d.quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)

    def calculate_fee(self) -> Decimal:
        """Computes protocol fee according to basis points with 6-decimal precision."""
        bps = Decimal(str(self.policy.fee_rate_basis_points))
        fee = (self.amount_usdc * bps) / Decimal("10000")
        return fee.quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)

    def net_seller_amount(self) -> Decimal:
        """Net amount released to seller upon verified settlement."""
        return (self.amount_usdc - self.calculate_fee()).quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)


class DisputeClaim(BaseModel):
    """Dispute initiated by buyer or arbitrator on subjective/semantic failure."""
    dispute_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    job_id: str
    claimant_address: str
    bond_amount_usdc: Decimal
    reason: str
    evidence_hash: str
    created_at_epoch: int = Field(default_factory=lambda: int(time.time()))

    @field_validator("bond_amount_usdc", mode="before")
    def convert_bond_to_decimal(cls, v: Any) -> Decimal:
        return Decimal(str(v)).quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)


class ArbitrationVote(BaseModel):
    """Vote submitted by a staked arbitrator node."""
    arbitrator_address: str
    vote_favor_buyer: bool
    staked_amount_pacta: Decimal = Field(default=Decimal("1000.000000"))
    rationale_hash: str
    voted_at_epoch: int = Field(default_factory=lambda: int(time.time()))

    @field_validator("staked_amount_pacta", mode="before")
    def convert_stake_to_decimal(cls, v: Any) -> Decimal:
        return Decimal(str(v)).quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)


class ArbitrationOutcome(BaseModel):
    """Final decision rendered by Schelling point arbitration quorum."""
    dispute_id: str
    job_id: str
    buyer_favored: bool
    votes_for_buyer: int
    votes_for_seller: int
    slashed_seller_bond_usdc: Decimal
    refunded_to_buyer_usdc: Decimal
    paid_to_seller_usdc: Decimal
    arbitrator_rewards: Dict[str, Decimal]
    resolved_at_epoch: int = Field(default_factory=lambda: int(time.time()))
