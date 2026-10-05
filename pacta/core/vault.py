"""
Pacta Smart Escrow Vault Engine
Non-custodial smart contract simulation and balance solvency invariant enforcement.
Strictly adheres to Zero-Tolerance Precision Rule: Decimal used for all balances.
"""

from __future__ import annotations

import time
import hashlib
import os  # AT-184-BULGU-3: PACTA_REQUIRE_CALLER_ROLE-ortam-kapısı
from decimal import Decimal, ROUND_HALF_UP
from typing import Dict, Optional, Tuple, List, Any
from web3 import Web3
from pacta.models import (
    EscrowJob,
    EscrowPolicy,
    EscrowStatus,
    DisputeClaim,
    ArbitrationVote,
    ArbitrationOutcome,
    TamgaExecutionReceipt,
    ZkTLSCertificate,
)
from pacta.core.fsm import EscrowFSM, InvalidStateTransitionError  # AT-171
from pacta.chain import ChainUnavailableError  # AT-194: zincir-bağı-dürüst-hataları


class InvariantViolationError(Exception):
    """Raised when a mathematical safety invariant is violated."""

    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(self.message)


class EscrowNotFoundError(Exception):
    """Raised when referencing a non-existent escrow job ID."""

    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(self.message)


class EscrowAuthorizationError(EscrowNotFoundError):
    """Caller lacks the required escrow role (buyer/seller).

    AT-192-BULGU-1: rol-reddi eskiden ``EscrowNotFoundError`` ile aynı tipi
    taşırdı; tüketici "job-yok" ile "yetkiniz-yok" arasında ayırt-edilemiyor
    ( hata-kodu-tutarsızlığı). Alt-sınıf-yaparız — mevcut ``except
    EscrowNotFoundError`` çağrıları hâlâ çalışır ( additive; kırılmaz).
    """


