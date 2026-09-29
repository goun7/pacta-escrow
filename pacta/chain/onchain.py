"""Pacta on-chain emanet yaşam-döngüsü ( AT-195).

DÜRÜST-SINIR-KAPANIŞI: ``pacta/contracts/PactaEscrowVault.sol`` gerçek-bir
EVM-zincirinde ( anvil — mainnet DEĞİL) derlenir, deploy edilir ve emanet
koşulları **on-chain** yürütülür. Bu modül şu yaşam-döngüleri çalıştırır:

  1. lock   : buyer, USDC approve + ``depositAndLock`` → on-chain ``Locked``
  2. submit : seller, ``submitOutput(outputHash)`` → ``OutputSubmitted``
  3. settle : buyer|seller, ``settle`` → net-seller + fee-transfer'leri
  4. dispute: buyer, ``raiseDispute`` ( %20-bond) → ``Disputed``
  5. resolve: arbitrator-oracle, ``resolveDispute`` → SLASH|SETTLE

Kısıtlar ( KISITLAR-bölümü-ile-birebir):
  - PRIVATE_KEY-KULLANILMAZ: yalnızca-anvil'in-kilitsiz-finanse-edilmiş
    hesapları ( ``eth_sendTransaction``-ile-anvil-kendisi-imzalar).
  - MAINNET-YASAK: ``connect_anvil``-üzerinden-gelir; chain_id-31337-dışı-
    gerçek-zincirlerde-çalışmaz ( bkz. ``assert_anvil_like``).
  - PARA-HARCAMA-YOK: MockUSDC-anvil-test-musluğundan-basilir ( 0-değerli).
"""

from __future__ import annotations

import json
import os
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from pacta.chain.adapter import EvmChainAdapter, ChainUnavailableError

# Foundry-artifacts: ``onchain/``-dizini-derleme-sonrası-oluşur.
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_FORGE_OUT = _REPO_ROOT / "onchain" / "out"


@dataclass
class OnchainStep:
    """Tek-bir-on-chain-adımın-kanıtı ( tx-hash + event'ler + on-chain-durum)."""
    name: str
    tx_hash: str
    block_number: int
    gas_used: int
    status: int
    events: List[str] = field(default_factory=list)
    onchain_status: Optional[str] = None
    detail: str = ""


@dataclass
class OnchainLifecycleResult:
    """Tam-on-chain-emanet-yaşam-döngüsünün-sonucu."""
    chain_backend: str
    chain_id: int
    vault_address: str
    usdc_address: str
    arbitrator_oracle: str
    steps: List[OnchainStep] = field(default_factory=list)

    @property
    def tx_hashes(self) -> List[str]:
        return [s.tx_hash for s in self.steps]

    def step(self, name: str) -> OnchainStep:
        for s in self.steps:
            if s.name == name:
                return s
        raise KeyError(f"on-chain-step-yok: {name!r}")


class OnchainContractError(RuntimeError):
    """On-chain-kontrat-çalışma-hatası ( revert/decode/deploy)."""


def _load_artifact(contract_name: str) -> Dict[str, Any]:
    path = _FORGE_OUT / f"{contract_name}.sol" / f"{contract_name}.json"
    if not path.exists():
        raise OnchainContractError(
            f"forge-artifact-yok: {path} — 'onchain/' dizininde "
            f"'forge build' çalıştırın (PATH'e anvil/forge ekleyin)")
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def assert_anvil_like(adapter: EvmChainAdapter) -> int:
    """MAINNET-KORUMA: yalnızca-anvil-benzeri-yerel-zincirlerde-çalışır.

    chain_id 1337/31337 veya yerel-test-zincirleri-olmalı; gerçek bir ağda
    ( mainnet/goerli/… ) PARA-HARCAMA-ve-PRIVATE_KEY-YASAK-olduğu-için-reddeder.
    """
    chain_id = int(adapter.chain_id())
    allowed = {1337, 31337, 31338, 1234, 8545}
    if chain_id not in allowed:
        raise OnchainContractError(
            f"mainnet-protection: chain_id={chain_id} anvil-benzeri-değil "
            f"( izinverilenler: {sorted(allowed)}) — gerçek-zincir-YASAK")
    return chain_id


def _receipt(adapter: EvmChainAdapter, tx_hash: Any) -> Dict[str, Any]:
    from web3 import Web3
    h = Web3.to_hex(tx_hash) if not isinstance(tx_hash, str) else tx_hash
    receipt = adapter.w3.eth.wait_for_transaction_receipt(h, timeout=adapter.receipt_timeout_s)
    return dict(receipt)


