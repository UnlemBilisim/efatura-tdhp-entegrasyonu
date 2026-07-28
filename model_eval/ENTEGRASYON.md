# KDV/Vergi Oranı Doğrulama Entegrasyonu (Mcp_mimarisi) — Adım 0

> Bu belge, bu pipeline'ın (TDHP hesap kodu tahmini) ayrı bir projeyle
> (`Mcp_mimarisi`, KDV/vergi oranı doğrulama katmanı) nasıl bağlanacağını
> tanımlar. Karar tarihi: 2026-07-22.

## Neden ayrı bir proje (monorepo değil)

`Mcp_mimarisi` (`~/Desktop/AıData2/Mcp_mimarisi/`), bu pipeline'dan
**bağımsız** geliştirilen bir doğrulama katmanı: gelen bir e-faturanın
beyan ettiği KDV oranının, satıcının NACE kod(lar)ının izin verdiği
oranlarla uyumlu olup olmadığını kontrol eder. Kendi PostgreSQL veritabanı,
kendi HTTP API'si (FastAPI) ve kendi test/dokümantasyon seti var —
`Mcp_mimarisi/PROJECT.md`, `Mcp_mimarisi/CLAUDE.md`.

İki proje kod olarak birleştirilmez (import edilmez, aynı süreçte
çalıştırılmaz) — sadece HTTP üzerinden konuşur. Gerekçe: bu pipeline'ın
(model_eval) kendi geliştirme hızı/deploy'u, Mcp_mimarisi'nin PostgreSQL/
API bağımlılıklarından etkilenmemeli; benzer şekilde Mcp_mimarisi de bu
pipeline'ın ChromaDB/Ollama bağımlılıklarını taşımaz.

## Akış noktası — "Adım 0"

Bu pipeline'da `parse_invoice_xml()` (`core/parsing.py`) ham, henüz
muhasebeleşmemiş bir XML faturayı (`--data-format xml`, ground truth YOK)
okuyup TDHP tahmini için hazırlar — bkz. `yeni_faturalar_tdhp.md`,
`results_new_invoices/` (gerçek çalıştırılmış örnekler, örn.
`AKK2026000000192`).

**Karar (2026-07-22):** KDV doğrulama, `parse_invoice_xml()`'den bile ÖNCE,
en başa (**Adım 0**) eklenir:

```
[Ham UBL-TR XML]
      │
      ▼
Adım 0: Mcp_mimarisi POST /fatura/kontrol-et
  (satici_vkn + satici_nace_kodlari + fatura_xml)
      │
      ├── genel_karar = "uygun" ──────────────┐
      │                                        ▼
      │                    Adım 1: parse_invoice_xml() (core/parsing.py)
      │                    Adım 2: RAG (ChromaDB, rag_common.py)
      │                    Adım 3: Fine-tuned/bulut LLM → TDHP kodu tahmini
      │                    Adım 4: Borç=Alacak doğrulaması
      │
      └── genel_karar = "insan_incelemesi_gerekli" ──▶ TDHP tahminine HİÇ girmez
                                                        (insan incelemesi kuyruğu)
```

## Sözleşme

**İstek** (`POST http://localhost:8000/fatura/kontrol-et`):

```json
{
  "fatura_xml": "<Invoice>...</Invoice>",
  "satici_vkn": "0460351893",
  "satici_nace_kodlari": ["251100"]
}
```

- `fatura_xml`: ham UBL-TR XML metni (dosya değil, string).
- `satici_vkn`: `DEFAULT_OWN_VKN` (`core/constants.py`) ile aynı değer —
  bu pipeline zaten şirketin kendi VKN'sini biliyor
  (`0460351893` — Akyüzlü Dövme ve Kaldırma Ekipmanları San.).
