r"""03-Pacta tamga_jcs._enc_string/_encode + tamga_d5._signer_address dal-kesen testleri (LEED).

Kural-1: mevcut dosyalara DOKUNULMADI, SADECE bu yeni dosya eklendi.
Kural-4: saf in-memory (saf fonksiyonlar; network/DB YASAK).

ORTAM-ANATOMI:
- _enc_string(s): 7-entry _ESCAPE table; ord<0x20 -> \\uXXXX; else RAW UTF-8
- _encode(o, out): None/is True/is False; bool (defensive); int
  [-(2^53),2^53] disi ValueError; float es_number; str; dict UTF-16-BE
  sorted; list/tuple; else TypeError
- _signer_address(signer): bytes/bytearray | .key attr (eth_account) |
  eth_keys.PrivateKey -> EVM address; else TypeError
"""
import sys

import pytest

sys.path.insert(0, ".")
sys.path.insert(0, "src")
from pacta.integrations.tamga_d5 import _signer_address  # noqa: E402
from pacta.integrations.tamga_jcs import _ESCAPE, _encode, _enc_string, jcs  # noqa: E402

_KEY_BYTES = b"\x01" * 32


# == _enc_string =======================================================================================

def test_enc_bos():
    assert _enc_string("") == '""'


def test_enc_duz():
    assert _enc_string("pacta") == '"pacta"'


def test_enc_tablo_7():
    r"""ORTAM-OGRENDI: _ESCAPE 7-entry — " \ b f n r t; tab/backspace/
    formfeed KISA isimler (\uXXXX DEGIL — tablo dali kontrol dalindan
    ÖNCE)."""
    assert sorted(_ESCAPE) == ["\x08", "\t", "\n", "\x0c", "\r", '"', "\\"]
    assert _enc_string('"') == r'"\""'
    assert _enc_string("\\") == r'"\\"'
    assert _enc_string("\b") == r'"\b"'
    assert _enc_string("\t") == r'"\t"'


def test_enc_kontrol():
    """ORTAM: ord<0x20 (tablo disi) -> \\uXXXX."""
    assert _enc_string("\x00") == r'"\u0000"'
    assert _enc_string("\x1f") == r'"\u001f"'


def test_enc_tab_ayri():
    assert _enc_string("\t") == r'"\t"'
    assert _enc_string("\t") != r'"\u0009"'


def test_enc_raw_utf8():
    """ORTAM: non-ASCII RAW (kacislanmaz)."""
    assert _enc_string("Örnek") == '"Örnek"'
    assert _enc_string("😀") == '"😀"'


def test_enc_solidus():
    """ORTAM: '/' escape YOK."""
    assert _enc_string("a/b") == '"a/b"'


def test_enc_donut_tipi():
    assert isinstance(_enc_string("x"), str)


def test_enc_stabil():
    assert _enc_string('a"b\n') == _enc_string('a"b\n')


# == _encode / jcs =====================================================================================

def test_encode_none():
    out = []
    _encode(None, out)
    assert out == ["null"]


def test_encode_true():
    assert jcs(True) == b"true"


def test_encode_false():
    assert jcs(False) == b"false"


def test_encode_bool_once():
    r"""ORTAM-OGRENDI: 'o is True'/'o is False' ÖNCE — 'elif isinstance(o,
    bool)' OLU KOD (bool int'in atasi; 'defensive' yorumuyla birakildi)."""
    assert jcs(True) == b"true"
    assert jcs(False) == b"false"


def test_encode_int():
    assert jcs(42) == b"42"
    assert jcs(0) == b"0"
    assert jcs(-7) == b"-7"


def test_encode_int_sinir():
    """ORTAM: [-(2^53), 2^53] DAHIL."""
    assert jcs(2 ** 53) == str(2 ** 53).encode()
    assert jcs(-(2 ** 53)) == str(-(2 ** 53)).encode()


def test_encode_int_asma():
    r"""ORTAM-OGRENDI: 2^53+1 -> ValueError ('ijson_number_out_of_range'
    — sessiz-koruma/veya sessiz-yuvarlama YERINE RED; #2887/GVP gvp-audit
    'integers past 2^53-1' sinifiyla ayni-koken — IEEE-754 Node yuvarlar,
    digest uyusmaz)."""
    with pytest.raises(ValueError):
        jcs(2 ** 53 + 1)
    with pytest.raises(ValueError):
        jcs(-(2 ** 53) - 1)


