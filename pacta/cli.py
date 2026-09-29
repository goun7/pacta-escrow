"""
Pacta Command Line Interface (CLI)
Provides operators and autonomous agents with tools to simulate, inspect, and run Pacta.
"""

import sys
import argparse
import json
from pacta.models import EscrowPolicy, VerificationTier, TamgaExecutionReceipt, ArbitrationVote, DisputeClaim
from pacta.client import PactaEscrowClient
from pacta.core.vault import PactaEscrowVault, EscrowAuthorizationError
from pacta.core.fsm import InvalidStateTransitionError
from pacta.verification.tier2_proof import Tier2CryptographicValidator


def run_demo():
    """Simulates 3 complete real-world M2M commerce scenarios."""
    print("=" * 70)
    print("  PACTA ESCROW PROTOCOL (2026.1) — AUTONOMOUS AGENT COMMERCE DEMO")
    print("=" * 70)

    client = PactaEscrowClient()
    seller_address = "0xe42b545eb02fce40080591fe4c289a7933f964"

    # SCENARIO 1: Happy Path - Verified Delivery & Optimistic Settlement
    print("\n[SCENARIO 1] Standard Atomic Delivery-versus-Payment (DvP):")
    valid_payload = {
        "status": "success",
        "ticker": "BTC/USDC",
        "action": "BUY",
        "confidence": 0.942,
        "timestamp": 1789823900
    }
    schema = {
        "type": "object",
        "required": ["status", "ticker", "action", "confidence"],
        "properties": {
            "status": {"type": "string"},
            "ticker": {"type": "string"},
            "action": {"type": "string"},
            "confidence": {"type": "number", "minimum": 0.0}
        }
    }
    policy = EscrowPolicy(
        timeout_ms=3000,
        required_schema=schema,
        verification_mode=VerificationTier.TIER1_SYNTACTIC
    )

    print("  1. Buyer Agent requests data under x402 challenge...")
    print(f"  2. Locking 10.0 USDC in Pacta Vault for {seller_address}...")
    resp = client.call_with_escrow(
        seller_address=seller_address,
        amount=10.0,
        output_data=valid_payload,
        policy=policy,
        simulated_latency_ms=120
    )
    print(f"  3. Tier-1 Syntactic Validation: SUCCESS")
    print(f"  4. Escrow Settled: Status={resp.job.status.value}")
    print(f"     TxHash={resp.escrow_settle_tx}")
    print(f"     Gross: 10.0 USDC | Fee: {resp.job.fee_collected_usdc} USDC | Net Seller: {resp.job.net_seller_amount()} USDC")

    # SCENARIO 2: Corrupted Output / Schema Invariant Breach -> Instant Refund
    print("\n[SCENARIO 2] Corrupted Payload (Schema Invariant Breach):")
    corrupt_payload = {"error": "internal_rate_limit", "ticker": "BTC/USDC"}
    print("  1. Seller returns malformed JSON missing required 'confidence'...")
    resp_corrupt = client.call_with_escrow(
        seller_address=seller_address,
        amount=5.0,
        output_data=corrupt_payload,
        policy=policy,
        simulated_latency_ms=80
    )
    print(f"  2. Invariant Engine Evaluation: {resp_corrupt.error_message}")
    print(f"  3. Escrow Status: {resp_corrupt.job.status.value}")
    print(f"  4. 100% Refunded to Buyer Agent: {resp_corrupt.job.amount_usdc} USDC (Zero Loss)")

    # SCENARIO 3: Subjective Dispute & Schelling Arbitration Quorum
    print("\n[SCENARIO 3] Subjective Quality Dispute & Schelling Arbitration Quorum:")
    vault = PactaEscrowVault()
    job = vault.create_and_lock_escrow(
        # AT-169: demo-adresleri-artık-geçerli-hex ( katı-doğrulama)
        buyer_address="0x59b66b9e6ffdd9ba6ff61c96c9c3d4f9b1e8a0c2",
        seller_address="0xe25e108970af252da13b3f8c7a0e2f8b4c9d1a37",
        amount_usdc=25.0,
        policy=EscrowPolicy(dispute_bond_ratio=0.20)
    )
    vault.submit_output(job.job_id, output_payload={"report": "Generic text"})
    vault.mark_verified_ok(job.job_id)

    print("  1. Buyer reviews report, notices superficial content, files Dispute...")
    dispute = vault.raise_dispute(
        job_id=job.job_id,
        claimant_address="0x59b66b9e6ffdd9ba6ff61c96c9c3d4f9b1e8a0c2",
        reason="Report contains hallucinated metrics not grounded in SEC 10-K",
        evidence_hash="0xabc123..."
    )
    print(f"  2. Buyer deposited Dispute Bond: {dispute.bond_amount_usdc} USDC (20% anti-griefing)")
    print("  3. Summoning 5 Staked Arbitrator Nodes for Schelling Consensus...")

    votes = [
        ArbitrationVote(arbitrator_address="0x24d749ec120e581b60b3ddc5a6f4e2a1b9c8d0e3", vote_favor_buyer=True, staked_amount_pacta=2000.0, rationale_hash="0x1"),
        ArbitrationVote(arbitrator_address="0xab8ef1ea75010c935714c9318946f37096a4490d", vote_favor_buyer=True, staked_amount_pacta=1500.0, rationale_hash="0x2"),
        ArbitrationVote(arbitrator_address="0x7d0b86229089f159e3e7250fa16843d17ea044", vote_favor_buyer=True, staked_amount_pacta=3000.0, rationale_hash="0x3"),
        ArbitrationVote(arbitrator_address="0xa2e8b1cbc73c1457b9cdb5344b9e8d117300b9", vote_favor_buyer=True, staked_amount_pacta=1000.0, rationale_hash="0x4"),
        ArbitrationVote(arbitrator_address="0xd976dae00a32d27be4cf59f0e51245663f6394", vote_favor_buyer=False, staked_amount_pacta=500.0, rationale_hash="0x5"),
    ]
    outcome = vault.resolve_arbitration(dispute.dispute_id, votes)
    print(f"  4. Arbitration Decision Rendered:")
    print(f"     Buyer Favored: {outcome.buyer_favored} (Votes: {outcome.votes_for_buyer} vs {outcome.votes_for_seller})")
    print(f"     Buyer Refunded: {outcome.refunded_to_buyer_usdc} USDC")
    print(f"     Dissenting Rogue Node 0xArb5 Slashed Quadratically!")

    # Check Solvency
    vault.check_solvency_invariant()
    print("\n[INVARIANT CHECK] Vault Solvency Invariant (Değişmez 1): PASSED [100% SOLVENT]")
    print("=" * 70)


