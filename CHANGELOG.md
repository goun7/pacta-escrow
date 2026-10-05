# Changelog

## [Unreleased]

### [Fix-2026-10-05] — Tamga D5-ledger mesh bağlantısı (RFC-010)
- **`pacta/integrations/tamga_d5.py`** — "Escrow FSM No Verified Delivery"
  deseninin kapanışı: bir settlement tamamlandığında karar artık bir Tamga D5
  hash-chain'ine (RFC-003 D5/D7/D8) sabitlenir ve RFC-010 cross-artifact
  settlement binding'in beş kontrolüyle bağımsız doğrulanır (receipt-verifies +
  claim-verifies + settlementRef-resolves + payer/payee-match + evidenceHash ==
  receiptHash; fail-closed).
- **`pacta/integrations/tamga_jcs.py`** — RFC 8785 (JCS) canonicalization'ın
  byte-identical vendor kopyası (Tamga'nın kendi `tamga_verify_mini.py`
  geleneği); D5 özetlerinin Tamga'nın `ledger-verify`'ında yeniden
  doğrulanabilmesi için gereklidir.
- `PactaEscrowVault(d5_ledger=...)` — opsiyonel D5-ledger; `settle_escrow`
  otomatik charge kaydı yazar (verilmezse eski davranış; saf-bellek).
- `EscrowJob.settlement_binding` alanı eklendi (additive; None = eski davranış).
- **Çapraz-proje doğrulaması (stub DEĞİL):** Pacta'nın ürettiği charge + imzalı
  claim, Tamga'nın kendi `tools/settlement_bind_verify.py` gate'inde GREEN
  rc=0; Pacta'nın `ledger.jsonl` dosyası Tamga'nın `tamga_runner.py
  ledger-verify`'ında sağlam çıkar.
- Testler: 57 → **70 passed** (+13; 5 skipped değişmedi).

## [0.1.0] — 2026-09-23
- İlk genel sürüm: Pacta — Escrow FSM + Schelling Arbitration
- Pacta, TAMGA-MESH'in **anlaşmazlık çözüm** protokolüdür: emanet (escrow)

## Sürümleme

- [SemVer](https://semver.org/lang/tr/) uyumludur.
