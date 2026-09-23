# 02. x402 VE AP2 PROTOKOL STANDARDI SPESİFİKASYONU

> **Belge No:** PACTA-DOC-02  
> **Sürüm:** 2026.1 Enterprise-Sovereign  
> **Referans Standartlar:** IETF RFC 9110 (HTTP Semantics), x402 Foundation Core Spec v1.2, Google AP2 v0.9 (FIDO Alliance Draft)

---

## 1. Protokolün Amacı ve Kapsamı

Bu doküman, HTTP 402 ("Payment Required") durum kodunun ve Google AP2 (Agent Payments Protocol) yetkilendirme akışının, **Pacta Kriptografik Emanet Rayı (Pacta Escrow Rail)** ile entegrasyonuna ilişkin biçimsel (formal) protokol kurallarını ve mesaj başlıklarını (headers) tanımlar.

Protokolün temel amacı; otonom ajanların harici API'larla veya birbirleriyle konuşurken ödemeyi doğrudan satıcıya aktarmak yerine, teslimat ispatı gerçekleşene kadar fonları şartlı akıllı emanet kasasında (Pacta Smart Vault) rehin tutmasını sağlamaktır.

---

## 2. Genişletilmiş x402 Başlık Taksonomisi (Header Taxonomy)

### 2.1. Sunucu Yanıt Başlıkları (HTTP 402 Challenge Headers)
Alıcı ajan korumalı bir API ucuna (endpoint) istek gönderdiğinde, satıcı sunucu veya Pacta Middleware şu başlıklarla yanıt verir:

```http
HTTP/1.1 402 Payment Required
Date: Sat, 19 Sep 2026 18:00:00 GMT
Content-Type: application/json
X-Pacta-Version: 2026.1
X-Pacta-Escrow-Address: 0x71C...B29
X-Pacta-Job-Id: 8f9b1c2d-4e5a-6b7c-8d9e-0f1a2b3c4d5e
X-Pacta-Price: 10.000000 USDC
X-Pacta-Deposit-Token: 0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913
X-Pacta-Timeout-Ms: 5000
X-Pacta-Required-Schema-Hash: 0xe3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
X-Pacta-Verification-Mode: TIER2_TAMGA_WASI
X-Pacta-Dispute-Window-Sec: 60
```

| Başlık Alanı | Tip | Zorunlu mu? | Açıklama |
|---|---|---|---|
| `X-Pacta-Version` | String | Evet | Protokol sürümü (örn. `2026.1`). |
| `X-Pacta-Escrow-Address` | Hex Address | Evet | Fonların kilitleneceği Base L2 akıllı sözleşme adresi. |
| `X-Pacta-Job-Id` | UUIDv4 | Evet | Bu işe özgü tekil kriptografik oturum kimliği. |
| `X-Pacta-Price` | String | Evet | Ödenecek tam miktar ve para birimi (Decimal 6 hane). |
| `X-Pacta-Deposit-Token` | Hex Address | Evet | Kabul edilen ERC-20 stablecoin kontratı (Base USDC). |
| `X-Pacta-Timeout-Ms` | Integer | Evet | Satıcının teslimatı tamamlaması gereken azami süre (milisaniye). |
| `X-Pacta-Required-Schema-Hash` | Hex Hash | Opsiyonel | Çıktının uymak zorunda olduğu JSON-Schema'nın SHA-256 özeti. |
| `X-Pacta-Verification-Mode` | Enum | Evet | `TIER1_SYNTACTIC`, `TIER2_CRYPTOGRAPHIC`, `TIER3_SCHELLING`. |
| `X-Pacta-Dispute-Window-Sec` | Integer | Evet | Çıktı tesliminden sonra itiraz açılabilecek süre (saniye). |

### 2.2. İstemci Yetkilendirme Başlığı (Authorization Header)
Alıcı ajan belirtilen emanet adresine fonu kilitledikten sonra (`depositAndLock` işlemi), isteği şu başlıkla yineler:

```http
POST /v1/alpha-signals HTTP/1.1
Host: api.seller-agent.ai
Authorization: PactaEscrow TxHash=0x9a8b...12ef, JobId=8f9b1c2d-4e5a-6b7c-8d9e-0f1a2b3c4d5e
X-Pacta-Buyer-Address: 0x1234567890abcdef1234567890abcdef12345678
Content-Type: application/json

{"query": "BTC/USDC", "timeframe": "1h"}
```

---

## 3. Google AP2 (Agent Payments Protocol) Entegrasyonu

Google tarafından başlatılan ve FIDO Alliance çatısı altında standartlaştırılan **AP2**, kullanıcıların yapay zeka ajanlarına harcama yetkisi (payment mandate) vermesini sağlar.

Pacta, AP2 yetki tokenlarını **şartlı emanet ahitlerine (Conditional Escrow Covenants)** bağlar:

```
[Kullanıcı / Şirket] ──(AP2 Yetki Mandatı: Max $100)──► [Alıcı Ajan]
                                                             │
                                                (Pacta AP2 Covenant Üretilir)
                                                             ▼
                                                [Pacta Escrow Vault (Base L2)]
                                                             │
                                                (Satıcı Şartları Karşılarsa)
                                                             ▼
                                                    [Fon Serbest Kalır]
```

### 3.1. EIP-712 İmzalı Taahhüt Veri Yapısı (Typed Data Signing)
Pacta, AP2 tokenlarını zincir üzerinde doğrulamak için EIP-712 standardını kullanır:

```json
{
  "types": {
    "EIP712Domain": [
      {"name": "name", "type": "string"},
      {"name": "version", "type": "string"},
      {"name": "chainId", "type": "uint256"},
      {"name": "verifyingContract", "type": "address"}
    ],
    "PactaEscrowCovenant": [
      {"name": "mandateId", "type": "string"},
      {"name": "jobId", "type": "bytes32"},
      {"name": "buyer", "type": "address"},
      {"name": "seller", "type": "address"},
      {"name": "amount", "type": "uint256"},
      {"name": "timeoutEpoch", "type": "uint256"},
      {"name": "schemaHash", "type": "bytes32"}
    ]
  },
  "primaryType": "PactaEscrowCovenant",
  "domain": {
    "name": "PactaProtocol",
    "version": "2026.1",
    "chainId": 8453,
    "verifyingContract": "0x71C...B29"
  }
}
```

---

## 4. Hata Kodları ve Telafi Mekanizmaları

| Durum Kodu | Hata Tanımı | Pacta Deterministik Eylemi |
|---|---|---|
| `400 Bad Request` | Geçersiz EIP-712 imzası veya eksik başlık. | İşlem başlamaz, emanet oluşturulmaz. |
| `402 Payment Required` | Standart emanet meydan okuması. | Alıcı cüzdan fonu kilitler ve isteği yineler. |
| `408 Request Timeout` | Satıcı SLA süresinde yanıt vermedi. | Alıcı `claimTimeoutRefund` çağırarak parasını %100 geri alır. |
| `422 Unprocessable Entity`| Çıktı şema testinden (Tier-1) geçmedi. | Emanet derhal feshedilir, fon alıcıya iade edilir. |
| `449 Retry With Proof` | Tamga makbuzu veya zkTLS ispatı eksik. | Satıcıya kanıtı tekrar sunması için 5 sn ek süre tanınır. |
| `499 Client Closed Request`| Alıcı haksız yere oturumu kapattı. | Satıcı çıktıyı teslim ettiğini kanıtlarsa fon satıcıya akar. |
