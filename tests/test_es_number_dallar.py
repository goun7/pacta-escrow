"""tamga_jcs.es_number dal-kesen testleri (LEED).

Kural-1: mevcut dosyalara DOKUNULMADI, SADECE bu yeni dosya eklendi.
Dış çağrı YOK: saf fonksiyon (ECMAScript Number.prototype.toString).
"""
import pytest

from pacta.integrations.tamga_jcs import es_number


# -- sifir ---------------------------------------------------------------------------------

def test_zero():
    assert es_number(0) == "0"


def test_neg_zero():
    assert es_number(-0.0) == "0"


def test_zero_str():
    assert isinstance(es_number(0.0), str)


# -- sonsuzluk/NaN ---------------------------------------------------------------------------------

def test_nan_raises():
    with pytest.raises(ValueError):
        es_number(float("nan"))


def test_inf_raises():
    with pytest.raises(ValueError):
        es_number(float("inf"))


def test_neg_inf_raises():
    with pytest.raises(ValueError):
        es_number(float("-inf"))


def test_nan_message_has_ijson():
    with pytest.raises(ValueError, match="ijson_number_not_finite"):
        es_number(float("nan"))


# -- kucuk tamsayilar ---------------------------------------------------------------------------------

@pytest.mark.parametrize("v,expected", [
    (1, "1"), (2, "2"), (9, "9"), (10, "10"), (11, "11"),
    (99, "99"), (100, "100"), (999, "999"), (1000, "1000"),
    (20, "20"), (21, "21"),
])
def test_integers(v, expected):
    assert es_number(v) == expected


@pytest.mark.parametrize("v,expected", [
    (-1, "-1"), (-10, "-10"), (-100, "-100"), (-999, "-999"),
])
def test_negative_integers(v, expected):
    assert es_number(v) == expected


# -- ondaliklar ---------------------------------------------------------------------------------

@pytest.mark.parametrize("v,expected", [
    (0.5, "0.5"), (0.1, "0.1"), (1.5, "1.5"), (2.5, "2.5"),
    (0.25, "0.25"), (0.125, "0.125"), (1.25, "1.25"),
    (123456.789, "123456.789"),
])
def test_decimals(v, expected):
    assert es_number(v) == expected


@pytest.mark.parametrize("v,expected", [
    (-0.5, "-0.5"), (-1.5, "-1.5"), (-0.1, "-0.1"),
    (-123456.789, "-123456.789"),
])
def test_negative_decimals(v, expected):
    assert es_number(v) == expected


# -- cok kucuk ---------------------------------------------------------------------------------

def test_1e_minus_6():
    assert es_number(1e-6) == "0.000001"


def test_1e_minus_7_exponential():
    assert es_number(1e-7) == "1e-7"


def test_5e_minus_7():
    assert es_number(5e-7) == "5e-7"


def test_1e_minus_5():
    assert es_number(1e-5) == "0.00001"


# -- cok buyuk ---------------------------------------------------------------------------------

def test_1e21_exponential():
    assert es_number(1e21) == "1e+21"


def test_1e22():
    assert es_number(1e22) == "1e+22"


def test_large_mantissa():
    """float precision: 21 hane -> exponent'siz."""
    r = es_number(123456789012345678901.0)
    assert r == "123456789012345680000"


# -- string turu ---------------------------------------------------------------------------------

@pytest.mark.parametrize("v", [0, 1, -1, 0.5, 1e21, 1e-7, 123456.789])
def test_always_str(v):
    assert isinstance(es_number(v), str)


# -- roundtrip semantiği ---------------------------------------------------------------------------------

@pytest.mark.parametrize("v", [
    0, 1, 5, 42, 0.5, 0.25, 1.5, 100, 1000, 0.001, -1, -0.5,
])
def test_parseable_back(v):
    assert float(es_number(v)) == v


def test_no_trailing_dot():
    for v in (1, 10, 100, 1000):
        assert "." not in es_number(v)


def test_no_leading_plus():
    assert not es_number(5).startswith("+")


def test_negative_has_minus():
    assert es_number(-5).startswith("-")


# -- repr-temelli davranis ---------------------------------------------------------------------------------

def test_int_valued_float_int_output():
    assert es_number(7.0) == "7"


def test_int_valued_negative_float():
    assert es_number(-7.0) == "-7"


def test_very_long_decimal():
    assert es_number(1 / 3) == es_number(1 / 3)


# -- karmasik ---------------------------------------------------------------------------------

def test_million():
    assert es_number(1000000) == "1000000"


def test_billion():
    assert es_number(1000000000) == "1000000000"


def test_trillion_plain():
    """1e15 = 16 hane <= 21 -> exponent'siz."""
    assert es_number(1e15) == "1000000000000000"


def test_tiny_reciprocal():
    assert es_number(1e-10) == "1e-10"


# -- tekrar ---------------------------------------------------------------------------------

def test_repeatable():
    assert es_number(123.456) == es_number(123.456)


def test_no_state():
    """Arka arkaya farklı değerler bağımsız."""
    a = es_number(1.5)
    b = es_number(2.5)
    assert a == "1.5" and b == "2.5"
