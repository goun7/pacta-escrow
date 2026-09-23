# 03. ÜÇ KADEMELİ DOĞRULAMA VE TAMGA WASI MİMARİSİ

> **Belge No:** PACTA-DOC-03  
> **Sürüm:** 2026.1 Enterprise-Sovereign  
> **Konu:** Deterministik Sentaks, Tamga-Protocol WASI Makbuzları, DECO zkTLS ve Schelling Hakemliği Doğrulama Mimarisi

---

## 1. Giriş: Çok Modlu Doğrulama Paradigması

Geleneksel blokzincir orakılları (Chainlink vb.) yalnızca basit tekil sayıları ("BTC = $65.000") zincire taşır. Otonom yapay zeka ajanlarının birbirine sunduğu karmaşık veri setlerini, model ağırlıklarını, kod yürütme sonuçlarını veya finansal raporları doğrulayamazlar.

Pacta, farklı işlem türlerinin doğrulama maliyetlerini ve gecikme gereksinimlerini optimize etmek için **Üç Kademeli Doğrulama Mimarisi (Three-Tier Verification Architecture)** kullanır:

```
+-----------------------------------------------------------------------------------+
|               KADEME 1: DETERMINISTIK SENTAKS VE SLA INVARIANT DENETİMİ           |
|  - Gecikme: <1 ms | Maliyet: 0 Gas (Zincir Dışı İstemci/Relayer)                 |
|  - JSON-Schema Uyumu, HTTP 200 Durumu, Latency <= SLA Max Denetimi                |
+-----------------------------------------------------------------------------------+
                                         │
                                         ▼ (Şema Geçerliyse)
+-----------------------------------------------------------------------------------+
|               KADEME 2: KRİPTOGRAFİK HESAPLAMA VE zkTLS KANITLARI                 |
|  - Gecikme: 50 - 200 ms | Maliyet: Düşük (Tekil Hash / SNARK Onayı)              |
|  - Tamga WASI Sandbox Hash-Zinciri + DECO / TLSNotary Oturum İspatı               |
+-----------------------------------------------------------------------------------+
                                         │
                                         ▼ (Subjektif Uyuşmazlık Varsa)
+-----------------------------------------------------------------------------------+
|               KADEME 3: SCHELLING ODAK NOKTASI OTONOM HAKEMLİK PANELİ             |
|  - Gecikme: 15 - 60 sn | Maliyet: İtiraz Teminatından Karşılanır                   |
|  - VRF ile Seçilen 5-7 Staked Düğüm Konsensüsü + Karesel Slashing                 |
+-----------------------------------------------------------------------------------+
```

---

## 2. Kademe 1: Deterministik Sentaks ve SLA Denetimi (Tier 1)

Kademe 1, ağ üzerindeki işlemlerin %95'ini sıfır blokzincir işlem ücretiyle (0 Gas) ve mikrosaniyeler mertebesinde filtreleyen ilk savunma hattıdır.

### 2.1. Denetlenen Katı Değişmezler (Invariants)
1. **HTTP Durum Kodu Değişmezi:** Satıcı sunucunun döndürdüğü kod kesin olarak `200 OK` olmalıdır. `500 Internal Server Error`, `502 Bad Gateway`, `504 Gateway Timeout` durumlarında emanet serbest bırakma fonksiyonu fiziksel olarak çağrılamaz.
2. **Gecikme (Latency) Değişmezi:** İstek ile yanıt arasındaki süre $t_{\text{roundtrip}} \le t_{\text{policy.max_latency_ms}}$ şartını sağlamalıdır. Süre aşılırsa satıcı hak iddia edemez.
3. **JSON-Schema Biçimsel Eşleşmesi:** Yanıt gövdesi, sözleşmede SHA-256 özeti kilitlenmiş olan JSON-Schema'ya harfi harfine uymalıdır.
   - Zorunlu alanların (`required`) varlığı,
   - Veri tiplerinin (string, integer, float, boolean, array, object) doğruluğu,
   - Sayısal alt/üst limitler (`minimum`, `maximum`) ve metin uzunluk sınırları.

---

## 3. Kademe 2: Tamga WASI Sandbox ve zkTLS Mimarisi (Tier 2)

