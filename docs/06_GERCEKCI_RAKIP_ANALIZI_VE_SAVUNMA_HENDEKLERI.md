# 06. GERÇEKÇİ RAKİP ANALİZİ VE SAVUNMA HENDEKLERİ (THE MOAT)

> **Belge No:** PACTA-DOC-06  
> **Sürüm:** 2026.1 Enterprise-Sovereign  
> **Kapsam:** Skyfire, Coinbase AgentKit, Google AP2, Kleros, UMA ve Escrow.com Teşrihi ve Pacta Savunma Hendekleri

---

## 1. Rakiplerin Teşrihi ve Yapısal Zayıf Noktaları

M2M ödemeleri ve emanet altyapısında faaliyet gösteren mevcut çözümler, yapay zeka ajanlarının hız, maliyet ve doğrulama gereksinimlerini karşılamaktan uzaktır:

### 1.1. Skyfire (KYA & KYAPay)
* **Konumlandırma:** Ajan kimliği (Know Your Agent - KYA) ve harcama limitli USDC cüzdanları.
* **Yapısal Zayıflığı:** Skyfire yalnızca *"Bu ajanın sahibi kim ve ne kadar harcayabilir?"* sorusuna yanıt verir. Satıcı ajan ödemeyi aldıktan sonra bozuk veri döndürürse, sunucusu çökerse veya halüsinasyon üretirse **parayı geri alacak hiçbir emanet veya tahkim mekanizması sunmaz.** Skyfire üzerinden yapılan ödemeler geri alınamazdır.

### 1.2. Coinbase AgentKit (Ham x402)
* **Konumlandırma:** Base L2 üzerinde CDP cüzdanlarıyla HTTP 402 ödemesi tetikleyen açık kaynak SDK.
* **Yapısal Zayıflığı:** x402 ham haliyle iki aktörlüdür (İstemci ve Sunucu). Sunucu HTTP 402 döndüğünde istemci doğrudan USDC transfer eder. Bu akış, klasik e-ticaretteki "kredi kartı chargeback" korumasını tamamen ortadan kaldırır. Ajan geliştiricileri büyük bütçeli kritik görevleri ham x402 rayına emanet edemez.

### 1.3. Kleros ve UMA (Merkeziyetsiz Adalet Protokolleri)
* **Konumlandırma:** İnsan jürilerin oy kullandığı Web3 uyuşmazlık çözüm mahkemeleri.
* **Yapısal Zayıflığı:** Kleros bir karara varmak için **3 ila 7 gün (72–168 saat)** bekletir ve insan jürilere yüksek gaz/ödül ücretleri (%2–%5) öder. Saniyede binlerce işlem yapan LLM ve trading ajanlarının 72 saat jüri beklemesi teknik ve ekonomik olarak imkansızdır.

### 1.4. Escrow.com (Geleneksel Web2 Emanet Tekeli)
* **Konumlandırma:** Domain, otomobil ve web sitesi satışlarında insan emanetçisi.
* **Yapısal Zayıflığı:** İşlem başına %0.89 – %3.25 komisyon keser, manuel pasaport kimlik onayı ister ve banka havalesiyle 3–10 iş günü sürer. Otonom yapay zeka makinelerinin bu sisteme kaydolması mümkün değildir.

---

## 2. Karşılaştırmalı Teşrih Matrisi

| Kriter | Skyfire | Coinbase AgentKit | Kleros / UMA | Escrow.com | **PACTA (Bizim Model)** |
|---|---|---|---|---|---|
| **Temel İşlevi** | Ajan Cüzdanı & KYA | Ham x402 Çağrısı | İnsan Jüri Mahkemesi | Web2 İnsan Emaneti | **Kriptografik A2A Emanet & Tahkim** |
| **Teslimat Güvencesi (DvP)**| Yok | Yok | Kısmi | Manuel İnceleme | **%100 Kriptografik Teslimat Kilitli** |
| **Çözüm Hızı** | Anlık (Korumasız) | Anlık (Korumasız) | 72–168 Saat | 3–10 İş Günü | **Optimistic: <50 ms, Dispute: <60 sn** |
| **Doğrulama Motoru** | Yok | Yok | İnsan Öznel Oyları | İnsan Gözlemi | **Tamga WASI + zkTLS + JSON-Schema** |
| **İşlem Maliyeti (COGS)**| SaaS Ücreti | Ağ Gas Ücreti | $50 – $300 + Gas | %3.25 + $25 | **~$0.0022 (Base L2 Blob)** |
| **İşlem Komisyonu** | Sabit / Spread | %0 (Protokolsüz) | %2.0 – %5.0 | %0.89 – %3.25 | **%0.35 – %0.75 Kademeli** |
| **HITL (Zorunlu İnsan)**| %0 (Korumasız) | %0 (Korumasız) | %100 (İnsan Jürisi) | %100 (Operatör) | **SIFIR (%0 HITL Otonom)** |

---

## 3. Pacta'nın 4 Katmanlı Savunma Hendeği (The Moat)

1. **Kriptografik Doğrulama Hendeği:** Rakipler gibi güvene veya insan jürisine değil; `tamga-protocol` deterministik WASI sanal makinesi ve DECO zkTLS kanıtlarına dayanır. Matematiksel olarak ispatlanamayan hiçbir işlem serbest bırakılmaz.
2. **Ultra Düşük Gecikme ve Maliyet Hendeği:** İyimser Adil Takas (Optimistic Fair Exchange) prensibiyle, dürüst teslimatlarda <50 ms sürede ve ~$0.0022 maliyetle mutabakat sağlanır.
3. **Mevzuat ve Vergi Hendeği:** UCC Article 12 (CER) ve FinCEN FIN-2019-G001 non-custodial muafiyetine tam uyumluluk; Türkiye'de 193 Sayılı GVK 89/13 ile %100 vergiden muaf kâr marjı (%98.5).
4. **Geliştirici Ekosistem Hendeği:** Coinbase AgentKit, LangChain, CrewAI, ElizaOS ve Model Context Protocol (MCP) için hazır tek satırlık eklentilerle pazara giriş bariyerini sıfıra indirmesi.
