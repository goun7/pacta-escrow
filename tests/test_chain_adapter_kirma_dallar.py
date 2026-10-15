"""chain/adapter EVM-zincir-bagi dal-kesen testleri (LEED).

Kapsanan modul: pacta/chain/adapter.py
  - probe_rpc: eth_chainId raw-JSON-RPC probu (tum hata dallari)
  - _make_web3 / connect_anvil: baglama-oncelikleri, probe+web3-catisi
  - EvmChainAdapter: operator_account, build_commitment, anchor (kind/terms/
    send-hatalari, receipt-status 0/1/None, tx-hash byte/str normalizasyonu),
    verify_anchor (chain-id farki, receipt/data tutarsizligi)

Kural-1: mevcut testlere/conftest'e/uretime DOKUNULMADI — SADECE bu yeni
dosya eklendi.
Saf-bellek: TUM w3 etkilesimleri yerel STUB (gercek RPC/py-evm YOK;
urlopen monkeypatch ile degistirildi) — ag/DNS/socket/gercek-subprocess YOK.
"""
import io
import json

import pytest
from web3 import Web3

from pacta.chain.adapter import (
    ANVIL_DEFAULT_CHAIN_ID,
    ANVIL_DEFAULT_RPC_URL,
    ChainProbeError,
    ChainUnavailableError,
    EvmChainAdapter,
    _make_web3,
    connect_anvil,
    probe_rpc,
)
from pacta.models import ChainAnchor

_OP = "0x" + "11" * 20
_OTHER = "0x" + "22" * 20


# ------------------------------------------------------------------ stub w3

class _Eth:
    """Yerel stub: gercek node YOK — tum davranislar test tarafindan belirlenir."""

    def __init__(self, *, chain_id=1337, accounts=(_OP, _OTHER),
                 receipt=None, tx=None, tx_hash=None,
                 send_error=None, receipt_error=None,
                 receipt_lookup_error=None, tx_lookup_error=None):
        self._chain_id = chain_id
        self._accounts = accounts
        self._receipt = receipt
        self._tx = tx
        self._tx_hash = tx_hash
        self._send_error = send_error
        self._receipt_error = receipt_error
        self._receipt_lookup_error = receipt_lookup_error
        self._tx_lookup_error = tx_lookup_error
        self._last_tx_data = None      # send_transaction'in girdisi 'zincirde'

    @property
    def chain_id(self):
        return self._chain_id

    @property
    def accounts(self):
        if isinstance(self._accounts, Exception):
            raise self._accounts
        return list(self._accounts)

    def send_transaction(self, tx):
        if self._send_error is not None:
            raise self._send_error
        self._last_tx_data = tx["data"]
        return self._tx_hash

    def wait_for_transaction_receipt(self, tx_hash, timeout=None):
        if self._receipt_error is not None:
            raise self._receipt_error
        return self._receipt

    def get_transaction_receipt(self, tx_hash):
        if self._receipt_lookup_error is not None:
            raise self._receipt_lookup_error
        return self._receipt

    def get_transaction(self, tx_hash):
        if self._tx_lookup_error is not None:
            raise self._tx_lookup_error
        sonuc = dict(self._tx) if self._tx is not None else {}
        if self._last_tx_data is not None:
            sonuc["input"] = self._last_tx_data
        return sonuc


class _W3:
    def __init__(self, **eth_kw):
        self.eth = _Eth(**eth_kw)
        self.connected = True

    def is_connected(self):
        return self.connected


class _Uzman:
    """urlopen stub: HTTP-YOK — govde dogrudan verilir."""

    def __init__(self, body=None, exc=None):
        self._body = body
        self._exc = exc
        self.calls = []

    def __call__(self, req, timeout=None):
        self.calls.append({"url": req.full_url if hasattr(req, "full_url")
                           else str(req), "timeout": timeout})
        if self._exc is not None:
            raise self._exc
        return self

    def __enter__(self):
        return io.BytesIO(json.dumps(self._body).encode("utf-8")) \
            if not isinstance(self._body, bytes) else io.BytesIO(self._body)

    def __exit__(self, *a):
        return False


