"""
Production REST API and Configuration Tests
Ensures 100% test coverage on pacta.api and pacta.config.
"""

import pytest
from starlette.testclient import TestClient
from pacta.api import app, shared_vault
from pacta.config import settings
from decimal import Decimal


@pytest.fixture
def client():
    return TestClient(app)


def test_config_settings_properties():
    assert settings.network is not None
    assert settings.protocol_fee_bps == 75
    assert settings.dispute_bond_bps == 2000
    assert settings.protocol_fee_rate == Decimal("0.0075")
    assert settings.dispute_bond_rate == Decimal("0.2000")


def test_api_health_check(client):
    resp = client.get("/healthz")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "healthy"
    assert data["vault_solvency_invariant"] == "PASS"


def test_api_metrics(client):
    resp = client.get("/metrics")
    assert resp.status_code == 200
    data = resp.json()
    assert "stats" in data
    assert "total_jobs" in data["stats"]


def test_api_lock_and_settle_flow(client):
    # 1. Create lock
    lock_payload = {
        "buyer_address": "0xBuyerAgent",
        "seller_address": "0xSellerAgent",
        "amount_usdc": 10.0,
        "timeout_ms": 5000,
        "required_schema": {"type": "object"}
    }
    resp = client.post("/v1/escrow/lock", json=lock_payload)
    assert resp.status_code == 200
    data = resp.json()
    job_id = data["job_id"]
    assert data["status"] == "ESCROW_LOCKED"
    assert data["amount_usdc"] == "10.000000"

    # 2. Submit output
    sub_resp = client.post("/v1/escrow/submit", json={
        "job_id": job_id,
        "output_payload": {"status": "success", "result": "computed"}
    })
    assert sub_resp.status_code == 200
    assert sub_resp.json()["status"] == "OUTPUT_SUBMITTED"

    # 3. Settle
    settle_resp = client.post("/v1/escrow/settle", json={"job_id": job_id})
    assert settle_resp.status_code == 200
    settle_data = settle_resp.json()
    assert settle_data["status"] == "SETTLED"
    assert "settlement_tx" in settle_data


def test_api_settle_not_found(client):
    resp = client.post("/v1/escrow/settle", json={"job_id": "non-existent-id"})
    assert resp.status_code == 404


def test_api_dispute_flow_and_not_found(client):
    # Create lock
    lock_payload = {
        "buyer_address": "0xBuyerAgent",
        "seller_address": "0xSellerAgent",
        "amount_usdc": 20.0,
        "timeout_ms": 5000
    }
    resp = client.post("/v1/escrow/lock", json=lock_payload)
    job_id = resp.json()["job_id"]

    # Submit output so it can be disputed
    shared_vault.submit_output(job_id, {"data": "substandard"})

    # Dispute
    dispute_payload = {
        "job_id": job_id,
        "claimant_address": "0xBuyerAgent",
        "reason": "Quality failure",
        "evidence_hash": "0xevidence"
    }
    disp_resp = client.post("/v1/escrow/dispute", json=dispute_payload)
    assert disp_resp.status_code == 200
    disp_data = disp_resp.json()
    assert disp_data["status"] == "ARBITRATION_IN_PROGRESS"
    assert disp_data["bond_amount_usdc"] == "4.000000"  # 20% of 20 USDC

    # Dispute non-existent
    err_resp = client.post("/v1/escrow/dispute", json={
        "job_id": "ghost-job",
        "claimant_address": "0xBuyerAgent",
        "reason": "None",
        "evidence_hash": "0x0"
    })
    assert err_resp.status_code == 404


def test_api_verify_tier1(client):
    schema = {
        "type": "object",
        "required": ["status", "value"]
    }
    # Valid payload
    resp_valid = client.post("/v1/verify", json={
        "payload": {"status": "ok", "value": 42},
        "required_schema": schema,
        "latency_ms": 50
    })
    assert resp_valid.status_code == 200
    assert resp_valid.json()["is_valid"] is True

    # Invalid payload (missing required value)
    resp_invalid = client.post("/v1/verify", json={
        "payload": {"status": "ok"},
        "required_schema": schema,
        "latency_ms": 50
    })
    assert resp_invalid.status_code == 200
    assert resp_invalid.json()["is_valid"] is False


def test_api_edge_errors(client):
    # 1. Submit to non-existent job (404)
    resp_sub_404 = client.post("/v1/escrow/submit", json={
        "job_id": "non-existent",
        "output_payload": {"test": 1}
    })
    assert resp_sub_404.status_code == 404

    # 2. Settle with failed Tier-1 verification (400)
    lock_payload = {
        "buyer_address": "0xBuyerAgent",
        "seller_address": "0xSellerAgent",
        "amount_usdc": 15.0,
        "timeout_ms": 5000,
        "required_schema": {"type": "object", "required": ["expected_field"]}
    }
    job_id = client.post("/v1/escrow/lock", json=lock_payload).json()["job_id"]
    client.post("/v1/escrow/submit", json={
        "job_id": job_id,
        "output_payload": {"wrong_field": True}
    })
    settle_fail_resp = client.post("/v1/escrow/settle", json={"job_id": job_id})
    assert settle_fail_resp.status_code == 400
    assert "Syntactic verification failed" in settle_fail_resp.json()["detail"]
