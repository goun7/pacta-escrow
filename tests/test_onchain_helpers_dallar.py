r"""Pacta pacta.chain.onchain._load_artifact/_event_names/_events_from/_receipt/assert_anvil_like dal-kesen testleri (LEED).

Kural-1: mevcut dosyalara DOKUNULMADI, SADECE bu yeni dosya eklendi.
Kural-4: saf in-memory + tmp_path + FAKE kontrat/adapter ( web3-objeleri
stub; GERCEK-RPC/anvil/forge CAGRILMAZ; _load_artifact MEVCUT forge
artefaktlarini OKUR — salt-okunur).

ORTAM-ANATOMI:
- _load_artifact(name): forge-out JSON yukle
- _event_names(contract): ABI event-isimleri
- _events_from(receipt, contract): receipt-log -> event-isimleri
- _receipt(adapter, tx_hash): web3 receipt dict
- assert_anvil_like(adapter): mainnet-korumasi ( chain_id whitelist)
"""
import json
import sys

import pytest

sys.path.insert(0, ".")
from pacta.chain.onchain import (  # noqa: E402
    OnchainContractError,
    _events_from,
    _event_names,
    _load_artifact,
    _receipt,
    _FORGE_OUT,
    assert_anvil_like,
)


class FakeEventsAttr:
    """contract.events.<Name>() -> FakeEventHandle."""

    def __init__(self, mapping):
        self.mapping = mapping

    def __getattr__(self, name):
        if name not in self.mapping:
            raise AttributeError(name)
        return lambda: FakeEventHandle(self.mapping[name])


class FakeEventHandle:
    def __init__(self, behavior):
        self.behavior = behavior  # 'ok' | 'raise' | 'none'

    def process_log(self, log):
        if self.behavior == "raise":
            raise ValueError("topic-uyusmazligi")
        if self.behavior == "none":
            return None
        return {"event": log.get("__name", "X")}


class FakeContract:
    def __init__(self, abi, events_mapping=None):
        self.abi = abi
        self.events = FakeEventsAttr(events_mapping or {})


class FakeEth:
    def __init__(self, receipt, timeout=5):
        self.receipt = receipt
        self.timeout = timeout
        self.got = None

    def wait_for_transaction_receipt(self, h, timeout=None):
        self.got = h
        self.got_timeout = timeout
        return self.receipt


class FakeW3:
    def __init__(self, receipt=None):
        self.eth = FakeEth(receipt)


class FakeAdapter:
    def __init__(self, chain=31337, receipt=None, timeout_s=5):
        self._chain = chain
        self.w3 = FakeW3(receipt)
        self.receipt_timeout_s = timeout_s

    def chain_id(self):
        return self._chain


# == _load_artifact ====================================================================================

@pytest.mark.parametrize("name", ["MockUSDC", "PactaEscrowVault"])
def test_artifact_yukle(name):
    """ORTAM: forge-out JSON yukle ( mevcut artefaktlar)."""
    d = _load_artifact(name)
    assert isinstance(d, dict)
    assert "abi" in d


def test_artifact_abi_tipi():
    """ORTAM: ABI liste."""
    d = _load_artifact("MockUSDC")
    assert isinstance(d["abi"], list)


def test_artifact_bytecode_var():
    """ORTAM: bytecode/deployedBytecode mevcut ( forge-artefakti)."""
    d = _load_artifact("MockUSDC")
    assert "bytecode" in d
    assert "deployedBytecode" in d


def test_artifact_mockusdc_eventleri():
    """ORTAM: MockUSDC ABI'sinde Approval + Transfer."""
    d = _load_artifact("MockUSDC")
    evs = [e["name"] for e in d["abi"] if e.get("type") == "event"]
    assert "Transfer" in evs
    assert "Approval" in evs


def test_artifact_escrow_eventleri():
    """ORTAM: PactaEscrowVault 6 event."""
    d = _load_artifact("PactaEscrowVault")
    evs = [e["name"] for e in d["abi"] if e.get("type") == "event"]
    assert set(evs) >= {"EscrowLocked", "EscrowSettled", "OutputSubmitted"}


def test_artifact_yok_hata():
    """ORTAM: olmayan kontrat -> OnchainContractError."""
    with pytest.raises(OnchainContractError, match="forge-artifact-yok"):
        _load_artifact("OlmayanKontrat")


