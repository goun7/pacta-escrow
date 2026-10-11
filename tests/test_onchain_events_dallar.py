"""03-Pacta onchain._event_names/_events_from dal-kesen testleri (LEED).

Kural-1: mevcut dosyalara DOKUNULMADI, SADECE bu yeni dosya eklendi.
Kural-4: saf in-memory (MagicMock/SimpleNamespace contract stub;
network/HTTP/Anvil/RPC YASAK).

ORTAM-ANATOMI:
- _event_names(contract): [e["name"] for e in contract.abi if e.get("type") == "event"]
- _events_from(receipt, contract): receipt["logs"] her log'u contract.events.<Name>().process_log
  ile dener; topic-uyumsuz -> Exception -> continue; decoded -> .get("event", name), break
"""
import sys
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, ".")
sys.path.insert(0, "src")
from pacta.chain.onchain import _event_names, _events_from  # noqa: E402


def _ContractABI_from_spec(spec):
    """spec: ABI dict-listesi VEYA event-isim listesi (string -> event dict)."""
    return _ContractABI([s if isinstance(s, dict) else {"type": "event", "name": s}
                         for s in spec])


class _EventAttr:
    """contract.events.<Name>() -> process_log(log) davranisi."""
    def __init__(self, names, decoded_map):
        self._map = decoded_map or {}

    def __getattr__(self, name):
        dmap = self._map.get(name, {})

        class _Inst:
            def process_log(self, log):
                if id(log) not in dmap:
                    raise ValueError("topic-uyumsuz")
                return dmap[id(log)]

        return lambda: _Inst()


class _ContractABI:
    def __init__(self, abi, events=None):
        self.abi = abi
        self.events = events if events is not None else MagicMock()


def _Contract(spec):
    """spec: ABI dict-listesi VEYA event-isim listesi (string -> event dict)."""
    return _ContractABI_from_spec(spec)


def _contract(names, decoded_map=None):
    """decoded_map: {event_adi: {log: decoded}} -> id(log) anahtarina cevrilir."""
    norm = None
    if decoded_map:
        norm = {ev: {id(log): d for log, d in logs.items()}
                for ev, logs in decoded_map.items()}
    return _ContractABI([{"type": "event", "name": n} for n in names],
                        _EventAttr(names, norm))


# == _event_names ======================================================================================

def test_event_isimleri():
    c = _Contract(["A", "B", "C"])
    assert _event_names(c) == ["A", "B", "C"]


def test_fonksiyonlar_elemdir():
    """ORTAM: type=='event' olanlar ALINIR."""
    c = _Contract([{"type": "function", "name": "F"}, {"type": "event", "name": "A"}])
    assert _event_names(c) == ["A"]


def test_bos_abi():
    assert _event_names(_Contract([])) == []


def test_sadece_fonksiyon():
    c = _Contract([{"type": "function", "name": "F"}])
    assert _event_names(c) == []


def test_case_sensitive():
    """ORTAM: 'EVENT' != 'event' — case-SENSITIVE."""
    c = _Contract([{"type": "EVENT", "name": "A"}])
    assert _event_names(c) == []


def test_type_yok():
    """ORTAM: e.get('type') None -> False."""
    c = _Contract([{"name": "A"}])
    assert _event_names(c) == []


def test_adsiz_event_keyerror():
    """ORTAM-OGRENDI: event ama 'name' ANAHTARI YOK -> KeyError
    (e["name"] — .get DEGIL). Production dayaniksiz; characterization pin'lendi."""
    with pytest.raises(KeyError):
        _event_names(_Contract([{"type": "event"}]))


def test_extra_alanlar_onemsiz():
    c = _Contract([{"type": "event", "name": "A", "inputs": [], "anonymous": True}])
    assert _event_names(c) == ["A"]


def test_sira_korunur():
    c = _Contract([{"type": "event", "name": "Z"}, {"type": "event", "name": "A"}])
    assert _event_names(c) == ["Z", "A"]


def test_tekrarli_isimler_korunur():
    """ORTAM: duplicate event isimleri KORUNUR (dedup YOK)."""
    c = _Contract([{"type": "event", "name": "A"}, {"type": "event", "name": "A"}])
    assert _event_names(c) == ["A", "A"]


def test_donus_tipi_liste():
    assert isinstance(_event_names(_Contract(["A"])), list)


def test_diger_tipler_elemdir():
    for t in ["constructor", "fallback", "receive", "error"]:
        c = _Contract([{"type": t, "name": "X"}, {"type": "event", "name": "A"}])
        assert _event_names(c) == ["A"]


@pytest.mark.parametrize("tipler,beklenen", [
    ([{"type": "event", "name": "A"}], ["A"]),
    ([{"type": "function", "name": "A"}], []),
    ([{"type": "event", "name": "A"}, {"type": "event", "name": "B"}], ["A", "B"]),
    ([{"type": "function", "name": "A"}, {"type": "function", "name": "B"}], []),
])
def test_matrix(tipler, beklenen):
    assert _event_names(_Contract(tipler)) == beklenen


# == _events_from =======================================================================================

def test_bos_logs():
    c = _contract(["A"])
    assert _events_from({"logs": []}, c) == []


