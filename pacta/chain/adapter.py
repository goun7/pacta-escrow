"""
EVM zincir-bağı-adaptörü ( AT-194).

Gerçek-bir-EVM-JSON-RPC'ye-bağlanır, settlement/dispute/arbitration-kararlarını
gerçek-transaction-ile-sabitleştirir ve bağı-bağımsız-olarak-yeniden-
doğrulanabilir-hale-getirir.

Mimari-seçim ( dürüst): değer-transferi-YAPMAYIZ ( 0-wei). Pacta'nın-fon-akışı
ledger-içinde-kalır — zincir-bağı **karar-taahhüdüdür**: alıcı/üçüncü-taraf
receipt-fetch-edip calldata'daki-keccak'i-teyit-ederek-Pacta'ya-güvenmeden-
doğrular. Bu, "zincir-simülasyonu" sınırının-dürüst-kapanışıdır ( tam-fon-
kusuru-değil; o-ayrı-bir-EVM-USDC-kontratı-işi-olurdu).
"""

from __future__ import annotations

import time
from typing import Any, Optional

from pacta.models import ChainAnchor

ANVIL_DEFAULT_RPC_URL = "http://127.0.0.1:8545"
ANVIL_DEFAULT_CHAIN_ID = 31337
_ANVIL_LAUNCH_HINT = (
    "anvir başlatmak için: anvil --port 8545 ( foundry) veya PACTA_RPC_URL="
    "http://127.0.0.1:8545 ile-herhangi-bir-EVM-node; zincir-yoksa-bu-çağrı-"
    "atlanabilir-zincir-modunda-çalışır ( uyarı-verilir)"
)


class ChainUnavailableError(RuntimeError):
    """Zincir-erişilemiyor — dürüst, actionable-hata ( sessiz-düşüş-DEĞİL)."""


class ChainProbeError(RuntimeError):
    """Zincir-probu-teknik-hata-verdi ( RPC-bozuk/yanıt-anlaşılmaz)."""