def _adapter(**eth_kw) -> EvmChainAdapter:
    return EvmChainAdapter(w3=_W3(**eth_kw), backend="stub",
                           rpc_url="stub://test")


def _ok_receipt(**ayir):
    esas = {"status": 1, "blockNumber": 5, "gasUsed": 21000}
    esas.update(ayir)
    return esas


# ================================================================== probe_rpc

def test_probe_gecerli(monkeypatch):
    u = _Uzman(body={"jsonrpc": "2.0", "id": 1, "result": "0x539"})
    monkeypatch.setattr("urllib.request.urlopen", u)
    out = probe_rpc("http://x:8545")
    assert out == {"rpc_url": "http://x:8545", "chain_id": 1337}


def test_probe_url_erisilemez(monkeypatch):
    u = _Uzman(exc=OSError("connection refused"))
    monkeypatch.setattr("urllib.request.urlopen", u)
    with pytest.raises(ChainProbeError, match="rpc-unreachable"):
        probe_rpc("http://x:8545")


def test_probe_govdesinde_hata(monkeypatch):
    u = _Uzman(body={"jsonrpc": "2.0", "id": 1,
                     "error": {"code": -32601, "message": "no method"}})
    monkeypatch.setattr("urllib.request.urlopen", u)
    with pytest.raises(ChainProbeError, match="rpc-error"):
        probe_rpc("http://x:8545")


def test_probe_result_yok(monkeypatch):
    u = _Uzman(body={"jsonrpc": "2.0", "id": 1})
    monkeypatch.setattr("urllib.request.urlopen", u)
    with pytest.raises(ChainProbeError, match="rpc-invalid-response"):
        probe_rpc("http://x:8545")


def test_probe_chainid_tip_hatasi(monkeypatch):
    """result int-biciminde degil -> int(result, 16) TypeError (satir 66-67)."""
    u = _Uzman(body={"jsonrpc": "2.0", "id": 1, "result": 31337})
    monkeypatch.setattr("urllib.request.urlopen", u)
    with pytest.raises(ChainProbeError, match="rpc-invalid-chainid"):
        probe_rpc("http://x:8545")


def test_probe_chainid_hex_degildir(monkeypatch):
    """result hex-biciminde degil -> int(...) ValueError (satir 66-67)."""
    u = _Uzman(body={"jsonrpc": "2.0", "id": 1, "result": "zzzz"})
    monkeypatch.setattr("urllib.request.urlopen", u)
    with pytest.raises(ChainProbeError, match="rpc-invalid-chainid"):
        probe_rpc("http://x:8545")


def test_probe_chainid_sifir_reddeder(monkeypatch):
    """chain_id 0 -> gecersiz (satir 70)."""
    u = _Uzman(body={"jsonrpc": "2.0", "id": 1, "result": "0x0"})
    monkeypatch.setattr("urllib.request.urlopen", u)
    with pytest.raises(ChainProbeError, match="rpc-invalid-chainid"):
        probe_rpc("http://x:8545")


def test_probe_chainid_negatif_reddeder(monkeypatch):
    u = _Uzman(body={"jsonrpc": "2.0", "id": 1, "result": "-0x1"})
    monkeypatch.setattr("urllib.request.urlopen", u)
    with pytest.raises(ChainProbeError, match="rpc-invalid-chainid"):
        probe_rpc("http://x:8545")


def test_probe_zaman_asimi_aktarilir(monkeypatch):
    u = _Uzman(body={"jsonrpc": "2.0", "id": 1, "result": "0x539"})
    monkeypatch.setattr("urllib.request.urlopen", u)
    probe_rpc("http://x:8545", timeout=7.5)
    assert u.calls[0]["timeout"] == 7.5


