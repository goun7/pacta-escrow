"""Pacta API endpoint'leri için dal-kesen testler (wave-16+, LEAD).

Kural-1'e uyuldu: mevcut dosyalara DOKUNULMADI, SADECE bu yeni dosya eklendi.
TestClient ile HTTP katmani test edilir; dış zincir-bağlantisi YOK
(shared_vault in-memory).
DALGA-7-A (hata-avi) ekin: PACTA-VLT-3 ve PACTA-VLT-4 onarımlarının-REST-
okuyucusu-üzerinden-pinleri eklendi (/metrics çökmeme + lock ücreti). Yalnız
YENİ test-fonksiyonları; mevcut-testler-DOKUNULMADI.
"""
import pytest
from decimal import Decimal
from fastapi.testclient import TestClient

from pacta.api import app, shared_vault

client = TestClient(app)


# -- /healthz --------------------------------------------------------------

def test_healthz_returns_200_with_status():
    r = client.get("/healthz")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "healthy"
    assert "version" in body
    assert "network" in body


def test_healthz_reports_solvency_verdict():
    body = client.get("/healthz").json()
    # solvent-invariant mutlaka PASS veya FAIL olarak raporlanmalı
    assert body["vault_solvency_invariant"] in ("PASS", "FAIL")


def test_healthz_unknown_path_is_404():
    assert client.get("/health").status_code == 404  # /healthz DOĞRU path


# -- /metrics --------------------------------------------------------------

def test_metrics_returns_200():
    r = client.get("/metrics")
    assert r.status_code == 200


def test_metrics_includes_vault_stats():
    body = client.get("/metrics").json()
    assert "network" in body
    assert "vault_address" in body
    assert isinstance(body["stats"], dict)


# -- PACTA-VLT-3 / VLT-4 icin REST-okuyucusu-üzerinden-kanitlar -------------

def test_metrics_yetersiz_kasada_cokmez_durum_raporlar():
    """BULGU (DUZELTILDI PACTA-VLT-3, REST-kanıtı): /metrics → get_vault_stats
    okumasıdır. Kasa-SOLVENTSİZ-olduğunda eskiden InvariantViolationError
    endpoint'ten dışarı sızıp 500 üretirdi; artık 200 + is_solvent=False +
    solvency_error ( durum-GİZLENMEZ). Modül-düzeyi shared_vault YALNIZ
    bakiye-üzerinden kırılır ve finally-ile-birebir-geri-kurulur.
    """
    onceki = dict(shared_vault.ledger_balances)
    try:
        # bakiyeyi-gereksinimin-altına-çek ( negatif → her-kilitli-tutarla
        # ve-hatta-boş-gereksinimde-de ihlal) → invariant-bozuk
        shared_vault.ledger_balances[shared_vault.USDC_TOKEN] = Decimal("-1")
        r = client.get("/metrics")
        assert r.status_code == 200  # 500-DEĞİL
        stats = r.json()["stats"]
        assert stats["is_solvent"] is False
        assert "Solvency Invariant Broken" in stats["solvency_error"]
    finally:
        shared_vault.ledger_balances.clear()
        shared_vault.ledger_balances.update(onceki)
    # onarım-geri-kuruldu → endpoint-tekrar-normal:
    assert client.get("/metrics").json()["stats"]["is_solvent"] is True


def test_lock_protocol_fee_politikadan_hesaplanir():
    """BULGU (DUZELTILDI PACTA-VLT-4, REST-kanıtı): lock-yanıtındaki
    protocol_fee_usdc eskiden job.fee_collected_usdc (=varsayılan "0.000000")
    idı — sessiz-SIFIR-ÜCRET vaadi. Artık sözleşme-ücreti politikadan
    hesaplanır (75bps → 100 USDC'de 0.750000); TAHSİL edilmiş ücret ise
    settle-öncesi hâlâ None ( sahte-0-yok).
    """
    r = client.post("/v1/escrow/lock", json={
        "buyer_address": "0x" + "11" * 20,
        "seller_address": "0x" + "22" * 20,
        "amount_usdc": 100.0,
        "timeout_ms": 60000,
        "required_schema": {},
    })
    assert r.status_code == 200
    body = r.json()
    assert body["protocol_fee_usdc"] == "0.750000"
    assert body["protocol_fee_usdc"] != "0.000000"
    assert body["net_seller_usdc"] == "99.250000"
    # tahsil-edilmiş-fee settle'a-kadar-YOK ( None) — sahte-"0.000000"-yok:
    assert shared_vault.jobs[body["job_id"]].fee_collected_usdc is None


# -- /v1/escrow/submit (404 error-path) -------------------------------------

def test_submit_unknown_job_returns_404():
    r = client.post("/v1/escrow/submit",
                    json={"job_id": "nonexistent-job-id-xyz",
                          "output_payload": {"data": "test"}})
    assert r.status_code == 404


def test_submit_malformed_body_returns_422_or_400():
    # eksik zorunlu alan → validation error
    r = client.post("/v1/escrow/submit", json={})
    assert r.status_code in (400, 422)


# -- /v1/escrow/lock (validation) ------------------------------------------

def test_lock_missing_fields_rejected():
    r = client.post("/v1/escrow/lock", json={})
    assert r.status_code in (400, 422)


def test_lock_negative_amount_rejected():
    r = client.post("/v1/escrow/lock", json={
        "buyer_address": "0x" + "11" * 20,
        "seller_address": "0x" + "22" * 20,
        "amount_usdc": "-100",
        "timeout_ms": 60000,
        "required_schema": {},
    })
    # negatif miktar ya reddedilir ya da validation hatası
    assert r.status_code in (400, 422)


# -- /v1/verify -------------------------------------------------------------

def test_verify_missing_body_rejected():
    r = client.post("/v1/verify", json={})
    assert r.status_code in (400, 422)


def test_verify_unknown_job_returns_error_not_500():
    r = client.post("/v1/verify", json={"job_id": "no-such-job", "proof": {}})
    # 404/400 beklenir; 500 asla
    assert r.status_code < 500


# -- openapi (route kayıt bütünlüğü) ----------------------------------------

def test_openapi_lists_all_escrow_routes():
    spec = client.get("/openapi.json").json()
    paths = spec["paths"]
    for p in ("/healthz", "/metrics", "/v1/escrow/lock",
              "/v1/escrow/submit", "/v1/escrow/settle",
              "/v1/escrow/dispute", "/v1/verify"):
        assert p in paths, f"route kayıt-değil: {p}"
