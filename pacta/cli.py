"""
Pacta Command Line Interface (CLI)
Provides operators and autonomous agents with tools to simulate, inspect, and run Pacta.
"""

import sys
import argparse
import json
from pacta.models import EscrowPolicy, VerificationTier, TamgaExecutionReceipt, ArbitrationVote
from pacta.client import PactaEscrowClient
from pacta.core.vault import PactaEscrowVault
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


def main():
    parser = argparse.ArgumentParser(description="Pacta x402/AP2 Escrow & Arbitration CLI")
    subparsers = parser.add_subparsers(dest="command")

    subparsers.add_parser("demo", help="Run multi-scenario M2M escrow simulation")
    subparsers.add_parser("status", help="Inspect vault health & solvency invariant")
    serve_p = subparsers.add_parser("serve", help="Launch interactive web cockpit server")
    serve_p.add_argument("--port", type=int, default=8090, help="Port to listen on (default: 8090)")

    args = parser.parse_args()
    if args.command == "status":
        vault = PactaEscrowVault()
        vault.check_solvency_invariant()
        print("Pacta Vault Status: ONLINE & 100% SOLVENT.")
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


if __name__ == "__main__":
    main()
