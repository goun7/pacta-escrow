"""Pacta tamga_jcs._enc_string/_encode/es_number dal-kesen testleri (LEED).

Kural-1: mevcut dosyalara DOKUNULMADI, SADECE bu yeni dosya eklendi.
Kural-4: saf in-memory (saf serilestirme; network/DB YASAK).

ORTAM-ANATOMI (RFC 8785 JCS):
- _enc_string(s): '"' + kacisli-govde + '"'; _ESCAPE = {'"'->\\"", '\\'->
  \\\\, '\n'->\\n, '\r'->\\r, '\t'->\\t}; ord<0x20 -> \\uXXXX; diger HAM
- _encode(o, out): None->null; True->true; False->false; bool->true/false;
  int -> str(int) (I-JSON sinir -(2**53)..2**53, disi ValueError);
  float -> es_number; str -> _enc_string; dict -> {sirali-uyeler};
  list/tuple -> [...]; else TypeError
- es_number(x): ECMAScript ToString (IEEE 754 shortest round-trip)
- dict anahtar siralamasi: sorted(k.encode('utf-16-be')) — UTF-16 code-unit
  order (RFC 8785 §3.2.3), ASCII'de ayni sonuc
"""
import math
import sys

import pytest

sys.path.insert(0, ".")
sys.path.insert(0, "src")
from pacta.integrations.tamga_jcs import (  # noqa: E402
    _enc_string, _encode, es_number, jcs, jcs_json,
)


# == _enc_string: temel ===============================================================================

def test_enc_string_basit():
    assert _enc_string("abc") == '"abc"'


def test_enc_string_bos():
    assert _enc_string("") == '""'


def test_enc_string_tirnak():
    """ORTAM: '"' -> '\\"'."""
    assert _enc_string('a"b') == '"a\\"b"'


def test_enc_string_ters_bolme():
    """ORTAM: '\\' -> '\\\\'."""
    assert _enc_string("a\\b") == '"a\\\\b"'


def test_enc_string_newline():
    assert _enc_string("a\nb") == '"a\\nb"'


def test_enc_string_carriage():
    assert _enc_string("a\rb") == '"a\\rb"'


def test_enc_string_tab():
    assert _enc_string("a\tb") == '"a\\tb"'


def test_enc_string_donut_tipi():
    assert isinstance(_enc_string("x"), str)


@pytest.mark.parametrize("g,b", [
    ("", '""'), ("a", '"a"'), ("abc", '"abc"'), ('a"b', '"a\\"b"'),
    ("a\\b", '"a\\\\b"'), ("a\nb", '"a\\nb"'), ("a\rb", '"a\\rb"'),
    ("a\tb", '"a\\tb"'), ('"', '"\\""'), ("\\", '"\\\\"'),
])
def test_enc_string_matrix(g, b):
    assert _enc_string(g) == b


# == _enc_string: kontrol-karakterleri ================================================================

def test_enc_string_control_u00():
    """ORTAM: ord<0x20 -> \\uXXXX (4 haneli, kucuk x? kontrol)."""
    out = _enc_string("\x00")
    assert out == '"\\u0000"' or out == '"\\u0000"'


def test_enc_string_control_01():
    out = _enc_string("\x01")
    assert out.startswith('"\\u00') and out.endswith('"')


def test_enc_string_control_1f():
    """ORTAM: SON control char 0x1F -> kacis."""
    out = _enc_string("\x1f")
    assert "\\u001f" in out


def test_enc_string_control_20_sinir():
    """ORTAM: 0x20 (space) control DEGIL -> HAM bosluk."""
    assert _enc_string("a b") == '"a b"'


def test_enc_string_control_7f():
    """ORTAM: 0x7F (DEL) >= 0x20 -> HAM (RFC 8785 kacislanMAZ)."""
    assert _enc_string("\x7f") == '"\x7f"'


def test_enc_string_control_form_feed():
    """ORTAM-OGRENDI: \f = 0x0C -> KISA kacis '\f' (_ESCAPE tablosunda)."""
    assert _enc_string("\f") == '"\\f"' 

def test_enc_string_backspace():
    """ORTAM-OGRENDI: \b = 0x08 -> KISA kacis '\b' (_ESCAPE tablosunda)."""
    assert _enc_string("\b") == '"\\b"' 

def test_enc_string_control_heks_kucuk():
    """ORTAM: f'\\u{ord(ch):04x}' — kucuk harf 'x' formati."""
    out = _enc_string("\x1f")
    assert "\\u001f" in out