def test_artifact_yok_mesaj_forge_onerisi():
    """ORTAM: hata mesajinda 'forge build' onerisi."""
    with pytest.raises(OnchainContractError, match="forge build"):
        _load_artifact("OlmayanKontrat")


def test_artifact_donut_dict():
    assert isinstance(_load_artifact("MockUSDC"), dict)


def test_artifact_stabil():
    assert _load_artifact("MockUSDC") == _load_artifact("MockUSDC")


def test_artifact_json_serializable():
    """ORTAM: tamami JSON-seriye-cevrilebilir."""
    json.dumps(_load_artifact("MockUSDC"))


def test_artifact_metot_identifiers():
    """ORTAM: forge 'methodIdentifiers' alani."""
    d = _load_artifact("MockUSDC")
    assert "methodIdentifiers" in d
    assert isinstance(d["methodIdentifiers"], dict)


def test_artifact_id_alani():
    d = _load_artifact("MockUSDC")
    assert "id" in d


# == _event_names ======================================================================================

def test_event_names_temel():
    """ORTAM: ABI'deki type=='event' kayitlarinin 'name' alani."""
    abi = [{"type": "event", "name": "Transfer"},
           {"type": "function", "name": "balanceOf"}]
    assert _event_names(FakeContract(abi)) == ["Transfer"]


def test_event_names_bos():
    """ORTAM: event YOKSA bos-liste."""
    assert _event_names(FakeContract([])) == []


def test_event_names_coklu():
    abi = [{"type": "event", "name": "A"}, {"type": "event", "name": "B"},
           {"type": "event", "name": "C"}]
    assert _event_names(FakeContract(abi)) == ["A", "B", "C"]


def test_event_names_sadece_event():
    """ORTAM: function/constructor/error/ 'event' DEGIL — FILTRELENIR."""
    abi = [{"type": "function", "name": "f"}, {"type": "event", "name": "E"},
           {"type": "constructor", "name": "C"},
           {"type": "error", "name": "Err"},
           {"type": "fallback"}]
    assert _event_names(FakeContract(abi)) == ["E"]


def test_event_names_gercek_abi():
    """ORTAM: gercek MockUSDC artefaktinin ABI'si."""
    d = _load_artifact("MockUSDC")
    assert set(_event_names(FakeContract(d["abi"]))) == {"Transfer", "Approval"}


def test_event_names_gercek_escrow():
    d = _load_artifact("PactaEscrowVault")
    names = _event_names(FakeContract(d["abi"]))
    assert len(names) == 6


def test_event_names_donut_list():
    assert isinstance(_event_names(FakeContract([])), list)


def test_event_names_sira():
    """ORTAM: ABI sirasi KORUNUR."""
    abi = [{"type": "event", "name": "Z"}, {"type": "event", "name": "A"}]
    assert _event_names(FakeContract(abi)) == ["Z", "A"]


def test_event_names_get_keyerror_yok():
    """ORTAM-OGRENDI: e.get('type') — 'type' ANAHTARI YOKSA hata-DEGIL
    None doner ( .get kullanimi); None == 'event' False."""
    assert _event_names(FakeContract([{"name": "X"}])) == []


# == _events_from ======================================================================================

def test_events_from_bos_receipt():
    """ORTAM: logs YOKSA bos-liste."""
    c = FakeContract([{"type": "event", "name": "E"}],
                     {"E": "ok"})
    assert _events_from({}, c) == []


def test_events_from_logs_yok_key():
    """ORTAM: receipt.get('logs', []) — 'logs' ANAHTARI YOKSA bos."""
    c = FakeContract([{"type": "event", "name": "E"}], {"E": "ok"})
    assert _events_from({"status": 1}, c) == []


def test_events_from_eslesme():
    """ORTAM: topic-uyan event decode edilir."""
    c = FakeContract([{"type": "event", "name": "E"}], {"E": "ok"})
    r = {"logs": [{"__name": "E"}]}
    assert _events_from(r, c) == ["E"]


def test_events_from_eslesmeyen_atlanir():
    """ORTAM: topic-uyusmazligi -> hata YUTULUR, log ATLANIR."""
    c = FakeContract([{"type": "event", "name": "E"}], {"E": "raise"})
    assert _events_from({"logs": [{"data": "x"}]}, c) == []