def test_probe_hata_ipucu_icerir(monkeypatch):
    u = _Uzman(exc=OSError("yok"))
    monkeypatch.setattr("urllib.request.urlopen", u)
    with pytest.raises(ChainProbeError) as bil:
        probe_rpc("http://x:8545")
    assert "anvil" in str(bil.value)


# ======================================================== _make_web3 / connect

def test_make_web3_web3_doner():
    from web3.providers.rpc import HTTPProvider
    w3 = _make_web3("http://127.0.0.1:8545", 1.0)
    assert isinstance(w3, Web3)
    assert isinstance(w3.provider, HTTPProvider)


def test_make_web3_baglanmaz_kurulum_guvenli():
    """Provider olusturmak baglantı KURMAZ — saf-bellek guvenli."""
    w3 = _make_web3("http://127.0.0.1:1", 0.5)
    assert w3 is not None


def _patch_probe(monkeypatch, donus=None, hata=None):
    cagrilar = []

    def fake(url, timeout=2.0):
        cagrilar.append((url, timeout))
        if hata is not None:
            raise hata
        return donus if donus is not None else {"rpc_url": url,
                                                "chain_id": 1337}

    monkeypatch.setattr("pacta.chain.adapter.probe_rpc", fake)
    return cagrilar


def _patch_make_web3(monkeypatch, w3):
    monkeypatch.setattr("pacta.chain.adapter._make_web3", lambda url, t: w3)


def test_connect_anvil_stub(monkeypatch):
    cagrilar = _patch_probe(monkeypatch)
    w3 = _W3(receipt=_ok_receipt(), tx={"input": b"\x00"})
    _patch_make_web3(monkeypatch, w3)
    adp = connect_anvil("http://stub:8545")
    assert adp.backend == "anvil"
    assert adp.rpc_url == "http://stub:8545"
    assert cagrilar[0][0] == "http://stub:8545"


def test_connect_anvil_url_onceligi(monkeypatch):
    """Parametre > PACTA_RPC_URL > varsayilan."""
    cagrilar = _patch_probe(monkeypatch)
    _patch_make_web3(monkeypatch, _W3())
    monkeypatch.setenv("PACTA_RPC_URL", "http://env:8545")
    connect_anvil("http://param:8545")
    assert cagrilar[0][0] == "http://param:8545"


def test_connect_anvil_env_yedegi(monkeypatch):
    cagrilar = _patch_probe(monkeypatch)
    _patch_make_web3(monkeypatch, _W3())
    monkeypatch.setenv("PACTA_RPC_URL", "http://env:8545")
    connect_anvil()
    assert cagrilar[0][0] == "http://env:8545"


def test_connect_anvil_vasayilan_url(monkeypatch):
    cagrilar = _patch_probe(monkeypatch)
    _patch_make_web3(monkeypatch, _W3())
    monkeypatch.delenv("PACTA_RPC_URL", raising=False)
    connect_anvil()
    assert cagrilar[0][0] == ANVIL_DEFAULT_RPC_URL


def test_connect_anvil_timeout_kirpilir(monkeypatch):
    """timeout [1.0, 2.0] araligina sikistirilir (probe ici)."""
    cagrilar = _patch_probe(monkeypatch)
    _patch_make_web3(monkeypatch, _W3())
    connect_anvil(timeout=10.0)
    assert cagrilar[0][1] == 2.0
    connect_anvil(timeout=0.25)
    assert cagrilar[1][1] == 1.0


def test_connect_anvil_web3_connected_degil(monkeypatch):
    _patch_probe(monkeypatch)
    w3 = _W3()
    w3.connected = False
    _patch_make_web3(monkeypatch, w3)
    with pytest.raises(ChainUnavailableError, match="web3-not-connected"):
        connect_anvil("http://stub:8545")


def test_connect_anvil_probe_hatasi_yayar(monkeypatch):
    _patch_probe(monkeypatch, hata=ChainProbeError("rpc-unreachable: yok"))
    _patch_make_web3(monkeypatch, _W3())
    with pytest.raises(ChainProbeError, match="rpc-unreachable"):
        connect_anvil("http://stub:8545")


