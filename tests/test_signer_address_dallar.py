"""tamga_d5._signer_address dal-kesen testleri (LEED).

Kural-1: mevcut dosyalara DOKUNULMADI, SADECE bu yeni dosya eklendi.
Kural-4: saf in-memory (eth-keys/eth-account local anahtar uretimi).
"""
import pytest
from eth_account import Account
from eth_utils import to_checksum_address
from eth_keys import keys as eth_keys
from eth_keys.datatypes import PrivateKey

from pacta.integrations.tamga_d5 import _signer_address


# -- eth_account.Account --------------------------------------------------------------------------

@pytest.fixture()
def acct():
    return Account.create()


def test_eth_account(acct):
    addr = _signer_address(acct)
    assert addr.lower().startswith("0x")


def test_eth_account_correct(acct):
    """Public-key'den adres = account.address ile AYNI."""
    assert _signer_address(acct).lower() == acct.address.lower()


def test_eth_account_is_lowercase(acct):
    """URETIM-SINIRI: to_address() KUCUK-HARF doner (EIP-55 checksum YOK)
    — Account.address checksummed ile ayni DEGIL, sadece .lower() ile esit."""
    addr = _signer_address(acct)
    assert addr == addr.lower()
    assert addr.lower() == acct.address.lower()
    assert addr != acct.address  # checksum farkli


def test_eth_account_40_hex(acct):
    addr = _signer_address(acct)[2:]
    assert len(addr) == 40
    int(addr, 16)


def test_eth_account_multiple_distinct():
    a, b = Account.create(), Account.create()
    assert _signer_address(a) != _signer_address(b)


# -- bytes / bytearray --------------------------------------------------------------------------

def test_bytes_signer(acct):
    addr = _signer_address(acct.key)
    assert addr.lower() == acct.address.lower()


def test_bytearray_signer(acct):
    addr = _signer_address(bytearray(acct.key))
    assert addr.lower() == acct.address.lower()


def test_bytes_type_priority(acct):
    """bytes-branch once kontrol edilir (bytearray bytes'a cevrilir)."""
    assert _signer_address(bytes(acct.key)) == _signer_address(acct.key)


def test_bytes_correct_from_raw():
    raw = b"\x01" * 32
    expected = eth_keys.PrivateKey(raw).public_key.to_address()
    assert _signer_address(raw) == expected


def test_bytes_vs_bytes_from_account(acct):
    """bytes(signer.key) ile ayni sonuc."""
    assert _signer_address(bytes(acct.key)) == _signer_address(acct)


# -- eth_keys.PrivateKey --------------------------------------------------------------------------

def test_private_key_signer():
    pk = PrivateKey(b"\x02" * 32)
    addr = _signer_address(pk)
    assert addr == pk.public_key.to_address()


def test_private_key_isinstance_branch(acct):
    pk = PrivateKey(acct.key)
    assert _signer_address(pk).lower() == acct.address.lower()


def test_private_key_uses_to_bytes():
    """PrivateKey branch -> signer.to_bytes()."""
    pk = PrivateKey(b"\x03" * 32)
    assert _signer_address(pk) == _signer_address(pk.to_bytes())


# -- TypeError-dali --------------------------------------------------------------------------

@pytest.mark.parametrize("v", [
    "0x" + "11" * 20,  # str
    12345,             # int
    1.5,               # float
    None,              # None
    ["a"],             # list
    {"a": 1},          # dict
    (1, 2),            # tuple
    {1, 2},            # set
    True,              # bool
])
def test_unsupported_type_raises_type_error(v):
    with pytest.raises(TypeError, match="unsupported_signer"):
        _signer_address(v)


def test_error_message_has_type():
    with pytest.raises(TypeError) as exc:
        _signer_address("x")
    assert "str" in str(exc.value)


def test_error_message_mentions_expected_types():
    with pytest.raises(TypeError) as exc:
        _signer_address(None)
    s = str(exc.value)
    assert "bytes" in s or "eth_account" in s or "PrivateKey" in s


def test_object_with_no_key_raises():
    class _Bare:
        pass
    with pytest.raises(TypeError):
        _signer_address(_Bare())


# -- hasattr-key-gotcha --------------------------------------------------------------------------

def test_object_with_key_attribute_uses_it():
    """hasattr(signer, 'key') -> bytes(signer.key)."""
    pk = PrivateKey(b"\x04" * 32)
    holder = type("_H", (), {"key": pk.to_bytes()})()
    assert _signer_address(holder) == pk.public_key.to_address()


def test_object_with_wrong_key_type_raises():
    holder = type("_H", (), {"key": "not-bytes"})()
    with pytest.raises((TypeError, ValueError)):
        _signer_address(holder)


def test_account_key_is_bytes():
    acct = Account.create()
    assert isinstance(acct.key, bytes)


# -- determinizm / tekrar --------------------------------------------------------------------------

def test_repeatable(acct):
    assert _signer_address(acct) == _signer_address(acct)


def test_independent_calls():
    for _ in range(5):
        acct = Account.create()
        assert _signer_address(acct).lower() == acct.address.lower()


def test_three_input_forms_agree():
    acct = Account.create()
    pk = PrivateKey(acct.key)
    a1 = _signer_address(acct)
    a2 = _signer_address(acct.key)
    a3 = _signer_address(pk)
    assert a1 == a2 == a3


# -- anahtar-gecterlilik --------------------------------------------------------------------------

def test_zero_key_raises_validation():
    """0 anahtar secp256k1 icin gecersiz -> ValidationError."""
    with pytest.raises(Exception, match="not greater"):
        _signer_address(b"\x00" * 32)


def test_max_key_raises_validation():
    """0xff*32 > curve order -> ValidationError."""
    with pytest.raises(Exception, match="not less"):
        _signer_address(b"\xff" * 32)


def test_short_key_raises():
    with pytest.raises(Exception, match="Unexpected private key"):
        _signer_address(b"\x01" * 31)


def test_long_key_raises():
    with pytest.raises(Exception, match="Unexpected private key"):
        _signer_address(b"\x01" * 33)


def test_empty_bytes_raises():
    with pytest.raises(Exception, match="Unexpected private key"):
        _signer_address(b"")


def test_secp256k1_out_of_range_raises():
    """k >= curve order -> ValidationError (range check)."""
    order = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEBAAEDCE6AF48A03BBFD25E8CD0364141
    with pytest.raises(Exception, match="not less"):
        _signer_address((order + 1).to_bytes(32, "big"))


# -- adres-formati --------------------------------------------------------------------------

def test_address_length(acct):
    assert len(_signer_address(acct)) == 42


def test_address_hex_charset(acct):
    addr = _signer_address(acct)[2:]
    assert all(c in "0123456789abcdefABCDEF" for c in addr)


def test_addresses_never_checksummed():
    """Her zaman kucuk-harf (EIP-55 uygulanmaz)."""
    acct = Account.create()
    addr = _signer_address(acct)
    assert addr == addr.lower()
