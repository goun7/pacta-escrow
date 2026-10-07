"""Tarama-9: kapsanmamış kritik fonksiyonlar — Tier1.validate_schema + EvmChainAdapter.anchor.

validate_schema: saf-özyinelemeli JSON-schema-doğrulayıcı (güvenlik: gelen
payload'un sözleşme şemasına uyumu). anchor: karar-taahhüdünü zincire-sabitleyen
finans-kritik yol — tüm zincir-çağrıları mock'lanmıştır (rule 7: sadece fonksiyonun
kendi mantığı test-edilir, dış RPC'ye asla gidilmez).
"""

import pytest

from pacta.chain.adapter import ChainUnavailableError, EvmChainAdapter
from pacta.models import ChainAnchor
from pacta.verification.tier1_syntax import Tier1SyntacticValidator


# ---------------------------------------------------------------- validate_schema


def test_validate_schema_object_ok():
    schema = {
        "type": "object",
        "required": ["ticker", "price"],
        "properties": {"ticker": {"type": "string"}, "price": {"type": "number", "minimum": 0}},
    }
    ok, reason = Tier1SyntacticValidator.validate_schema({"ticker": "ETH", "price": 10}, schema)
    assert ok is True
    assert reason == "Valid"


def test_validate_schema_object_wrong_type():
    ok, reason = Tier1SyntacticValidator.validate_schema([1, 2], {"type": "object"})
    assert ok is False
    assert "Expected object, got list" in reason


def test_validate_schema_missing_required():
    ok, reason = Tier1SyntacticValidator.validate_schema(
        {"ticker": "ETH"}, {"type": "object", "required": ["ticker", "price"]})
    assert ok is False
    assert "Missing required property: 'price'" in reason


def test_validate_schema_nested_property_failure():
    schema = {
        "type": "object",
        "required": ["data"],
        "properties": {"data": {"type": "object", "required": ["sig"]}},
    }
    ok, reason = Tier1SyntacticValidator.validate_schema({"data": {}}, schema)
    assert ok is False
    assert "Property 'data' failed validation" in reason
    assert "Missing required property: 'sig'" in reason


def test_validate_schema_string_minlength():
    ok, reason = Tier1SyntacticValidator.validate_schema("ab", {"type": "string", "minLength": 5})
    assert ok is False
    assert "String shorter than minLength 5" in reason
    ok2, _ = Tier1SyntacticValidator.validate_schema("abcdef", {"type": "string", "minLength": 5})
    assert ok2 is True


def test_validate_schema_string_wrong_type():
    ok, reason = Tier1SyntacticValidator.validate_schema(42, {"type": "string"})
    assert ok is False
    assert "Expected string, got int" in reason


def test_validate_schema_integer_rejects_bool():
    # bool bir int alt-sınıfıdır — integer-şeması True'yu kabul-etmemeli.
    ok, reason = Tier1SyntacticValidator.validate_schema(True, {"type": "integer"})
    assert ok is False
    assert "Expected number, got bool" in reason
    ok2, _ = Tier1SyntacticValidator.validate_schema(7, {"type": "integer"})
    assert ok2 is True


def test_validate_schema_number_below_minimum():
    ok, reason = Tier1SyntacticValidator.validate_schema(-1, {"type": "number", "minimum": 0})
    assert ok is False
    assert "Value less than minimum 0" in reason
    ok2, _ = Tier1SyntacticValidator.validate_schema(0, {"type": "number", "minimum": 0})
    assert ok2 is True


def test_validate_schema_number_wrong_type():
    ok, reason = Tier1SyntacticValidator.validate_schema("9", {"type": "number"})
    assert ok is False
    assert "Expected number, got str" in reason


def test_validate_schema_array_items():
    ok, reason = Tier1SyntacticValidator.validate_schema(
        [1, 2], {"type": "array", "items": {"type": "string"}})
    assert ok is False
    assert "Array item [0] failed validation" in reason
    ok2, _ = Tier1SyntacticValidator.validate_schema(["a", "b"], {"type": "array", "items": {"type": "string"}})
    assert ok2 is True