def probe_rpc(rpc_url: str, timeout: float = 2.0) -> dict:
    """En-düşük-seviye-canlılık-probu: eth_chainId-over-raw-JSON-RPC.

    Web3-bağlantı-kurmadan-hızlıca-öğrenir: node-ayakta-mı, EVM-mi?
    """
    import json
    import urllib.request

    payload = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "eth_chainId",
                          "params": []}).encode()
    req = urllib.request.Request(rpc_url, data=payload,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = json.loads(r.read().decode("utf-8", "replace"))
    except Exception as exc:  # noqa: BLE001 - probe-her-türlü-hatayı-yer
        raise ChainProbeError(
            f"rpc-unreachable: {rpc_url} — {type(exc).__name__}: {exc}. "
            f"{_ANVIL_LAUNCH_HINT}") from exc
    if "error" in body:
        raise ChainProbeError(
            f"rpc-error: {rpc_url} — {body['error']!r}. {_ANVIL_LAUNCH_HINT}")
    if "result" not in body:
        raise ChainProbeError(
            f"rpc-invalid-response: {rpc_url} — chainId-yok: {body!r}")
    try:
        chain_id = int(body["result"], 16)
    except (TypeError, ValueError) as exc:
        raise ChainProbeError(
            f"rpc-invalid-chainid: {rpc_url} — {body['result']!r}") from exc
    if chain_id <= 0:
        raise ChainProbeError(f"rpc-invalid-chainid: {rpc_url} — {chain_id}")
    return {"rpc_url": rpc_url, "chain_id": chain_id}


def _make_web3(rpc_url: str, timeout: float):
    from web3 import Web3
    from web3.providers.rpc import HTTPProvider
    return Web3(HTTPProvider(rpc_url, request_kwargs={"timeout": timeout}))


def connect_anvil(rpc_url: Optional[str] = None, timeout: float = 3.0) -> EvmChainAdapter:
    """Üretim-yolu: anvil veya herhangi-bir-EVM-JSON-RPC'ye-bağlan.

    Sıralama:
      1. ``rpc_url``-parametresi
      2. ``PACTA_RPC_URL``-ortam-değişkeni
      3. anvil-varsayılanı ``http://127.0.0.1:8545``

    Erişilemezse ``ChainUnavailableError`` — actionable-mesaj-ile ( anvil-
    başlatma-talimatı). Sessizce-simülasyona-düşmez.
    """
    import os

    url = rpc_url or os.environ.get("PACTA_RPC_URL") or ANVIL_DEFAULT_RPC_URL
    probe = probe_rpc(url, timeout=max(1.0, min(timeout, 2.0)))
    w3 = _make_web3(url, timeout)
    if not w3.is_connected():
        raise ChainUnavailableError(
            f"web3-not-connected: {url} ( probe-başarılı-AMA-web3.isConnected "
            f"False) — RPC'nin-JSON-RPC-2.0-EVM-node-olduğunu-doğrulayın")
    return EvmChainAdapter(w3=w3, backend="anvil", rpc_url=probe["rpc_url"])


def connect_in_memory_evm(chain_id_hint: int = 1337) -> EvmChainAdapter:
    """Gerçek-in-memory-EVM ( py-evm-via-EthereumTesterProvider).

    Sıfır-kurulum: gerçek-EVM-semantiği ( gerçek-tx-hash, gerçek-block, gerçek
    receipt, gerçek-gas) — anvil-ayakta-değilse-bile-zincir-bağı-yolu-test-
    edilebilir. Production'da-anvil-kullanılır.
    """
    try:
        from web3 import Web3, EthereumTesterProvider
    except Exception as exc:  # noqa: BLE001
        raise ChainUnavailableError(
            f"in-memory-evm-unavailable: web3-kurulu-değil — {exc}. "
            "pip install web3 eth-tester py-evm") from exc
    try:
        w3 = Web3(EthereumTesterProvider())
    except Exception as exc:  # noqa: BLE001
        raise ChainUnavailableError(
            f"in-memory-evm-init-failed: py-evm-backend-eksik — {exc}. "
            "pip install py-evm eth-tester") from exc
    if not w3.is_connected():
        raise ChainUnavailableError("in-memory-evm-not-connected")
    return EvmChainAdapter(w3=w3, backend="in-memory-pyevm", rpc_url="memory://py-evm")


class EvmChainAdapter:
    """Gerçek-EVM-zincirine-bağ-koyucu.

    Bağlama-semantiği: ``anchor(...)``-bir-transaction-gönderir-calldata=
    keccak256(canonical-commitment), receipt-bekler, ``ChainAnchor``-döner.
    Operatör-hesabı-önceden-finanse-edilmiş-olmalıdır ( anvil/eth-tester-varsayılan
    hesapları-finanse-edilmiş-ve-kilitsizdir; PRIVATE_KEY-GEREKMEZ).
    """

    def __init__(self, w3: Any, backend: str, rpc_url: str,
                 operator_account: Optional[str] = None,
                 receipt_timeout_s: float = 30.0):
        self.w3 = w3
        self.backend = backend
        self.rpc_url = rpc_url
        self.receipt_timeout_s = receipt_timeout_s
        self._operator = operator_account

    # ------------------------------------------------------------------ canlılık

    def chain_id(self) -> int:
        return int(self.w3.eth.chain_id)

    def operator_account(self) -> str:
        """Gönderici-hesap: kilitsiz-finanse-edilmiş-hesap ( PRIVATE_KEY-YOK).

        Seçim: ``operator_account``-verildiyse-o; yoksa-eth_accounts[0].
        Hesap-yoksa-dürüst-hata ( anvil --unlock veya-fon-transferi-gerekir).
        """
        if self._operator is not None:
            return self._operator
        try:
            accts = self.w3.eth.accounts
        except Exception as exc:  # noqa: BLE001
            raise ChainUnavailableError(
                f"accounts-unavailable: {self.rpc_url} — {type(exc).__name__}: "
                f"{exc}. anvil --unlock <addr> veya-önceden-finanse-edilmiş-"
                f"kilitsiz-hesap-gerekir ( PRIVATE_KEY-istenmez)") from exc
        if not accts:
            raise ChainUnavailableError(
                f"no-unlocked-accounts: {self.rpc_url} — anvil'i "
                f"'--unlock 0' ile-başlatın veya-PACTA_OPERATOR_ACCOUNT-verin "
                f"( private-key-YASAK; yalnız-kilitsiz-hesap)")
        self._operator = str(accts[0])
        return self._operator

    # -------------------------------------------------------------- bağlama

    @staticmethod
    def build_commitment(job_id: str, anchor_kind: str, terms: dict) -> bytes:
        """Deterministik-taahhüt: keccak256-over-sabit-sıralı-kanonik-alanlar.

        Sabit-sıralı ( K0-disiplini, Sester-receipt-ile-aynı-yaklaşım): alıcılar
        bu-sözleşmeyi-bilir; değişiklik = yeni-sürüm.
        """
        from web3 import Web3

        parts = [f"PACTA:v1:{anchor_kind}:{job_id}"]
        for key in sorted(terms):
            parts.append(f"{key}={terms[key]}")
        return Web3.keccak(text="|".join(parts))

    def anchor(self, job_id: str, anchor_kind: str, terms: dict,
               to_address: Optional[str] = None) -> ChainAnchor:
        """Karar-taahhüdünü-gerçek-zincire-sabitle.

        ``anchor_kind``: settlement | dispute | arbitration | refund
        ``terms``      : kanonik-alanlar ( amount_usdc, fee, net_seller, ...)
        ``to_address`` : alıcı ( varsayılan: operatör-kendisi = self-anchor;
                         satıcı-verilirse-onun-adına-kayıt)
        """
        if anchor_kind not in ("settlement", "dispute", "arbitration", "refund"):
            raise ValueError(
                f"anchor-kind-invalid: {anchor_kind!r} — settlement|dispute|"
                f"arbitration|refund-bekleniyor")
        if not isinstance(terms, dict) or not terms:
            raise ValueError("terms-required: boş-sözlük-bağlanamaz")

        commitment = self.build_commitment(job_id, anchor_kind, terms)
        operator = self.operator_account()
        recipient = to_address or operator
        try:
            tx_hash = self.w3.eth.send_transaction({
                "from": operator,
                "to": recipient,
                "value": 0,          # 0-wei: para-harcama-YASAK — taahhüt-bağı
                "data": commitment,
            })
            receipt = self.w3.eth.wait_for_transaction_receipt(
                tx_hash, timeout=self.receipt_timeout_s)
        except Exception as exc:  # noqa: BLE001
            raise ChainUnavailableError(
                f"anchor-failed: {self.rpc_url} — {type(exc).__name__}: {exc}. "
                f"Operatör-hesabın-gas'i-var-mı? ( anvil-varsayılan-hesaplar-"
                f"finanse-edilmiş; mainnet-YASAK)") from exc

        status = int(receipt.get("status", 1) or 1)
        # EVM-status: 1=başarılı, 0=revert. Bazı-backendler-True/False-döner.
        if isinstance(status, bool):
            status = 1 if status else 0
        # web3-8.x: send_transaction-HexBytes-döner; str()-bozuk-bytes-repr-
        # verir ( "b'\\xff…'"). HexBytes-durumunda-to_hex-ile-0x-hex'e-
        # normalleştirilmeli — yoksa-tx_hash-zincirden-fetch-edilemez.
        from web3 import Web3 as _W3
        tx_hash_hex = _W3.to_hex(tx_hash) if not isinstance(tx_hash, str) else tx_hash
        anchor = ChainAnchor(
            chain_id=self.chain_id(),
            tx_hash=tx_hash_hex,
            block_number=int(receipt.get("blockNumber", 0)),
            gas_used=int(receipt.get("gasUsed", 0)),
            anchor_kind=anchor_kind,
            job_id=job_id,
            commitment_keccak="0x" + commitment.hex(),
            anchored_at_epoch_ms=int(time.time() * 1000),
            from_address=operator,
            to_address=recipient,
            rpc_url=self.rpc_url,
            backend=self.backend,
            tx_status=status,
        )
        if status != 1:
            raise ChainUnavailableError(
                f"anchor-reverted: tx {anchor.tx_hash} status=0 ( EVM-revert) "
                f"— bağı-başarısız; tekrar-deneyin")
        return anchor

    def verify_anchor(self, anchor: ChainAnchor) -> bool:
        """Bağı-bağımsız-yeniden-doğrula ( receipt-fetch + calldata-teyiti)."""
        if anchor.chain_id != self.chain_id():
            return False
        return bool(anchor.verify_against_chain(self.w3))