# ================================================================== adapter

def test_init_alanlar():
    w3 = _W3()
    adp = EvmChainAdapter(w3=w3, backend="stub", rpc_url="stub://t",
                          operator_account=_OP, receipt_timeout_s=7.0)
    assert adp.w3 is w3
    assert adp.backend == "stub"
    assert adp.rpc_url == "stub://t"
    assert adp.receipt_timeout_s == 7.0


def test_init_varsayilan_operator_none():
    adp = _adapter()
    assert adp._operator is None


def test_chain_id_stub():
    assert _adapter().chain_id() == 1337
    assert _adapter(chain_id=31337).chain_id() == 31337


def test_operator_verildi_dokunmaz():
    adp = EvmChainAdapter(w3=_W3(), backend="stub", rpc_url="stub://t",
                          operator_account=_OP)
    assert adp.operator_account() == _OP


def test_operator_hesaplardan_ilki():
    assert _adapter().operator_account() == _OP


def test_operator_hesap_yoksa_hatadir():
    with pytest.raises(ChainUnavailableError, match="no-unlocked-accounts"):
        _adapter(accounts=()).operator_account()


def test_operator_hesaplar_hata_verirse_hatadir():
    with pytest.raises(ChainUnavailableError, match="accounts-unavailable"):
        _adapter(accounts=RuntimeError("node-kilidi")).operator_account()


def test_operator_onbellege_alinir():
    adp = _adapter()
    adp.operator_account()
    assert adp._operator == _OP


# ------------------------------------------------------------ build_commitment

def test_build_commitment_determinist():
    a = EvmChainAdapter.build_commitment("j-1", "settlement",
                                         {"amount": "100", "fee": "1"})
    b = EvmChainAdapter.build_commitment("j-1", "settlement",
                                         {"amount": "100", "fee": "1"})
    assert a == b and isinstance(a, bytes) and len(a) == 32


def test_build_commitment_alan_sirasi_sabit():
    a = EvmChainAdapter.build_commitment("j-1", "settlement",
                                         {"amount": "1", "fee": "2", "z": "3"})
    b = EvmChainAdapter.build_commitment(
        "j-1", "settlement", {"z": "3", "fee": "2", "amount": "1"})
    assert a == b


def test_build_commitment_on_ek_ve_ayrac():
    """Govde: PACTA:v1:<kind>:<job_id>|anahtar=deger|... (sirali)."""
    from web3 import Web3 as _W
    beklenen = _W.keccak(text="PACTA:v1:settlement:j-1|amount=100|fee=1")
    sonuc = EvmChainAdapter.build_commitment("j-1", "settlement",
                                             {"amount": "100", "fee": "1"})
    assert sonuc == beklenen


def test_build_commitment_kind_degisince_degisir():
    a = EvmChainAdapter.build_commitment("j-1", "settlement", {"a": "1"})
    b = EvmChainAdapter.build_commitment("j-1", "dispute", {"a": "1"})
    assert a != b


def test_build_commitment_job_id_degisince_degisir():
    a = EvmChainAdapter.build_commitment("j-1", "settlement", {"a": "1"})
    b = EvmChainAdapter.build_commitment("j-2", "settlement", {"a": "1"})
    assert a != b


# ----------------------------------------------------------------------- anchor

def _anchor_adapter(**eth_kw):
    esas = dict(chain_id=1337, receipt=_ok_receipt(),
                tx={"input": b"\x01" * 32}, tx_hash=b"\x01" * 32)
    esas.update(eth_kw)
    return _adapter(**esas)


def test_anchor_gecerli_tum_alanlar():
    adp = _anchor_adapter()
    a = adp.anchor("j-1", "settlement", {"amount": "100"})
    assert isinstance(a, ChainAnchor)
    assert a.chain_id == 1337
    assert a.tx_hash == Web3.to_hex(b"\x01" * 32)
    assert a.block_number == 5
    assert a.gas_used == 21000
    assert a.anchor_kind == "settlement"
    assert a.job_id == "j-1"
    assert a.commitment_keccak == "0x" + EvmChainAdapter.build_commitment(
        "j-1", "settlement", {"amount": "100"}).hex()
    assert a.from_address == _OP
    assert a.to_address == _OP            # self-anchor varsayilani
    assert a.rpc_url == "stub://test"
    assert a.backend == "stub"
    assert a.tx_status == 1
    assert a.anchored_at_epoch_ms > 0


