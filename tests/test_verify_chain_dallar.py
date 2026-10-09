"""models.ChainAnchor.verify_against_chain dal-kesen testleri (LEED).

Kural-1: mevcut dosyalara DOKUNULMADI, SADECE bu yeni dosya eklendi.
Dış çağrı YOK: w3 stub (gercek RPC YOK).
"""
import pytest

from pacta.models import ChainAnchor

_COMMIT = "0x" + "ab" * 32
_TX = "0x" + "cd" * 32


class _Eth:
    def __init__(self, receipt=None, tx=None,
                 receipt_exc=None, tx_exc=None):
        self._receipt = receipt
        self._tx = tx
        self.receipt_exc = receipt_exc
        self.tx_exc = tx_exc
        self.calls = []

    def get_transaction_receipt(self, h):
        self.calls.append(("receipt", h))
        if self.receipt_exc:
            raise self.receipt_exc
        return self._receipt

    def get_transaction(self, h):
        self.calls.append(("tx", h))
        if self.tx_exc:
            raise self.tx_exc
        return self._tx


class _W3:
    def __init__(self, **kw):
        self.eth = _Eth(**kw)


def _anchor(**kw):
    args = dict(
        chain_id=1, tx_hash=_TX, block_number=42,
        gas_used=21000, anchor_kind="settlement",
        job_id="j1", commitment_keccak=_COMMIT,
        anchored_at_epoch_ms=1700000000000,
        from_address="0xFROM", to_address="0xTO",
        rpc_url="http://x", backend="anvil",
    )
    args.update(kw)
    return ChainAnchor(**args)


def _ok_w3(receipt=None, tx=None):
    receipt = receipt if receipt is not None else {
        "status": 1, "blockNumber": 42}
    tx = tx if tx is not None else {"input": _COMMIT}
    return _W3(receipt=receipt, tx=tx)


# -- tam dogrulama ---------------------------------------------------------------------------------

def test_valid_returns_true():
    assert _anchor().verify_against_chain(_ok_w3()) is True


def test_receipt_fetched():
    w = _ok_w3()
    _anchor().verify_against_chain(w)
    assert w.eth.calls[0] == ("receipt", _TX)


def test_tx_fetched():
    w = _ok_w3()
    _anchor().verify_against_chain(w)
    assert ("tx", _TX) in w.eth.calls


def test_two_rpc_calls():
    w = _ok_w3()
    _anchor().verify_against_chain(w)
    assert len(w.eth.calls) == 2


# -- receipt hatalari ---------------------------------------------------------------------------------

def test_receipt_exception_false():
    w = _W3(receipt_exc=RuntimeError("rpc-down"))
    assert _anchor().verify_against_chain(w) is False


def test_status_zero_false():
    w = _ok_w3(receipt={"status": 0, "blockNumber": 42})
    assert _anchor().verify_against_chain(w) is False


def test_status_missing_false():
    w = _ok_w3(receipt={"blockNumber": 42})
    assert _anchor().verify_against_chain(w) is False


def test_status_two_false():
    w = _ok_w3(receipt={"status": 2, "blockNumber": 42})
    assert _anchor().verify_against_chain(w) is False


def test_block_mismatch_false():
    w = _ok_w3(receipt={"status": 1, "blockNumber": 99})
    assert _anchor().verify_against_chain(w) is False


def test_block_missing_false():
    w = _ok_w3(receipt={"status": 1})
    assert _anchor().verify_against_chain(w) is False


def test_status_str_int_like_ok():
    """status '1' (str) -> int('1') == 1."""
    w = _ok_w3(receipt={"status": "1", "blockNumber": 42})
    assert _anchor().verify_against_chain(w) is True


def test_status_hex_str_raises():
    """int('0x1') ValueError -> try-disinda firlar."""
    import pytest as _pt
    w = _ok_w3(receipt={"status": "0x1",
                        "blockNumber": 42})
    with _pt.raises(ValueError):
        _anchor().verify_against_chain(w)


# -- tx hatalari ---------------------------------------------------------------------------------