def test_validate_schema_array_wrong_type():
    ok, reason = Tier1SyntacticValidator.validate_schema("x,y", {"type": "array"})
    assert ok is False
    assert "Expected array, got str" in reason


def test_validate_schema_absent_type_is_lenient():
    # "type" belirtilmeyen şema her değeri-geçerli-sayar (kasıtlı gevşeklik).
    ok, _ = Tier1SyntacticValidator.validate_schema({"any": "thing"}, {"required": ["any"]})
    assert ok is True


# ------------------------------------------------------------------ anchor (mock)

class _FakeEth:
    def __init__(self, *, accounts=("0xOPERATOR",), chain_id=31337,
                 tx_hash=None, receipt=None, send_error=None):
        self.accounts = list(accounts)
        self.chain_id = chain_id
        self._tx_hash = tx_hash if tx_hash is not None else b"\x11" * 32
        self._receipt = receipt if receipt is not None else {"status": 1, "blockNumber": 42, "gasUsed": 21000}
        self.send_error = send_error
        self.sent = []

    def send_transaction(self, tx):
        if self.send_error is not None:
            raise self.send_error
        self.sent.append(tx)
        return self._tx_hash

    def wait_for_transaction_receipt(self, tx_hash, timeout=None):
        self.received_tx_hash = tx_hash
        return self._receipt


class _FakeW3:
    def __init__(self, eth):
        self.eth = eth


def _adapter(eth=None, operator=None):
    return EvmChainAdapter(
        w3=_FakeW3(eth or _FakeEth()), backend="anvil", rpc_url="http://127.0.0.1:8545",
        operator_account=operator, receipt_timeout_s=5.0)


def test_anchor_success_normalizes_tx_hash_and_builds_chainanchor():
    eth = _FakeEth()
    adapter = _adapter(eth, operator="0xOPERATOR")
    terms = {"amount_usdc": 100, "fee": 1, "net_seller": 99}

    anchor = adapter.anchor("job-1", "settlement", terms)

    assert isinstance(anchor, ChainAnchor)
    assert anchor.chain_id == 31337
    # web3 HexBytes -> 0x-hex normalizasyonu (web3-8.x str()-bozuk-repr düzeltmesi)
    assert anchor.tx_hash == "0x" + "11" * 32
    assert anchor.block_number == 42
    assert anchor.gas_used == 21000
    assert anchor.anchor_kind == "settlement"
    assert anchor.job_id == "job-1"
    assert anchor.from_address == "0xOPERATOR"
    assert anchor.to_address == "0xOPERATOR"  # self-anchor varsayılan
    assert anchor.tx_status == 1
    assert anchor.rpc_url == "http://127.0.0.1:8545"
    assert anchor.backend == "anvil"
    assert anchor.anchored_at_epoch_ms > 0


def test_anchor_sends_zero_value_commitment_calldata():
    eth = _FakeEth()
    adapter = _adapter(eth, operator="0xOPERATOR")
    terms = {"amount_usdc": 100, "fee": 1}

    adapter.anchor("job-2", "dispute", terms)

    assert len(eth.sent) == 1
    tx = eth.sent[0]
    # değer-transferi YASAK: 0-wei taahhüt-bağı
    assert tx["value"] == 0
    assert tx["from"] == "0xOPERATOR"
    assert tx["to"] == "0xOPERATOR"
    # calldata = kanonik-sıralı keccak; model-ile aynı-commitment
    expected = EvmChainAdapter.build_commitment("job-2", "dispute", terms)
    assert tx["data"] == expected
    # receipt-bekleme doğru tx-hash ile-çağrıldı
    assert eth.received_tx_hash == eth._tx_hash