def _event_names(contract: Any) -> List[str]:
    """Kontrat-ABI'sindeki-event-isimlerini-döner."""
    return [e["name"] for e in contract.abi if e.get("type") == "event"]


def _events_from(receipt: Dict[str, Any], contract: Any) -> List[str]:
    """Receipt-log'larını-kontrat-event'lerine-göre-decode-et.

    web3-8.x-UYUMLULUK: ``contract.events.process_log(log)``-artık-YOK ( 5.x-
    API'siydi — çağrılınca ``ABIEventNotFound: 'process_log'``-fırlatır, bu
    yüzden ``events=[]``-dönüyordu). Doğru-yol: her-event-için-ayrı-ayrı
    ``contract.events.<EventName>().process_log(log)``-denenir; topic'i-
    uymayanlar-zaten-hata-fırlatır. Eşleşmeyen-log'lar ( örn. MockUSDC'nin
    ERC20-Transfer'i) sessizce-atlanır.
    """
    events: List[str] = []
    names = _event_names(contract)
    for log in receipt.get("logs", []):
        for name in names:
            try:
                decoded = getattr(contract.events, name)().process_log(log)
            except Exception:  # noqa: BLE001 - topic-uyuşmazlığı/tanımsız-log
                continue
            if decoded is not None:
                events.append(decoded.get("event", name))
                break
    return events


