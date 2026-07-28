# TDHP Hesap Kodu Tahmin/Değerlendirme Pipeline'ı — Proje Belgesi

> **Amaç:** Gerçek e-faturaları alıp, birden fazla LLM sağlayıcısının Türkiye
> Tek Düzen Hesap Planı'na (TDHP) göre doğru 3 haneli hesap kodu + Borç/
> Alacak yönünü **kendi bilgisiyle** üretip üretemediğini ölçmek; ayrıca ham/
> henüz muhasebeleşmemiş faturalar için gerçek TDHP tahmini üretmek.

Bu belge projenin teknik kapsamını, mimari kararlarını ve gerçek altyapı
değerlerini içerir. Günlük çalışma kuralları için ayrıca [`CLAUDE.md`](CLAUDE.md).

---

## 0. Hızlı Bağlam (TL;DR)

- **Ne:** Çoklu-model karşılaştırma + TDHP tahmin pipeline'ı. İki mod:
  (1) `--data-format json` (varsayılan) — Archive2/jsons'daki ground-truth'lu
  gerçek faturalarla doğruluk ölçer; (2) `--data-format xml` — ham UBL-TR
  XML'lerle (ground-truth yok) gerçek tahmin üretir.
- **Ölçek (bugün):** Araştırma/deney aşamasında, CLI/batch aracı olarak
  çalışıyor. Sonuç deposu PostgreSQL'e taşındı (2026-07-22) çünkü gelecekte
  bir HTTP servisinin (Mcp_mimarisi'nin Adım 0'ından sonraki adımlar,
  bkz. `ENTEGRASYON.md`) parçası olması planlanıyor — henüz o servis kodu
  yazılmadı.
- **Durum:** Deneysel bulgular olgun (RAG/self-correct/hint'ler test edildi,
  bkz. §2), mimari sağlamlık denetimi tamamlandı (§3).

---

## 1. Veri ve Girdi

- **Ground-truth'lu veri:** `../Archive2/jsons/` — muhasebeleşmiş gerçek
  faturalar, `accounting_entries` alanı ground-truth'tur (1646 dosya).
- **Ham/yeni fatura verisi:** `--data-format xml` ile ayrı bir UBL-TR XML
  klasörü okunur (ground-truth yok, `yeni_faturalar_tdhp.md`/
  `yeni_faturalar_tdhp_30.md` bu modun çıktı örnekleridir).
- **Şirketin kendi VKN'si:** `DEFAULT_OWN_VKN = "0460351893"`
  (`core/constants.py`) — Akyüzlü Dövme ve Kaldırma Ekipmanları San.
  XML modunda inbox/outbox yönünü ve karşı tarafı bu VKN'ye göre tespit eder.
- **RAG kaynağı:** Aynı şirketin geçmiş faturaları, `build_vector_db.py` ile
  ChromaDB'ye (`vector_db/`, koleksiyon `tdhp_invoices`) indekslenir.

## 2. Deneysel Bulgular (özet — tam detay `RESULTS.md`/`RAG_MODEL_COMPARISON.md`/`GLM52_vs_GEMMA4_n500.md`)

| Deney | Sonuç |
|---|---|
| Referanssız model karşılaştırması | `gemma4:31b-cloud` en iyi (pair_F1≈0.835) |
| `--with-glossary` (tam TDHP kod listesi verildi) | 4/6 modelde işe yaramadı/kötüleşti — sorun bilgi değil, seçim |
| `--rag` (geçmiş faturalardan few-shot) | 0.835→0.935 (n=100) — en büyük tekil iyileştirme |
| `--rag --self-correct` (precedent-mismatch) | 0.961 (n=100) |
| Tüm iyileştirmeler birlikte (n=500) | 0.817→0.956, exact_pair 54.3%→85.6% |
| `--tevkifat-hint` tek başına | balanced% 9.5→95.1 (tevkifatlı faturalarda) |
| `--iade-hint` + direction düzeltmesi | IADE doğruluğu %0→%70 (n=20) |
| Context uzunluğu duyarlılığı | `gemma4` kötüleşiyor, `glm-5.2` iyileşiyor (0.624→0.814) — model bazında zıt yönlü |
| inbox vs outbox hata oranı | inbox %16.2 hatalı, outbox %7.8 — 2 kattan fazla fark |