def test_tx_exception_false():
    w = _W3(receipt={"status": 1, "blockNumber": 42},
            tx_exc=RuntimeError("rpc-down"))
    assert _anchor().verify_against_chain(w) is False


def test_wrong_input_false():
    w = _ok_w3(tx={"input": "0x" + "ff" * 32})
    assert _anchor().verify_against_chain(w) is False


def test_empty_input_false():
    w = _ok_w3(tx={"input": "0x"})
    assert _anchor().verify_against_chain(w) is False


def test_input_missing_uses_data():
    w = _ok_w3(tx={"data": _COMMIT})
    assert _anchor().verify_against_chain(w) is True


def test_no_data_false():
    w = _ok_w3(tx={})
    assert _anchor().verify_against_chain(w) is False


def test_data_and_input_both():
    w = _ok_w3(tx={"input": _COMMIT, "data": "0x00"})
    assert _anchor().verify_against_chain(w) is True


# -- str vs bytes ---------------------------------------------------------------------------------

def test_input_str_hex_ok():
    w = _ok_w3(tx={"input": _COMMIT})
    assert _anchor().verify_against_chain(w) is True


def test_input_no_prefix_ok():
    """input '0x'-oneksiz -> bytes.fromhex kabul eder."""
    w = _ok_w3(tx={"input": _COMMIT[2:]})
    assert _anchor().verify_against_chain(w) is True


def test_input_bytes_ok():
    w = _ok_w3(tx={"input": bytes.fromhex(_COMMIT[2:])})
    assert _anchor().verify_against_chain(w) is True


def test_commitment_no_prefix_ok():
    """commitment '0x'-oneksiz -> bytes.fromhex kabul eder."""
    w = _ok_w3(tx={"input": bytes.fromhex(_COMMIT[2:])})
    a = _anchor(commitment_keccak=_COMMIT[2:])
    assert a.verify_against_chain(w) is True


# -- cesitli parametreler ---------------------------------------------------------------------------------

def test_different_block_ok():
    w = _ok_w3(receipt={"status": 1, "blockNumber": 7})
    assert _anchor(block_number=7).verify_against_chain(w) is True


def test_different_tx_hash_ok():
    tx2 = "0x" + "ee" * 32
    w = _W3(receipt={"status": 1, "blockNumber": 42},
            tx={"input": _COMMIT})
    a = _anchor(tx_hash=tx2)
    a.verify_against_chain(w)
    assert w.eth.calls[0] == ("receipt", tx2)


def test_chain_id_not_checked():
    """rpc chain_id dogrulamasi yok (yerel anchor)."""
    assert _anchor(chain_id=5).verify_against_chain(
        _ok_w3()) is True


def test_rpc_url_not_called():
    """rpc_url dogrulamada kullanilmaz."""
    assert _anchor(rpc_url="").verify_against_chain(
        _ok_w3()) is True


# -- hata turleri ---------------------------------------------------------------------------------

@pytest.mark.parametrize("exc", [
    ConnectionError, TimeoutError, ValueError, KeyError,
])
def test_various_receipt_exceptions(exc):
    w = _W3(receipt_exc=exc("x"))
    assert _anchor().verify_against_chain(w) is False


@pytest.mark.parametrize("exc", [
    ConnectionError, TimeoutError, ValueError, KeyError,
])
def test_various_tx_exceptions(exc):
    w = _W3(receipt={"status": 1, "blockNumber": 42},
            tx_exc=exc("x"))
    assert _anchor().verify_against_chain(w) is False


# -- tekrar ---------------------------------------------------------------------------------

def test_repeatable():
    w = _ok_w3()
    a = _anchor()
    assert a.verify_against_chain(w) == a.verify_against_chain(w)


def test_two_anchors_one_w3():
    w = _ok_w3()
    a1 = _anchor()
    a2 = _anchor(block_number=42)
    assert a1.verify_against_chain(w) is True
    assert a2.verify_against_chain(w) is True
    assert len(w.eth.calls) == 4


def test_no_mutation():
    a = _anchor()
    a.verify_against_chain(_ok_w3())
    assert a.tx_hash == _TX
    assert a.block_number == 42