def test_anchor_tx_hash_str_oldugu_gibi_kalir():
    adp = _anchor_adapter(tx_hash="0xabc")
    assert adp.anchor("j-1", "refund", {"a": "1"}).tx_hash == "0xabc"


def test_anchor_tx_hash_bytes_hexe_normallesir():
    adp = _anchor_adapter(tx_hash=b"\xaa" * 32)
    assert adp.anchor("j-1", "arbitration", {"a": "1"}).tx_hash \
        == Web3.to_hex(b"\xaa" * 32)


def test_anchor_status_none_basari_kabul():
    adp = _anchor_adapter(receipt=_ok_receipt(status=None))
    assert adp.anchor("j-1", "settlement", {"a": "1"}).tx_status == 1


def test_anchor_status_true_basari():
    """Bazi-backendler bool doner — int(True)=1 -> basari (not: bool-dali
    'status = 1 if status else 0' satiri 231 bu yolla ulasilamaz; bkz. PACTA-3)."""
    adp = _anchor_adapter(receipt=_ok_receipt(status=True))
    assert adp.anchor("j-1", "settlement", {"a": "1"}).tx_status == 1


def test_anchor_status_false_revert_hatadir():
    adp = _anchor_adapter(receipt=_ok_receipt(status=False))
    with pytest.raises(ChainUnavailableError, match="anchor-reverted"):
        adp.anchor("j-1", "settlement", {"a": "1"})


def test_anchor_status_sifir_revert_hatadir():
    """EVM status=0 ASLA 1'e zorlanmaz (finans-kritik: eski '0 or 1' bug'i)."""
    adp = _anchor_adapter(receipt=_ok_receipt(status=0))
    with pytest.raises(ChainUnavailableError, match="anchor-reverted"):
        adp.anchor("j-1", "settlement", {"a": "1"})


@pytest.mark.parametrize("kind", ["settlement", "dispute",
                                  "arbitration", "refund"])
def test_anchor_kind_lari_kabul(kind):
    adp = _anchor_adapter()
    assert adp.anchor("j-1", kind, {"a": "1"}).anchor_kind == kind


def test_anchor_kind_gecersiz_reddeder():
    adp = _anchor_adapter()
    with pytest.raises(ValueError, match="anchor-kind-invalid"):
        adp.anchor("j-1", "baska", {"a": "1"})


def test_anchor_terms_bos_reddeder():
    adp = _anchor_adapter()
    with pytest.raises(ValueError, match="terms-required"):
        adp.anchor("j-1", "settlement", {})


def test_anchor_terms_dict_degil_reddeder():
    adp = _anchor_adapter()
    with pytest.raises(ValueError, match="terms-required"):
        adp.anchor("j-1", "settlement", None)


def test_anchor_to_adres_verildi():
    adp = _anchor_adapter()
    a = adp.anchor("j-1", "settlement", {"a": "1"}, to_address=_OTHER)
    assert a.to_address == _OTHER and a.from_address == _OP


def test_anchor_send_hatasi_fail_closed():
    adp = _anchor_adapter(send_error=RuntimeError("insufficient funds"))
    with pytest.raises(ChainUnavailableError, match="anchor-failed"):
        adp.anchor("j-1", "settlement", {"a": "1"})


def test_anchor_receipt_hatasi_fail_closed():
    adp = _anchor_adapter(receipt_error=RuntimeError("timeout"))
    with pytest.raises(ChainUnavailableError, match="anchor-failed"):
        adp.anchor("j-1", "settlement", {"a": "1"})