**Gerekçe (self-correct'in iki farklı tetikleyicisi):** `core/runner.py`
`process()` içinde iki bağımsız neden var — (1) `balance`: Borç≠Alacak
tespit edilirse (matematiksel), (2) `precedent_mismatch`: RAG'ın gösterdiği
GÜÇLÜ bir emsalden (aynı tedarikçi, çok yüksek benzerlik) farklı ama dengeli
bir kod üretilmişse. İkisi aynı anda geçerliyse `balance` önceliklidir
(RAG önerisi matematiksel olarak geçersiz bir cevaba anlamsızdır).

## 3. Mimari Denetim ve PostgreSQL Geçişi (2026-07-22)

`model_eval` ve `Mcp_mimarisi` birlikte "çok kullanıcılı MVP'ye çıkmadan önce
mimari sağlamlık" denetiminden geçirildi. Bulunan ve düzeltilen riskler:

1. **Dosya bazlı sonuç deposu → PostgreSQL.** Eski `result_path_for_model()`
   (artık yok) dosya adını sadece model+bayrak etiketinden türetiyordu,
   `threading.Lock` koruması tek process'e özgüydü — çok process/worker'lı
   bir HTTP servisinde çakışma riski taşıyordu. Yeni: `core/db.py`
   (`ThreadedConnectionPool`, process ömrü boyunca tek pool) +
   `core/reporting.py` (`append_result`/`load_done_ids`/`delete_results`/
   `summarize_model`, hepsi `model_eval_sonuclar` tablosu üzerinden).
2. **ChromaDB `PersistentClient` tekilleştirmesi.** `rag_common.
   get_collection()` artık `(persist_dir, embed_model, ollama_host)`
   anahtarına göre process ömrü boyunca tek bir client/collection
   döndürüyor — "Could not connect to tenant" hatasının kök nedeni
   giderildi.

Detaylı gerekçe, doğrulama adımları ve kapsam dışı bırakılanlar:
[`docs/mimari-denetim-2026-07-22.md`](docs/mimari-denetim-2026-07-22.md).

### 3.1 PostgreSQL şeması

```sql
CREATE TABLE model_eval_sonuclar (
    id             BIGSERIAL PRIMARY KEY,
    file_label     TEXT NOT NULL,   -- result_label() cikisi (model+deney kolu etiketi)
    invoice_id     TEXT NOT NULL,
    record         JSONB NOT NULL,  -- eski jsonl satirinin karsiligi (ayni alan adlari)
    is_error       BOOLEAN NOT NULL DEFAULT FALSE,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_model_eval_sonuclar_label_invoice
    ON model_eval_sonuclar (file_label, invoice_id);
```

- Aynı `(file_label, invoice_id)` için birden fazla satır olabilir (önce
  hata, sonra retry ile başarı) — `load_done_ids`/`summarize_model`
  `DISTINCT ON (invoice_id) ... ORDER BY invoice_id, id DESC` ile her zaman
  **en son** kaydı esas alır (bkz. `core/reporting.py` `_latest_records`).
- Tablo adı `model_eval_` önekini taşır çünkü **Mcp_mimarisi ile aynı
  Postgres sunucusu** paylaşılıyor (bkz. `ENTEGRASYON.md`) — isim alanı
  çakışması olmasın diye. `gecmis_fatura_kalemleri`/`islenmis_faturalar`
  (Mcp_mimarisi'nin tabloları) buradan hiç dokunulmaz.

### 3.2 Test izolasyonu

Testler (`tests/test_reporting.py`, `tests/test_runner.py`) gerçek bir
PostgreSQL'e karşı çalışır — mock kullanılmaz (üst dizin CLAUDE.md kuralı:
"muhtemelen çalışır" değil, gerçekten test et). `TEST_DATABASE_URL` env
var'ı (varsayılan `postgresql://efatura:efatura@localhost:5434/model_eval_test`)
tanımlı değilse veya bağlanılamıyorsa bu testler `requires_postgres` marker'ı
ile otomatik `skip` edilir (`tests/conftest.py`). `db_conn` fixture'ı her
testten önce `model_eval_sonuclar`'ı `TRUNCATE` eder ve `core.db` singleton
pool'unu sıfırlar — testler birbirinden ve gerçek prod DB'sinden izole kalır.

## 4. Mcp_mimarisi ile İlişki

Ayrı bir proje (`~/Desktop/AıData2/Mcp_mimarisi/`) — kod olarak birleştirilmez
(import edilmez, aynı süreçte çalışmaz), sadece HTTP üzerinden konuşur. Tam
sözleşme: [`ENTEGRASYON.md`](ENTEGRASYON.md). Özet: ham XML işlenmeden önce
"Adım 0" olarak `POST /fatura/kontrol-et` (satıcı VKN + NACE kodları + fatura
XML) çağrılır; `genel_karar="uygun"` ise bu pipeline'ın Adım 1-4'ü
(parse→RAG→LLM→borç=alacak doğrulaması) çalışır, `"insan_incelemesi_gerekli"`
ise hiç çalışmaz. PostgreSQL paylaşımı zaten uygulandı (§3).

Asıl HTTP orkestrasyon kodu (Adım 0 çağrısı, "uygun" kararına göre
dallanma) bu pipeline'da DEĞİL — AıData2 kökündeki ayrı, bağımsız bir
`entegrasyon/` klasöründe yaşayacak (başka bir agent'ın sorumluluğunda).
Bu pipeline'ın (`model_eval/`) sağladığı tek şey, o klasörün import edeceği
tek-fatura tahmin fonksiyonu (§4.1).

### 4.1 `core/single.py::predict_single_invoice()` — dış katmanların import edeceği sözleşme

> ✅ **Uygulandı (2026-07-22):** `entegrasyon/` klasörünün ihtiyaç duyduğu,
> tek bir faturayı (henüz diske yazılmamış ham UBL-TR XML string) senkron
> olarak TDHP tahminine sokup sonucu döndüren fonksiyon eklendi.

**İmza:**

```python
def predict_single_invoice(
    invoice_xml: str,                       # ham UBL-TR XML metni (dosya degil, string)
    model=DEFAULT_MODEL_SPEC_STR,           # "ollama:gemma4:31b-cloud" ya da parse_model_spec() ciktisi
    ollama_host=None,
    sector=DEFAULT_SECTOR,
    own_vkn=DEFAULT_OWN_VKN,
    rag=True, self_correct=True, tevkifat_hint=True, iade_hint=True,  # RESULTS.md'deki en iyi kombinasyon
    with_glossary=False,
    rag_k=3, rag_collection=None, rag_persist_dir=None, rag_embed_model=None, rag_ollama_host=None,
    temperature=0.0, timeout=180.0,
) -> dict
```

**Dönüş sözlüğü:**

```python
{
    "invoice_id": str, "direction": "inbox" | "outbox",
    "entries": [{"account_code": "150", "dc": "Borc", "amount": 1234.56}, ...],  # amount KORUNUR
    "balanced": bool, "borc_toplam": float, "alacak_toplam": float,
    "self_corrected": bool, "self_correct_reason": "balance" | "precedent_mismatch" | None,
    "raw_response": str | None, "error": str | None,
}
```

**Kesin gereksinimler (bozulmaması gereken):**
- **`amount` kaybolmaz.** `core/scoring.py::score_entries()`'in aksine
  (o sadece `(code3, dc)` çiftini tutar, tutarı `balance` toplamına
  ekleyip atar) — `predict_single_invoice()` her kalemin `amount`'unu
  korur, çünkü entegrasyon katmanı "hangi hesaba ne kadar yazılacağını"
  bilmek zorunda. Regresyon testi: `tests/test_single.py::
  test_amount_field_is_present_and_correct_per_entry`.
- **DB'ye hiçbir şey yazmaz.** `core/reporting.py`/`core/db.py`'ye hiç
  dokunmaz — `append_result`/`get_conn` çağrılmaz. Çağıran taraf sonucu
  kendi tercih ettiği şekilde saklar. Regresyon testi:
  `test_single.py::test_no_db_write_happens`.
- **`run_model()`'ı bozmaz.** Aynı alt modülleri (providers/prompting/
  scoring/rag_common) tekrar kullanır ama orkestrasyonu kendi içinde
  tekrarlar — `core/runner.py`'den ortak bir yardımcı çıkarılmadı (mevcut
  test edilmiş davranışı bozma riski bilinçli olarak alınmadı).