def test_events_from_none_atlanir():
    """ORTAM: process_log None donerse ATLANIR ( if decoded is not None)."""
    c = FakeContract([{"type": "event", "name": "E"}], {"E": "none"})
    assert _events_from({"logs": [{}]}, c) == []


def test_events_from_coklu_log():
    """ORTAM: her-log icin event'ler SIRA ile denenir."""
    c = FakeContract([{"type": "event", "name": "A"},
                      {"type": "event", "name": "B"}],
                     {"A": "ok", "B": "ok"})
    r = {"logs": [{"__name": "A"}, {"__name": "B"}]}
    assert _events_from(r, c) == ["A", "B"]


class _CountingHandle:
    """process_log cagrilarini sayar ( break davranisi icin)."""

    def __init__(self, counter, name):
        self.counter = counter
        self.name = name

    def process_log(self, log):
        self.counter.append(self.name)
        return {"event": self.name}


class _CountingEvents:
    def __init__(self, counter):
        self.counter = counter

    def __getattr__(self, name):
        return lambda: _CountingHandle(self.counter, name)


def test_events_from_ilk_eslesme_kazanir():
    """ORTAM: break — ILK-eslesen event'ten sonra digerleri DENENMEZ."""
    counter = []
    c = FakeContract([{"type": "event", "name": "A"},
                      {"type": "event", "name": "B"}], {})
    c.events = _CountingEvents(counter)
    assert _events_from({"logs": [{"__name": "A"}]}, c) == ["A"]
    assert counter == ["A"]  # B denenmedi (break)


def test_events_from_baska_event_atlanir():
    """ORTAM: 2 event'ten 1'i uyarsa digeri sessizce-atlanir."""
    c = FakeContract([{"type": "event", "name": "A"},
                      {"type": "event", "name": "B"}],
                     {"A": "raise", "B": "ok"})
    assert _events_from({"logs": [{"__name": "B"}]}, c) == ["B"]


def test_events_from_event_yoksa_bos():
    """ORTAM: kontrat-in event'i YOKSA tum-log'lar atlanir."""
    c = FakeContract([], {})
    assert _events_from({"logs": [{"x": 1}]}, c) == []


def test_events_from_donut_list():
    c = FakeContract([], {})
    assert isinstance(_events_from({"logs": []}, c), list)


def test_events_from_stabil():
    c = FakeContract([{"type": "event", "name": "E"}], {"E": "ok"})
    r = {"logs": [{"__name": "E"}]}
    assert _events_from(r, c) == _events_from(r, c)


def test_events_from_attributes_error_yutulur():
    """ORTAM: contract.events.<Bilinmeyen> -> AttributeError DA yutulur
    ( except Exception) — _event_names yalnizca ABI'deki isimleri verdigi
    icin bu dal normalde ulasilamaz."""
    c = FakeContract([{"type": "event", "name": "YOK"}], {})
    assert _events_from({"logs": [{}]}, c) == []


def test_events_from_coklu_event_ayni_log():
    """ORTAM: ayni-log icin ilk-eslesen break ile bitirir."""
    c = FakeContract([{"type": "event", "name": "A"},
                      {"type": "event", "name": "B"}],
                     {"A": "ok", "B": "ok"})
    assert _events_from({"logs": [{"__name": "A"}]}, c) == ["A"]


# == _receipt ==========================================================================================

def test_receipt_str_hash():
    """ORTAM: tx_hash STR ise oldugu-gibi gonderilir."""
    a = FakeAdapter(receipt={"status": 1})
    assert _receipt(a, "0xabc") == {"status": 1}
    assert a.w3.eth.got == "0xabc"


def test_receipt_dict_donut():
    """ORTAM: donus dict ( receipt kopyasi)."""
    a = FakeAdapter(receipt={"status": 1, "gasUsed": 21000})
    assert _receipt(a, "0x1") == {"status": 1, "gasUsed": 21000}


def test_receipt_timeout_adapter_degeri():
    """ORTAM: timeout=adapter.receipt_timeout_s ( adapter karari)."""
    a = FakeAdapter(receipt={"status": 1}, timeout_s=7)
    _receipt(a, "0x1")
    assert a.w3.eth.got_timeout == 7