@pytest.mark.parametrize("ch,b", [
    ("\x00", '"\\u0000"'), ("\x01", '"\\u0001"'), ("\x02", '"\\u0002"'),
    ("\x08", '"\\b"'), ("\x0c", '"\\f"'), ("\x0e", '"\\u000e"'),
    ("\x1f", '"\\u001f"'), ("\n", '"\\n"'), ("\r", '"\\r"'), ("\t", '"\\t"'),
])
def test_enc_string_control_matrix(ch, b):
    """ORTAM-OGRENDI: _ESCAPE tablosundaki 7 char KISA kacis; geri kalan
    ord<0x20 -> \\uXXXX."""
    assert _enc_string(ch) == b


# == _enc_string: unicode =============================================================================

def test_enc_string_ascii():
    assert _enc_string("hello") == '"hello"'


def test_enc_string_turkce():
    """ORTAM: non-ASCII HAM (RFC 8785: BMP char'lar kacislanMAZ)."""
    assert _enc_string("ö") == '"ö"'


def test_enc_string_turkce_kelime():
    assert _enc_string("ğüşı") == '"ğüşı"'


def test_enc_string_emoji():
    """ORTAM: emoji HAM (surrogate kacisi YOK)."""
    assert _enc_string("🎉") == '"🎉"'


def test_enc_string_bmp_sinir():
    """ORTAM: 0xFFFF BMP son char HAM."""
    assert _enc_string("\uffff") == '"\uffff"'


# == _encode: null/bool ===============================================================================

def test_encode_none():
    out = []
    _encode(None, out)
    assert out == ["null"]


def test_encode_true():
    out = []
    _encode(True, out)
    assert out == ["true"]


def test_encode_false():
    out = []
    _encode(False, out)
    assert out == ["false"]


def test_encode_bool_true():
    """ORTAM-OGRENDI: bool True 'is True' dalina girer; 'isinstance(bool)'
    dalina ASLA ulasilamaz (bool True/False once yakalanir). Dead-code
    characterization."""
    out = []
    _encode(bool(True), out)
    assert out == ["true"]


def test_encode_bool_false():
    out = []
    _encode(bool(False), out)
    assert out == ["false"]


def test_encode_bool_int_ayni():
    """ORTAM: bool VE True/FALSE AYNI cikti (true/false)."""
    a, b = [], []
    _encode(True, a)
    _encode(True.__class__(1), b)
    assert a == b == ["true"]


# == _encode: int =====================================================================================

def test_encode_int_sifir():
    out = []
    _encode(0, out)
    assert out == ["0"]


def test_encode_int_negatif():
    out = []
    _encode(-1, out)
    assert out == ["-1"]


def test_encode_int_buyuk():
    out = []
    _encode(123456, out)
    assert out == ["123456"]


def test_encode_int_sinir_ust():
    """ORTAM: I-JSON sinir TAM 2**53 KABUL."""
    out = []
    _encode(2 ** 53, out)
    assert out == [str(2 ** 53)]


def test_encode_int_sinir_ust_asim():
    """ORTAM: 2**53 + 1 -> ValueError (I-JSON disi)."""
    out = []
    with pytest.raises(ValueError):
        _encode(2 ** 53 + 1, out)


def test_encode_int_sinir_alt():
    out = []
    _encode(-(2 ** 53), out)
    assert out == [str(-(2 ** 53))]


def test_encode_int_sinir_alt_asim():
    out = []
    with pytest.raises(ValueError):
        _encode(-(2 ** 53) - 1, out)


def test_encode_int_bool_duzeltme():
    """ORTAM-OGRENDI: True int DEGIL — once bool dalina girer (true)."""
    out = []
    _encode(True, out)
    assert out == ["true"]
    # ama int(True) -> 1
    out2 = []
    _encode(int(True), out2)
    assert out2 == ["1"]


@pytest.mark.parametrize("v,b", [(0, "0"), (1, "1"), (-1, "-1"), (42, "42"),
                                  (2 ** 53, str(2 ** 53)), (-(2 ** 53), str(-(2 ** 53)))])
def test_encode_int_matrix(v, b):
    out = []
    _encode(v, out)
    assert out == [b]


# == _encode: float ===================================================================================

def test_encode_float_sifir():
    out = []
    _encode(0.0, out)
    assert out == ["0"]