- **XML string parse:** `core/parsing.py::parse_invoice_xml_string()`
  eklendi (yeni), `parse_invoice_xml()` (dosya yolu alan orijinal
  fonksiyon) DEĞİŞMEDİ — ikisi ortak bir iç fonksiyonu
  (`_parse_invoice_xml_tree`) paylaşır, `xml.etree.ElementTree.parse()`
  dosya yolu VEYA file-like nesne (`io.StringIO`) kabul ettiği için geçici
  dosyaya yazmaya gerek kalmadı.

> ✅ **Düzeltildi (2026-07-22, aynı gün):** `ollama_host=None` (varsayılan,
> hiç verilmediğinde) artık `DEFAULT_OLLAMA_HOST`'a düşüyor. Önceden
> doğrudan `parse_model_spec(model, ollama_host)`'a `None` olarak
> geçiyordu — bu `spec["base_url"] = None` üretip `call_ollama_messages()`
> içinde `host.rstrip("/")` çağrısında `AttributeError` ile 500 hatasına
> yol açıyordu. Bu, `core/cli.py`'nin davranışıyla (orada `--ollama-host`
> argümanının varsayılanı hep `DEFAULT_OLLAMA_HOST`, hiçbir zaman `None`
> değil) tutarsızdı. `entegrasyon/` ile gerçek bir uçtan uca testte
> (Mcp_mimarisi'nden `uygun` kararı alınan gerçek bir fatura, `ollama_host`
> parametresi hiç verilmeden) bulundu. Regresyon testi:
> `tests/test_single.py::
> test_model_string_without_ollama_host_falls_back_to_default`.