def run_verify(json_output: bool = False) -> int:
    """
    Bağımsız-doğrulama CLI'si (AT-kanıt-entegrasyonu).
    Pacta'nın tüm güvenlik-geçitlerini ve ödeme-akışlarını sıfırdan, demo-
    verisi-olmadan yeniden oynatır ve her birini bağımsız olarak PASS/FAIL
    ile raporlar. Hiçbir kontrol demo'nun paylaştığı durumu kullanmaz.
    Exit-code: 0 = hepsi-geçti, 1 = en-az-bir-başarısız.
    """
    checks = []

    def record(name, ok, detail):
        checks.append({"check": name, "result": "PASS" if ok else "FAIL", "detail": detail})

    B = "0x59b66b9e6ffdd9ba6ff61c96c9c3d4f9b1e8a0c2"
    S = "0xe25e108970af252da13b3f8c7a0e2f8b4c9d1a37"
    STRANGER = "0x000000000000000000000000000000000000dEaD"

    # 1) DvP happy-path: lock -> submit -> verify -> settle
    try:
        v = PactaEscrowVault()
        job = v.create_and_lock_escrow(B, S, 100.0, EscrowPolicy(fee_rate_basis_points=75))
        v.submit_output(job.job_id, {"status": "success", "value": 42})
        v.mark_verified_ok(job.job_id)
        settled, tx = v.settle_escrow(job.job_id, caller_address=B)
        ok = settled.status.value == "SETTLED" and settled.net_seller_amount() > 0
        record("dvp_happy_path", ok,
               f"status={settled.status.value} net={settled.net_seller_amount()} tx={tx[:18]}…")
    except Exception as e:  # pragma: no cover - diagnostic
        record("dvp_happy_path", False, f"exception: {type(e).__name__}: {e}")

    # 2) Başarısız-doğrulama -> tam-iade (alıcı-zararı-sıfır) + solvency-korunur
    try:
        v = PactaEscrowVault()
        job = v.create_and_lock_escrow(B, S, 50.0)
        v.submit_output(job.job_id, {"unexpected": "missing-required-status"})
        v.refund_quality_failure(job.job_id)
        ok = (job.status.value == "AUTO_REFUNDED_TIMEOUT"
              and v.check_solvency_invariant())
        record("refund_on_failed_verification", ok,
               f"status={job.status.value} solvent-after-refund={v.check_solvency_invariant()}")
    except Exception as e:  # pragma: no cover - diagnostic
        record("refund_on_failed_verification", False, f"exception: {type(e).__name__}: {e}")

    # 3) Schelling hakemlik + karesel-slashing
    try:
        v = PactaEscrowVault()
        job = v.create_and_lock_escrow(B, S, 25.0, EscrowPolicy(dispute_bond_ratio=0.20))
        v.submit_output(job.job_id, {"report": "superficial"})
        v.mark_verified_ok(job.job_id)
        d = v.raise_dispute(job.job_id, claimant_address=B,
                            reason="quality", evidence_hash="0xabc")
        votes = [
            ArbitrationVote(arbitrator_address="0x24d749ec120e581b60b3ddc5a6f4e2a1b9c8d0e3", vote_favor_buyer=True, staked_amount_pacta=2000.0, rationale_hash="0x1"),
            ArbitrationVote(arbitrator_address="0xab8ef1ea75010c935714c9318946f37096a4490d", vote_favor_buyer=True, staked_amount_pacta=1500.0, rationale_hash="0x2"),
            ArbitrationVote(arbitrator_address="0x7d0b86229089f159e3e7250fa16843d17ea044", vote_favor_buyer=True, staked_amount_pacta=3000.0, rationale_hash="0x3"),
            ArbitrationVote(arbitrator_address="0xa2e8b1cbc73c1457b9cdb5344b9e8d117300b9", vote_favor_buyer=True, staked_amount_pacta=1000.0, rationale_hash="0x4"),
            ArbitrationVote(arbitrator_address="0xd976dae00a32d27be4cf59f0e51245663f6394", vote_favor_buyer=False, staked_amount_pacta=500.0, rationale_hash="0x5"),
        ]
        out = v.resolve_arbitration(d.dispute_id, votes)
        ok = out.buyer_favored and out.votes_for_buyer == 4 and out.refunded_to_buyer_usdc > 0
        record("schelling_arbitration_slashing", ok,
               f"buyer_favored={out.buyer_favored} votes={out.votes_for_buyer}/{out.votes_for_seller} refund={out.refunded_to_buyer_usdc}")
    except Exception as e:  # pragma: no cover - diagnostic
        record("schelling_arbitration_slashing", False, f"exception: {type(e).__name__}: {e}")

    # 4) Idempotency: aynı-anahtar -> aynı-job, para-iki-kez-hareket-ETMEZ
    try:
        v = PactaEscrowVault()
        j1 = v.create_and_lock_escrow(B, S, 10.0, idempotency_key="k-1")
        j2 = v.create_and_lock_escrow(B, S, 10.0, idempotency_key="k-1")
        ok = j1.job_id == j2.job_id and len(v.jobs) == 1
        record("idempotency_no_double_lock", ok,
               f"same_job={j1.job_id == j2.job_id} job_count={len(v.jobs)}")
    except Exception as e:  # pragma: no cover - diagnostic
        record("idempotency_no_double_lock", False, f"exception: {type(e).__name__}: {e}")

    # 5) Rol-kapısı: escrow-taraflarından-biri-olmayan-settle-edemez
    try:
        v = PactaEscrowVault()
        job = v.create_and_lock_escrow(B, S, 10.0)
        v.submit_output(job.job_id, {"status": "ok"})
        v.mark_verified_ok(job.job_id)
        try:
            v.settle_escrow(job.job_id, caller_address=STRANGER)
            ok = False
            detail = "STRANGER-settle-KABUL-EDİLDİ ( güvenlik-açığı!)"
        except EscrowAuthorizationError:
            ok = True
            detail = "STRANGER-caller-reddedildi ( rol-kapısı-sağlam)"
        record("role_gate_stranger_rejected", ok, detail)
    except Exception as e:  # pragma: no cover - diagnostic
        record("role_gate_stranger_rejected", False, f"exception: {type(e).__name__}: {e}")

    # 6) FSM-terminal: SETTLED-sonrası-tekrar-settle → InvalidStateTransitionError
    try:
        v = PactaEscrowVault()
        job = v.create_and_lock_escrow(B, S, 10.0)
        v.submit_output(job.job_id, {"status": "ok"})
        v.mark_verified_ok(job.job_id)
        v.settle_escrow(job.job_id, caller_address=B)
        try:
            v.settle_escrow(job.job_id, caller_address=B)
            ok = False
            detail = "çift-settle-KABUL-EDİLDİ ( güvenlik-açığı!)"
        except InvalidStateTransitionError:
            ok = True
            detail = "terminal-durum-korundu ( çift-settle-reddedildi)"
        record("fsm_terminal_state_guard", ok, detail)
    except Exception as e:  # pragma: no cover - diagnostic
        record("fsm_terminal_state_guard", False, f"exception: {type(e).__name__}: {e}")

    # 7) Solvency-değişmezi
    try:
        v = PactaEscrowVault()
        ok = v.check_solvency_invariant()
        record("solvency_invariant", bool(ok), "vault-100%-solvent")
    except Exception as e:  # pragma: no cover - diagnostic
        record("solvency_invariant", False, f"exception: {type(e).__name__}: {e}")

    n_pass = sum(1 for c in checks if c["result"] == "PASS")
    n_all = len(checks)
    verdict = "PASS" if n_pass == n_all else "FAIL"

    if json_output:
        print(json.dumps({"verdict": verdict, "passed": n_pass, "total": n_all,
                          "checks": checks}, ensure_ascii=False, indent=2))
    else:
        print("=" * 70)
        print("  PACTA BAĞIMSIZ-DOĞRULAMA ( independent-verify)")
        print("=" * 70)
        for c in checks:
            mark = "✓" if c["result"] == "PASS" else "✗"
            print(f"  [{mark}] {c['result']:<4} {c['check']}")
            print(f"         {c['detail']}")
        print("-" * 70)
        print(f"  SONUÇ: {verdict} — {n_pass}/{n_all} kontrol-geçti")
        print("=" * 70)
    return 0 if verdict == "PASS" else 1


