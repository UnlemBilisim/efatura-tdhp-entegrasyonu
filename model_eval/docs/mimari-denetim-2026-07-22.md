# Çok Kullanıcılı MVP Mimari Denetimi — 2026-07-22

Bu belge, `model_eval` ve `Mcp_mimarisi` projelerinin "çok kullanıcılı MVP'ye
çıkmadan önce mimari sağlamlık" denetiminin sonucunu ve bu pipeline
(model_eval) tarafında yapılan düzeltmeleri kaydeder. Karşı taraf
(Mcp_mimarisi) için görev tanımı:
`Mcp_mimarisi/GOREV_MIMARI_DUZELTME.md`.

## Neden bu değişiklik gerekti

Denetimde bu pipeline'ın CLI/batch aracı olarak tasarlandığı ama gelecekte
(ENTEGRASYON.md'deki Adım 1-4) bir HTTP servisinin parçası olacağı
belirlendi. Servis çok kullanıcılı/çok process (worker) altında
çalıştığında iki kritik sorun tespit edildi:

1. **Dosya bazlı sonuç deposu** (`core/reporting.py`, eski
   `result_path_for_model`) dosya adını sadece model+bayrak etiketinden
   türetiyordu — kullanıcı/istek kimliği taşımıyordu. Tek process içindeki
   `threading.Lock` koruması, birden fazla process/worker'a (gerçek HTTP
   servisi) geçildiğinde SIFIRA inerdi; eşzamanlı yazmalar birbirine
   karışabilirdi.
2. **ChromaDB `PersistentClient`** (`rag_common.get_collection()`) her
   çağrıda yeniden açılıyordu. Kodun kendi eski yorumu bunu zaten
   belgeliyordu: aynı `persist_dir`'e birden fazla client'ın AYNI ANDA
   bağlanması "Could not connect to tenant" hatasına yol açıyordu
   (SQLite tabanlı ChromaDB'nin bilinen bir kısıtı).

## Ne değişti

### Sonuç deposu: dosya → PostgreSQL

- **Yeni:** `core/db.py` — process ömrü boyunca tek bir
  `psycopg2.pool.ThreadedConnectionPool` (`get_pool()`/`get_conn()`).
  `DATABASE_URL` env var'dan okunur, Mcp_mimarisi ile **aynı Postgres
  sunucusu** paylaşılır (bkz. ENTEGRASYON.md) ama tablo isim alanı
  çakışmasın diye tüm tablolar `model_eval_` önekini taşır.
- **Yeni şema:** `model_eval_sonuclar (id, file_label, invoice_id, record
  JSONB, is_error, created_at)`. Eski jsonl satırının karşılığı `record`
  sütunudur (aynı alan adlarıyla JSON).
- `core/reporting.py` tamamen bu tabloya göre yeniden yazıldı:
  `result_path_for_model` kaldırıldı (dosya yolu kavramı yok artık),
  `append_result`/`load_done_ids`/`delete_results`/`count_results` eklendi.
  `summarize_model` artık `file_label` alır, dosya değil.
- `core/runner.py`: `write_lock` parametresi kaldırıldı — PostgreSQL'in
  kendi satır bazlı INSERT garantisi, artık process'ler arası da geçerli
  (eski `threading.Lock` sadece tek process içinde korurdu).
- `core/cli.py`: 3 çağrı noktası (`--summarize-only`, `--data-format xml`
  özet, normal özet) yeni API'ye göre güncellendi.
- Testler (`tests/test_reporting.py`, `tests/test_runner.py`) gerçek bir
  PostgreSQL'e karşı çalışacak şekilde yeniden yazıldı — `TEST_DATABASE_URL`
  env var'ı yoksa/bağlanılamıyorsa otomatik `skip` edilir (bkz.
  `tests/conftest.py`, `requires_postgres` marker'ı).

### ChromaDB: her-çağrı-yeni-client → process singleton

- `rag_common.get_collection()` artık `(persist_dir, embed_model,
  ollama_host)` anahtarına göre process ömrü boyunca tek bir client/
  collection döndürür (`_collection_cache`, thread-safe). CLI'daki eski
  "sadece `--model-parallelism>1` için önceden ortak collection aç" özel
  durumu artık gerekli değil ama zararsız olduğu için `cli.py`'de
  bırakıldı (yorum güncellendi).

## Doğrulama

- 155 test geçti (`python3 -m pytest tests/ -v`, `TEST_DATABASE_URL` ile
  ayrı bir test veritabanına karşı).
- Gerçek CLI ile manuel doğrulama: `--dry-run` (DB'ye dokunmuyor, prompt
  üretimi bozulmadı), `--summarize-only` (PostgreSQL'den doğru okuyor),
  ve doğrudan `core.reporting` üzerinden 2 eşzamanlı thread'in aynı
  `file_label`'a 40 kayıt yazması (çakışma/kayıp yok — eski dosya bazlı
  yaklaşımda garanti edilemeyen bir senaryo).

## Kapsam dışı (bu turda yapılmadı)

- Auth/rate-limiting (bilinçli olarak dışarıda bırakıldı, ayrı bir karar).
- `evaluate_models.py`/`core/parsing.py` akışına Adım 0 (Mcp_mimarisi)
  HTTP çağrısının eklenmesi — hâlâ ENTEGRASYON.md'de tanımlı ama kodu
  yazılmamış bir sözleşme.
- ChromaDB'nin kendisinin (SQLite tabanlı) çok-process (farklı OS
  process'leri, tek process içindeki thread'ler değil) senaryosunda
  davranışı ayrıca test edilmedi — singleton çözümü tek process içindeki
  thread'ler için geçerli, gerçek bir multi-worker HTTP servisinde
  (örn. `gunicorn -w 4`) her worker kendi process'inde kendi singleton'ını
  açacağından, ChromaDB'nin çoklu-process erişimi mevzusu HTTP servisi
  kodu yazılırken yeniden değerlendirilmeli.
