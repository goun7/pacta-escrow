"""Pacta API endpoint'leri için dal-kesen testler (wave-16+, LEAD).

Kural-1'e uyuldu: mevcut dosyalara DOKUNULMADI, SADECE bu yeni dosya eklendi.
TestClient ile HTTP katmani test edilir; dış zincir-bağlantisi YOK
(shared_vault in-memory).
"""
import pytest
from fastapi.testclient import TestClient

from pacta.api import app

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
