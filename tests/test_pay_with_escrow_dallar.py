"""agentkit.pay_with_escrow dal-kesen testleri (LEED).

Kural-1: mevcut dosyalara DOKUNULMADI, SADECE bu yeni dosya eklendi.
Dış çağrı YOK: PactaEscrowClient.call_with_escrow monkeypatch stub.
"""
import pytest

from pacta.integrations.agentkit import PactaEscrowActionProvider
from pacta.models import EscrowPolicy, VerificationTier


class _Job:
    def __init__(self, jid="job-1", status="completed"):
        self.job_id = jid

        class _S:
            value = status
        self.status = _S()


class _Resp:
    def __init__(self, success=True, job=None, tx="0xabc",
                 error=None):
        self.success = success
        self.job = job or _Job()
        self.escrow_settle_tx = tx
        self.error_message = error


class _FakeClient:
    def __init__(self, resp=None):
        self.resp = resp or _Resp()
        self.calls = []

    def call_with_escrow(self, **kw):
        self.calls.append(kw)
        return self.resp


@pytest.fixture
def prov(monkeypatch):
    seen = {}

    def _make(resp=None, mode=None):
        client = _FakeClient(resp)
        provider = PactaEscrowActionProvider(client=client)
        seen["client"] = client
        seen["resp"] = resp
        return provider, client

    return _make


def _call(provider, **kw):
    args = {"seller_address": "0xSELLER", "amount_usdc": 1.5,
            "output_payload": {"data": "x"}}
    args.update(kw)
    return provider.pay_with_escrow(**args)


# -- temel ---------------------------------------------------------------------------------

def test_returns_dict(prov):
    p, _ = prov()
    assert isinstance(_call(p), dict)


def test_success_key(prov):
    p, _ = prov()
    assert _call(p)["success"] is True


def test_job_id_key(prov):
    p, _ = prov()
    assert _call(p)["job_id"] == "job-1"


def test_settlement_tx_key(prov):
    p, _ = prov()
    assert _call(p)["settlement_tx"] == "0xabc"


def test_error_key(prov):
    p, _ = prov()
    assert _call(p)["error"] is None


def test_status_key(prov):
    p, _ = prov()
    assert _call(p)["status"] == "completed"


# -- client cagrisi ---------------------------------------------------------------------------------

def test_client_called(prov):
    p, c = prov()
    _call(p)
    assert len(c.calls) == 1


def test_seller_passed(prov):
    p, c = prov()
    _call(p)
    assert c.calls[0]["seller_address"] == "0xSELLER"


def test_amount_passed(prov):
    p, c = prov()
    _call(p)
    assert c.calls[0]["amount"] == 1.5


def test_output_data_passed(prov):
    p, c = prov()
    _call(p)
    assert c.calls[0]["output_data"] == {"data": "x"}


def test_policy_is_escrow_policy(prov):
    p, c = prov()
    _call(p)
    assert isinstance(c.calls[0]["policy"], EscrowPolicy)


def test_policy_timeout(prov):
    p, c = prov()
    _call(p, timeout_ms=9000)
    assert c.calls[0]["policy"].timeout_ms == 9000


def test_policy_default_timeout(prov):
    p, c = prov()
    _call(p)
    assert c.calls[0]["policy"].timeout_ms == 5000


# -- verification tier ---------------------------------------------------------------------------------

def test_default_tier1(prov):
    p, c = prov()
    _call(p)
    assert c.calls[0]["policy"].verification_mode == \
        VerificationTier.TIER1_SYNTACTIC


def test_verify_tamga_tier2(prov):
    p, c = prov()
    _call(p, verify_tamga=True)
    assert c.calls[0]["policy"].verification_mode == \
        VerificationTier.TIER2_CRYPTOGRAPHIC


def test_verify_false_tier1(prov):
    p, c = prov()
    _call(p, verify_tamga=False)
    assert c.calls[0]["policy"].verification_mode == \
        VerificationTier.TIER1_SYNTACTIC


# -- response yayilimi ---------------------------------------------------------------------------------

def test_failure_propagates(prov):
    r = _Resp(success=False, error="timeout")
    p, _ = prov(resp=r)
    res = _call(p)
    assert res["success"] is False
    assert res["error"] == "timeout"


def test_job_id_propagates(prov):
    r = _Resp(job=_Job(jid="job-99"))
    p, _ = prov(resp=r)
    assert _call(p)["job_id"] == "job-99"


def test_status_propagates(prov):
    r = _Resp(job=_Job(status="refunded"))
    p, _ = prov(resp=r)
    assert _call(p)["status"] == "refunded"


def test_tx_propagates(prov):
    r = _Resp(tx="0xSETTLE")
    p, _ = prov(resp=r)
    assert _call(p)["settlement_tx"] == "0xSETTLE"


def test_error_message_none_on_success(prov):
    r = _Resp(success=True, error=None)
    p, _ = prov(resp=r)
    assert _call(p)["error"] is None


def test_error_message_string(prov):
    r = _Resp(success=False, error="dispute-raised")
    p, _ = prov(resp=r)
    assert _call(p)["error"] == "dispute-raised"


# -- cesitli payloadlar ---------------------------------------------------------------------------------

def test_empty_payload(prov):
    p, c = prov()
    _call(p, output_payload={})
    assert c.calls[0]["output_data"] == {}


def test_nested_payload(prov):
    p, c = prov()
    payload = {"a": {"b": [1, 2, {"c": None}]}}
    _call(p, output_payload=payload)
    assert c.calls[0]["output_data"] == payload


def test_string_payload(prov):
    p, c = prov()
    _call(p, output_payload="raw")
    assert c.calls[0]["output_data"] == "raw"


def test_zero_amount(prov):
    p, c = prov()
    _call(p, amount_usdc=0.0)
    assert c.calls[0]["amount"] == 0.0


def test_large_amount(prov):
    p, c = prov()
    _call(p, amount_usdc=1e6)
    assert c.calls[0]["amount"] == 1e6


def test_checksum_address(prov):
    p, c = prov()
    _call(p, seller_address="0xAbCdEf0123456789")
    assert c.calls[0]["seller_address"] == "0xAbCdEf0123456789"


# -- tekrar ---------------------------------------------------------------------------------

def test_repeatable(prov):
    p, _ = prov()
    assert _call(p) == _call(p)


def test_two_calls_two_requests(prov):
    p, c = prov()
    _call(p)
    _call(p)
    assert len(c.calls) == 2


def test_keys_stable(prov):
    p, _ = prov()
    assert set(_call(p)) == {"success", "job_id",
                             "settlement_tx", "error",
                             "status"}
