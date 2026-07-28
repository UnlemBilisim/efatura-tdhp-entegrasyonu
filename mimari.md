# Sistem Mimarisi

> **Amaç:** Bu belge, `System/` altındaki çalışan sistemin **nasıl** çalıştığını
> ve tasarım kararlarının **neden** öyle verildiğini anlatır. Diátaxis
> sınıflandırmasında bu bir **explanation** belgesidir.
>
> - **Ne çalıştırılır / nasıl başlatılır** → [`System/proje-calistirma.md`](System/proje-calistirma.md)
> - **Klasör yapısı / nerede ne var** → [`OKU-YAPI.md`](OKU-YAPI.md)
> - **Alt projelerin haritası ve durumu** → [`PROJECT.md`](PROJECT.md)
> - **Bileşen içi teknik detay** → ilgili alt projenin kendi `PROJECT.md`/`docs/`'u
>
> Bu belge onları tekrar etmez.
>
> ✅ **Doğrulandı** (2026-07-27): Aşağıdaki akış, gerçek bir UBL faturası
> (`0012025015078595`, Turkcell) `POST /fatura/isle` ile uçtan uca işlenerek
> gözlemlendi — ön filtreleme + TDHP tahmini çalıştı, kayıt dengeli döndü.

---

## 1. Sistem ne yapar?

Tek cümleyle: **gelen bir e-faturanın (UBL-TR XML) KDV oranının mevzuata
uygunluğunu denetler, sonra o faturanın muhasebe kaydını (Tek Düzen Hesap
Planı kodu + Borç/Alacak yönü + tutar) otomatik üretir.**

İki ayrı problem, iki ayrı bileşen tarafından çözülür:

| Problem | Çözen | Yöntem |
|---|---|---|
| "Bu faturada beyan edilen KDV oranı mevzuata uygun mu?" | `Mcp_mimarisi/` | **Kural tabanlı** — NACE kodu → izin verilen oran havuzu (PostgreSQL) |
| "Bu fatura hangi TDHP hesabına, hangi yönde, ne tutarla kaydedilir?" | `model_eval/` | **LLM + RAG** — geçmiş emsal faturalar + şirkete özel mizan |

Bu ayrım kasıtlıdır: **mevzuat uygunluğu deterministik bir kural sorusudur,
LLM'e sorulmaz.** Muhasebe kaydı ise yorum gerektirir, kurala indirgenemez.

---

## 2. Bileşenler ve aralarındaki sınırlar

```
                    ┌──────────────────────────────────┐
                    │ Tarayıcı (entegrasyon/static/    │
                    │           index.html)            │
                    └────────────────┬─────────────────┘
                                     │ HTTP
                    ┌────────────────▼─────────────────┐
                    │   entegrasyon/  (port 8100)      │
                    │   ORKESTRASYON — karar vermez,   │
                    │   sadece sırayı yönetir          │
                    └───┬─────────────────────────┬────┘
                        │ HTTP                    │ Python import
                        │ (ayrık süreç)           │ (aynı süreç)
          ┌─────────────▼──────────┐   ┌──────────▼─────────────────┐
          │ Mcp_mimarisi (:8000)   │   │ model_eval  (kütüphane)    │
          │ KDV mevzuat ön filtresi│   │ TDHP tahmini (LLM + RAG)   │
          └─────────────┬──────────┘   └──────────┬─────────────────┘
                        │                          │
              ┌─────────▼──────────┐    ┌──────────▼──────────┐  ┌──────────┐
              │ PostgreSQL :5434   │    │ ChromaDB (vector_db)│  │ Ollama   │
              │ nace_oranlari      │    │ tdhp_invoices       │  │ :11434   │
              │ gecmis_fatura_*    │    │ model_eval_sonuclar │  │ (LLM)    │
              └────────────────────┘    └─────────────────────┘  └──────────┘
```

### 2.1 Neden iki farklı bağlanma şekli (HTTP vs import)?

Bu, belgelenmesi gereken en kritik asimetri:

- **`Mcp_mimarisi` → HTTP.** Bağımsız geliştirilen, kendi veritabanı şeması ve
  kendi yaşam döngüsü olan bir servis. Ayrı süreçte çalışır, ayrı deploy
  edilebilir, ayrı ekip dokunabilir.
- **`model_eval` → Python import.** Ağır bir bilimsel bağımlılık yığını
  (ChromaDB, embedding modeli, LLM istemcileri) taşır. Bunu HTTP arkasına
  koymak, her istekte model/koleksiyon yeniden yüklenmesi riskini ve gereksiz
  bir serileştirme katmanı getirirdi. Aynı süreçte import edilerek ChromaDB
  koleksiyonu **process ömrü boyunca cache'lenir**.

Bu asimetri, "alt projeler birbirine kod olarak bağlanmaz" kuralını **ihlal
etmez** — çünkü kural, `Mcp_mimarisi` ile `model_eval`'ın *birbirine*
bağlanmamasını söyler. `entegrasyon/` ikisinden de ayrı, üçüncü bir bileşendir
ve her birine kendi doğasına uygun şekilde bağlanır.

> **Değişmez kısıt:** `entegrasyon/` ve `model_eval/` aynı üst dizinde
> (`System/`) **kardeş kalmalıdır** — `entegrasyon/model_eval_yolu.py` bunu
> varsayarak `sys.path`'e ekleme yapar. Klasörleri ayırmak sistemi bozar.

### 2.2 Paylaşılan PostgreSQL, ayrık tablolar

İki bileşen aynı PostgreSQL sunucusunu (`:5434`) kullanır ama **birbirinin
tablosuna dokunmaz**:

| Tablo | Sahibi | İçerik |
|---|---|---|
| `nace_oranlari` | Mcp_mimarisi | NACE kodu → izin verilen KDV oranları (referans veri) |
| `gecmis_fatura_kalemleri` | Mcp_mimarisi | Geçmişte kesilmiş outbox kalemleri (emsal kontrolü) |
| `model_eval_sonuclar` | model_eval | Tahmin sonuçları + onay kayıtları (denetim izi) |

---

## 3. Ana akış — bir fatura sistemden nasıl geçer?

### 3.1 Yön tespiti: akışı belirleyen ilk karar

Sistem, kullanıcıya "bu fatura bize mi ait?" diye **sormaz** — faturanın kendi
XML'ine bakar (`model_eval/core/parsing.py::parse_invoice_xml_string`):

- `AccountingSupplierParty` VKN'si = bizim VKN → **outbox** (biz kestik)
- `AccountingCustomerParty` VKN'si = bizim VKN → **inbox** (bize geldi)

Bu ayrım kritik, çünkü **ön filtreleme sadece outbox faturalara uygulanır:**

```
outbox (biz kestik):
    XML → [KDV mevzuat ön filtresi] → [TDHP tahmini]
inbox (bize geldi):
    XML → ─────────────────────────→ [TDHP tahmini]
```

**Neden inbox'ta ön filtreleme yok?** Başkasının kestiği faturanın KDV oranını
denetlemek bizim sorumluluğumuz değil — o satıcının mevzuat sorumluluğudur.
Biz sadece kaydı doğru atmakla yükümlüyüz. Ön filtreleme, *kendi*
faturalarımızda hata yapmamak için var.

### 3.2 Aşama 1 — KDV mevzuat ön filtresi (yalnızca outbox)

`POST /fatura/kontrol-et` → `Mcp_mimarisi`

Her fatura kalemi için ayrı ayrı:
1. Satıcının NACE kodları alınır
2. `nace_oranlari` tablosundan o kodların izin verdiği oran havuzu çıkarılır
3. Kalemde beyan edilen oran bu havuzda mı diye bakılır

Kalem başına iki sonuç mümkün
(`Mcp_mimarisi/src/efatura_kdv/kalem_nace_esleme.py`):