def test_encode_float():
    assert jcs(1.0) == b"1"


def test_encode_float_ussu():
    assert jcs(2.93e-07) == b"2.93e-7"


def test_encode_float_nan():
    with pytest.raises(ValueError):
        jcs(float("nan"))


def test_encode_str():
    assert jcs("pacta") == b'"pacta"'


def test_encode_bos_liste():
    assert jcs([]) == b"[]"


def test_encode_liste():
    assert jcs([1, "a", True, None]) == b'[1,"a",true,null]'


def test_encode_icice_liste():
    assert jcs([[1], [2]]) == b"[[1],[2]]"


def test_encode_tuple():
    """ORTAM: tuple list dalinda."""
    assert jcs((1, 2)) == b"[1,2]"


def test_encode_bos_dict():
    assert jcs({}) == b"{}"


def test_encode_dict():
    assert jcs({"a": 1}) == b'{"a":1}'


def test_encode_dict_sorted():
    """ORTAM: UTF-16-BE code-unit sirasi (RFC 8785 §3.2.3)."""
    assert jcs({"b": 2, "a": 1}) == b'{"a":1,"b":2}'


def test_encode_dict_utf16_be():
    r"""ORTAM-OGRENDI: 'Z'(0x5A) < 'a'(0x61) < 'é'(0xE9) — UTF-16 code-unit
    sirasi ASCII sort'tan FARKLI (BMP-disi surrogate pair ile ayrilir)."""
    assert jcs({"é": 1, "Z": 2, "a": 3}) == b'{"Z":2,"a":3,"\xc3\xa9":1}'


def test_encode_dict_bmp_disi():
    r"""ORTAM-OGRENDI: '𝓐' U+1D4D0 -> UTF-16 surrogate pair (0xD835 0xDD50)
    — 'z'(0x7A)'den SONRA; jcs(sort_keys=True) YETERLI DEGILDIR."""
    v = jcs({"z": 1, "𝓐": 2})
    assert v.startswith(b'{"z":1,"')


def test_encode_dict_nonstr_key_hata():
    """ORTAM-OGRENDI (KRITIK-FARK): k.encode('utf-16-be') — str() CAST
    YAPILMAZ! PQHaven 'str(k)' (tolarant) iken Pacta non-str anahtarda
    AttributeError (sözlesme: anahtarlar str olmali)."""
    with pytest.raises(AttributeError):
        jcs({1: "x"})


def test_encode_bilinmeyen_tip():
    """ORTAM: else -> TypeError ('unsupported canonical value')."""
    with pytest.raises(TypeError):
        jcs({1, 2})
    with pytest.raises(TypeError):
        jcs(complex(1, 2))


def test_encode_yan_etki():
    """ORTAM: out listesine append, None doner."""
    out = []
    assert _encode(1, out) is None
    assert out == ["1"]


def test_jcs_donut_bytes():
    """ORTAM: jcs -> UTF-8 BYTES ('.encode('utf-8')')."""
    assert isinstance(jcs(1), bytes)


def test_jcs_stabil():
    assert jcs({"b": 2, "a": 1}) == jcs({"a": 1, "b": 2})


# == _signer_address ===================================================================================

def test_signer_bytes():
    """ORTAM: bytes(32) -> EVM address."""
    v = _signer_address(_KEY_BYTES)
    assert v.startswith("0x") and len(v) == 42


def test_signer_bytes_degeri():
    """ORTAM: eth_keys PrivateKey(public_key).to_address() — b'\x01'*32."""
    assert _signer_address(_KEY_BYTES) == "0x1a642f0e3c3af545e7acbd38b07251b3990914f1"


def test_signer_bytearray():
    """ORTAM: bytearray KABUL (bytes | bytearray dalinda)."""
    assert _signer_address(bytearray(_KEY_BYTES)) == _signer_address(_KEY_BYTES)


def test_signer_eth_keys():
    """ORTAM: eth_keys.PrivateKey -> .to_bytes() -> address."""
    from eth_keys import keys as _eth_keys
    k = _eth_keys.PrivateKey(_KEY_BYTES)
    assert _signer_address(k) == _signer_address(_KEY_BYTES)