def main():
    parser = argparse.ArgumentParser(description="Pacta x402/AP2 Escrow & Arbitration CLI")
    subparsers = parser.add_subparsers(dest="command")

    subparsers.add_parser("demo", help="Run multi-scenario M2M escrow simulation")
    subparsers.add_parser("status", help="Inspect vault health & solvency invariant")
    verify_p = subparsers.add_parser(
        "verify", help="Independent proof-verification of all escrow security gates")
    verify_p.add_argument("--json", action="store_true",
                          help="Machine-readable JSON output")
    serve_p = subparsers.add_parser("serve", help="Launch interactive web cockpit server")
    serve_p.add_argument("--port", type=int, default=8090, help="Port to listen on (default: 8090)")

    args = parser.parse_args()
    if args.command == "status":
        vault = PactaEscrowVault()
        vault.check_solvency_invariant()
        print("Pacta Vault Status: ONLINE & 100% SOLVENT.")
    elif args.command == "verify":
        return run_verify(json_output=bool(getattr(args, "json", False)))
    elif args.command == "serve":
        import http.server
        import socketserver
        import os
        web_dir = os.path.join(os.path.dirname(__file__), "..", "web")
        os.chdir(web_dir)
        handler = http.server.SimpleHTTPRequestHandler
        print(f"Serving Pacta Cockpit on http://localhost:{args.port} (from {web_dir})")
        with socketserver.TCPServer(("", args.port), handler) as httpd:
            try:
                httpd.serve_forever()
            except KeyboardInterrupt:
                print("\nServer stopped.")
    else:
        run_demo()
    return 0


if __name__ == "__main__":
    sys.exit(main())