- **`uygun`** → doğrudan TDHP tahminine geçilir
- **`insan_incelemesi_gerekli`** → **akış durur**, kullanıcıya gerekçe gösterilir

> Üçüncü bir "hatalı/reddedildi" kararı bilinçli olarak **yoktur.** Sistem
> "bu oran yanlış" demez, "bunu bir insan görmeli" der. Mevzuat yorumu
> gerektiren bir alanda otomatik ret vermek, yanlış pozitiflerde faturayı
> haksızca bloke ederdi.

Kullanıcı uyarıyı görüp yine de devam etmek isterse, isteği `onay=True` ile
tekrar gönderir ve akış TDHP tahminine geçer. **Onay, kararın kullanıcıya
devredildiği yerdir — sistem sessizce geçmez.**

### 3.3 Aşama 2 — TDHP tahmini (LLM + RAG)

`model_eval/core/single.py::predict_single_invoice()` — sistemin en karmaşık
parçası. Sırayla:

1. **Parse** — XML'den başlık, kalemler, vergi kırılımları çıkarılır
2. **RAG geri getirme** — faturanın metinsel temsili embed edilir
   (`embeddinggemma`), ChromaDB'deki `tdhp_invoices` koleksiyonundan en benzer
   *k* geçmiş fatura çekilir (varsayılan `k=3`, aynı VKN'li emsaller tercih
   edilir). Bunlar prompt'a **few-shot örnek** olarak eklenir.
3. **LLM çağrısı** — sistem promptu + TDHP sözlüğü + emsal blok + fatura
   verisi → hesap kodu / yön / tutar üretimi
4. **Self-correction** — üretilen kayıt en güçlü emsalle çelişiyorsa, modele
   düzeltme talebi ile **ikinci bir çağrı** yapılır
   (`rag_common.build_precedent_correction_request`)
5. **Mizan alt kırılımı** — üretilen 3 haneli kodlar (`120`, `600`, `391`),
   şirkete özel `exceller/mizan.xlsx`'ten okunan alt kırılımlarla eşlenir
   (`120` → `120.01.00008`). Bu **tek bir ek LLM çağrısıyla** yapılır.
6. **Denge kontrolü** — borç toplamı = alacak toplamı mı?

Testte gözlemlenen çıktı:

```
DENGELİ: True   (borç 291.70 = alacak 291.70)
  120.01.00008  Borç      291.70
  600.01.00005  Alacak    229.33
  391.01.00020  Alacak     41.57
  600.01.00005  Alacak     20.80
```

**Neden RAG, salt prompt mühendisliği değil?** TDHP kodu seçimi şirkete
özgüdür — aynı tarif başka bir şirkette başka bir alt hesaba gider. Genel bir
kural yazmak mümkün değil; geçmiş kararlar tek güvenilir kaynak. RAG bu
kurumsal hafızayı prompt'a taşır.

**Neden mizan ayrı bir adım?** 3 haneli TDHP kodu evrenseldir (`600` = Yurtiçi
Satışlar, her şirkette aynı). Alt kırılım (`600.01.00005`) tamamen şirkete
özeldir ve mizandan okunur. İkisini tek LLM çağrısında karıştırmak, evrensel
bilgiyi şirket verisiyle bulaştırırdı.

### 3.4 Aşama 3 — Onay ve geri besleme döngüsü

`POST /fatura/onayla` — kullanıcı "bu kayıt doğru" dediğinde **iki yere** yazar
(`entegrasyon/model_eval_koprusu.py::faturayi_onayla`):

1. **PostgreSQL** (`model_eval_sonuclar`) — denetim izi. Aynı fatura tekrar
   onaylanırsa **yeni satır** eklenir (geçmiş silinmez).
2. **ChromaDB** (`tdhp_invoices`) — onaylanan tahmin, gelecekteki benzer
   faturalar için **emsal örneğe dönüşür**. `invoice_id` ile upsert edilir,
   yani tekrar onayda kayıt **güncellenir**, çoğalmaz.

