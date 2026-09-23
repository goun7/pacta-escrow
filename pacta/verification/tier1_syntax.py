"""
Pacta Verification Engine: Tier 1 (Syntactic & SLA Invariants)
High-speed, zero-gas off-chain validation for HTTP codes, latency, and schema.
"""

from typing import Any, Dict, Optional, Tuple
from pacta.models import EscrowPolicy


class Tier1VerificationResult:
    def __init__(self, is_valid: bool, reason: str, latency_ms: int):
        self.is_valid = is_valid
        self.reason = reason
        self.latency_ms = latency_ms

    def __bool__(self) -> bool:
        return self.is_valid


class Tier1SyntacticValidator:
    """
    Executes syntactic and SLA invariant checks:
    1. HTTP Status Code Invariant (200 OK required)
    2. Response latency <= policy.max_latency_ms
    3. Structural schema compliance against required_schema
    """

    @staticmethod
    def validate_schema(data: Any, schema: Dict[str, Any]) -> Tuple[bool, str]:
        """
        Lightweight JSON-Schema validator supporting types, required properties,
        and nested objects without external bloated dependencies.
        """
        expected_type = schema.get("type")
        if expected_type == "object":
            if not isinstance(data, dict):
                return False, f"Expected object, got {type(data).__name__}"
            
            required_props = schema.get("required", [])
            for prop in required_props:
                if prop not in data:
                    return False, f"Missing required property: '{prop}'"
            
            properties = schema.get("properties", {})
            for key, subschema in properties.items():
                if key in data:
                    valid, reason = Tier1SyntacticValidator.validate_schema(data[key], subschema)
                    if not valid:
                        return False, f"Property '{key}' failed validation: {reason}"

        elif expected_type == "string":
            if not isinstance(data, str):
                return False, f"Expected string, got {type(data).__name__}"
            if "minLength" in schema and len(data) < schema["minLength"]:
                return False, f"String shorter than minLength {schema['minLength']}"

        elif expected_type == "number" or expected_type == "integer":
            if not isinstance(data, (int, float)) or (expected_type == "integer" and isinstance(data, bool)):
                return False, f"Expected number, got {type(data).__name__}"
            if "minimum" in schema and data < schema["minimum"]:
                return False, f"Value less than minimum {schema['minimum']}"

        elif expected_type == "array":
            if not isinstance(data, list):
                return False, f"Expected array, got {type(data).__name__}"
            if "items" in schema and isinstance(schema["items"], dict):
                for idx, item in enumerate(data):
                    valid, reason = Tier1SyntacticValidator.validate_schema(item, schema["items"])
                    if not valid:
                        return False, f"Array item [{idx}] failed validation: {reason}"

        return True, "Valid"

    @classmethod
    def verify(
        cls,
        payload: Optional[Dict[str, Any]],
        policy: EscrowPolicy,
        latency_ms: int,
        http_status: int = 200
    ) -> Tier1VerificationResult:
        """Runs the complete Tier-1 syntactic invariant evaluation."""
        # 1. Check HTTP Status Invariant
        if http_status != 200:
            return Tier1VerificationResult(
                is_valid=False,
                reason=f"Non-200 HTTP status code returned: {http_status}",
                latency_ms=latency_ms
            )

        # 2. Check Latency SLA Invariant
        if latency_ms > policy.max_latency_ms:
            return Tier1VerificationResult(
                is_valid=False,
                reason=f"SLA breach: Latency {latency_ms}ms exceeded max {policy.max_latency_ms}ms",
                latency_ms=latency_ms
            )

        # 3. Check Payload presence
        if payload is None:
            return Tier1VerificationResult(
                is_valid=False,
                reason="Empty or null output payload received from seller",
                latency_ms=latency_ms
            )

        # 4. Check JSON-Schema compliance if required
        if policy.required_schema:
            valid, reason = cls.validate_schema(payload, policy.required_schema)
            if not valid:
                return Tier1VerificationResult(
                    is_valid=False,
                    reason=f"Schema Invariant violation: {reason}",
                    latency_ms=latency_ms
                )

        return Tier1VerificationResult(
            is_valid=True,
            reason="Tier-1 Syntactic & SLA invariants satisfied",
            latency_ms=latency_ms
        )