def test_encode_float_neg_sifir():
    """ORTAM: -0.0 -> '-0' (es_number x==0 -> '0'; neg -> '-0'? kontrol)."""
    out = []
    _encode(-0.0, out)
    assert out == ["-0"] or out == ["0"]


def test_encode_float_bir():
    out = []
    _encode(1.0, out)
    assert out == ["1"]


def test_encode_float_kesir():
    out = []
    _encode(1.5, out)
    assert out == ["1.5"]


def test_encode_float_int_gorunum():
    """ORTAM-OGRENDI: 1.0 -> '1' DEGIL '1'? ECMAScript ToString:
    float 1.0 -> '1' (trailing '.0' YOK). Python json.dumps -> '1.0'!
    Bu RFC 8785 ile Python arasindaki EN ONEMLI fark (digest uyumsuzlugu)."""
    out = []
    _encode(1.0, out)
    assert out == ["1"]
    import json
    assert json.dumps(1.0) == "1.0"  # karsilastirma


def test_encode_float_buyuk():
    """ORTAM: 1e21 -> ECMAScript exponent notation."""
    out = []
    _encode(1e21, out)
    assert out == ["1e+21"]


def test_encode_float_buyuk2():
    out = []
    _encode(1e22, out)
    assert out == ["1e+22"]


def test_encode_float_kucuk():
    """ORTAM: 1e-7 -> ECMAScript exponent."""
    out = []
    _encode(1e-7, out)
    assert out == ["1e-7"]


def test_encode_float_cok_kucuk():
    out = []
    _encode(1e-8, out)
    assert out == ["1e-8"]


def test_encode_float_nan():
    """ORTAM-OGRENDI: NaN -> es_number -> ValueError (ijson_number_not_finite).
    I-JSON (RFC 7493) NaN/Infinity'yi yasaklar! JSON.parse'te patlamasini
    engellemek icin ERKEN-yakalama."""
    out = []
    with pytest.raises(ValueError):
        _encode(float("nan"), out)


def test_encode_float_inf():
    """ORTAM: inf -> ValueError (I-JSON finite zorunlulugu)."""
    out = []
    with pytest.raises(ValueError):
        _encode(float("inf"), out)


def test_encode_float_neg_inf():
    """ORTAM: -inf -> ValueError."""
    out = []
    with pytest.raises(ValueError):
        _encode(float("-inf"), out)


def test_encode_float_nan_mesaj():
    out = []
    with pytest.raises(ValueError) as e:
        _encode(float("nan"), out)
    assert "ijson_number_not_finite" in str(e.value)


def test_encode_float_round_trip():
    """ORTAM: es_number shortest round-trip — repr ile ayni."""
    import json
    for v in [0.1, 1.1, 3.14, 2.5, 1e16, 1e-6]:
        out = []
        _encode(v, out)
        assert float(out[0]) == v


# == _encode: str =====================================================================================

def test_encode_str():
    out = []
    _encode("abc", out)
    assert out == ['"abc"']


def test_encode_str_tirnak():
    out = []
    _encode('a"b', out)
    assert out == ['"a\\"b"']


def test_encode_str_turkce():
    out = []
    _encode("ö", out)
    assert out == ['"ö"']


def test_encode_str_bos():
    out = []
    _encode("", out)
    assert out == ['""']


# == _encode: dict ====================================================================================

def test_encode_dict_bos():
    out = []
    _encode({}, out)
    assert out == ["{", "}"]


def test_encode_dict_basit():
    out = []
    _encode({"a": 1}, out)
    assert out == ["{", '"a"', ":", "1", "}"]


def test_encode_dict_sirali():
    """ORTAM: anahtarlar UTF-16 code-unit order (RFC 8785 §3.2.3)."""
    out = []
    _encode({"b": 1, "a": 2}, out)
    assert "".join(out) == '{"a":2,"b":1}'


def test_encode_dict_sirali_z_y():
    """ORTAM: z y'den once (UTF-16 BE siralama)."""
    out = []
    _encode({"y": 1, "z": 2}, out)
    assert "".join(out) == '{"y":1,"z":2}'


def test_encode_dict_buyuk_harf_once():
    """ORTAM: ASCII buyuk harfler kucukten once (UTF-16 code-unit order)."""
    out = []
    _encode({"a": 1, "B": 2}, out)
    assert "".join(out) == '{"B":2,"a":1}'


