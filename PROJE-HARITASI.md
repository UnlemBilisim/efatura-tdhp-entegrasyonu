# Proje Haritası — Bu Dosya Ne İşe Yarar?

> **Bu belge, projeye yeni bakan biri için giriş noktasıdır.** Sistemin ne
> yaptığını, bileşenlerin nasıl bir araya geldiğini ve her dosyanın işlevini
> özetler. Derinlemesine mimari gerekçe için [`mimari.md`](mimari.md)'ye,
> API kullanımı için [`teslim/API-ENTEGRASYON-KILAVUZU.md`](teslim/API-ENTEGRASYON-KILAVUZU.md)'ye bakın.

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
Detaylı gerekçe: [`mimari.md`](mimari.md) §1.

## 2. Üç bileşen, üç farklı rol

```
                    ┌──────────────────────────────────┐
                    │ Dış ekip / test arayüzü           │
                    └────────────────┬─────────────────┘
                                     │ HTTP
                    ┌────────────────▼─────────────────┐
                    │   entegrasyon/  (port 8100)      │
                    │   ORKESTRASYON — karar vermez,   │
                    │   sadece sırayı yönetir          │
                    └───┬─────────────────────────┬────┘
                        │ HTTP                    │ Python import
          ┌─────────────▼──────────┐   ┌──────────▼─────────────────┐
          │ Mcp_mimarisi (:8000)   │   │ model_eval  (kütüphane)    │
          │ KDV mevzuat ön filtresi│   │ TDHP tahmini (LLM + RAG)   │
          └─────────────┬──────────┘   └──────────┬─────────────────┘
                        │                          │
              ┌─────────▼──────────┐    ┌──────────▼──────────┐  ┌──────────┐
              │ PostgreSQL :5434   │    │ ChromaDB (vector_db)│  │ Ollama   │
              │ nace_oranlari      │    │                     │  │ :11434   │
              │ gecmis_fatura_*    │    │ model_eval_sonuclar │  │ (RAG+LLM)│
              └────────────────────┘    └─────────────────────┘  └──────────┘
```

| Bileşen | Rol | Nasıl çalıştırılır |
|---|---|---|
| **`Mcp_mimarisi/`** | KDV/NACE ön filtreleme — bağımsız FastAPI servisi, HTTP ile çağrılır | `uvicorn efatura_kdv.api:app --port 8000` |
| **`entegrasyon/`** | Orkestrasyon + dış API — hangi sırayla hangi bileşen çağrılacağına karar verir, kendi karar üretmez | `uvicorn app:app --port 8100` |
| **`model_eval/`** | TDHP tahmini (LLM + RAG) — ağır bağımlılık yığını taşıdığı için servis değil, `entegrasyon/` tarafından Python import ile çağrılan bir kütüphane | Doğrudan çalıştırılmaz, `entegrasyon/model_eval_koprusu.py` üzerinden kullanılır |

**Neden `Mcp_mimarisi` HTTP, `model_eval` import ile çağrılıyor?** Bu bilinçli
bir asimetri — detaylı gerekçe [`mimari.md`](mimari.md) §2.1'de.

## 3. Dosya haritası

### 3.1 Kök dizin

