# AıData2 — Çalışma Alanı Haritası

> **Amaç:** Bu belge, `AıData2/` çalışma alanındaki bağımsız alt projelerin
> her birinin ne işe yaradığını ve aralarındaki (varsa) ilişkiyi tek yerden
> özetler. Her alt projenin kendi teknik detayı, mimari kararları ve faz
> planı kendi `PROJECT.md`/`CLAUDE.md` dosyasındadır — bu belge onları
> **tekrar etmez**, sadece haritayı çizer.
>
> Sistemin nasıl çalıştığının ve hangi teknolojilerin neden seçildiğinin
> derinlemesine anlatımı için: [`MIMARI.md`](MIMARI.md).

---

## 0. Hızlı Bağlam (TL;DR)

- **Ne:** Bu klasör tek bir proje değil, ortak bir veri kümesi (aynı gerçek
  şirketin — Akyüzlü Dövme ve Kaldırma Ekipmanları San., VKN `0460351893` —
  e-faturaları) üzerinde çalışan **3 bağımsız kod tabanı + 1 orkestrasyon
  katmanı** + o veriyi besleyen ham veri klasörleri barındırır.
- **Üç aktif alt proje + entegrasyon katmanı:**
  1. **`model_eval/`** — e-faturayı Türkiye Tek Düzen Hesap Planı'na (TDHP)
     otomatik aktaran, RAG + çoklu-LLM karşılaştırmalı bir tahmin/değerlendirme
     pipeline'ı. "Var olan sistem" — dokunulması değil, önüne katman
     eklenmesi hedeflenen taraf.
  2. **`Mcp_mimarisi/`** — `model_eval`'ın **önüne** eklenen, bağımsız
     geliştirilen bir KDV/vergi oranı mevzuat doğrulama (ön filtreleme)
     katmanı (NACE kodu + beyan edilen oran kontrolü, FastAPI + PostgreSQL).
  3. **`preprocessing/`** — KDV doğrulama sistemiyle **doğrudan ilgisiz**,
     ayrı bir alt proje: `Archive/`'daki ham HTML muhasebe/vergi içeriğini
     LLM domain-adaptation için temiz bir JSONL corpus'a çeviren pipeline.
  4. **`entegrasyon/`** — `Mcp_mimarisi` (HTTP) ve `model_eval` (import)
     ile ayrı ayrı bağlanan, üçüncü bağımsız bir orkestrasyon servisi +
     test arayüzü. Akış: fatura önce Mcp_mimarisi'nde ön filtrelenir;
     `uygun` ise (ya da `insan_incelemesi_gerekli` + kullanıcı onayı varsa)
     model_eval'a TDHP tahmini için gönderilir.