def test_encode_dict_icice():
    out = []
    _encode({"z": {"y": 1, "x": 2}}, out)
    assert "".join(out) == '{"z":{"x":2,"y":1}}'


def test_encode_dict_deger_str():
    out = []
    _encode({"a": "x"}, out)
    assert "".join(out) == '{"a":"x"}'


def test_encode_dict_deger_none():
    out = []
    _encode({"a": None}, out)
    assert "".join(out) == '{"a":null}'


def test_encode_dict_deger_bool():
    out = []
    _encode({"a": True, "b": False}, out)
    assert "".join(out) == '{"a":true,"b":false}'


def test_encode_dict_deger_liste():
    out = []
    _encode({"a": [1, 2]}, out)
    assert "".join(out) == '{"a":[1,2]}'


def test_encode_dict_anahtar_str_cast():
    """ORTAM-OGRENDI (ANATOMI BULGUSU): int anahtar -> AttributeError!
    Cunku sorted(key=lambda k: k.encode('utf-16-be')) — int.encode YOK.
    Anahtarlar str OLMALI; _enc_string(str(key)) cast'i sorted'dan SONRA.
    Production kullaniminda anahtarlar hep str (JSON)."""
    out = []
    with pytest.raises(AttributeError):
        _encode({1: "a"}, out)


def test_encode_dict_str_anahtar_ok():
    """ORTAM: str anahtarlar sorunsuz."""
    out = []
    _encode({"1": "a"}, out)
    assert "".join(out) == '{"1":"a"}' 

def test_encode_dict_bosluk_yok():
    """ORTAM: compact — ':' VE ',' bosluk YOK (separators)."""
    out = []
    _encode({"a": 1, "b": 2}, out)
    sonuc = "".join(out)
    assert sonuc == '{"a":1,"b":2}'


def test_encode_dict_stabil():
    """ORTAM: ayni dict her zaman ayni canonical (deterministik)."""
    a, b = [], []
    _encode({"b": 1, "a": 2, "c": 3}, a)
    _encode({"a": 2, "c": 3, "b": 1}, b)
    assert a == b


# == _encode: list/tuple ==============================================================================

def test_encode_liste_bos():
    out = []
    _encode([], out)
    assert out == ["[", "]"]


def test_encode_liste_basit():
    out = []
    _encode([1, 2], out)
    assert "".join(out) == "[1,2]"


def test_encode_liste_str():
    out = []
    _encode(["a", "b"], out)
    assert "".join(out) == '["a","b"]'


def test_encode_liste_sira_korunur():
    """ORTAM-OGRENDI: liste siralamasi KORUNUR (siralama YOK — RFC 8785
    dict'ler icin gecerli, array'ler KORUNMALI)."""
    out = []
    _encode([3, 1, 2], out)
    assert "".join(out) == "[3,1,2]"


def test_encode_tuple_ayni():
    """ORTAM: tuple liste ile AYNI cikti ([...])."""
    out1, out2 = [], []
    _encode((1, 2), out1)
    _encode([1, 2], out2)
    assert out1 == out2


def test_encode_liste_icice():
    out = []
    _encode([[1, 2], [3]], out)
    assert "".join(out) == "[[1,2],[3]]"


def test_encode_liste_dict():
    out = []
    _encode([{"b": 1, "a": 2}], out)
    assert "".join(out) == '[{"a":2,"b":1}]'


def test_encode_liste_karisik():
    out = []
    _encode([1, "a", None, True], out)
    assert "".join(out) == '[1,"a",null,true]'


# == _encode: TypeError ===============================================================================

def test_encode_set_hata():
    """ORTAM: set -> TypeError."""
    out = []
    with pytest.raises(TypeError):
        _encode({1}, out)


def test_encode_object_hata():
    out = []
    with pytest.raises(TypeError):
        _encode(object(), out)


def test_encode_bytes_hata():
    """ORTAM: bytes -> TypeError (JCS UTF-8 string ister)."""
    out = []
    with pytest.raises(TypeError):
        _encode(b"x", out)


def test_encode_tuple_icerik_object():
    out = []
    with pytest.raises(TypeError):
        _encode([object()], out)


def test_encode_dict_deger_object():
    out = []
    with pytest.raises(TypeError):
        _encode({"a": object()}, out)


def test_encode_typeerror_mesaj():
    out = []
    with pytest.raises(TypeError) as e:
        _encode(object(), out)
    assert "unsupported" in str(e.value)


