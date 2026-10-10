"""tamga_jcs._enc_string dal-kesen testleri (LEED).

Kural-1: mevcut dosyalara DOKUNULMADI, SADECE bu yeni dosya eklendi.
Kural-4: saf in-memory (dis cagri YOK).
RFC-8785 JCS string encoding: escape table + kontrol-karakterleri.
"""
import pytest

from pacta.integrations.tamga_jcs import _enc_string, _ESCAPE


# -- temel ---------------------------------------------------------------------------------

def test_empty_string():
    assert _enc_string("") == '""'


def test_simple():
    assert _enc_string("hello") == '"hello"'


def test_returns_str():
    assert isinstance(_enc_string("x"), str)


def test_quotes_surround():
    assert _enc_string("abc").startswith('"') and _enc_string("abc").endswith('"')


def test_length():
    assert len(_enc_string("")) == 2


# -- escape-table ---------------------------------------------------------------------------------

def test_double_quote():
    assert _enc_string('"') == '"\\""'


def test_backslash():
    assert _enc_string("\\") == '"\\\\"'


def test_backspace():
    assert _enc_string("\b") == '"\\b"'


def test_formfeed():
    assert _enc_string("\f") == '"\\f"'


def test_newline():
    assert _enc_string("\n") == '"\\n"'


def test_carriage_return():
    assert _enc_string("\r") == '"\\r"'


def test_tab():
    assert _enc_string("\t") == '"\\t"'


@pytest.mark.parametrize("ch", list(_ESCAPE))
def test_all_escapes(ch):
    assert _enc_string(ch) == '"' + _ESCAPE[ch] + '"'


def test_escape_table_size():
    assert len(_ESCAPE) == 7


def test_mixed_escapes():
    assert _enc_string('a\nb"c\\d') == '"a\\nb\\"c\\\\d"'


# -- kontrol-karakterleri (< 0x20) ---------------------------------------------------------------------------------

@pytest.mark.parametrize("code", list(range(0x20)))
def test_control_chars(code):
    ch = chr(code)
    if ch in _ESCAPE:
        assert _enc_string(ch) == '"' + _ESCAPE[ch] + '"'
    else:
        assert _enc_string(ch) == f'"\\u{code:04x}"'


def test_null_byte():
    assert _enc_string("\x00") == '"\\u0000"'


def test_unit_separator():
    assert _enc_string("\x1f") == '"\\u001f"'


def test_start_of_heading():
    assert _enc_string("\x01") == '"\\u0001"'


def test_lowcase_hex():
    # kucuk-harf hex kullanilir
    assert "\\u001f" in _enc_string("\x1f")


def test_4_digit_hex():
    assert _enc_string("\x05") == '"\\u0005"'


# -- sinir: 0x20 ve ustu raw ---------------------------------------------------------------------------------

def test_space_raw():
    """0x20 escape edilmez (raw)."""
    assert _enc_string(" ") == '" "'


def test_exclaim_raw():
    assert _enc_string("!") == '"!"'


def test_tilde_raw():
    assert _enc_string("~") == '"~"'


def test_del_raw():
    """0x7f raw (sadece <0x20 escape)."""
    assert _enc_string("\x7f") == '"\x7f"'


# -- unicode ---------------------------------------------------------------------------------

def test_turkish_raw():
    """0x20 ustu UTF-8 raw."""
    assert _enc_string("çğıöşü") == '"çğıöşü"'


def test_emoji_raw():
    assert _enc_string("😀") == '"😀"'


def test_euro_raw():
    assert _enc_string("€") == '"€"'


def test_hebrew_raw():
    assert _enc_string("אבג") == '"אבג"'


def test_cjk_raw():
    assert _enc_string("日本語") == '"日本語"'


def test_supplementary_plane():
    """U+10000+ raw (4 byte UTF-8)."""
    s = "𝄞"
    assert _enc_string(s) == '"' + s + '"'


# -- ozel-karakterler (escape-tablosu disinda) ---------------------------------------------------------------------------------

def test_slash_not_escaped():
    """JSON'da / escape gerekmez (JCS de etmez)."""
    assert _enc_string("/") == '"/"'


def test_backtick_raw():
    assert _enc_string("`") == '"`"'


def test_braces_raw():
    assert _enc_string("{}") == '"{}"'


def test_brackets_raw():
    assert _enc_string("[]") == '"[]"'


def test_colon_raw():
    assert _enc_string(":") == '":"'


def test_comma_raw():
    assert _enc_string(",") == '","'


def test_ampersand_raw():
    assert _enc_string("&") == '"&"'


def test_at_raw():
    assert _enc_string("@") == '"@"'


# -- karmasik ---------------------------------------------------------------------------------

def test_multiline():
    assert _enc_string("line1\nline2") == '"line1\\nline2"'


def test_tab_indent():
    assert _enc_string("\tx") == '"\\tx"'


def test_crlf():
    assert _enc_string("a\r\nb") == '"a\\r\\nb"'


def test_only_control():
    assert _enc_string("\x01\x02\x03") == '"\\u0001\\u0002\\u0003"'


def test_mixed_unicode_control():
    assert _enc_string("a\x01ç") == '"a\\u0001ç"'


# -- tekrar ---------------------------------------------------------------------------------

def test_repeatable():
    assert _enc_string('a"b') == _enc_string('a"b')


def test_idempotent_inner():
    """encode edilmis string'in ic-kismi tekrar encode edilirse farkli."""
    once = _enc_string('"')[1:-1]
    assert once == '\\"'


def test_returns_new_string():
    s = "abc"
    assert _enc_string(s) is not s


def test_independent_calls():
    assert _enc_string("x") + _enc_string("y") == '"x""y"'


# -- uzun ---------------------------------------------------------------------------------

def test_long_string():
    s = "a" * 1000
    assert _enc_string(s) == '"' + s + '"'


def test_long_with_escapes():
    s = "\n" * 100
    assert _enc_string(s) == '"' + "\\n" * 100 + '"'


# -- input-not-mutated ---------------------------------------------------------------------------------

def test_input_not_mutated():
    s = 'a"b'
    _enc_string(s)
    assert s == 'a"b'