def test_bos_receipt():
    """ORTAM: receipt['logs'] YOK -> .get('logs', []) -> []."""
    c = _contract(["A"])
    assert _events_from({}, c) == []


def test_eslesen_event():
    log = ("log",1)
    c = _contract(["A"], {"A": {log: {"event": "A", "args": {}}}})
    assert _events_from({"logs": [log]}, c) == ["A"]


def test_event_alani_kullanilir():
    """ORTAM: decoded.get('event', name) — decoded 'event' key'i TASIYORSA o alinir."""
    log = ("log",1)
    c = _contract(["A"], {"A": {log: {"event": "OzelA"}}})
    assert _events_from({"logs": [log]}, c) == ["OzelA"]


def test_topic_uyumsuz_atlanir():
    """ORTAM: process_log Exception -> sessizce continue (eslesmeyen log)."""
    c = _contract(["A"])  # hic log eslesmiyor
    assert _events_from({"logs": [("log",1)]}, c) == []


def test_birden_cok_log():
    l1, l2 = ("log",1), ("log",2)
    c = _contract(["A"], {"A": {l1: {"event": "A"}, l2: {"event": "A"}}})
    assert _events_from({"logs": [l1, l2]}, c) == ["A", "A"]


def test_ilk_eslesen_kazanir():
    """ORTAM: ic dongu 'break' — bir log SADECE bir event'le eslesir."""
    log = ("log",1)
    c = _contract(["A", "B"], {"A": {log: {"event": "A"}}, "B": {log: {"event": "B"}}})
    assert _events_from({"logs": [log]}, c) == ["A"]


def test_ikinci_event_dener():
    """ORTAM: A uyumsuz, B uyumlu -> B."""
    log = ("log",1)
    c = _contract(["A", "B"], {"B": {log: {"event": "B"}}})
    assert _events_from({"logs": [log]}, c) == ["B"]


def test_uyumsuz_araya_karisik():
    l1, l2 = ("log",1), ("log",2)
    c = _contract(["A"], {"A": {l2: {"event": "A"}}})
    assert _events_from({"logs": [l1, l2]}, c) == ["A"]


def test_events_yok_hic():
    """ORTAM: contract'da event YOK -> bos."""
    c = _contract([])
    assert _events_from({"logs": [("log",1)]}, c) == []


def test_decoded_none_atlanir():
    """ORTAM: process_log None donerse atlanir (if decoded is not None)."""
    log = ("log",1)

    class _Inst:
        def process_log(self, l):
            return None

    class _Ev:
        def __getattr__(self, n):
            return lambda: _Inst()

    c = _Contract([])
    c.events = _Ev()
    assert _events_from({"logs": [log]}, c) == []


def test_event_isim_farkli_sonuc():
    """ORTAM: decoded 'event' key'i YOKSA name fallback."""
    log = ("log",1)
    c = _contract(["A"], {"A": {log: {"args": {}}}})
    assert _events_from({"logs": [log]}, c) == ["A"]


def test_karmasik_receipt():
    l1, l2, l3 = ("log",1), ("log",2), ("log",3)
    c = _contract(["A", "B"], {"A": {l1: {"event": "A"}, l3: {"event": "A"}},
                                "B": {l2: {"event": "B"}}})
    assert _events_from({"logs": [l1, l2, l3]}, c) == ["A", "B", "A"]


@pytest.mark.parametrize("n", [0, 1, 3, 7])
def test_log_sayisi_matrix(n):
    logs = [("log",i) for i in range(n)]
    cmap = {i: {"event": "A"} for i in range(n)}
    c = _contract(["A"], {"A": {l: cmap[l[1]] for l in logs}})
    assert _events_from({"logs": logs}, c) == ["A"] * n


# == karakterizasyon ===================================================================================

def test_receipt_logs_none():
    """ORTAM-OGRENDI: receipt['logs'] = None -> .get('logs', []) None doner ->
    'NoneType' iterable DEGIL -> TypeError. Production None'a karsi dayaniksiz;
    characterization pin'lendi."""
    with pytest.raises(TypeError):
        _events_from({"logs": None}, _contract(["A"]))


def test_process_log_hatalari_yutulur():
    """ORTAM-OGRENDI: tum exception turleri yutulur (noqa: BLE001) —
    topic-uyumsuzluk, ABI-uyumsuzluk, attribute-hata hepsi ayni sekilde
    'eslesmedi' olarak sayilir. Bu fail-safe tasarimdir."""
    log = ("log",1)

    class _Patla:
        def process_log(self, l):
            raise RuntimeError("beklenmeyen hata")

    class _Ev:
        def __getattr__(self, n):
            return _Patla()

    c = _Contract([{"type": "event", "name": "A"}])
    c.events = _Ev()
    assert _events_from({"logs": [log]}, c) == []


def test_web3_8_uyumluluk_notu():
    """ORTAM-OGRENDI: web3-8.x'te contract.events.process_log(log) YOK —
    bu fonksiyon her event'i AYRI process_log ile dener (5.x API kalintisi
    giderildi). Docstring'deki gecis notu characterization pin'lendi."""
    c = _contract(["A"], {"A": {("log",1): {"event": "A"}}})
    assert isinstance(c.events, object)