class OnchainEscrowRunner:
    """Anvil-üzerinde-gerçek-PactaEscrowVault-yaşam-döngüsü-çalıştırıcısı.

    Kurulum: ``runner = OnchainEscrowRunner(adapter)`` → ``deploy()``-ile
    MockUSDC + PactaEscrowVault-deploy-edilir. Ardından ``run_happy_path()``
    ve ``run_dispute_path()``-ile-on-chain-emanet-yürütülür.
    """

    # Kontratın-enum-indeksleri ( PactaEscrowVault.sol: EscrowStatus)
    _S = {"Uninitialized": 0, "Locked": 1, "OutputSubmitted": 2, "Verified": 3,
          "Settled": 4, "Disputed": 5, "Refunded": 6}

    def __init__(self, adapter: EvmChainAdapter):
        self.adapter = adapter
        self.chain_id = assert_anvil_like(adapter)
        self.w3 = adapter.w3
        self._usdc: Any = None
        self._vault: Any = None
        self.usdc_address: Optional[str] = None
        self.vault_address: Optional[str] = None
        self.oracle: Optional[str] = None

    # -------------------------------------------------------------- deploy

    def _deploy(self, name: str, *ctor_args) -> str:
        from web3 import Web3
        art = _load_artifact(name)
        contract = self.w3.eth.contract(
            abi=art["abi"], bytecode=art["bytecode"]["object"])
        operator = self.adapter.operator_account()
        tx_hash = contract.constructor(*ctor_args).transact({"from": operator})
        receipt = self.w3.eth.wait_for_transaction_receipt(
            Web3.to_hex(tx_hash), timeout=self.adapter.receipt_timeout_s)
        if int(receipt.get("status", 0) or 0) != 1:
            raise OnchainContractError(
                f"deploy-revert: {name} status={receipt.get('status')}")
        addr = receipt.get("contractAddress")
        if not addr:
            raise OnchainContractError(f"deploy-address-yok: {name}")
        return str(addr)

    def deploy(self) -> OnchainLifecycleResult:
        """MockUSDC + PactaEscrowVault-deploy-et ( anvil'in-kilitsiz-hesapları)."""
        if self.vault_address is not None:
            return self._result()
        self.usdc_address = self._deploy("MockUSDC")
        self.oracle = self.adapter.operator_account()
        # vault: ( usdcToken, protocolTreasury, arbitratorOracle)
        self.vault_address = self._deploy(
            "PactaEscrowVault", self.usdc_address, self.oracle, self.oracle)
        art_v = _load_artifact("PactaEscrowVault")
        art_u = _load_artifact("MockUSDC")
        self._vault = self.w3.eth.contract(address=self.vault_address, abi=art_v["abi"])
        self._usdc = self.w3.eth.contract(address=self.usdc_address, abi=art_u["abi"])
        return self._result()

    def _result(self) -> OnchainLifecycleResult:
        return OnchainLifecycleResult(
            chain_backend=self.adapter.backend,
            chain_id=self.chain_id,
            vault_address=str(self.vault_address),
            usdc_address=str(self.usdc_address),
            arbitrator_oracle=str(self.oracle),
        )

    # ---------------------------------------------------------------- yardımcı

    def _mint(self, to: str, amount: int) -> None:
        op = self.adapter.operator_account()
        tx = self._usdc.functions.faucet(to, amount).transact({"from": op})
        self._wait(tx)

    def _wait(self, tx_hash: Any) -> Dict[str, Any]:
        from web3 import Web3
        return dict(self.w3.eth.wait_for_transaction_receipt(
            Web3.to_hex(tx_hash), timeout=self.adapter.receipt_timeout_s))

    def _record(self, name: str, receipt: Dict[str, Any],
                onchain_status: Optional[str] = None,
                detail: str = "") -> OnchainStep:
        status = receipt.get("status")
        if isinstance(status, bool):
            status = 1 if status else 0
        ev = _events_from(receipt, self._vault) if self._vault is not None else []
        # web3-8.x: transactionHash-HexBytes-döner; str()-bozuk-bytes-repr-
        # verir ( "b'\\x0f1…'") ve-receipt-fetch-edilemez. to_hex-ile-normalle.
        from web3 import Web3
        tx_hash = receipt.get("transactionHash")
        return OnchainStep(
            name=name,
            tx_hash=Web3.to_hex(tx_hash) if not isinstance(tx_hash, str) else tx_hash,
            block_number=int(receipt.get("blockNumber", 0)),
            gas_used=int(receipt.get("gasUsed", 0)),
            status=int(status or 0),
            events=ev,
            onchain_status=onchain_status,
            detail=detail,
        )

    def _status_field_index(self) -> int:
        """ABI'den ``EscrowAgreement.status``-alanının-pozisyonunu-çıkar.

        web3-8.x bir-struct'ı-pozisyonel-bir-liste-olarak-döndürür ( dict-DEĞİL),
        bu yüzden ``status``-için-indeksi-sabit-kodlamak-yerine-ABI'dan-okuruz
        ( alan-sırası-değişirse-bozulmaz). İki-temsil desteklenir:
          * forge-artifact: struct-çıktısı-düz-liste-olarak ( her-alan-ayrı-output)
          * kanonik-ABI    : tek-bir ``tuple``-output-``components``-ile.
        """
        for entry in _load_artifact("PactaEscrowVault")["abi"]:
            if (entry.get("name") != "escrows"
                    or entry.get("type") != "function"
                    or not entry.get("outputs")):
                continue
            outputs = entry["outputs"]
            # ( a) kanonik-ABI: tek-tuple
            if len(outputs) == 1 and outputs[0].get("components"):
                for i, comp in enumerate(outputs[0]["components"]):
                    if comp.get("name") == "status":
                        return i
            # ( b) forge-artifact: düz-alan-listesi
            for i, out in enumerate(outputs):
                if out.get("name") == "status":
                    return i
        raise OnchainContractError(
            "abi-çözümleme-hatası: PactaEscrowVault.escrows.status-alanı-yok "
            "— 'forge build'-sonrası-artifact-güncel-mi?")

    def _onchain_status(self, job_id: str) -> str:
        """web3-8.x: struct'ları-pozisyonel-liste-olarak-döner ( status=son-alan).

        HATA-GEÇMİŞİ: eski-kod ``raw[6]``-okuyordu ( bu ``outputHash``'dir,
        ``status``-DEĞİL) ve ``int(bytes)``-ValueError-fırlatınca-``except``-
        kolunda ``idx=6``-atıyor-du → **her-sonuç-"Refunded"-dönüyordu**.
        Doğru-indeks-ABI'dan-çıkarılır ve-hata-durumunda-güvenli-varsayılan
        ``0``=Uninitialized'dır ( 6=Refunded-DEĞİL).
        """
        raw = self._vault.functions.escrows(job_id).call()
        if isinstance(raw, dict):
            idx = int(raw.get("status", 0))
        elif isinstance(raw, (list, tuple)):
            try:
                idx = int(raw[self._status_field_index()])
            except (TypeError, ValueError, IndexError):
                idx = 0
        else:
            idx = 0
        for label, i in self._S.items():
            if i == idx:
                return label
        return f"Unknown({idx})"

    @staticmethod
    def _job_id_bytes32(job_id: str) -> bytes:
        from web3 import Web3
        return Web3.to_bytes(text=job_id).ljust(32, b"\x00")[:32]

    @staticmethod
    def _new_job_id(prefix: str) -> str:
        """Her-çağrıda-UNIQUE-job-id ( uuid4) — job_id-ÇAKIŞMASI-kapandı.

        HATA-GEÇMİŞİ: eski-kod ``f"pacta-happy-{chain_id}-{len(res.steps)}"``
        kullanıyordu; ``res.steps``-o-ana-kadar-her-zaman-boş-olduğu-için-
        sonuç-her-zaman ``pacta-happy-31337-0``-oluyordu. Aynı-runner'la-ikinci
        bir-çalıştırma AYNI-slot'a-yazıyor, ``depositAndLock``-``InvalidStatus``
        ile-revert-ediyor ve-eski-slot-okunuyordu. uuid4-ile-çakışma-ihtimali
        ~0 ( 8-hex-karakter-uzaylığı).
        """
        return f"{prefix}-{uuid.uuid4().hex[:8]}"

    # --------------------------------------------------------------- yollar

    def run_happy_path(self, buyer: str, seller: str, amount: int = 10_000_000,
                       timeout_seconds: int = 3600,
                       schema_hash: Optional[bytes] = None) -> OnchainLifecycleResult:
        """lock → submit → settle ( on-chain DvP): para-akışı-ERC20-transfer'leri.

        ``amount`` 6-desimal-USDC'dir ( 10_000_000 = 10 USDC). Gerçek-değer-
        DEĞİL — anvil-MockUSDC-musluğundan-basilir.
        """
        self.deploy()
        res = self._result()
        buyer_op = buyer or self.adapter.operator_account()
        schema = schema_hash or bytes(32)

        # 1) buyer'a-USDC-bas + vault'a-approve-et
        self._mint(buyer_op, amount * 2)
        approve = self._usdc.functions.approve(self.vault_address, amount).transact(
            {"from": buyer_op})
        self._wait(approve)

        # 2) depositAndLock — UNIQUE-job_id ( uuid4): eski-slot-çakışması-YOK
        jb = self._job_id_bytes32(self._new_job_id(f"pacta-happy-{self.chain_id}"))
        lock_tx = self._vault.functions.depositAndLock(
            jb, seller, amount, timeout_seconds, schema).transact({"from": buyer_op})
        res.steps.append(self._record(
            "deposit_and_lock", self._wait(lock_tx),
            onchain_status=self._onchain_status(jb),
            detail=f"amount={amount} buyer={buyer_op[:10]}… seller={seller[:10]}…"))

        # 3) submitOutput ( seller)
        output_hash = self._keccak(b"pacta-output-happy")
        sub_tx = self._vault.functions.submitOutput(jb, output_hash).transact(
            {"from": seller})
        res.steps.append(self._record(
            "submit_output", self._wait(sub_tx),
            onchain_status=self._onchain_status(jb),
            detail=f"outputHash=0x{output_hash.hex()[:16]}…"))

        # 4) settle ( buyer)
        settle_tx = self._vault.functions.settle(jb).transact({"from": buyer_op})
        res.steps.append(self._record(
            "settle", self._wait(settle_tx),
            onchain_status=self._onchain_status(jb),
            detail="DvP-tamamlandı: net-seller + fee-dağıtıldı"))

        # on-chain-solvency: kilitsiz-kalıcı-bakiye-beklenmez ( hepsi-dağıtıldı)
        res.steps[-1].detail += (
            f" | vaultUSDC={self._usdc.functions.balanceOf(self.vault_address).call()}")
        return res

    def run_dispute_path(self, buyer: str, seller: str, amount: int = 10_000_000,
                         buyer_favored: bool = True) -> OnchainLifecycleResult:
        """lock → submit → dispute → resolve ( Schelling-sonucu-on-chain-icra).

        ``buyer_favored``: hakemlik-kararı ( true=SLASH&refund, false=seller'e-öde).
        """
        self.deploy()
        res = self._result()
        buyer_op = buyer or self.adapter.operator_account()

        self._mint(buyer_op, amount * 3)
        approve = self._usdc.functions.approve(
            self.vault_address, amount + amount // 5 + 1).transact({"from": buyer_op})
        self._wait(approve)

        jb = self._job_id_bytes32(self._new_job_id(f"pacta-dispute-{self.chain_id}"))
        lock_tx = self._vault.functions.depositAndLock(
            jb, seller, amount, 3600, bytes(32)).transact({"from": buyer_op})
        res.steps.append(self._record(
            "deposit_and_lock", self._wait(lock_tx),
            onchain_status=self._onchain_status(jb)))

        output_hash = self._keccak(b"pacta-output-dispute")
        sub_tx = self._vault.functions.submitOutput(jb, output_hash).transact(
            {"from": seller})
        res.steps.append(self._record(
            "submit_output", self._wait(sub_tx),
            onchain_status=self._onchain_status(jb)))

        # raiseDispute: %20-bond ( DISPUTE_BOND_BPS=2000)
        bond = amount * 2000 // 10000
        dis_tx = self._vault.functions.raiseDispute(jb).transact({"from": buyer_op})
        res.steps.append(self._record(
            "raise_dispute", self._wait(dis_tx),
            onchain_status=self._onchain_status(jb),
            detail=f"bond={bond} ( %20-anti-griefing)"))

        # resolveDispute: yalnızca-arbitrator-oracle-çağırabilir
        res_tx = self._vault.functions.resolveDispute(jb, buyer_favored).transact(
            {"from": self.oracle})
        res.steps.append(self._record(
            "resolve_dispute", self._wait(res_tx),
            onchain_status=self._onchain_status(jb),
            detail=("buyer_favored=SLASH&refund" if buyer_favored
                    else "seller_favored=öde+bonun-yarısı")))
        return res

    def run_timeout_refund_path(self, buyer: str, seller: str,
                                amount: int = 10_000_000) -> OnchainLifecycleResult:
        """lock → ( SLA-aşımı) → claimTimeoutRefund ( alıcı-iadesi)."""
        self.deploy()
        res = self._result()
        buyer_op = buyer or self.adapter.operator_account()
        self._mint(buyer_op, amount * 2)
        approve = self._usdc.functions.approve(self.vault_address, amount).transact(
            {"from": buyer_op})
        self._wait(approve)

        jb = self._job_id_bytes32(self._new_job_id(f"pacta-timeout-{self.chain_id}"))
        lock_tx = self._vault.functions.depositAndLock(
            jb, seller, amount, 1, bytes(32)).transact({"from": buyer_op})
        res.steps.append(self._record(
            "deposit_and_lock", self._wait(lock_tx),
            onchain_status=self._onchain_status(jb),
            detail="timeoutSeconds=1 ( SLA-penceresi-kısa)"))

        # anvil'de-zamanı-ileri-al: 2-saniye-bekle ( block-time-1s) veya-evm_mine
        self._advance_time(3)
        refund_tx = self._vault.functions.claimTimeoutRefund(jb).transact(
            {"from": buyer_op})
        res.steps.append(self._record(
            "claim_timeout_refund", self._wait(refund_tx),
            onchain_status=self._onchain_status(jb),
            detail="SLA-aşımı → alıcıya-tam-iade"))
        return res

    # ----------------------------------------------------- anvil-zaman-yardımcı

    def reset_chain(self) -> None:
        """Anvil-özel: ``anvil_reset``-ile-zinciri-genesis'e-sıfırla.

        Test-izolasyonu: her-testin-önce-çağırması-gerekir-ki-önceki-test'in
        bıraktığı job-slotları/kontratlar/bakiyeler-kalmasın ( aksi-halde
        eski-``pacta-happy-31337-0``-gibi-slotlar-okunabilir). Deploy-cache'i-de
        boşaltılır-ki-sonraki-çağrı-taze-MockUSDC+vault-deploy-etsin.
        """
        try:
            self.w3.provider.make_request("anvil_reset", [])
        except Exception as exc:  # noqa: BLE001
            raise OnchainContractError(
                f"anvil-reset-unavailable: {type(exc).__name__}: {exc} — "
                f"yalnızca-anvil/in-memory-EVM'de-desteklenir") from exc
        self._usdc = None
        self._vault = None
        self.vault_address = None
        self.usdc_address = None
        self.oracle = None

    def _advance_time(self, seconds: int) -> None:
        """Anvil-özel: ``evm_increaseTime`` + ``evm_mine``-ile-zamanı-ileri-al."""
        try:
            self.w3.provider.make_request("evm_increaseTime", [seconds])
            self.w3.provider.make_request("evm_mine", [])
        except Exception as exc:  # noqa: BLE001
            raise OnchainContractError(
                f"time-travel-unavailable: {type(exc).__name__}: {exc} — "
                f"yalnızca-anvil/in-memory-EVM'de-desteklenir") from exc

    @staticmethod
    def _keccak(data: bytes) -> bytes:
        from web3 import Web3
        return Web3.keccak(data)
