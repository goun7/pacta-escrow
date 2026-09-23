"""Unit tests for Tier 1 Syntactic and SLA Invariant validation."""

from pacta.models import EscrowPolicy
from pacta.verification.tier1_syntax import Tier1SyntacticValidator


def test_tier1_valid_schema():
    schema = {
        "type": "object",
        "required": ["ticker", "price"],
        "properties": {
            "ticker": {"type": "string"},
            "price": {"type": "number", "minimum": 0}
        }
    }
    policy = EscrowPolicy(required_schema=schema, max_latency_ms=2000)
    data = {"ticker": "ETH", "price": 3450.50}

    res = Tier1SyntacticValidator.verify(payload=data, policy=policy, latency_ms=100, http_status=200)
    assert bool(res) is True
    assert "satisfied" in res.reason


def test_tier1_missing_required_property():
    schema = {
        "type": "object",
        "required": ["ticker", "price"],
        "properties": {
            "ticker": {"type": "string"},
            "price": {"type": "number"}
        }
    }
    policy = EscrowPolicy(required_schema=schema)
    data = {"ticker": "ETH"}  # Missing price

    res = Tier1SyntacticValidator.verify(payload=data, policy=policy, latency_ms=100)
    assert bool(res) is False
    assert "Missing required property: 'price'" in res.reason


def test_tier1_latency_sla_breach():
    policy = EscrowPolicy(max_latency_ms=1000)
    data = {"result": "ok"}
    res = Tier1SyntacticValidator.verify(payload=data, policy=policy, latency_ms=1500)
    assert bool(res) is False
    assert "SLA breach" in res.reason


def test_tier1_non_200_status():
    policy = EscrowPolicy()
    res = Tier1SyntacticValidator.verify(payload={"err": True}, policy=policy, latency_ms=100, http_status=500)
    assert bool(res) is False
    assert "500" in res.reason