def test_anchor_commitment_keccak_matches_canonical_ordering():
    adapter = _adapter(operator="0xOPERATOR")
    terms = {"zeta": 1, "alpha": 2, "mid": 3}  # sıralı-değil girildi
    anchor = adapter.anchor("job-3", "arbitration", terms)
    # sabit-sıralı (K0) kanonik-alanlar: sorted(terms)
    expected = EvmChainAdapter.build_commitment("job-3", "arbitration",
                                                {"alpha": 2, "mid": 3, "zeta": 1})
    assert anchor.commitment_keccak == "0x" + expected.hex()


def test_anchor_to_address_override_routes_to_recipient():
    eth = _FakeEth()
    adapter = _adapter(eth, operator="0xOPERATOR")
    anchor = adapter.anchor("job-4", "refund", {"amount_usdc": 5}, to_address="0xSELLER")
    assert anchor.to_address == "0xSELLER"
    assert eth.sent[0]["to"] == "0xSELLER"
    assert eth.sent[0]["from"] == "0xOPERATOR"


def test_anchor_resolves_operator_from_accounts_when_not_given():
    eth = _FakeEth(accounts=["0xFIRST", "0xSECOND"])
    adapter = _adapter(eth)  # operator verilmedi
    anchor = adapter.anchor("job-5", "settlement", {"amount_usdc": 1})
    assert anchor.from_address == "0xFIRST"
    assert adapter._operator == "0xFIRST"  # önbellek


def test_anchor_rejects_invalid_kind():
    adapter = _adapter(operator="0xOPERATOR")
    with pytest.raises(ValueError, match="anchor-kind-invalid"):
        adapter.anchor("job-6", "hack", {"amount_usdc": 1})


def test_anchor_rejects_empty_terms():
    adapter = _adapter(operator="0xOPERATOR")
    with pytest.raises(ValueError, match="terms-required"):
        adapter.anchor("job-7", "settlement", {})
    with pytest.raises(ValueError, match="terms-required"):
        adapter.anchor("job-8", "settlement", ["not", "a", "dict"])


def test_anchor_wraps_send_failure_as_chain_unavailable():
    eth = _FakeEth(send_error=RuntimeError("nonce-too-low"))
    adapter = _adapter(eth, operator="0xOPERATOR")
    with pytest.raises(ChainUnavailableError, match="anchor-failed"):
        adapter.anchor("job-9", "settlement", {"amount_usdc": 1})


def test_anchor_raises_on_reverted_receipt_status_zero():
    eth = _FakeEth(receipt={"status": 0, "blockNumber": 43, "gasUsed": 100})
    adapter = _adapter(eth, operator="0xOPERATOR")
    with pytest.raises(ChainUnavailableError, match="anchor-reverted"):
        adapter.anchor("job-10", "settlement", {"amount_usdc": 1})


def test_anchor_no_longer_masks_falsy_status_fixed():
    # DÜZELTİLDİ (Fix-2026-10-08): 'or 1' kaldırıldı; status=0 artık korunur.
    # Önceki maskelenmiş-davranış testi (tx_status == 1) kaldırıldı.
    eth = _FakeEth(receipt={"status": 0, "blockNumber": 43, "gasUsed": 100})
    adapter = _adapter(eth, operator="0xOPERATOR")
    with pytest.raises(ChainUnavailableError, match="anchor-reverted"):
        adapter.anchor("job-10b", "settlement", {"amount_usdc": 1})


def test_anchor_accepts_bool_status_true_as_success():
    # bazı-backendler status'u True/False döner — True => 1
    eth = _FakeEth(receipt={"status": True, "blockNumber": 44, "gasUsed": 100})
    adapter = _adapter(eth, operator="0xOPERATOR")
    anchor = adapter.anchor("job-11", "settlement", {"amount_usdc": 1})
    assert anchor.tx_status == 1


def test_anchor_accepts_str_tx_hash_without_renormalization():
    eth = _FakeEth(tx_hash="0xABCDEF")
    adapter = _adapter(eth, operator="0xOPERATOR")
    anchor = adapter.anchor("job-12", "settlement", {"amount_usdc": 1})
    assert anchor.tx_hash == "0xABCDEF"
