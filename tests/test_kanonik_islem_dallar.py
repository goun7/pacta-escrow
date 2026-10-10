"""UnpumpPaymentBridge._kanonik_islem dal-kesen testleri (LEED).

Kural-1: mevcut dosyalara DOKUNULMADI, SADECE bu yeni dosya eklendi.
Kural-4: saf in-memory; kc stub (CANONICAL_ALANLAR + delilix sozlesmesi).
RFC-8785 JCS anahtar-siralama: kanonik-alan sirasini korur.
"""
from types import SimpleNamespace

import pytest

from pacta.integrations.unpump_bridge import UnpumpPaymentBridge


def _kc(alanlar=("a", "b", "c", "d")):
    return SimpleNamespace(CANONICAL_ALANLAR=list(alanlar))


def test_returns_dict():
    r = UnpumpPaymentBridge._kanonik_islem(_kc(), {"a": 1})
    assert isinstance(r, dict)


def test_only_canonical_fields():
    kc = _kc(("a", "b"))
    r = UnpumpPaymentBridge._kanonik_islem(kc, {"a": 1, "b": 2, "x": 9})
    assert set(r) == {"a", "b"}


def test_extra_fields_dropped():
    kc = _kc(("a", "b"))
    r = UnpumpPaymentBridge._kanonik_islem(kc, {"a": 1, "b": 2, "z": 99, "w": 88})
    assert r == {"a": 1, "b": 2}


def test_missing_fields_none():
    """operation.get(a) -> None (anahtar yine EKLENIR)."""
    kc = _kc(("a", "b"))
    r = UnpumpPaymentBridge._kanonik_islem(kc, {"a": 1})
    assert r == {"a": 1, "b": None}


def test_empty_operation():
    kc = _kc(("a", "b"))
    r = UnpumpPaymentBridge._kanonik_islem(kc, {})
    assert r == {"a": None, "b": None}


def test_empty_canonical():
    kc = _kc(())
    r = UnpumpPaymentBridge._kanonik_islem(kc, {"a": 1})
    assert r == {}


def test_order_preserved():
    """RFC-8785: kanonik sirayla uretilir."""
    kc = _kc(("c", "a", "b"))
    r = UnpumpPaymentBridge._kanonik_islem(kc, {"a": 1, "b": 2, "c": 3})
    assert list(r) == ["c", "a", "b"]


def test_order_independent_of_input():
    kc = _kc(("a", "b", "c"))
    r1 = UnpumpPaymentBridge._kanonik_islem(kc, {"c": 3, "b": 2, "a": 1})
    r2 = UnpumpPaymentBridge._kanonik_islem(kc, {"a": 1, "b": 2, "c": 3})
    assert list(r1) == list(r2) == ["a", "b", "c"]


def test_deterministic_bytes():
    """Ayni sonuc -> ayni bytes (hash-tekrar-uretilebilir)."""
    kc = _kc(("a", "b"))
    a = UnpumpPaymentBridge._kanonik_islem(kc, {"b": 2, "a": 1, "z": 9})
    b = UnpumpPaymentBridge._kanonik_islem(kc, {"a": 1, "b": 2})
    assert a == b


def test_values_preserved():
    kc = _kc(("amount", "agent", "nonce"))
    op = {"amount": 50000, "agent": "0xabc", "nonce": "n1", "extra": "drop"}
    r = UnpumpPaymentBridge._kanonik_islem(kc, op)
    assert r["amount"] == 50000 and r["agent"] == "0xabc"


def test_static_method():
    assert callable(UnpumpPaymentBridge._kanonik_islem)


def test_no_self_needed():
    """staticmethod -> kc ilk arguman (self degil)."""
    kc = _kc(("a",))
    assert UnpumpPaymentBridge._kanonik_islem(kc, {"a": 1}) == {"a": 1}


def test_nested_dict_value():
    kc = _kc(("payload",))
    inner = {"z": 1, "a": 2}
    r = UnpumpPaymentBridge._kanonik_islem(kc, {"payload": inner})
    assert r["payload"] == inner


def test_list_value():
    kc = _kc(("items",))
    r = UnpumpPaymentBridge._kanonik_islem(kc, {"items": [3, 1, 2]})
    assert r["items"] == [3, 1, 2]


def test_none_value_kept():
    kc = _kc(("a",))
    r = UnpumpPaymentBridge._kanonik_islem(kc, {"a": None})
    assert r == {"a": None}


def test_none_operation():
    """{}.get uygulanmaz — operation None -> AttributeError."""
    with pytest.raises(AttributeError):
        UnpumpPaymentBridge._kanonik_islem(_kc(("a",)), None)


def test_duplicate_canonical_fields():
    """kanonik listede tekrar -> son deger kazanir."""
    kc = _kc(("a", "a", "b"))
    r = UnpumpPaymentBridge._kanonik_islem(kc, {"a": 1, "b": 2})
    assert list(r) == ["a", "b"]


def test_tuple_canonical_ok():
    kc = SimpleNamespace(CANONICAL_ALANLAR=("a", "b"))
    r = UnpumpPaymentBridge._kanonik_islem(kc, {"a": 1, "b": 2})
    assert r == {"a": 1, "b": 2}


def test_missing_canonical_attr_raises():
    with pytest.raises(AttributeError):
        UnpumpPaymentBridge._kanonik_islem(SimpleNamespace(), {"a": 1})


def test_operation_empty_and_canonical_many():
    alanlar = tuple(f"f{i}" for i in range(20))
    kc = _kc(alanlar)
    r = UnpumpPaymentBridge._kanonik_islem(kc, {})
    assert len(r) == 20


def test_turkish_field_names():
    alanlar = ("miktar", "acente", "kanit")
    kc = _kc(alanlar)
    r = UnpumpPaymentBridge._kanonik_islem(kc, {"miktar": 5, "acente": "x"})
    assert set(r) == {"miktar", "acente", "kanit"}


def test_repeatable():
    kc = _kc(("a", "b"))
    op = {"a": 1, "b": 2}
    assert UnpumpPaymentBridge._kanonik_islem(kc, op) == \
        UnpumpPaymentBridge._kanonik_islem(kc, op)


def test_input_not_mutated():
    kc = _kc(("a",))
    op = {"a": 1, "z": 2}
    UnpumpPaymentBridge._kanonik_islem(kc, op)
    assert op == {"a": 1, "z": 2}


def test_independent_kc():
    kc1 = _kc(("a",))
    kc2 = _kc(("b",))
    assert UnpumpPaymentBridge._kanonik_islem(kc1, {"a": 1, "b": 2}) == {"a": 1}
    assert UnpumpPaymentBridge._kanonik_islem(kc2, {"a": 1, "b": 2}) == {"b": 2}


def test_single_field():
    kc = _kc(("only",))
    r = UnpumpPaymentBridge._kanonik_islem(kc, {"only": 42})
    assert r == {"only": 42}


def test_int_keys_operation():
    """operation anahtarlari int -> get(str) None doner."""
    kc = _kc(("a",))
    r = UnpumpPaymentBridge._kanonik_islem(kc, {1: "x"})
    assert r == {"a": None}