def test_anchor_operator_hatasi_yayar():
    adp = _anchor_adapter(accounts=())
    with pytest.raises(ChainUnavailableError, match="no-unlocked-accounts"):
        adp.anchor("j-1", "settlement", {"a": "1"})


def test_anchor_sozlesme_0_wei_taahhut():
    """Deger-transferi YASAK: tx her zaman value=0 (karar-taahhudu)."""
    giden = {}

    def _send(tx):
        giden.update(tx)
        return b"\x01" * 32

    w3 = _W3(chain_id=1337, accounts=(_OP, _OTHER),
             receipt=_ok_receipt(), tx={"input": b"\x01" * 32},
             tx_hash=b"\x01" * 32)
    w3.eth.send_transaction = _send
    adp = EvmChainAdapter(w3=w3, backend="stub", rpc_url="stub://t",
                          operator_account=_OP)
    adp.anchor("j-1", "settlement", {"a": "1"})
    assert giden["value"] == 0
    assert giden["from"] == _OP
    assert giden["to"] == _OP
    assert isinstance(giden["data"], bytes) and len(giden["data"]) == 32


# ------------------------------------------------------------------ verify_anchor

def test_verify_anchor_green():
    adp = _anchor_adapter()
    a = adp.anchor("j-1", "settlement", {"amount": "100"})
    assert adp.verify_anchor(a) is True


def test_verify_anchor_chain_id_farkli_false():
    adp = _anchor_adapter(chain_id=1337)
    a = ChainAnchor(chain_id=999, tx_hash="0x" + "01" * 32, block_number=5,
                    gas_used=21000, anchor_kind="settlement", job_id="j-1",
                    commitment_keccak="0x" + "01" * 32,
                    anchored_at_epoch_ms=1, from_address=_OP, to_address=_OP,
                    rpc_url="stub://test", backend="stub", tx_status=1)
    assert adp.verify_anchor(a) is False


def test_verify_anchor_receipt_yok_false():
    adp = _anchor_adapter(receipt_lookup_error=ValueError("not found"))
    a = adp.anchor("j-1", "settlement", {"a": "1"})
    assert adp.verify_anchor(a) is False


def test_verify_anchor_data_farkli_false():
    adp = _anchor_adapter()
    a = adp.anchor("j-1", "settlement", {"a": "1"})
    adp.w3.eth._last_tx_data = b"\xee" * 32   # zincirdeki calldata degisti
    assert adp.verify_anchor(a) is False


def test_verify_anchor_receipt_status_farkli_false():
    adp = _anchor_adapter(receipt=_ok_receipt(status=1),
                          receipt_lookup_error=None)
    a = adp.anchor("j-1", "settlement", {"a": "1"})
    adp.w3.eth._receipt = _ok_receipt(status=0)   # sonradan degisti
    assert adp.verify_anchor(a) is False


def test_verify_anchor_block_farkli_false():
    adp = _anchor_adapter()
    a = adp.anchor("j-1", "settlement", {"a": "1"})
    adp.w3.eth._receipt = _ok_receipt(blockNumber=999)
    assert adp.verify_anchor(a) is False


def test_verify_anchor_tx_hex_str_input():
    """tx['input'] hex-string olarak doner — calldata teyiti yine gecer."""
    adp = _anchor_adapter()
    a = adp.anchor("j-1", "settlement", {"a": "1"})
    adp.w3.eth._last_tx_data = None
    adp.w3.eth._tx = {"input": "0x" + a.commitment_keccak[2:]}
    adp.w3.eth._receipt = _ok_receipt()
    assert adp.verify_anchor(a) is True


# ------------------------------------------------------------------ hata tipleri

def test_chain_hata_tipleri_runtime_error():
    assert issubclass(ChainProbeError, RuntimeError)
    assert issubclass(ChainUnavailableError, RuntimeError)


def test_anvil_sabutleri():
    assert ANVIL_DEFAULT_RPC_URL == "http://127.0.0.1:8545"
    assert ANVIL_DEFAULT_CHAIN_ID == 31337
