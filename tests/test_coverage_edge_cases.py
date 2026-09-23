"""Edge case tests to ensure >90% coverage on all branches."""

import pytest
from pacta.models import EscrowPolicy, VerificationTier, ZkTLSCertificate
from pacta.client import PactaEscrowClient
from pacta.core.vault import PactaEscrowVault, EscrowNotFoundError
from pacta.verification.tier1_syntax import Tier1SyntacticValidator
from pacta.verification.tier2_proof import Tier2CryptographicValidator
from pacta.cli import main


def test_tier1_array_and_number_types():
    schema = {
        "type": "object",
        "properties": {
            "counts": {"type": "array", "items": {"type": "number", "minimum": 10}},
            "title": {"type": "string", "minLength": 3},
            "age": {"type": "integer"}
        }
    }
    policy = EscrowPolicy(required_schema=schema)

    # Valid
    valid_data = {"counts": [12, 15], "title": "Hello", "age": 25}
    assert bool(Tier1SyntacticValidator.verify(valid_data, policy, 50)) is True

    # Invalid array
    invalid_data = {"counts": "not_an_array"}
    res = Tier1SyntacticValidator.verify(invalid_data, policy, 50)
    assert bool(res) is False

    # Invalid array item
    invalid_item = {"counts": [5]}  # Minimum is 10
    res2 = Tier1SyntacticValidator.verify(invalid_item, policy, 50)
    assert bool(res2) is False

    # Invalid string length
    invalid_str = {"title": "hi"}
    res3 = Tier1SyntacticValidator.verify(invalid_str, policy, 50)
    assert bool(res3) is False

    # Invalid integer type
    invalid_int = {"age": "twenty"}
    res4 = Tier1SyntacticValidator.verify(invalid_int, policy, 50)
    assert bool(res4) is False


def test_client_zktls_verification_flow():
    client = PactaEscrowClient()
    policy = EscrowPolicy(verification_mode=VerificationTier.TIER2_CRYPTOGRAPHIC)
    payload = {"rate": 1.25}
    payload_hash = Tier2CryptographicValidator.compute_payload_hash(payload)

    cert = ZkTLSCertificate(
        session_id="s1",
        server_name="ecb.europa.eu",
        data_hash=payload_hash,
        zk_proof_snark="0x" + "0" * 64,
        attestation_key="0xbbd6b8b1235e2120b04df7b1ec85bfc5c52705"
    )

    # AT-157-güvenlik-düzeltmesi: zk-SNARK-doğrulanmıyordu ( sahte-'A'*32-
    # bile-'authentic'-geçiyordu). verify_zktls_certificate-artık-fail-closed
    # ( gerçek-DECO/TLSNotary-uygulanana-kadar-KAPALI) → escrow-settle-OLMAZ.
    resp = client.call_with_escrow(
        seller_address="0xc5ad63e263ab5f3f722d3fa1c71bf73d73dd11",
        amount=5.0,
        output_data=payload,
        policy=policy,
        zktls_cert=cert
    )
    assert resp.success is False
    assert resp.job.status.value != "SETTLED"


def test_client_zktls_failure_flow():
    client = PactaEscrowClient()
    policy = EscrowPolicy(verification_mode=VerificationTier.TIER2_CRYPTOGRAPHIC)
    payload = {"rate": 1.25}

    # Pass invalid cert with wrong hash
    bad_cert = ZkTLSCertificate(
        session_id="s1",
        server_name="ecb.europa.eu",
        data_hash="0xwrong",
        zk_proof_snark="0x" + "0" * 64,
        attestation_key="0xbbd6b8b1235e2120b04df7b1ec85bfc5c52705"
    )
    resp = client.call_with_escrow(
        seller_address="0xc5ad63e263ab5f3f722d3fa1c71bf73d73dd11",
        amount=5.0,
        output_data=payload,
        policy=policy,
        zktls_cert=bad_cert
    )
    assert resp.success is False
    assert "Tier 2 zkTLS Failed" in resp.error_message