- `satici_nace_kodlari`: Mcp_mimarisi VKN→NACE lookup YAPMAZ — bu bilgi
  dışarıdan (bu pipeline'dan) sağlanmalıdır.

**Cevap:** `genel_karar` alanı `"uygun"` veya `"insan_incelemesi_gerekli"`
(kesin `"uyumsuz"` Faz 1'de üretilmez — bkz. Mcp_mimarisi `PROJECT.md`
§0.1). Tam şema: `Mcp_mimarisi/docs/reference/api-semasi.md`.

## Kapsam dışı (henüz netleşmedi)

- Production'da bu pipeline'ın Mcp_mimarisi API'sine hangi adresten
  erişeceği (aynı makine varsayıldı, `localhost:8000`).
- Mcp_mimarisi API'si erişilemezse (network hatası, timeout) bu
  pipeline'ın davranışı — şimdilik tanımsız, ayrıca ele alınmalı.
- Auth — Mcp_mimarisi tarafında da kapsam dışı bırakıldı (bkz.
  `Mcp_mimarisi/PROJECT.md` §3.8), iki servis arası çağrıda da yok.

## Durum

> ✅ **Karar verildi (2026-07-22):** Entegrasyon şekli (HTTP API, Adım 0)
> netleşti ve belgelendi. **Henüz kod yazılmadı** — bu pipeline'ın
> `core/parsing.py`/`evaluate_models.py` akışına Adım 0 HTTP çağrısının
> eklenmesi ayrı bir görevdir. Karşı taraf (Mcp_mimarisi) referansı:
> `Mcp_mimarisi/PROJECT.md` §3.10.

> ✅ **Uygulandı (2026-07-22):** Çok kullanıcılı MVP mimari denetiminin
> sonucunda bu pipeline'ın sonuç deposu (`core/reporting.py`,
> `core/runner.py`, `core/db.py`) dosya bazlı `.jsonl`'den **PostgreSQL**'e
> taşındı (`model_eval_sonuclar` tablosu). Bu değişiklik, Mcp_mimarisi ile
> **aynı Postgres sunucusunu** (aynı `DATABASE_URL`) paylaşma kararını da
> getirdi — bu nedenle Adım 0 entegrasyonu artık sadece HTTP çağrısı değil,
> aynı zamanda ortak bir altyapı bağımlılığı (Postgres erişilebilirliği)
> anlamına geliyor. Tablo isim alanı çakışmasını önlemek için bu pipeline'ın
> tüm tabloları `model_eval_` önekini taşır — Mcp_mimarisi'nin
> `gecmis_fatura_kalemleri`/`islenmis_faturalar` tablolarına dokunulmaz.
> ChromaDB client'ı da (`rag_common.get_collection()`) artık process ömrü
> boyunca tek bir singleton — çoklu eşzamanlı çağrı "Could not connect to
> tenant" hatasına yol açmıyor. Detay: `docs/mimari-denetim-2026-07-22.md`
> (yeni). `DATABASE_URL` env var artık zorunlu (`--dry-run` hariç tüm
> akışlarda) — `requirements.txt`'ye `psycopg2-binary` eklendi.

> ✅ **Uygulandı (2026-07-22):** "Henüz kod yazılmadı" notu artık KISMEN
> geçersiz. AıData2 kökünde ayrı, bağımsız bir `entegrasyon/` klasörü
> açılıyor (başka bir agent tarafından yazılıyor) — Mcp_mimarisi'nin
> `POST /fatura/kontrol-et` (Adım 0) çağrısını yapacak asıl HTTP
> orkestrasyon kodu ORADA yaşayacak, bu pipeline'da (`model_eval/`) değil.
> `entegrasyon/`'un bu pipeline'dan import edeceği ihtiyaç — "uygun" kararı
> çıkan tek bir faturayı (henüz diske yazılmamış ham XML string) senkron
> olarak TDHP tahminine sokup sonucu döndüren, DB'ye dokunmayan bir
> fonksiyon — `core/single.py::predict_single_invoice()` olarak eklendi.
> Bu fonksiyon `core/runner.py::run_model()`'ın (toplu, es zamanlı,
> PostgreSQL resume'lü) aksine tek fatura işler ve hiçbir şeyi kalıcı
> depoya yazmaz — çağıran taraf (`entegrasyon/`) sonucu kendi tercih ettiği
> şekilde saklar/iletir. İmza ve alan şeması: `PROJECT.md` §4.1.
> Mcp_mimarisi'ne ve kökteki `entegrasyon/` klasörüne bu pipeline
> tarafından hiç dokunulmadı — sorumluluk ayrımı gereği (bkz. proje
> hafızası: bu agent sadece `model_eval/`'dan sorumlu).