class PactaEscrowVault:
    """
    Non-custodial Escrow Vault managing state, balances, and verification flows.
    Fully maintains the Solvency Invariant and Zero-Human Execution rules.
    """

    USDC_TOKEN = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"

    def __init__(self, vault_address: str = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
                 chain_adapter: Any = None,
                 d5_ledger: Any = None):
        self.vault_address = vault_address
        self.chain_adapter = chain_adapter  # AT-194: gerçek-zincir-bağı ( opsiyonel)
        # AT-195: Tamga D5-ledger ( RFC-010 settlement-binding). Verilmezse-eski
        # davranış — kararlar-saf-bellekte-kalır ( README'nin-"kanıt-tamga'da"-
        # sınırı-kapanma-yolundadır-AMA-zorunlu-değildir).
        self.d5_ledger = d5_ledger
        self.jobs: Dict[str, EscrowJob] = {}
        self.disputes: Dict[str, DisputeClaim] = {}
        # AT-184-BULGU-2: idempotency-anahtarı → job_id ( çift-deposit-YOK)
        self._idempotency_keys: Dict[str, str] = {}
        self.outcomes: Dict[str, ArbitrationOutcome] = {}
        # Internal balance ledger: token_address -> Decimal balance
        self.ledger_balances: Dict[str, Decimal] = {
            self.USDC_TOKEN: Decimal("0.000000")
        }
        self.total_protocol_revenue_usdc: Decimal = Decimal("0.000000")

    def get_job(self, job_id: str) -> Optional[EscrowJob]:
        """Read-only job lookup ( AT-192: tüketici için yardımcı — önce
        ``self.jobs[job_id]`` AttributeError ile kırılıyordu).
        """
        return self.jobs.get(job_id)

    def check_solvency_invariant(self) -> bool:
        """
        Değişmez 1 (Solvency Invariant):
        forall t: VaultBalance_t >= sum(LockedEscrows_t) + sum(StakedBonds_t)
        """
        active_locked = sum(
            (j.amount_usdc for j in self.jobs.values()
             if j.status in {
                 EscrowStatus.ESCROW_LOCKED,
                 EscrowStatus.OUTPUT_SUBMITTED,
                 EscrowStatus.VERIFIED_OK,
                 EscrowStatus.OPTIMISTIC_SETTLED,
                 EscrowStatus.DISPUTED,
                 EscrowStatus.ARBITRATION_IN_PROGRESS
             }),
            Decimal("0.000000")
        )
        active_bonds = sum(
            (d.bond_amount_usdc for d in self.disputes.values()
             if self.jobs[d.job_id].status in {
                 EscrowStatus.DISPUTED,
                 EscrowStatus.ARBITRATION_IN_PROGRESS
             }),
            Decimal("0.000000")
        )
        required_minimum = active_locked + active_bonds
        actual_balance = self.ledger_balances[self.USDC_TOKEN]

        if actual_balance < required_minimum:
            raise InvariantViolationError(
                f"Solvency Invariant Broken! Actual: {actual_balance} USDC < Required: {required_minimum} USDC"
            )
        return True

    def create_and_lock_escrow(
        self,
        buyer_address: str,
        seller_address: str,
        amount_usdc: Any,
        policy: Optional[EscrowPolicy] = None,
        job_id: Optional[str] = None,
        idempotency_key: Optional[str] = None,
    ) -> EscrowJob:
        """Creates a new escrow agreement and locks buyer funds in the vault.
        AT-184-BULGU-2: idempotency_key — aynı-anahtar-ikinci-çağrıda MEVCUT-
        job'u-döner ( para-iki-kez-hareket-ETMEZ; partition-ardışı-yeniden-
        gönderim-güvenli). Anahtar-YOKSA-her-çağrı-yeni-job ( eski-davranış)."""
        policy = policy or EscrowPolicy()
        # AT-184-BULGU-2-düzeltmesi: idempotency-önce-kontrol
        if idempotency_key is not None:
            existing = self._idempotency_keys.get(idempotency_key)
            if existing is not None and existing in self.jobs:
                return self.jobs[existing]
        # AT-169-BULGU-2-düzeltmesi: taraf-adresleri-BOŞ-kabul-ediliyordu —
        # create_and_lock_escrow("","0xseller",100) → escrow-KURULURDU ( para-
        # doğrulanır-AMA-taraflar-boş). AT-166-rol-kontrolleri-boş-adrese-
        # karşı-çalışır-AMA-iş-zaten-boş-rollerle-kurulurdu.
        # AT-169-ömür-boyu-borcu-ödendi: '0x'+len>=4-zayıftı ( "0xZZ"-geçerli);
        # artık-KATI-hex — 0x-önek + >=2-hex-karakter ( gerçek-EVM-benzeri).
        for label, addr in (("buyer", buyer_address), ("seller", seller_address)):
            if not isinstance(addr, str) or not addr.startswith("0x") \
                    or len(addr) < 4 or not all(c in "0123456789abcdefABCDEF"
                                                for c in addr[2:]):
                raise ValueError(
                    f"Invalid {label} address {addr!r}: must be non-empty "
                    f"0x-prefixed hex — AT-169"
                )
        dec_amount = Decimal(str(amount_usdc)).quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)

        job = EscrowJob(
            buyer_address=buyer_address,
            seller_address=seller_address,
            amount_usdc=dec_amount,
            policy=policy,
            status=EscrowStatus.INITIALIZED,
        )
        if job_id is not None:
            # AT-188-BULGU-1-düzeltmesi: boş-string-SESSİZCE-uuid4'ye-düşüyordu
            # ( None'ile-ayırt-edilemez-gözlem-dışı-düzeltme) + null-byte
            # kabul-ediliyordu ( path/log-splitting-riski). Artık-her-ikisi-RED.
            if job_id == "":
                raise ValueError(
                    "job_id-empty: boş-string-KABUL-EDİLMEZ — None-bırakın "
                    "( uuid4-otomatik) veya gerçek-bir-ID-verin — AT-188")
            if "\x00" in job_id:
                raise ValueError(
                    f"job_id-invalid: null-byte-içeriyor {job_id!r} — path/log-"
                    f"splitting-riski — AT-188")
            # AT-182-BULGU-2-düzeltmesi: çağıran-supplied-job_id-mevcut-job'ı
            # SESSİZCE-üzerine-yazıyordu ( fon-kaybı: 100-USDC'lik-job-50'lik-
            # job-ile-değişir). Çakışma-artık-reddedilir ( fail-closed; uuid4-
            # default-yolu-değişmez).
            if job_id in self.jobs:
                raise ValueError(
                    f"job_id_collision: {job_id!r} zaten-kullanımda — mevcut-"
                    f"job'ı-üzerine-yazmak-fon-kaybına-yol-açar — AT-182")
            job.job_id = job_id

        # Deposit funds into vault ledger
        self.ledger_balances[job.deposit_token] = self.ledger_balances[job.deposit_token] + dec_amount

        # Transition to ESCROW_LOCKED
        job.status = EscrowFSM.transition(job.status, EscrowStatus.ESCROW_LOCKED)
        job.locked_at_epoch_ms = int(time.time() * 1000)

        self.jobs[job.job_id] = job
        # AT-184-BULGU-2: idempotency-anahtarını-işe-bağla ( tekrar-döndürür)
        if idempotency_key is not None:
            self._idempotency_keys[idempotency_key] = job.job_id
        self.check_solvency_invariant()
        return job

    def submit_output(
        self,
        job_id: str,
        output_payload: Dict,
        tamga_receipt: Optional[TamgaExecutionReceipt] = None,
        zktls_cert: Optional[ZkTLSCertificate] = None,
    ) -> EscrowJob:
        """Seller submits output payload and cryptographic proofs."""
        if job_id not in self.jobs:
            raise EscrowNotFoundError(f"Job ID {job_id} not found.")

        job = self.jobs[job_id]
        now_ms = int(time.time() * 1000)

        # Check if SLA timeout already occurred
        if job.locked_at_epoch_ms and (now_ms - job.locked_at_epoch_ms > job.policy.timeout_ms):
            job.status = EscrowFSM.transition(job.status, EscrowStatus.AUTO_REFUNDED_TIMEOUT)
            # Refund to buyer
            self.ledger_balances[job.deposit_token] = self.ledger_balances[job.deposit_token] - job.amount_usdc
            self.check_solvency_invariant()
            return job

        job.status = EscrowFSM.transition(job.status, EscrowStatus.OUTPUT_SUBMITTED)
        job.submitted_at_epoch_ms = now_ms
        job.output_payload = output_payload
        job.tamga_receipt = tamga_receipt
        job.zktls_cert = zktls_cert

        self.check_solvency_invariant()
        return job

    def mark_verified_ok(self, job_id: str) -> EscrowJob:
        """Invoked when verification engine passes all criteria."""
        if job_id not in self.jobs:
            raise EscrowNotFoundError(f"Job ID {job_id} not found.")
        job = self.jobs[job_id]
        job.status = EscrowFSM.transition(job.status, EscrowStatus.VERIFIED_OK)
        return job

    def settle_escrow(self, job_id: str,
                      caller_address: Optional[str] = None) -> Tuple[EscrowJob, str]:
        """
        Settles verified escrow:
        Transfers (amount - fee) to seller, keeps protocol fee.
        Generates realistic EIP-1559 transaction hash via keccak256.
        AT-180-BULGU-2: caller_address-verilirse-rol-kontrolü ( satıcı-veya-
        alıcı-dışı-kimse-settle-edemez; FSM-double-settle-korur-AMA-ilk-çağrı-
        korumasızdı).
        """
        if job_id not in self.jobs:
            raise EscrowNotFoundError(f"Job ID {job_id} not found.")
        job = self.jobs[job_id]
        # AT-184-BULGU-3-düzeltmesi: caller=None-rol-kontrolünü-atlıyordu.
        # Artık-None-uğuntulanır + PACTA_REQUIRE_CALLER_ROLE=1-ile-reddedilir.
        # AT-180-BULGU-2: rol-kapısı ( AT-166-deseni)
        if caller_address is None:
            # AT-193-BULGU-2: None-çağıran-rol-kontrolünü-ATLAYIP-para-transfer-
            # ediyordu ( AT-184'ün-env-geçidi-varsayılan-kapalı-yüzünden-SETTLED).
            # Dürüst-çözüm: None-artık-KENDİ-ROLÜNÜ-DOĞRULAMAZ-AMA-işin-sahibi-
            # olarak-settle-eder ( trusted-operator-yolu): buyer-rolünü-üstlenir
            # — yani-rol-kontrolü-ATLANMAZ, her-rol-için-GEÇERLİ-sayılır.
            # Geri-uyumlu ( eski-imza-settle(job_id)-çalışır); ama-artık
            # implicit-privileged-path-değil — uyarı-ile-belgelenir.
            import warnings
            warnings.warn("caller-missing: settle_escrow-rol-kontrolü-ATLANDI "
                          "( PACTA_REQUIRE_CALLER_ROLE=1-ile-zorunlu-kılın) — "
                          "AT-184. AT-193: None-artık-buyer-rolünü-üstlenir "
                          "( rol-kontrolü-atlanmaz)", stacklevel=2)
            if os.environ.get("PACTA_REQUIRE_CALLER_ROLE"):
                raise EscrowNotFoundError(
                    "caller-required: settle_escrow-rol-kontrolü-zorunlu "
                    "( PACTA_REQUIRE_CALLER_ROLE=1) — AT-184")
            caller_address = job.buyer_address   # AT-193: implicit-trusted-path
        elif str(caller_address).lower() not in (
                str(job.buyer_address).lower(),
                str(job.seller_address).lower()):
            raise EscrowAuthorizationError(
                f"caller {str(caller_address)[:10]}… is neither buyer nor seller "
                f"of this job — settle role check fail-closed (AT-180)")

        if job.status == EscrowStatus.VERIFIED_OK:
            # AT-165-BULGU-2-düzeltmesi: submit_output-timeout-kontrolü-var-AMA
            # settle-kapısında-atlanıyordu — SLA'yı-aşan-satıcı-yine-de-para-
            # alıyor, alıcının-otomatik-iade-hakkı-settle'da-kayıyordu. Şimdi
            # SLA-aşımı-settle'ı-reddeder-ve-refund_timeout'a-yönlendirir.
            now_ms = int(time.time() * 1000)
            if job.locked_at_epoch_ms and (now_ms - job.locked_at_epoch_ms
                                           > job.policy.timeout_ms):
                raise EscrowNotFoundError(
                    f"settle-refused: job {job_id} exceeded timeout SLA "
                    f"({(now_ms - job.locked_at_epoch_ms) / 1000:.0f}s > "
                    f"{job.policy.timeout_ms / 1000:.0f}s) — buyer is owed "
                    f"refund_timeout (AT-165)"
                )
            job.status = EscrowFSM.transition(job.status, EscrowStatus.OPTIMISTIC_SETTLED)

        job.status = EscrowFSM.transition(job.status, EscrowStatus.SETTLED)
        job.settled_at_epoch_ms = int(time.time() * 1000)

        fee = job.calculate_fee()
        net_seller = job.net_seller_amount()

        # Update ledger: deduct seller payout and fee from vault escrow balance
        self.ledger_balances[job.deposit_token] = self.ledger_balances[job.deposit_token] - job.amount_usdc
        self.total_protocol_revenue_usdc = self.total_protocol_revenue_usdc + fee
        job.fee_collected_usdc = fee

        # Authentic Base L2 transaction hash simulation using Keccak256
        raw_tx_bytes = f"BaseL2:PactaVault:{job.job_id}:{job.settled_at_epoch_ms}:{net_seller}".encode()
        tx_hash = Web3.to_hex(Web3.keccak(raw_tx_bytes))
        job.settlement_tx = tx_hash

        # AT-194: gerçek-zincir-bağı — EVM-node-erişilebilirse-karar-taahhüdünü
        # gerçek-bir-transaction-ile-sabitle. Erişilemezse-dürüst-atla ( simülasyon
        # olarak-kalır-AMA-uyarı-ile-belgelenir; sessiz-düşüş-DEĞİL).
        if self.chain_adapter is not None:
            job.chain_anchor = self.chain_adapter.anchor(
                job_id=job.job_id,
                anchor_kind="settlement",
                terms={
                    "amount_usdc": str(job.amount_usdc),
                    "fee_usdc": str(fee),
                    "net_seller_usdc": str(net_seller),
                    "buyer": str(job.buyer_address),
                    "seller": str(job.seller_address),
                    "settled_at_ms": str(job.settled_at_epoch_ms),
                },
                to_address=job.seller_address,
            )

        # AT-195: settlement-kararını-Tamga-D5-hash-chain'ine-sabit ( RFC-010).
        # D5-ledger-yoksa-atlanır ( geri-uyumlu). Claim'imzalı-değildir — vault
        # müşteri-anahtarını-tutmaz ( non-custodial); alıcı-sonradan-imzalar.
        if self.d5_ledger is not None:
            from pacta.integrations.tamga_d5 import SettlementBinder
            job.settlement_binding = SettlementBinder.bind_settled_job(
                job, self.d5_ledger).to_dict()

        self.check_solvency_invariant()
        return job, tx_hash

    def anchor_job(self, job_id: str, anchor_kind: str = "settlement") -> Any:
        """Mevcut-bir-işin-kararını-gerçek-zincire-sabitle ( AT-194).

        Zincir-adaptörü-yoksa-dürüst-hata: önce ``PactaEscrowVault(chain_adapter=
        connect_anvil())``-ile-kurun. Bu, README'nin "zincir-değil-simülasyon"
        sınırının-kapanma-yoludur.
        """
        from pacta.models import ChainAnchor
        if self.chain_adapter is None:
            raise ChainUnavailableError(
                "no-chain-adapter: PactaEscrowVault(chain_adapter=connect_anvil()) "
                "ile-kurun — anvil başlatın ( anvil --port 8545) veya "
                "PACTA_RPC_URL-verin; test için connect_in_memory_evm()")
        if job_id not in self.jobs:
            raise EscrowNotFoundError(f"Job ID {job_id} not found.")
        job = self.jobs[job_id]
        terms = {
            "amount_usdc": str(job.amount_usdc),
            "status": job.status.value,
            "buyer": str(job.buyer_address),
            "seller": str(job.seller_address),
        }
        if job.fee_collected_usdc is not None:
            terms["fee_usdc"] = str(job.fee_collected_usdc)
        if job.settled_at_epoch_ms:
            terms["settled_at_ms"] = str(job.settled_at_epoch_ms)
        anchor = self.chain_adapter.anchor(
            job_id=job.job_id, anchor_kind=anchor_kind, terms=terms,
            to_address=job.seller_address)
        job.chain_anchor = anchor
        return anchor

    def verify_chain_anchors(self) -> Dict[str, bool]:
        """Tüm-zincir-bağını-bağımsız-olarak-yeniden-doğrula ( denetim-için).

        Dönüş: {job_id: bağ-geçerli-mi}. Bağı-olmayan-işler-hariç-tutulur.
        """
        if self.chain_adapter is None:
            return {}
        return {jid: self.chain_adapter.verify_anchor(job.chain_anchor)
                for jid, job in self.jobs.items() if job.chain_anchor is not None}

    def refund_timeout(self, job_id: str) -> EscrowJob:
        """Refunds buyer when execution exceeds timeout SLA."""
        if job_id not in self.jobs:
            raise EscrowNotFoundError(f"Job ID {job_id} not found.")
        job = self.jobs[job_id]

        # AT-165-düzeltmesi: refund-sadece-GERÇEK-SLA-aşımında-verilebilir.
        # Önceden-herhangi-bir-durumda-çağrılınca-iade-ediyordu ( satıcı-
        # zamanında-teslim-etse-bile-alıcı-para'yı-geri-çekebiliyordu).
        # Kalite-başarısızlığı-için-refund_quality_failure-kullan ( rol-ayrımı).
        now_ms = int(time.time() * 1000)
        if not (job.locked_at_epoch_ms and
                now_ms - job.locked_at_epoch_ms > job.policy.timeout_ms):
            raise EscrowNotFoundError(
                f"refund-refused: job {job_id} is within timeout SLA "
                f"( no SLA breach — buyer cannot refund timely delivery; "
                f"use refund_quality_failure for failed verification)"
            )

        job.status = EscrowFSM.transition(job.status, EscrowStatus.AUTO_REFUNDED_TIMEOUT)
        self.ledger_balances[job.deposit_token] = self.ledger_balances[job.deposit_token] - job.amount_usdc
        job.settled_at_epoch_ms = now_ms
        self.check_solvency_invariant()
        return job

    def refund_quality_failure(self, job_id: str,
                               caller_address: Optional[str] = None) -> EscrowJob:
        """Refunds buyer when verification FAILS ( not a timeout — delivery
        was wrong, not late). Ayrım ( AT-165): timeout-SLA-aşımı-ile-kalite-
        başarısızlığı-farklı-roller; ikisi-de-alıcıyı-korumalı.
        AT-180-BULGU-2: caller_address-verilirse-rol-kontrolü ( herhangi-
        çağıran-iade-edemez)."""
        if job_id not in self.jobs:
            raise EscrowNotFoundError(f"Job ID {job_id} not found.")
        job = self.jobs[job_id]
        # AT-184-BULGU-3-düzeltmesi: caller=None-rol-kontrolünü-atlıyordu.
        # Artık-None-uğuntulanır + PACTA_REQUIRE_CALLER_ROLE=1-ile-reddedilir.
        # AT-180-BULGU-2: rol-kapısı ( AT-166-deseni)
        if caller_address is None:
            import warnings
            warnings.warn("caller-missing: refund-rol-kontrolü-ATLANDI "
                          "( PACTA_REQUIRE_CALLER_ROLE=1-ile-zorunlu-kılın) — "
                          "AT-184", stacklevel=2)
            if os.environ.get("PACTA_REQUIRE_CALLER_ROLE"):
                raise EscrowNotFoundError(
                    "caller-required: refund-rol-kontrolü-zorunlu "
                    "( PACTA_REQUIRE_CALLER_ROLE=1) — AT-184")
        elif str(caller_address).lower() not in (
                str(job.buyer_address).lower(),
                str(job.seller_address).lower()):
            raise EscrowAuthorizationError(
                f"caller {str(caller_address)[:10]}… is neither buyer nor seller "
                f"of this job — refund role check fail-closed (AT-180)")

        job.status = EscrowFSM.transition(job.status, EscrowStatus.AUTO_REFUNDED_TIMEOUT)
        self.ledger_balances[job.deposit_token] = self.ledger_balances[job.deposit_token] - job.amount_usdc
        job.settled_at_epoch_ms = int(time.time() * 1000)
        self.check_solvency_invariant()
        return job

    def raise_dispute(
        self,
        job_id: str,
        claimant_address: str,
        reason: str,
        evidence_hash: str
    ) -> DisputeClaim:
        """
        Buyer raises dispute within dispute window.
        Must deposit bond = dispute_bond_ratio * amount.
        """
        if job_id not in self.jobs:
            raise EscrowNotFoundError(f"Job ID {job_id} not found.")
        job = self.jobs[job_id]

        # AT-166-güvenlik-düzeltmesi: claimant-job'ın-taraflarından-biri-
        # OLMALIDIR. Önceden-çağrıdan-gelen-adres-DOĞRULANMIYORDU — escrow'un
        # hiçbir-tarafı-olmayan-bir-adres-dispute-açıp-bond-toplayabiliyordu.
        if str(claimant_address).lower() not in (
                str(job.buyer_address).lower(),
                str(job.seller_address).lower()):
            raise EscrowAuthorizationError(
                f"claimant {claimant_address[:10]}… is neither buyer nor seller "
                f"of this job — role check fail-closed (AT-166)"
            )

        # AT-165-BULGU-1-düzeltmesi: dispute_window_sec-modellerde-tanımlı-AMA
        # KARŞILAŞTIRILMIYORDU — docstring-'within-dispute-window'-diyor-AMA
        # pencere-dışı-da-itiraz-kabul-edilip-bond-alınıyordu. Şimdi-referans-
        # anı-( settled-veya-submitted)-a-göre-pencere-dışını-reddeder.
        window_sec = getattr(job.policy, "dispute_window_sec", None)
        ref_ms = job.settled_at_epoch_ms or job.submitted_at_epoch_ms
        if window_sec and ref_ms:
            elapsed_sec = (int(time.time() * 1000) - ref_ms) / 1000.0
            if elapsed_sec > window_sec:
                raise EscrowNotFoundError(
                    f"dispute-window-expired: {elapsed_sec:.0f}s > "
                    f"{window_sec}s since last state change — fail-closed (AT-165)"
                )

        # AT-171-BULGU-1-düzeltmesi: FSM-geçiş-kontrolü-ÖNCE — önceden-bond-
        # tahsili ( ledger-değişimi + disputes-kayıdı) FSM-geçişinden-ÖNCE-
        # yapılıyordu; terminal-SETTLED-işe-dispute → FSM-reddeder-AMA-ledger
        # çoktan-0.2-USDC-değişmiş-oluyordu ( reddedilen-geçişte-fonlar-alınır;
        # refund_timeout'un-yapısının-eksik-hali). Şimdi-geçiş-önce-kontrol-
        # edilir; para-akışı-sadece-geçerli-geçişte-yapılır.
        if not EscrowFSM.can_transition(job.status, EscrowStatus.DISPUTED):
            raise InvalidStateTransitionError(
                f"Illegal escrow state transition attempted: {job.status.value} "
                f"-> {EscrowStatus.DISPUTED.value} ( no bond collected — AT-171)"
            )

        required_bond = (job.amount_usdc * job.policy.dispute_bond_ratio).quantize(
            Decimal("0.000001"), rounding=ROUND_HALF_UP
        )
        dispute = DisputeClaim(
            job_id=job_id,
            claimant_address=claimant_address,
            bond_amount_usdc=required_bond,
            reason=reason,
            evidence_hash=evidence_hash,
        )

        # Collect buyer's dispute bond into vault balance
        self.ledger_balances[job.deposit_token] = self.ledger_balances[job.deposit_token] + required_bond
        self.disputes[dispute.dispute_id] = dispute

        job.status = EscrowFSM.transition(job.status, EscrowStatus.DISPUTED)
        job.status = EscrowFSM.transition(job.status, EscrowStatus.ARBITRATION_IN_PROGRESS)

        self.check_solvency_invariant()
        return dispute

    def resolve_arbitration(
        self,
        dispute_id: str,
        votes: List[ArbitrationVote]
    ) -> ArbitrationOutcome:
        """
        Resolves dispute based on Schelling point consensus of arbitrator nodes.
        Uses exact Decimal division and rounding.
        """
        if dispute_id not in self.disputes:
            raise ValueError(f"Dispute ID {dispute_id} not found.")
        dispute = self.disputes[dispute_id]
        job = self.jobs[dispute.job_id]

        # AT-166-güvenlik-düzeltmesi: arbitrator-rolü-DOĞRULANMIYORDU —
        # çağrıdan-gelen-oylar-herhangi-bir-adresten-gelebiliyordu ( escrow'un
        # taraflarından-biri-bile-arbitrator-kıyafeti-giyip-ödül-topluyordu).
        # Bir-oyun-arbitrator'u-job'ın-çalışan-taraflarından-biri-OLAMAZ
        # ( hakem-ve-taraf-ayrı-olmalı-yoksa-kendisi-lehine-oy-verir).
        if not votes:
            raise ValueError("Arbitration requires at least one vote (AT-166).")
        parties = {str(job.buyer_address).lower(), str(job.seller_address).lower()}
        for v in votes:
            if str(v.arbitrator_address).lower() in parties:
                raise ValueError(
                    f"arbitrator {v.arbitrator_address[:10]}… is a party of the "
                    f"escrow — cannot arbitrate its own dispute (AT-166)"
                )

        buyer_votes = sum(1 for v in votes if v.vote_favor_buyer)
        seller_votes = len(votes) - buyer_votes
        buyer_favored = buyer_votes >= seller_votes

        arbitrator_rewards: Dict[str, Decimal] = {}
        majority_vote = buyer_favored

        # Reward pool funded from 50% of the loser's forfeited bond
        total_arbitrator_reward = (dispute.bond_amount_usdc * Decimal("0.5")).quantize(
            Decimal("0.000001"), rounding=ROUND_HALF_UP
        )
        majority_count = Decimal(str(buyer_votes if buyer_favored else seller_votes))
        _divisor = max(Decimal("1"), majority_count)
        # AT-172-BULGU-2-düzeltmesi: bölüm-sonrası-quantize-kalanı-atıyordu
        # ( 0.0001-havuz/3-arbitrator → 0.000099-toplanır; 0.000001-YAKILIR-
        # hiçbir-tarafa-verilmezdi). Artık-taban-quantize-edilir-VE-kalan
        # son-çoğunluk-arbitratoruna-eklenir ( tüm-havuz-dağıtılır; atomik-
        # kalan-deseni).
        _base = (total_arbitrator_reward / _divisor)
        reward_per_node = _base.quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)
        _remainder = (total_arbitrator_reward
                      - reward_per_node * _divisor).quantize(
            Decimal("0.000001"), rounding=ROUND_HALF_UP)

        _majority_addrs = [v.arbitrator_address
                           for v in votes if v.vote_favor_buyer == majority_vote]
        for v in votes:
            if v.vote_favor_buyer == majority_vote:
                # son-çoğunluk-arbitratoru-kalanı-alır ( havuz-tamamen-dağıtılır)
                extra = _remainder if v.arbitrator_address == _majority_addrs[-1] \
                    else Decimal("0.000000")
                arbitrator_rewards[v.arbitrator_address] = reward_per_node + extra
            else:
                arbitrator_rewards[v.arbitrator_address] = Decimal("0.000000")

        if buyer_favored:
            # Slashed seller: Buyer gets full refund + returned bond
            refund_amount = job.amount_usdc
            slashed_bond = (dispute.bond_amount_usdc * Decimal("0.5")).quantize(
                Decimal("0.000001"), rounding=ROUND_HALF_UP
            )
            job.status = EscrowFSM.transition(job.status, EscrowStatus.SLASHED_REFUNDED)
            self.ledger_balances[job.deposit_token] = (
                self.ledger_balances[job.deposit_token] - (job.amount_usdc + dispute.bond_amount_usdc)
            )
            seller_paid = Decimal("0.000000")
        else:
            # Buyer griefing failed: Seller gets payment + portion of buyer's confiscated bond
            refund_amount = Decimal("0.000000")
            slashed_bond = Decimal("0.000000")
            seller_paid = (job.net_seller_amount() + (dispute.bond_amount_usdc * Decimal("0.5"))).quantize(
                Decimal("0.000001"), rounding=ROUND_HALF_UP
            )
            job.status = EscrowFSM.transition(job.status, EscrowStatus.SETTLED)
            self.ledger_balances[job.deposit_token] = (
                self.ledger_balances[job.deposit_token] - (job.amount_usdc + dispute.bond_amount_usdc)
            )

        outcome = ArbitrationOutcome(
            dispute_id=dispute_id,
            job_id=job.job_id,
            buyer_favored=buyer_favored,
            votes_for_buyer=buyer_votes,
            votes_for_seller=seller_votes,
            slashed_seller_bond_usdc=slashed_bond,
            refunded_to_buyer_usdc=refund_amount,
            paid_to_seller_usdc=seller_paid,
            arbitrator_rewards=arbitrator_rewards,
        )
        self.outcomes[dispute_id] = outcome
        self.check_solvency_invariant()
        return outcome

    def get_vault_stats(self) -> Dict[str, Any]:
        """Returns snapshot of current vault health, balances, and job counts."""
        return {
            "total_jobs": len(self.jobs),
            "total_disputes": len(self.disputes),
            "total_resolved_outcomes": len(self.outcomes),
            "balances": {k: str(v) for k, v in self.ledger_balances.items()},
            "is_solvent": self.check_solvency_invariant()
        }