def test_vault_error_branches():
    vault = PactaEscrowVault()
    with pytest.raises(EscrowNotFoundError):
        vault.submit_output("non-existent-id", {})

    with pytest.raises(EscrowNotFoundError):
        vault.settle_escrow("non-existent-id")

    with pytest.raises(EscrowNotFoundError):
        vault.refund_timeout("non-existent-id")

    with pytest.raises(EscrowNotFoundError):
        vault.raise_dispute("non-existent-id", "0xd80f4b9e3ae902da59fc3f8172e54f92c0813c", "reason", "0xhash")

    with pytest.raises(ValueError):
        vault.resolve_arbitration("non-existent-dispute", [])

    # Test mark_verified_ok non-existent
    with pytest.raises(EscrowNotFoundError):
        vault.mark_verified_ok("non-existent-id")


def test_vault_explicit_job_id_and_timeout():
    import time
    vault = PactaEscrowVault()
    # Explicit job_id
    job = vault.create_and_lock_escrow(
        buyer_address="0x59b66b9e6ffdd9ba6ff61c12acfec66f46cd32",
        seller_address="0x2fe8de9732027146046b7f4603994c5a5f5cb0",
        amount_usdc=5.0,
        policy=EscrowPolicy(timeout_ms=10),
        job_id="custom-job-123"
    )
    assert job.job_id == "custom-job-123"

    # Simulate timeout before submit
    time.sleep(0.02)
    timed_out_job = vault.submit_output("custom-job-123", {"data": "too_late"})
    assert timed_out_job.status.value == "AUTO_REFUNDED_TIMEOUT"


def test_vault_dispute_seller_wins():
    from decimal import Decimal
    from pacta.models import ArbitrationVote
    vault = PactaEscrowVault()
    job = vault.create_and_lock_escrow(
        buyer_address="0x59b66b9e6ffdd9ba6ff61c12acfec66f46cd32",
        seller_address="0x2fe8de9732027146046b7f4603994c5a5f5cb0",
        amount_usdc=10.0,
        policy=EscrowPolicy()
    )
    vault.submit_output(job.job_id, {"res": "ok"})
    claim = vault.raise_dispute(
        job_id=job.job_id,
        claimant_address="0x59b66b9e6ffdd9ba6ff61c12acfec66f46cd32",
        reason="Frivolous complaint",
        evidence_hash="0xev"
    )
    # 2 votes for seller, 0 for buyer (seller wins)
    votes = [
        ArbitrationVote(arbitrator_address="0x24d749ec120e581b60b3dd0fcb8e7a0cf0753a", vote_favor_buyer=False, stake_amount_pacta=Decimal("100"), rationale_hash="0x54fd580f81be3e09ae45a05c507295d1c3635f"),
        ArbitrationVote(arbitrator_address="0xab8ef1ea75010c935714c9318946f37096a449", vote_favor_buyer=False, stake_amount_pacta=Decimal("100"), rationale_hash="0xfe26576731c057e0ef78f7a21e8b8b9cceed6b"),
    ]
    outcome = vault.resolve_arbitration(claim.dispute_id, votes)
    assert outcome.buyer_favored is False
    assert outcome.paid_to_seller_usdc > Decimal("9.9")
    assert job.status.value == "SETTLED"