def test_signer_key_attr():
    """ORTAM: hasattr(signer, 'key') — eth_account.Account dalı."""

    class _FakeAccount:
        key = _KEY_BYTES

    assert _signer_address(_FakeAccount()) == _signer_address(_KEY_BYTES)


def test_signer_key_attr_none_hata():
    """ORTAM-OGRENDI: .key var ama bytes DEGILse — bytes(None) TypeError."""

    class _Bad:
        key = None

    with pytest.raises(TypeError):
        _signer_address(_Bad())


def test_signer_str_hata():
    """ORTAM: else -> TypeError ('unsupported_signer')."""
    with pytest.raises(TypeError):
        _signer_address("0xabc")


def test_signer_int_hata():
    with pytest.raises(TypeError):
        _signer_address(12345)


def test_signer_none_hata():
    with pytest.raises(TypeError):
        _signer_address(None)


def test_signer_kisa_bytes_hata():
    """ORTAM: 32 byte'tan KISA -> eth_keys ValueError/TypeError."""
    with pytest.raises(Exception):
        _signer_address(b"\x01" * 31)


def test_signer_deterministik():
    assert _signer_address(_KEY_BYTES) == _signer_address(_KEY_BYTES)


def test_signer_farkli_key_farkli_adres():
    a = _signer_address(b"\x01" * 32)
    b = _signer_address(b"\x02" * 32)
    assert a != b


def test_signer_hex_karakterler():
    """ORTAM: EIP-55 checksum'li adres (eth_keys to_address)."""
    v = _signer_address(_KEY_BYTES)
    assert all(c in "0123456789abcdef" for c in v[2:])


def test_signer_hepsi_ayni_adres():
    """ORTAM-OGRENDI: bytes / bytearray / eth_keys.PrivateKey / .key attr
    — hepsi AYNI key_bytes'ten AYNI adres (giriş-formati seffaf)."""
    from eth_keys import keys as _eth_keys

    class _FakeAccount:
        key = _KEY_BYTES

    ref = _signer_address(_KEY_BYTES)
    assert _signer_address(bytearray(_KEY_BYTES)) == ref
    assert _signer_address(_eth_keys.PrivateKey(_KEY_BYTES)) == ref
    assert _signer_address(_FakeAccount()) == ref


# == karakterizasyon ===================================================================================

def test_encode_amaci():
    r"""ORTAM-OGRENDI (DOCSTACK): RFC 8785 JCS — UTF-16 code-unit sirasi
    (§3.2.3) jcs(sort_keys=True)'ten FARKLI (BMP-disi surrogate pair);
    int [−2^53, 2^53] disi RED (RFC 7493 I-JSON; #2887/GVP gvp-audit
    'integers past 2^53-1' ile ayni-koken — Node IEEE-754 yuvarlar,
    digest uyusmaz; sessiz-yuvarlama YERINE RED); bool 'is' ile ÖNCE
    (elif bool OLU KOD)."""
    assert jcs({"é": 1, "Z": 2, "a": 3}) == b'{"Z":2,"a":3,"\xc3\xa9":1}'
    with pytest.raises(ValueError):
        jcs(2 ** 53 + 1)


def test_signer_amaci():
    """ORTAM-OGRENDI (DOCSTACK): payer_signer'dan EVM adresi çöz —
    eth-keys/eth-account/bytes kabul (giris-formati seffaf; hepsi ayni
    key_bytes -> ayni adres); desteklenmeyen tip TypeError
    ('unsupported_signer')."""
    assert _signer_address(_KEY_BYTES) == _signer_address(bytearray(_KEY_BYTES))
    with pytest.raises(TypeError):
        _signer_address("x")


def test_enc_amaci():
    r"""ORTAM-OGRENDI: _ESCAPE 7-entry — tablo dali kontrol dalindan ÖNCE
    (tab 0x09 '\t' '\u0009' DEGIL); non-ASCII RAW UTF-8 (kacislanmaz);
    PQHaven mesh_anchor ile BIRE-BIT (cross-repo JCS paritesi)."""
    assert _enc_string("\t") == r'"\t"'
    assert _enc_string("\x01") == r'"\u0001"'
    assert _enc_string("Ö") == '"Ö"'