## 5. Dış Bağımlılıklar

- **PostgreSQL** (zorunlu, `--dry-run` hariç tüm akışlarda):
  `DATABASE_URL` env var.
- **ChromaDB + Ollama** (opsiyonel, sadece `--rag`): `chromadb`, `ollama`
  paketleri (`requirements.txt`), embedding modeli varsayılan
  `embeddinggemma`.
- **LLM sağlayıcı API key'leri** (env var, sadece kullanılan sağlayıcı için
  gerekli): `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GOOGLE_API_KEY`/
  `GEMINI_API_KEY`; `openai-compat:` için istekte belirtilen özel env var
  adı; Ollama için `OLLAMA_HOST` (varsayılan `http://localhost:11434`).

## 6. Kapsam Dışı / Sıradaki Adımlar

- Mcp_mimarisi Adım 0 HTTP çağrısının `core/parsing.py`/`evaluate_models.py`
  akışına eklenmesi (ENTEGRASYON.md'de sözleşme var, kod yok).
- Bu pipeline'ın kendisinin bir HTTP servisi haline getirilmesi (şu an CLI/
  batch aracı) — PostgreSQL geçişi bunun ön koşullarından biriydi ama servis
  katmanının kendisi (endpoint, request/response şeması) henüz tasarlanmadı.
- ChromaDB'nin gerçek çoklu-**process** (tek process içindeki thread'ler
  değil, örn. `gunicorn -w 4` gibi ayrı worker process'leri) senaryosunda
  davranışı — singleton çözümü tek process kapsamında geçerli, HTTP servisi
  yazılırken yeniden değerlendirilmeli.