İki farklı davranış (append vs upsert) kasıtlıdır: denetim izi tarihsel
olmalı, emsal havuzu ise güncel olmalı.

Bu, sistemin **öğrenen** kısmıdır:

```
   tahmin ──▶ kullanıcı onayı ──▶ emsal havuzuna ekleme
      ▲                                    │
      └────────── sonraki faturada ────────┘
                  few-shot örnek olarak geri gelir
```

> Bu döngü, `build_vector_db.py`'nin "yalnızca `Archive2/jsons` ground-truth'unu
> indeksle" kuralını bilinçli olarak **genişletir** — kullanıcı onayı da bir tür
> ground-truth sayılır.

---

## 4. Dış bağımlılıklar

| Bağımlılık | Ne için | Erişilemezse |
|---|---|---|
| **PostgreSQL** (`:5434`, Docker) | NACE oran tablosu, geçmiş kalemler, sonuç kaydı | Ön filtreleme çalışmaz |
| **Ollama** (`:11434`) | Hem LLM çıkarımı hem RAG embedding'i | TDHP tahmini çalışmaz |
| **ChromaDB** (`model_eval/vector_db/`, gömülü) | Emsal fatura vektör indeksi | RAG'sız tahmine düşer |

`baslat.sh` üçünü de kontrol eder; PostgreSQL ve Ollama'yı gerekirse başlatır.
`durdur.sh` ise Ollama ve PostgreSQL'i **bilerek durdurmaz** — başka süreçler
de kullanıyor olabilir.

### 4.1 İzole venv kararı

`baslat.sh`, `Mcp_mimarisi` için `.calistirma/mcp_venv` altında **kendi izole
venv'ini** kurar ve `Mcp_mimarisi/` klasörüne hiç dokunmaz. Sebep: sistem
`python3`'ü PATH'e bağlı olarak başka bir alt projenin venv'ine
düşebiliyordu; bu, `fastapi`/`psycopg2` bulunamama hatalarına yol açtı.

---

## 5. Mimari kararların özeti

| Karar | Gerekçe |
|---|---|
| KDV kontrolü kural tabanlı, LLM'e sorulmaz | Mevzuat uygunluğu deterministiktir; LLM belirsizliği burada kabul edilemez |
| Ön filtre yalnızca outbox'a | Başkasının kestiği faturanın mevzuat sorumluluğu bizde değil |
| "Reddedildi" kararı yok, "insan incelemesi" var | Yanlış pozitifte faturayı haksızca bloke etmemek için |
| `Mcp_mimarisi` HTTP, `model_eval` import | Biri bağımsız servis; diğeri ağır bağımlılık yığını taşıyan kütüphane |
| Ortak DB, ayrık tablolar | Tek altyapı maliyeti, ama sahiplik sınırı net |
| TDHP kodu ve mizan alt kırılımı ayrı LLM adımları | Evrensel bilgiyi şirkete özel veriyle karıştırmamak için |
| Onay → RAG'a geri yazma | Kurumsal hafıza büyüsün; sistem kullanıldıkça iyileşsin |
| Denetim izi append, emsal havuzu upsert | Geçmiş tarihsel kalmalı, emsal güncel olmalı |

---

## 6. Bu belgenin kapsamı dışında kalanlar

- **`preprocessing/`** — KDV sistemiyle ilgisiz ayrı alt proje (ham HTML →
  LLM eğitim corpus'u). Bu mimariye dahil değildir.
- **`arsiv/`** — çalışan sistemin kullanmadığı eski dosyalar.
- **Mevzuat MCP katmanı (Faz 2)** — `Mcp_mimarisi/docs/explanation/mevzuat-mcp-mimarisi.md`'de
  tasarlanmış, henüz kodda değil.

> ⚠️ Bu belge, bileşenlerden biri mimari karar değiştirdiğinde en hızlı
> bayatlayan belgedir (özellikle §3). Kodla çelişen bir cümle görürsen
> düzelt, ayrı onay bekleme (bkz. kök `CLAUDE.md`).