- **Durum (2026-07-27):** Zincirin tamamı çalışıyor. `entegrasyon/` servisi +
  test arayüzü ayakta, Mcp_mimarisi bağlantısı gerçek HTTP ile çalışıyor ve
  model_eval tarafındaki tek-fatura senkron tahmin fonksiyonu
  (`core/single.py::predict_single_invoice`) **yazıldı ve uçtan uca
  doğrulandı** — gerçek bir UBL faturası `POST /fatura/isle` ile işlendi,
  ön filtreleme + TDHP tahmini çalıştı, kayıt dengeli döndü.
  `preprocessing` kendi başına tamamlanmış durumda (bkz. kendi `PROJECT.md`'si).

  > ✅ **Uygulandı** (2026-07-27): Bu bölüm 2026-07-22 tarihli "henüz
  > yazılmadı" ifadesini taşıyordu; `core/single.py::predict_single_invoice`
  > o tarihten sonra eklendiği için bayatlamıştı. Sistemin nasıl/neden böyle
  > kurulduğunun anlatımı için: [`MIMARI.md`](MIMARI.md).
- **Kritik kural:** `model_eval`, `Mcp_mimarisi`, `preprocessing` birbirine
  kod olarak bağlı değildir. `entegrasyon/` bu üçünden ayrı, dördüncü bir
  bileşendir — Mcp_mimarisi'ye sadece HTTP ile, model_eval'a ise doğrudan
  Python import ile bağlanır (bkz. `entegrasyon/README.md` — bu, model_eval
  ↔ Mcp_mimarisi arasındaki "HTTP üzerinden ayrık" kuralını ihlal etmez,
  çünkü o kural iki alt projenin birbirine değil, entegrasyon katmanının
  onlara bağlanma şeklini tanımlar).

---

## 1. Alt Projeler

| Alt proje | Ne yapar | Durum | Kendi belgesi |
|---|---|---|---|
| `model_eval/` | UBL-TR fatura → TDHP hesap kodu + Borç/Alacak yönü tahmini (RAG + çoklu-LLM karşılaştırma) | Deneysel bulgular olgun, PostgreSQL'e geçti (2026-07-22) | [`model_eval/PROJECT.md`](model_eval/PROJECT.md), [`model_eval/CLAUDE.md`](model_eval/CLAUDE.md) |
| `Mcp_mimarisi/` | Fatura KDV oranının NACE koduna göre mevzuata uygunluğunu doğrulama (Faz 1: kural tabanlı; Faz 2: mevzuat MCP) | Faz 1 kodda tamamlandı, HTTP API + PostgreSQL ile çalışıyor | [`Mcp_mimarisi/PROJECT.md`](Mcp_mimarisi/PROJECT.md), [`Mcp_mimarisi/CLAUDE.md`](Mcp_mimarisi/CLAUDE.md) |
| `preprocessing/` | `Archive/`'daki ~17.000 HTML sayfasını LLM eğitim corpus'una (JSONL) çevirme | Tamamlandı, tam veri setinde çalıştırıldı (2026-07-14) | [`preprocessing/PROJECT.md`](preprocessing/PROJECT.md), [`preprocessing/CLAUDE.md`](preprocessing/CLAUDE.md) |
| `entegrasyon/` | Mcp_mimarisi (ön filtre) → model_eval (TDHP tahmini) orkestrasyonu + test arayüzü | Ön filtre bağlantısı çalışıyor; model_eval tarafı `predict_single_invoice` eklenene kadar eksik | [`entegrasyon/README.md`](entegrasyon/README.md) |

### 1.1 model_eval ↔ Mcp_mimarisi ↔ entegrasyon ilişkisi

```
[Ham UBL-TR XML]
      │
      ▼
entegrasyon/ → Mcp_mimarisi POST /fatura/kontrol-et   (KDV oranı mevzuat ön filtresi)
      │
      ├── "uygun" ────────────────────────────────────────┐
      │                                                     ▼
      ├── "insan_incelemesi_gerekli" + kullanıcı ONAYI ──▶ entegrasyon/ → model_eval:
      │                                                     predict_single_invoice()
      │                                                     (parse → RAG → LLM → TDHP kodu+yön+tutar)
      └── "insan_incelemesi_gerekli" + onay YOK ──▶ durur, insan incelemesi kuyruğu
```

`model_eval` ve `Mcp_mimarisi` kendi aralarında **kod olarak birleştirilmez**
— sadece `entegrasyon/` üzerinden, o da Mcp_mimarisi'ye HTTP, model_eval'a
Python import ile bağlanarak konuşurlar (bkz. `entegrasyon/README.md`).
Orijinal HTTP-sözleşmesi tasarımı (`model_eval/ENTEGRASYON.md`) hâlâ
Mcp_mimarisi tarafının şemasını tanımlar; gerçek orkestrasyon kodu
`entegrasyon/`'da yaşar. Mcp_mimarisi ve model_eval ayrıca aynı PostgreSQL
sunucusunu paylaşırlar ama farklı tablo önekleriyle (`model_eval_*` vs
`nace_oranlari`/`gecmis_fatura_kalemleri`) — birbirinin tablosuna dokunmazlar.

### 1.2 preprocessing'in konumu

`preprocessing/`, `model_eval`/`Mcp_mimarisi` ile aynı workspace'te durur
ama aralarında **hiçbir bağımlılık yoktur** — farklı bir hedefe (LLM'e genel
muhasebe/vergi bilgisi kazandırmak, continued pretraining) hizmet eder.
Kendi `PROJECT.md`'sinde de bu ayrım açıkça belirtilmiştir.

---

## 2. Ortak Veri Klasörleri

| Klasör | İçerik | Kullanan |
|---|---|---|
| `System/Archive2/jsons/` | 1646 ground-truth fatura (muhasebe kaydı içerir) | `model_eval/` — **RAG vektör indeksinin kaynağı** |
| `System/Archive2/` (diğer) | `markdowns/`, `toons/`, `nace kodları/`, mizan/yevmiye Excel'leri | `model_eval/`, kısmen `Mcp_mimarisi/` |
| `System/Mcp_mimarisi/ubls/` | 1829 gerçek fatura XML'i (inbox/outbox) | `Mcp_mimarisi/` (parser testi + geçmiş kontrol katmanı) |
| `System/model_eval/vector_db/` | ChromaDB kalıcı indeksi (`tdhp_invoices` koleksiyonu) | `model_eval/` (RAG geri getirme) |
| `System/model_eval/exceller/mizan.xlsx` | Şirkete özel TDHP alt kırılımları | `model_eval/core/mizan.py` |
| `System/Mcp_mimarisi/exceller/` | `nace_kdv (1).xlsx` (oran referansı), `Istisna_Kodlari_GIB.xlsx` | `Mcp_mimarisi/scripts/excel_to_postgres.py` |
| `docs/` (kök) | `model_eval`/RAG özelliğinin Diátaxis dokümantasyonu | `model_eval/` |
| `arsiv/` | Çalışan sistemin kullanmadığı eski dosyalar (eski MIMARI.md, TDHP metin listesi, test örnekleri) | Aktif kullanım yok |
| `sunucu-yönlendirme.md` | Uzak GPU sunucusunda (unlem-gx10-01) fine-tuning, SSH port forwarding notları | `model_eval/` |

> ✅ **Uygulandı** (2026-07-27): Tablo, temizlik sonrası gerçek duruma
> güncellendi. Artık var olmayan girdiler kaldırıldı: kök `Archive/`,
> `Archive2/ubls/` (`Mcp_mimarisi/ubls/` kopyasıydı), `zipler/`, kök
> `*.xml` + timestamp klasörleri ve `çalıştırma.txt` (→ `arsiv/`),
> `tekdüzenhesapkoları.txt` (→ `arsiv/eski-dokuman/`). Ayrıca yollar
> `System/` taşımasını yansıtacak şekilde düzeltildi. Bkz. [`OKU-YAPI.md`](OKU-YAPI.md).

---

## 3. Sistemi Çalıştırma

Tek komutla: `./baslat.sh` (durdurmak için `./durdur.sh`). Üç servisin
(PostgreSQL, Mcp_mimarisi API, entegrasyon servisi) neden/nasıl ayağa
kalktığı, manuel adımlar ve sık karşılaşılan sorunlar:
[`PROJE_CALISTIRMA.md`](PROJE_CALISTIRMA.md).

## 4. Çalışma Kuralları

Genel, alan-bağımsız çalışma disiplini (docs güncelleme, hafıza kullanımı,
varsayım yapmama, güvenlik onayı) kök [`CLAUDE.md`](CLAUDE.md)'de tanımlıdır
ve tüm alt projeleri kapsar. Her alt projenin kendi `CLAUDE.md`'si, bu genel
kurala ek olarak **kendine özgü** bilgiyi (kritik gerçekler, değişmez
kurallar, dış bağımlılıklar) içerir — genel kuralı tekrar etmez.

> ⚠️ Bu bölüm, üç alt projeden biri yeni bir mimari karar aldığında en hızlı
> bayatlayan bölümdür (özellikle §1.1). Kodla/alt proje belgeleriyle
> çelişen bir cümle görürsen düzelt, ayrı onay bekleme.