def test_tier2_tamga_and_zktls_edge_cases():
    from pacta.models import TamgaExecutionReceipt
    from eth_account import Account
    from eth_account.messages import encode_defunct

    payload = {"status": "ok"}
    payload_hash = Tier2CryptographicValidator.compute_payload_hash(payload)

    # 1. None receipt
    res_none = Tier2CryptographicValidator.verify_tamga_receipt(payload, None)
    assert res_none.is_valid is False

    # 2. Corrupt integrity (instruction_count <= 0)
    receipt_corrupt = TamgaExecutionReceipt(
        job_id="job-c1",
        program_hash="0xprog",
        input_commitment="0xcc5297e2235fdcaa24ea70ac1fab1c97be6882",
        output_hash=payload_hash,
        instruction_count=0,
        memory_pages=1,
        wasi_trace_root="0xroot",
        timestamp_epoch=1000,
        signature="0x626668025320af3bceab39308dfe5b6f6ee3de"
    )
    assert receipt_corrupt.verify_tamga_integrity() is False
    res_corrupt = Tier2CryptographicValidator.verify_tamga_receipt(payload, receipt_corrupt)
    assert res_corrupt.is_valid is False

    # 3. Valid ECDSA signature verification
    acct = Account.create()
    msg = encode_defunct(text=payload_hash)
    signed = acct.sign_message(msg)
    sig_hex = signed.signature.hex()
    if not sig_hex.startswith("0x"):
        sig_hex = "0x" + sig_hex

    receipt_valid_ecdsa = TamgaExecutionReceipt(
        job_id="job-c2",
        program_hash="0xprog",
        input_commitment="0xcc5297e2235fdcaa24ea70ac1fab1c97be6882",
        output_hash=payload_hash,
        instruction_count=100,
        memory_pages=1,
        wasi_trace_root="0xroot",
        timestamp_epoch=1000,
        signature=sig_hex
    )
    res_ecdsa = Tier2CryptographicValidator.verify_tamga_receipt(
        payload, receipt_valid_ecdsa, expected_signer=acct.address
    )
    assert res_ecdsa.is_valid is True

    # 4. Mismatched signer
    res_mismatch = Tier2CryptographicValidator.verify_tamga_receipt(
        payload, receipt_valid_ecdsa, expected_signer="0x21bab531a09130b0a7486dfe88bfa0ff7a3ff0"
    )
    assert res_mismatch.is_valid is False

    # 5. Invalid signature string causing recovery error
    receipt_bad_sig = TamgaExecutionReceipt(
        job_id="job-c3",
        program_hash="0xprog",
        input_commitment="0xcc5297e2235fdcaa24ea70ac1fab1c97be6882",
        output_hash=payload_hash,
        instruction_count=100,
        memory_pages=1,
        wasi_trace_root="0xroot",
        timestamp_epoch=1000,
        signature="0x" + "ff" * 65
    )
    res_bad_sig = Tier2CryptographicValidator.verify_tamga_receipt(
        payload, receipt_bad_sig, expected_signer=acct.address
    )
    assert res_bad_sig.is_valid is False

    # 6. zkTLS None cert and invalid cert
    res_zktls_none = Tier2CryptographicValidator.verify_zktls_certificate(payload, None)
    assert res_zktls_none.is_valid is False

    bad_cert_snark = ZkTLSCertificate(
        session_id="s1",
        server_name="example.com",
        data_hash=payload_hash,
        zk_proof_snark="short",
        attestation_key="0xkey"
    )
    assert bad_cert_snark.verify_certificate() is False
    res_bad_cert = Tier2CryptographicValidator.verify_zktls_certificate(payload, bad_cert_snark)
    assert res_bad_cert.is_valid is False


def test_tier3_empty_votes_raises():
    from decimal import Decimal
    from pacta.verification.tier3_arbitration import Tier3ArbitrationEngine
    with pytest.raises(ValueError):
        Tier3ArbitrationEngine.calculate_schelling_outcome([], Decimal("1"), Decimal("1"))


def test_tier1_none_and_type_mismatches():
    policy = EscrowPolicy(
        required_schema={"type": "string"},
        max_latency_ms=1000
    )
    # None payload
    res_none = Tier1SyntacticValidator.verify(None, policy, 100)
    assert res_none.is_valid is False

    # String type mismatch (pass int)
    res_type = Tier1SyntacticValidator.verify(123, policy, 100)  # type: ignore
    assert res_type.is_valid is False

    # Object type mismatch (pass int)
    obj_policy = EscrowPolicy(required_schema={"type": "object"})
    res_obj_type = Tier1SyntacticValidator.verify(123, obj_policy, 100)  # type: ignore
    assert res_obj_type.is_valid is False