# == jcs / jcs_json ===================================================================================

def test_jcs_donut_tipi():
    assert isinstance(jcs({}), bytes)


def test_jcs_json_donut_tipi():
    assert isinstance(jcs_json({}), str)


def test_jcs_bos_dict():
    assert jcs({}) == b"{}"


def test_jcs_json_bos_dict():
    assert jcs_json({}) == "{}"


def test_jcs_json_esit_jcs_decode():
    """ORTAM: jcs_json == jcs().decode('utf-8')."""
    obj = {"b": 1, "a": [1.0, "x"]}
    assert jcs_json(obj) == jcs(obj).decode("utf-8")


def test_jcs_utf8():
    """ORTAM: .encode('utf-8') — Turkce UTF-8 byte."""
    assert jcs("ö") == '"ö"'.encode("utf-8")


def test_jcs_deterministik():
    """ORTAM: ayni icerik -> ayni byte (farkli anahtar-sirasi olsa bile)."""
    a = jcs({"b": 1, "a": 2, "c": 3})
    b = jcs({"a": 2, "c": 3, "b": 1})
    assert a == b


def test_jcs_bilinen_hash_eslesme():
    """ORTAM-OGRENDI: canonical byte'lar NIST sha256 ile birebir
    dogrulanabilir (diger dilde yeniden-uretim ile anlasma)."""
    import hashlib
    assert hashlib.sha256(jcs({"a": 1})).hexdigest() == hashlib.sha256(
        b'{"a":1}').hexdigest()


# == es_number ========================================================================================

def test_es_number_sifir():
    assert es_number(0.0) == "0"


def test_es_number_bir():
    assert es_number(1.0) == "1"


def test_es_number_kesir():
    assert es_number(1.5) == "1.5"


def test_es_number_negatif():
    assert es_number(-1.5) == "-1.5"


def test_es_number_int_gorunum():
    """ORTAM-OGRENDI: 10.0 -> '10' (trailing '.0' YOK) — ECMAScript
    ToString; Python '10.0' verirdi."""
    assert es_number(10.0) == "10"


def test_es_number_yuvarlama():
    assert es_number(1.5) == "1.5"


@pytest.mark.parametrize("v", [0.0, 1.0, -1.0, 1.5, 0.1, 3.14, 1e16, 1e-6])
def test_es_number_round_trip(v):
    """ORTAM: shortest round-trip — float(es_number(x)) == x."""
    assert float(es_number(v)) == v


# == karakterizasyon ===================================================================================

def test_rfc8785_amaci():
    """ORTAM-OGRENDI (DOCSTACK): RFC 8785 JCS — AYNI nesne -> AYNI byte
    (dil-bagimsiz). Diger DIL yeniden-uretimi ile digest uyumu icin:
    ECMAScript number format, UTF-16 code-unit member order, compact
    separators. Plain json.dumps YETERSIZ (1.0 -> '1.0' vs JCS '1')."""
    import json
    obj = {"b": 1.0, "a": 2}
    py = json.dumps(obj, sort_keys=True, separators=(",", ":"))
    jc = jcs_json(obj)
    # Python '1.0' verir, JCS '1' verir -> FARKLI!
    assert py != jc
    assert jc == '{"a":2,"b":1}'


def test_ijson_sinir_amaci():
    """ORTAM-OGRENDI: I-JSON (RFC 7493) sinir -(2**53)..2**53 — ECMAScript
    Number MAX_SAFE_INTEGER. Disi deger Python'da dogru, Node'da yuvarlanir
    -> digest uyumsuzlugu. Bu yuzden ValueError ile erken-yakalama.
    (2026-09-18 tarihli duzeltme, kod-yorumunda belgeli.)"""
    out = []
    with pytest.raises(ValueError):
        _encode(2 ** 54, out)


def test_unicode_kacis_yok():
    """ORTAM-OGRENDI: RFC 8785 non-ASCII'yi HAM yazar (ensure_ascii=False
    ile ayni ruh). Turkce/emoji kacislanmaz."""
    assert jcs_json({"x": "ö🎉"}) == '{"x":"ö🎉"}'


def test_utf16_siralama_ascii_ayni():
    """ORTAM: ASCII icin UTF-16 code-unit order == code-point order
    (hepsi 1 code-unit). Fark sadece non-BMP/surrogate'larda belirir."""
    a = jcs_json({"z": 1, "a": 2})
    assert a == '{"a":2,"z":1}'
