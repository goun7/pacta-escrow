"""tamga_d5.delivery_artifact dal-kesen testleri (LEED).

Kural-1: mevcut dosyalara DOKUNULMADI, SADECE bu yeni dosya eklendi.
Dış çağrı YOK: saf dict-uretici (job'dan).
"""
import pytest
from decimal import Decimal

from pacta.integrations.tamga_d5 import SettlementBinder
from pacta.models import EscrowJob, EscrowStatus, TamgaExecutionReceipt


class _R:
    def __init__(self, **kw):
        args = dict(
            program_hash="0xPROG",
            session_id="sess-1",
            output_hash="0xOUT",
            wasi_trace_root="0xWASI",
            instruction_count=42,
        )
        args.update(kw)
        self.__dict__.update(args)


def _job(**kw):
    args = dict(
        job_id="job-1", buyer_address="0xB",
        seller_address="0xS", amount_usdc=Decimal("10.5"),
        status=EscrowStatus.SETTLED,
        settlement_tx="0xSETTLE",
        output_payload={"result": "ok"},
        settled_at_epoch_ms=1700000000000,
    )
    args.update(kw)
    return EscrowJob(**args)


def _call(job=None):
    return SettlementBinder.delivery_artifact(job or _job())


# -- temel ---------------------------------------------------------------------------------

def test_returns_dict():
    assert isinstance(_call(), dict)


def test_job_id():
    assert _call()["job_id"] == "job-1"


def test_status_is_value():
    assert _call()["status"] == "SETTLED"


def test_amount_is_str():
    """pydantic Decimal -> quantize."""
    assert _call()["amount_usdc"] == "10.500000"


def test_amount_str_type():
    assert isinstance(_call()["amount_usdc"], str)


def test_output_payload():
    assert _call()["output_payload"] == {"result": "ok"}


def test_settlement_tx():
    assert _call()["settlement_tx"] == "0xSETTLE"


def test_settled_at():
    assert _call()["settled_at_epoch_ms"] == 1700000000000


# -- fee ---------------------------------------------------------------------------------

def test_fee_key_present():
    assert "fee_usdc" in _call()


def test_fee_none_is_str():
    """fee_collected None -> str(None)?"""
    job = _job()
    r = _call(job)
    assert isinstance(r["fee_usdc"], str)


def test_fee_value():
    job = _job()
    job.fee_collected_usdc = Decimal("0.7")
    assert _call(job)["fee_usdc"] == "0.7"


def test_fee_zero():
    job = _job()
    job.fee_collected_usdc = Decimal("0")
    assert _call(job)["fee_usdc"] == "0"


def test_fee_int_value():
    job = _job()
    job.fee_collected_usdc = 5
    assert _call(job)["fee_usdc"] == "5"


# -- status cesitleri ---------------------------------------------------------------------------------

@pytest.mark.parametrize("status", [
    EscrowStatus.INITIALIZED, EscrowStatus.ESCROW_LOCKED,
    EscrowStatus.OUTPUT_SUBMITTED, EscrowStatus.VERIFIED_OK,
    EscrowStatus.OPTIMISTIC_SETTLED, EscrowStatus.DISPUTED,
    EscrowStatus.SETTLED,
])
def test_all_statuses(status):
    r = _call(_job(status=status))
    assert r["status"] == status.value


def test_status_enum_not_object():
    r = _call()
    assert r["status"] == "SETTLED"


# -- tamga_receipt YOK ---------------------------------------------------------------------------------

def test_no_receipt_no_tamga_keys():
    r = _call()
    assert "tamga_output_hash" not in r
    assert "tamga_wasi_trace_root" not in r
    assert "tamga_instruction_count" not in r


def test_no_receipt_core_keys_present():
    r = _call()
    for k in ("job_id", "status", "amount_usdc", "fee_usdc",
              "output_payload", "settlement_tx",
              "settled_at_epoch_ms"):
        assert k in r


# -- tamga_receipt VAR ---------------------------------------------------------------------------------

def test_receipt_output_hash():
    job = _job()
    job.tamga_receipt = _R()
    assert _call(job)["tamga_output_hash"] == "0xOUT"


def test_receipt_wasi_trace_root():
    job = _job()
    job.tamga_receipt = _R()
    assert _call(job)["tamga_wasi_trace_root"] == "0xWASI"


def test_receipt_instruction_count():
    job = _job()
    job.tamga_receipt = _R()
    assert _call(job)["tamga_instruction_count"] == 42


def test_receipt_all_three():
    job = _job()
    job.tamga_receipt = _R()
    r = _call(job)
    assert len([k for k in r if k.startswith("tamga_")]) == 3


def test_receipt_int_count():
    job = _job()
    job.tamga_receipt = _R(instruction_count=999)
    assert _call(job)["tamga_instruction_count"] == 999


def test_receipt_zero_count():
    job = _job()
    job.tamga_receipt = _R(instruction_count=0)
    assert _call(job)["tamga_instruction_count"] == 0


# -- cesitli job degerleri ---------------------------------------------------------------------------------

def test_empty_payload():
    r = _call(_job(output_payload={}))
    assert r["output_payload"] == {}


def test_none_payload():
    r = _call(_job(output_payload=None))
    assert r["output_payload"] is None


def test_nested_payload():
    p = {"a": {"b": [1, {"c": None}]}}
    r = _call(_job(output_payload=p))
    assert r["output_payload"] == p


def test_none_settlement_tx():
    r = _call(_job(settlement_tx=None))
    assert r["settlement_tx"] is None


def test_large_amount():
    r = _call(_job(amount_usdc=Decimal("999999.999")))
    assert Decimal(r["amount_usdc"]) == Decimal("999999.999")


def test_tiny_amount():
    r = _call(_job(amount_usdc=Decimal("0.000001")))
    assert Decimal(r["amount_usdc"]) == Decimal("0.000001")


def test_epoch_zero():
    r = _call(_job(settled_at_epoch_ms=0))
    assert r["settled_at_epoch_ms"] == 0


# -- tamga_receipt modeli ---------------------------------------------------------------------------------

def test_real_receipt_model():
    job = _job()
    job.tamga_receipt = TamgaExecutionReceipt(
        job_id="j1", program_hash="0xP",
        input_commitment="0xI", output_hash="0xO",
        wasi_trace_root="0xW", instruction_count=7,
        timestamp_epoch=1700000000, signature="0xS")
    r = _call(job)
    assert r["tamga_output_hash"] == "0xO"
    assert r["tamga_instruction_count"] == 7


# -- determinizm ---------------------------------------------------------------------------------

def test_repeatable():
    assert _call() == _call()


def test_same_job_twice():
    job = _job()
    assert SettlementBinder.delivery_artifact(job) == \
        SettlementBinder.delivery_artifact(job)


def test_no_mutation():
    job = _job(output_payload={"a": 1})
    _call(job)
    assert job.output_payload == {"a": 1}
    assert job.status == EscrowStatus.SETTLED