def test_protocols_x402_and_ap2():
    from pacta.protocols.x402 import X402ProtocolHandler
    from pacta.protocols.ap2 import AP2MandateToken
    from pacta.models import EscrowJob, EscrowStatus
    from decimal import Decimal

    # x402 challenge with schema hash
    policy_with_schema = EscrowPolicy(required_schema={"type": "object"})
    job = EscrowJob(
        job_id="job-schema",
        buyer_address="0x59b66b9e6ffdd9ba6ff61c12acfec66f46cd32",
        seller_address="0x2fe8de9732027146046b7f4603994c5a5f5cb0",
        amount_usdc=Decimal("5.0"),
        policy=policy_with_schema,
        status=EscrowStatus.INITIALIZED
    )
    headers = X402ProtocolHandler.create_challenge_headers(job, "0x384e75adc6ffe6e2165db3de23d72e2f70acc6")
    assert "X-Pacta-Required-Schema-Hash" in headers

    # x402 invalid auth headers
    assert X402ProtocolHandler.parse_authorization_header("Bearer token") is None
    assert X402ProtocolHandler.parse_authorization_header("PactaEscrow OnlyTx=0x123") is None

    # AP2 mandate expired
    expired_token = AP2MandateToken(
        mandate_id="man-1",
        principal_authority="0x53fa1a77747f52496d510eea548f3970db8855",
        delegated_agent_address="0xa1a38fcd9717b9dea7b3e5210c6de1328301d9",
        payer_address="0xac3fad1f9c6fca45f8ad275c4f1fc0ce7bf6ad",
        merchant_scope="0xf051d357327197d7cba0d55df1d311f113d9ae",
        max_amount_usdc=100.0,
        expires_at_epoch=10,  # Far past
        mandate_signature="0x626668025320af3bceab39308dfe5b6f6ee3de"
    )
    assert expired_token.is_valid(50.0, "0xf051d357327197d7cba0d55df1d311f113d9ae") is False

    # AP2 mandate wrong merchant
    valid_time_token = AP2MandateToken(
        mandate_id="man-2",
        principal_authority="0x53fa1a77747f52496d510eea548f3970db8855",
        delegated_agent_address="0xa1a38fcd9717b9dea7b3e5210c6de1328301d9",
        payer_address="0xac3fad1f9c6fca45f8ad275c4f1fc0ce7bf6ad",
        merchant_scope="0x5935c581e6cc38ba54807f537c46d5b7c5c485",
        max_amount_usdc=100.0,
        expires_at_epoch=2000000000,
        mandate_signature="0x626668025320af3bceab39308dfe5b6f6ee3de"
    )
    assert valid_time_token.is_valid(50.0, "0xb34433b7a5d5daf0b98fdf405a40b0c1e4f9d3") is False