Daha yüksek güvenlik gerektiren hesaplama veya üçüncü taraf veri tedariki işlemlerinde devreye girer.

### 3.1. Tamga-Protocol WASI Sandbox Entegrasyonu
Eğer satıcı ajan bir veri analizi, kod derlemesi veya model çıkarımı yapmışsa; bu işlem portföydeki `tamga-protocol` WASI (WebAssembly System Interface) sanal makinesinde izole edilir:
* **Deterministik Bellek İzleme:** Yürütülen her WebAssembly talimatı (instruction) ve bellek yazımı deterministik bir Merkle hash zincirine dökülür.
* **TamgaReceipt Yapısı:**
  ```python
  TamgaReceipt {
      job_id: "8f9b1c2d-...",
      program_hash: "0x3a4b...",      # Çalıştırılan WASM ikilisinin SHA-256'sı
      input_commitment: "0x12ef...",  # İş emrinin girdi özet taahhüdü
      output_hash: "0x8f1a...",       # Üretilen sonucun SHA-256'sı
      wasi_trace_root: "0x77ab...",   # Yürütme Merkle kök hash'i
      instruction_count: 4520,        # Toplam CPU komut sayısı
      signature: "0xECDSA..."         # Satıcı düğümün özel anahtar imzası
  }
  ```
* **Doğrulama:** Pacta akıllı sözleşmesi veya SDK, `output_hash`'in sunulan veriyle birebir eşleştiğini ve satıcı düğümün imzasını tek bir `ecrecover` çağrısıyla doğrular.

### 3.2. DECO / TLSNotary zkTLS Entegrasyonu
Eğer satıcı ajan harici bir Web2 kaynağından (örneğin Bloomberg, New York Times, SEC EDGAR) veri getirdiğini iddia ediyorsa:
* **Üç Taraflı El Sıkışma (3-Party Handshake):** DECO protokolü uyarınca, ajan ile web sunucusu arasındaki TLS 1.3 oturum anahtarları gizli paylaşım (secret sharing) ile bölünür.
* **Sıfır Bilgi İspatı (zk-SNARK):** Ajan, hedef sunucunun özel anahtarlarını ifşa etmeden veya kendi API şifrelerini sızdırmadan verinin orijinal sunucudan geldiğini kanıtlayan bir ZK kanıtı üretir.
* Bu sayede "uydurma finansal haber" veya "sahte borsa fiyatı" ile emanet fonlarının çalınması kriptografik olarak imkansız hale gelir.

---

## 4. Kademe 3: Schelling Odak Noktası Hakemlik Paneli (Tier 3)

Matematiksel olarak formüle edilemeyen semantik uyuşmazlıklarda (örn. "Bu hukuki özet dava dosyasını tam yansıtıyor mu?"):

### 4.1. Anti-Griefing İtiraz Depozitosu ($B_{\text{dispute}}$)
Alıcı ajanın sistemi tıkamasını veya satıcının parasını bedavaya dondurmasını engellemek için:

$$B_{\text{dispute}} = 0.20 \times V_{\text{escrow}}$$

İtiraz teminatsız açılamaz. Eğer alıcı haksız bulunursa bu teminatın %50'si satıcıya tazminat olarak aktarılır, %50'si dürüst hakemlere dağıtılır.

### 4.2. Karesel Slashing (Quadratic Slashing) Formülasyonu
Hakem düğümleri $PACTA token stake ederek jüri havuzuna katılır. Rastgele VRF ile seçilen 5 veya 7 düğüm bağımsız oy verir.

Çoğunluk kararına uymayan veya rüşvet alarak taraflı oy kullanan azınlık düğümlerinin cezası karesel olarak artar:

$$\text{Slashing Cezası} = \left( \frac{N_{\text{azınlık}}}{N_{\text{toplam}}} \right)^2 \times S_{\text{staked}} \times 0.10$$

Bu kural, hakemler arasında Thomas Schelling'in **Odak Noktası (Focal Point)** teoremini tetikler: Her hakem diğer rasyonel hakemlerin "gerçek ve dürüst" karara oy vereceğini bildiği için, kendi teminatını kaybetmemek adına mutlak dürüstlükle oy kullanır.
