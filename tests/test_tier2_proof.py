"""Unit tests for Tier 2 Cryptographic and zkTLS Verification."""

from pacta.models import TamgaExecutionReceipt, ZkTLSCertificate
from pacta.verification.tier2_proof import Tier2CryptographicValidator


def test_tier2_tamga_receipt_success():
    payload = {"prediction": "bullish", "confidence": 0.88}
    payload_hash = Tier2CryptographicValidator.compute_payload_hash(payload)

    receipt = TamgaExecutionReceipt(
        job_id="job-abc",
        program_hash="0xprog123",
        input_commitment="0xinput123",
        output_hash=payload_hash,
        wasi_trace_root="0xtrace123",
        instruction_count=1250,
        timestamp_epoch=1789823000,
        signature="0xsig123"
    )

    res = Tier2CryptographicValidator.verify_tamga_receipt(payload, receipt)
    assert bool(res) is True
    assert "instructions: 1250" in res.reason


def test_tier2_tamga_receipt_hash_mismatch():
    payload = {"prediction": "bullish"}
    receipt = TamgaExecutionReceipt(
        job_id="job-abc",
        program_hash="0xprog123",
        input_commitment="0xinput123",
        output_hash="0xwronghash",
        wasi_trace_root="0xtrace123",
        instruction_count=1250,
        timestamp_epoch=1789823000,
        signature="0xsig123"
    )
    res = Tier2CryptographicValidator.verify_tamga_receipt(payload, receipt)
    assert bool(res) is False
    assert "mismatch" in res.reason


def test_tier2_zktls_certificate_success():
    # AT-157-güvenlik-düzeltmesi: zk-SNARK-asla-doğrulanmıyordu — 'A'*32-
    # gibi-değerler-'authentic'-geçiyordu. Bu-yol-artık-fail-closed'dur:
    # gerçek-DECO/TLSNotary-doğrulaması-uygulanana-kadar-KAPALI. Eski-test
    # açık-davranışını-doğruluyordu ( sahte-snark + True); şimdi-dürüst
    # RED-beklenir.
    payload = {"price": 100.5}
    payload_hash = Tier2CryptographicValidator.compute_payload_hash(payload)

    cert = ZkTLSCertificate(
        session_id="tls-sess-1",
        server_name="api.nasdaq.com",
        data_hash=payload_hash,
        zk_proof_snark="0x" + "f" * 64,
        attestation_key="0xattest"
    )
    res = Tier2CryptographicValidator.verify_zktls_certificate(payload, cert)
    assert bool(res) is False
    assert "not implemented" in res.reason