| Dosya | Ne işe yarar |
|---|---|
| `mimari.md` | Sistem mimarisi — bileşenler, akış, tasarım kararlarının gerekçesi (explanation) |
| `proje-calistirma.md` | Yerel (Docker'sız) çalıştırma kılavuzu, sık karşılaşılan sorunlar (how-to) |
| `CLAUDE.md` | AI ajanları (Claude Code vb.) için çalışma disiplini rehberi |
| `baslat.sh` / `durdur.sh` | Tüm sistemi (PostgreSQL + Mcp_mimarisi + entegrasyon) tek komutla başlatır/durdurur |
| `Dockerfile` | Tek image'da üç Python bileşeni (kardeş dizin yapısını korur) |
| `docker-compose.yml` | PostgreSQL + Ollama + app servislerini birlikte ayağa kaldırır |
| `docs/` | Üç bileşenin **birlikte** çalışmasına ait belgeler (Diátaxis: how-to/reference/explanation) |
| `teslim/API-ENTEGRASYON-KILAVUZU.md` | **Dış ekibin okuması gereken tek belge** — `POST /fatura/isle` nasıl çağrılır |

### 3.2 `Mcp_mimarisi/` — KDV/NACE ön filtreleme

| Dosya | Ne yapar |
|---|---|
| `src/efatura_kdv/api.py` | FastAPI HTTP API — UBL-TR XML'i alıp NACE+KDV kuralına göre `uygun`/`insan_incelemesi_gerekli` döner |
| `src/efatura_kdv/nace_kural_kontrolu.py` | `nace_oranlari` PostgreSQL tablosunu belleğe yükleyip bir NACE kodu için izinli oranı kontrol eder |
| `src/efatura_kdv/kalem_nace_esleme.py` | Satıcının tüm NACE kodlarının izin verdiği oranları tek havuzda birleştirip her fatura satırını bu havuzla karşılaştırır; GİB istisna kodlarını tanır |
| `src/efatura_kdv/gecmis_kontrol.py` | Geçmişte aynı satıcı+kalemin hangi oranla kesildiğini gösterir — ek bilgi sinyali, karar üretmez |
| `src/efatura_kdv/ubl_parser.py` | UBL-TR XML'ini taraf/kalem/vergi veri sınıflarına ayrıştırır |
| `scripts/excel_to_postgres.py` | NACE-KDV referans Excel'ini `nace_oranlari` tablosuna yükler (idempotent, elle çalıştırılır) |
| `scripts/gecmis_faturalari_yukle.py` | Geçmiş outbox faturalarını `gecmis_fatura_kalemleri` tablosuna yükler (bir kerelik, elle çalıştırılır) |
| `alembic/` | PostgreSQL şema migrasyonları |
| `exceller/` | NACE-KDV ve istisna kodu referans tabloları (Excel) |

### 3.3 `entegrasyon/` — orkestrasyon + dış API

| Dosya | Ne yapar |
|---|---|
| `app.py` | Ana FastAPI servisi — faturanın yönünü (inbox/outbox) tespit edip Mcp_mimarisi ve model_eval'ı doğru sırayla çağırır |
| `yon_tespiti.py` | Faturanın inbox mu outbox mu olduğunu (kendi VKN'niz satıcı/alıcı tarafında mı) tespit eder |
| `mcp_mimarisi_istemcisi.py` | Mcp_mimarisi'nin HTTP uçlarına istek atan istemci |
| `model_eval_koprusu.py` | model_eval'ın kodunu import edip TDHP tahmini işlevini entegrasyon katmanına açan köprü |
| `model_eval_yolu.py` | model_eval'i kardeş dizin olarak `sys.path`'e ekleyen ortak yardımcı |
| `v2_api.py` / `v2_semalar.py` | Asenkron (job_id tabanlı) v2 API ve dış şema dönüştürücüleri — v1'i bozmadan ayrı router |
| `is_deposu.py` | v2 API için PostgreSQL tabanlı kalıcı iş (job) deposu |
| `static/index.html` | Kendi test arayüzümüz — **teslim kapsamında değil**, dış ekip referans almamalı |

### 3.4 `model_eval/` — TDHP tahmini (LLM + RAG)

| Dosya | Ne yapar |
|---|---|
| `core/single.py` | Tek bir fatura için senkron TDHP tahmini üreten ana fonksiyon (`predict_single_invoice`) — entegrasyon katmanının çağırdığı asıl işlev |
| `core/parsing.py` | Fatura ayrıştırma (JSON ground-truth + ham UBL XML) |
| `core/prompting.py` | LLM'e gönderilecek prompt'u ve deterministik ipuçlarını inşa eder |
| `core/providers.py` | Çoklu LLM sağlayıcı (Ollama/OpenAI/Anthropic/Google) dispatch katmanı |
| `core/mizan.py` | Şirkete özel mizan Excel'inden TDHP alt kırılımlarını çıkarır |
| `core/disa_aktarim.py` | İç şemayı (`entries[]`, Borç/Alacak) dış ekip şemasına (`records[]`) çevirir |
| `core/db.py` | PostgreSQL bağlantı havuzu ve `model_eval_sonuclar` şeması |
| `core/reporting.py` / `core/scoring.py` / `core/runner.py` / `core/cli.py` | Model değerlendirme/karşılaştırma altyapısı — **üretim akışının parçası değil**, geliştirme sırasında farklı LLM'leri kıyaslamak için |
| `rag_common.py` | ChromaDB tabanlı emsal fatura arama ortak mantığı |
| `build_vector_db.py` | Geçmiş faturaları ChromaDB'ye indeksler (RAG'ın ön koşulu) |
| `evaluate_models.py` / `generate_report.py` | Model karşılaştırma testleri için CLI araçları — üretimde kullanılmaz |

## 4. Nereden başlamalı?

- **Sadece API'yi çağıracaksanız:** [`teslim/API-ENTEGRASYON-KILAVUZU.md`](teslim/API-ENTEGRASYON-KILAVUZU.md) yeterli, koda bakmanıza gerek yok.
- **Sistemi çalıştıracaksanız:** [`proje-calistirma.md`](proje-calistirma.md) (yerel) veya [`docs/how-to/docker-ile-calistirma.md`](docs/how-to/docker-ile-calistirma.md) (Docker).
- **Mimariyi/tasarım kararlarını anlayacaksanız:** [`mimari.md`](mimari.md).
- **Koda katkı verecekseniz:** Her bileşenin kendi `CLAUDE.md`'si daha ayrıntılıdır — [`Mcp_mimarisi/CLAUDE.md`](Mcp_mimarisi/CLAUDE.md), [`model_eval/CLAUDE.md`](model_eval/CLAUDE.md).