def test_receipt_non_str_hex_cevir():
    """ORTAM: tx_hash STR DEGILSE Web3.to_hex ile cevrilir ( web3-8)."""
    from web3 import Web3
    a = FakeAdapter(receipt={"status": 1})
    h = "0x" + "ab" * 32
    _receipt(a, h.encode())  # bytes girdi
    assert a.w3.eth.got == Web3.to_hex(h.encode())


def test_receipt_bytes_girdi():
    """ORTAM: bytes tx_hash -> hex stringe cevrilip gonderilir."""
    a = FakeAdapter(receipt={"status": 1})
    _receipt(a, b"\x01\x02")
    assert isinstance(a.w3.eth.got, str)


def test_receipt_donut_dict_tipi():
    a = FakeAdapter(receipt={"status": 1})
    assert isinstance(_receipt(a, "0x1"), dict)


def test_receipt_stabil():
    a = FakeAdapter(receipt={"status": 1})
    assert _receipt(a, "0x1") == _receipt(a, "0x1")


def test_receipt_immutable_degil():
    """ORTAM: dict(receipt) — ayni-referans DEGIL ( kopya)."""
    src = {"status": 1}
    a = FakeAdapter(receipt=src)
    out = _receipt(a, "0x1")
    out["status"] = 2
    assert src["status"] == 1


# == assert_anvil_like =================================================================================

@pytest.mark.parametrize("cid", [1337, 31337, 31338, 1234, 8545])
def test_anvil_izinli(cid):
    """ORTAM: izinverilen chain_id'ler ( anvil-benzeri yerel-zincirler)."""
    assert assert_anvil_like(FakeAdapter(chain=cid)) == cid


@pytest.mark.parametrize("cid", [1, 5, 11155111, 8453, 10, 137, 56, 42161])
def test_anvil_yasakli(cid):
    """ORTAM: gercek-zincir chain_id'leri YASAK ( mainnet/goerli/base/
    optimism/polygon/bnb/arbitrum) — mainnet-protection."""
    with pytest.raises(OnchainContractError, match="mainnet-protection"):
        assert_anvil_like(FakeAdapter(chain=cid))


def test_anvil_hata_mesaj_izinler():
    """ORTAM: hata mesajinda izinverilen chain_id listesi."""
    with pytest.raises(OnchainContractError, match="1337"):
        assert_anvil_like(FakeAdapter(chain=1))


def test_anvil_sifir_yasakli():
    with pytest.raises(OnchainContractError):
        assert_anvil_like(FakeAdapter(chain=0))


def test_anvil_donut_int():
    """ORTAM: donus chain_id ( int)."""
    assert isinstance(assert_anvil_like(FakeAdapter(chain=31337)), int)


def test_anvil_int_cevirim():
    """ORTAM: int(adapter.chain_id()) — str chain_id kabul."""
    a = FakeAdapter()
    a.chain_id = lambda: "31337"
    assert assert_anvil_like(a) == 31337


def test_anvil_stabil():
    assert assert_anvil_like(FakeAdapter(chain=31337)) == \
        assert_anvil_like(FakeAdapter(chain=31337))


# == karakterizasyon ===================================================================================

def test_events_from_amaci():
    r"""ORTAM-OGRENDI (DOCSTACK): web3-8.x UYUMLULUK —
'contract.events.process_log(log)' artik YOK ( 5.x API'siydi;
ABIEventNotFound firlatirdi); dogru-yol: her-event ayri-ayri
'contract.events.<Name>().process_log(log)' denenir; topic'i-umayanlar
hata-firlatir ( except Exception ile YUTULUR); eslesmeyen-log'lar (
MockUSDC'nin ERC20-Transfer'i) sessizce-atlanir; ILK-eslesen break."""
    c = FakeContract([{"type": "event", "name": "A"},
                      {"type": "event", "name": "B"}],
                     {"A": "raise", "B": "ok"})
    assert _events_from({"logs": [{"__name": "B"}]}, c) == ["B"]


def test_anvil_amaci():
    r"""ORTAM-OGRENDI (DOCSTACK): MAINNET-KORUMA — yalnizca anvil-benzeri
yerel-zincirlerde calisir ( chain_id 1337/31337/31338/1234/8545); gercek
agda PARA-HARCAMA ve PRIVATE_KEY-YASAK oldugu icin reddeder."""
    assert assert_anvil_like(FakeAdapter(chain=31337)) == 31337
    with pytest.raises(OnchainContractError):
        assert_anvil_like(FakeAdapter(chain=1))