def test_integrations_edge_cases():
    from pacta.integrations.agentkit import PactaEscrowActionProvider
    from pacta.integrations.langchain_tool import PactaEscrowTool
    from pacta.integrations.mcp_server import PactaMCPServer
    from pacta.client import PactaEscrowClient
    from pacta.models import EscrowPolicy

    client = PactaEscrowClient()
    # AgentKit dispute
    prov = PactaEscrowActionProvider(client=client)
    actions = prov.get_actions()
    assert "pacta_pay_with_escrow" in actions
    # Create and submit a job that remains in dispute window
    active_job = client.vault.create_and_lock_escrow(
        buyer_address=client.wallet_address,
        seller_address="0x2fe8de9732027146046b7f4603994c5a5f5cb0",
        amount_usdc=5.0,
        policy=EscrowPolicy()
    )
    client.vault.submit_output(active_job.job_id, {"result": "substandard"})
    disp = prov.raise_dispute(
        job_id=active_job.job_id,
        reason="Bad delivery",
        evidence_hash="0xhash"
    )
    assert disp["status"] == "ARBITRATION_IN_PROGRESS"

    # LangChain refund failure string
    tool = PactaEscrowTool(client=client)
    res_str = tool._run(
        seller_address="0x2fe8de9732027146046b7f4603994c5a5f5cb0",
        amount_usdc=5.0,
        output_payload={"status": "ok"}
    )
    assert "SUCCESS" in res_str or "FAILED" in res_str

    # Test refund path in langchain tool by passing None payload
    client_refund = PactaEscrowClient()
    tool_refund = PactaEscrowTool(client=client_refund)
    refund_str = tool_refund._run(
        seller_address="0x2fe8de9732027146046b7f4603994c5a5f5cb0",
        amount_usdc=5.0,
        output_payload=None,  # type: ignore
        timeout_ms=5000
    )
    assert "FAILED:" in refund_str
    assert "refunded to buyer" in refund_str

    # MCP server dispute and unknown tool
    client_mcp = PactaEscrowClient()
    mcp = PactaMCPServer(client=client_mcp)
    
    # Active job for dispute in MCP
    mcp_job = client_mcp.vault.create_and_lock_escrow(
        buyer_address=client_mcp.wallet_address,
        seller_address="0x2fe8de9732027146046b7f4603994c5a5f5cb0",
        amount_usdc=10.0,
        policy=EscrowPolicy()
    )
    client_mcp.vault.submit_output(mcp_job.job_id, {"data": "bad"})
    disp_res = mcp.execute_tool("pacta_raise_dispute", {
        "job_id": mcp_job.job_id,
        "reason": "Test dispute via MCP",
        "evidence_hash": "0xev"
    })
    assert disp_res["status"] == "ARBITRATION_IN_PROGRESS"

    unknown_res = mcp.execute_tool("unknown_tool_name", {})
    assert "error" in unknown_res


def test_cli_main_status(monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["pacta", "status"])
    main()
    captured = capsys.readouterr()
    assert "ONLINE & 100% SOLVENT" in captured.out


def test_client_tamga_failure_flow():
    from pacta.models import TamgaExecutionReceipt
    client = PactaEscrowClient()
    policy = EscrowPolicy(verification_mode=VerificationTier.TIER2_CRYPTOGRAPHIC)
    payload = {"rate": 1.25}

    bad_receipt = TamgaExecutionReceipt(
        job_id="job-bad",
        program_hash="0xprog",
        input_commitment="0xcc5297e2235fdcaa24ea70ac1fab1c97be6882",
        output_hash="0xb0520dc55242a430018cdb1db26028f10f7a3b",
        instruction_count=100,
        memory_pages=1,
        wasi_trace_root="0xroot",
        timestamp_epoch=1000,
        signature="0x626668025320af3bceab39308dfe5b6f6ee3de"
    )
    resp = client.call_with_escrow(
        seller_address="0xc5ad63e263ab5f3f722d3fa1c71bf73d73dd11",
        amount=5.0,
        output_data=payload,
        policy=policy,
        tamga_receipt=bad_receipt
    )
    assert resp.success is False
    assert "Tier 2 Tamga Failed" in resp.error_message


def test_cli_main_demo_and_empty(monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["pacta", "demo"])
    main()
    captured = capsys.readouterr()
    assert "Vault Solvency Invariant" in captured.out

    # Invalid command triggers help
    monkeypatch.setattr("sys.argv", ["pacta", "invalid_cmd"])
    with pytest.raises(SystemExit):
        main()


def test_cli_main_serve(monkeypatch, capsys):
    class DummyServer:
        def __init__(self, addr, handler):
            self.addr = addr
            self.handler = handler
        def __enter__(self):
            return self
        def __exit__(self, exc_type, exc_val, exc_tb):
            return False
        def serve_forever(self):
            raise KeyboardInterrupt()

    monkeypatch.setattr("socketserver.TCPServer", DummyServer)
    monkeypatch.setattr("sys.argv", ["pacta", "serve", "--port", "9999"])
    main()
    captured = capsys.readouterr()
    assert "Serving Pacta Cockpit on http://localhost:9999" in captured.out
    assert "Server stopped." in captured.out
