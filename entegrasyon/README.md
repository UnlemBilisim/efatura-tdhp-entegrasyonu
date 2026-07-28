# Entegrasyon — Ön Filtreleme (Mcp_mimarisi) → TDHP Tahmini (model_eval)

> **Amaç:** `Mcp_mimarisi`'nin KDV/vergi oranı mevzuat ön filtresi ile
> `model_eval`'ın TDHP hesap kodu tahmin pipeline'ı arasında, `model_eval/
> ENTEGRASYON.md`'de sözleşmesi tanımlanmış "Adım 0" akışını gerçekten
> çalıştıran bağımsız orkestrasyon servisi + test arayüzü.

Bu klasör **hem Mcp_mimarisi hem model_eval'dan bağımsız üçüncü bir
bileşendir** — ikisine de dışarıdan bağlanır, ikisinin de koduna dokunmaz:

- **Mcp_mimarisi** ile: gerçek HTTP isteği (`POST /fatura/kontrol-et`,
  bkz. `mcp_mimarisi_istemcisi.py`). Mcp_mimarisi ayrı bir süreç olarak
  (kendi PostgreSQL'i, kendi `uvicorn`'u ile) ayrıca çalıştırılmış olmalı.
- **model_eval** ile: doğrudan Python import (`model_eval_koprusu.py`,
  `core.single.predict_single_invoice` fonksiyonunu çağırır). Bu, iki
  proje arasındaki "HTTP üzerinden ayrık" kuralını ihlal etmez — o kural
  Mcp_mimarisi ↔ model_eval arasındaki ayrımı korumak içindi
  (`Mcp_mimarisi/PROJECT.md` §3.10); bu entegrasyon katmanı model_eval'ın
  kendi çalışma alanının bir parçası olarak model_eval'ı import eder.

## Akış

**Yöne (inbox/outbox) göre ikiye ayrılır** (kullanıcı kararı, 2026-07-22).
Yön, faturanın kendi XML'inden tespit edilir — kullanıcı sadece kendi
şirketinin VKN'sini girer, sistem bunu faturanın `AccountingSupplierParty`/
`AccountingCustomerParty` VKN'leriyle karşılaştırıp otomatik karar verir
(`yon_tespiti.py`, model_eval'ın `parse_invoice_xml_string()`'ini kullanır).

**outbox (bizim kestiğimiz fatura — kendi VKN'miz SATICI tarafında):**

```
[Ham UBL-TR XML]
      │
      ▼
Mcp_mimarisi POST /fatura/kontrol-et
      │
      ├── genel_karar = "uygun" ─────────────────────┐
      │                                               ▼
      │                                    model_eval TDHP tahmini
      │                                    (core.single.predict_single_invoice)
      │
      └── genel_karar = "insan_incelemesi_gerekli"
              │
              ▼
        Kullanıcıya UYARI gösterilir (hangi kalem, hangi NACE, neden uyuşmuyor)
              │
              ├── Kullanıcı onaylar ("yine de devam et") ──▶ model_eval TDHP tahmini
              └── Kullanıcı onaylamaz ───────────────────────▶ durur (insan incelemesi kuyruğu)
```

**inbox (dışarıdan gelen fatura — kendi VKN'miz ALICI tarafında):**

```
[Ham UBL-TR XML] ─────────────────────────────────────▶ model_eval TDHP tahmini
```

Mcp_mimarisi'nin KDV/NACE ön filtrelemesi inbox faturalarda **hiç
çağrılmaz** — sistem bilinçli olarak sadece bizim kestiğimiz faturaları
mevzuata uygunluk açısından doğrulamak üzere tasarlandı (bkz.
`Mcp_mimarisi/PROJECT.md` §3.9, "bu proje şuan sadece bizim kestiğimiz
faturaları incelemeli" kapsam kararı). Dışarıdan gelen faturalarda bu
doğrulama sorumluluğu bu sisteme ait değil — doğrudan TDHP tahminine
geçilir. `satici_nace_kodlari` alanı bu durumda kullanılmaz/boş bırakılabilir.

> ✅ **Uygulandı (2026-07-22):** İnbox faturalar için de TDHP tahmini
> desteği eklendi — önceden sistem sadece outbox akışını (Mcp_mimarisi →
> model_eval) destekliyordu. `yon_tespiti.py` (yeni) faturayı Mcp_mimarisi'ne
> göndermeden ÖNCE yönünü tespit eder; `app.py::fatura_isle()` buna göre
> dallanır. model_eval'ın kendisi zaten hem inbox hem outbox faturalar için
> TDHP tahmini üretebiliyordu (bkz. `model_eval/RESULTS.md` §7 — inbox
> %16.2 hatalı, outbox %7.8 hatalı, ayrı ayrı ölçülmüş) — bu değişiklik
> sadece entegrasyon katmanının bu tahmin yeteneğine dış-fatura senaryosunda
> da erişmesini sağladı, model_eval'ın kendi koduna dokunulmadı. Gerçek bir
> inbox faturasıyla (`Mcp_mimarisi/ubls/VM02025000000346-*-inbox.xml`,
> satıcı Varzene Metalurji VKN 9241090843, bize kesilmiş) test edildi:
> `yon: inbox`, `on_filtre_sonucu: null` (Mcp_mimarisi hiç çağrılmadı),
> TDHP tahmini `150 Borç 585.75 / 191 Borç 117.15 / 320 Alacak 644.33 /
> 360 Alacak 58.57`, `balanced: true`. Aynı oturumda outbox regresyonu da
> (ihracat faturası `AKK2025000000071`) doğrulandı — davranış değişmedi.

> ✅ **Uygulandı (2026-07-23):** Yabancı para birimli (EUR/USD vb.)
> faturalarda kur çevirisi kararı kullanıcıya soruluyor, sessizce
> yapılmıyor. Fatura XML'inde kur bilgisi (`cac:PricingExchangeRate/
> cbc:CalculationRate`) varsa, `app.py::fatura_isle()` model_eval'a
> geçmeden ÖNCE durur ve `kur_onayi_bekliyor` aşamasını döner (`kur_bilgisi`
> alanında para birimi + kur oranı). Kullanıcı `kur_secimi="orijinal"`
> (fatura kendi para biriminde işlenir) ya da `kur_secimi="tl"` (tutarlar
> XML'deki kur oranıyla TL'ye çevrilip TDHP tahmini TL üzerinden üretilir)
> seçip tekrar gönderir. TL faturalarda ya da kur bilgisi taşımayan
> faturalarda bu adım hiç tetiklenmez, akış eskisi gibi devam eder.
> Uygulama: `model_eval/core/parsing.py::convert_invoice_to_try`,
> `core/single.py::predict_single_invoice(convert_to_try=...)`,
> `model_eval_koprusu.py::fatura_kur_bilgisi`, `app.py::
> _kur_onayi_gerekiyor_mu`, `static/index.html` (uyarı kutusu + "TL'ye
> çevir" butonu). Gerçek bir EUR faturasıyla (`AAB2025000003056-*-inbox.xml`,
> 1 EUR = 44.2855 TRY) uçtan uca test edildi: `kur_secimi` verilmeden
> `kur_onayi_bekliyor` döndü; `orijinal` seçilince sonuç EUR cinsinden
> (`currency: "EUR"`, tutarlar değişmedi); `tl` seçilince sonuç TRY
> cinsinden (`currency: "TRY"`, tutarlar kur oranıyla çarpılmış,
> `balanced: true` korunmuş).

## Durum

> ✅ **Uygulandı (2026-07-22):** Orkestrasyon servisi (`app.py`) ve test
> arayüzü (`static/index.html`) yazıldı. Mcp_mimarisi bağlantısı
> (`mcp_mimarisi_istemcisi.py`) gerçek HTTP çağrısı yapar, ayrı onay
> gerektiren kod eklenmedi (Mcp_mimarisi'nin auth'u yok, bu servis de
> eklemedi — bkz. `Mcp_mimarisi/PROJECT.md` §3.8).
>
> ✅ **model_eval bağlantısı tamamlandı (2026-07-22, aynı gün):**
> `model_eval/core/single.py::predict_single_invoice` eklendi (kod+yön+tutar
> üçlüsünü koruyan, DB'ye yazmayan tek-fatura tahmin fonksiyonu — model_eval
> tarafının kendi 167 testi geçiyor). Bu köprü (`model_eval_koprusu.py`)
> onu gerçekten import edip çağırıyor; `entegrasyon/requirements.txt`'e
> model_eval'ın bağımlılıkları (`requests`, `chromadb`, `ollama`,
> `psycopg2-binary` — sonuncusu `core/__init__.py`'nin transitive import
> zinciri yüzünden gerekli, `predict_single_invoice`'in kendisi DB'ye
> dokunmuyor) eklendi. `GET /durum` gerçek uvicorn ile test edildi:
> `{"model_eval_hazir": true, "model_eval_mesaj": "hazır"}`.
>
> ✅ **Uçtan uca gerçek testte iki sorun bulundu ve düzeltildi (2026-07-22,
> aynı gün):**
> 1. `predict_single_invoice`'te `ollama_host=None` varsayılanı doğrudan
>    `parse_model_spec()`'e sızıp `base_url=None` üretiyordu — bu, gerçek
>    bir modelle (`gemma4:31b-cloud`) ilk uçtan uca denemede `AttributeError`
>    (`'NoneType' object has no attribute 'rstrip'`) ile 500 hatasına yol
>    açtı. `model_eval` tarafında düzeltildi (bkz. `model_eval/PROJECT.md`
>    §4.1) — artık `ollama_host=None` verilirse `DEFAULT_OLLAMA_HOST`'a
>    düşüyor.
> 2. Düzeltme sonrası ikinci denemede **401 Kimlik doğrulama hatası** alındı
>    — `gemma4:31b-cloud` bir Ollama "bulut" modeli (ollama.com hesabına
>    bağlı), yerel Ollama'da (port 11434) DEĞİL, kullanıcının SSH tüneliyle
>    bağlandığı uzak GPU sunucusunda (unlem-gx10-01, bkz.
>    `sunucu-yönlendirme.md`/`çalıştırma.txt`) çalışıyor — tünel varsayılan
>    olarak `localhost:11435`'e açılıyor. `model_eval_koprusu.py` artık
>    `predict_single_invoice`'e `ollama_host="http://localhost:11435"`
>    (env var `MODEL_EVAL_OLLAMA_HOST` ile override edilebilir) geçiriyor.
>
> Gerçek bir ihracat faturasıyla (`AKK2025000000071`, istisna kodu 301) tam
> uçtan uca doğrulandı: ön filtre `uygun`, TDHP tahmini `120 Borç / 601
> Alacak`, `balanced: true`, `error: null` — muhasebe açısından da doğru
> (ihracat için Yurtdışı Satışlar hesabı 601).
>
> ✅ **Bir performans sorunu daha bulundu ve düzeltildi (2026-07-22, aynı
> gün):** `model_eval_koprusu.py` başta hem `ollama_host` (LLM tahmini) hem
> `rag_ollama_host` (RAG embedding) parametrelerini SSH tüneline
> yönlendiriyordu — ama `embeddinggemma` (embedding modeli) yerelde zaten
> kurulu, tünele hiç ihtiyacı yok. Bu yüzden RAG embedding çağrısı
> gereksiz yere tünelden geçiyor, bazen `Connection reset by peer` ile
> tamamen başarısız oluyordu (bir denemede toplam istek 40s sürüp boş
> cevap döndü). `rag_ollama_host` artık verilmiyor (rag_common'ın kendi
> yerel varsayılanına düşüyor) — düzeltme sonrası aynı istek **1.7-2
> saniyede** tamamlandı.
>
> ✅ **Adım-adım loglama eklendi (2026-07-22, aynı gün):** `app.py`'ye
> `logging` ile `[1/4]`-`[4/4]` etiketli INFO seviyesi log satırları
> eklendi (istek alındı → Mcp_mimarisi'ne gönderildi/cevap geldi → karar
> dallanması → model_eval'a gönderildi/cevap geldi), her adımın süresi
> dahil. Kullanıcı geri bildirimi: "loglar yetersiz, her kritik adımın
> girdi/çıktısını terminalde görmek istiyorum". Aynı loglama
> `Mcp_mimarisi/src/efatura_kdv/api.py`'ye de eklendi (`[MCP 1/3]`-
> `[MCP 3/3]`) — bkz. `Mcp_mimarisi/CLAUDE.md`. Canlı izleme:
> `PROJE_CALISTIRMA.md` "Her adımı canlı terminalde izlemek" bölümü.

## Çalıştırma

```bash
# 1. Mcp_mimarisi'nin kendi API'sini ayrıca başlat (bkz. Mcp_mimarisi/docs/how-to/api-calistirma.md)
#    DATABASE_URL=... uvicorn efatura_kdv.api:app --app-dir src --host 0.0.0.0 --port 8000

# 2. Bu servisi başlat
cd entegrasyon
pip install -r requirements.txt
uvicorn app:app --reload --port 8100
```

Tarayıcıda `http://localhost:8100` — XML dosyası yükle, satıcı VKN +
NACE kod(lar)ını gir, "Ön Filtreden Geçir"e bas.

Mcp_mimarisi başka bir adreste çalışıyorsa: `MCP_MIMARISI_BASE_URL` env
var'ı ile belirt (varsayılan `http://localhost:8000`).

## Sözleşme / Şema

- Mcp_mimarisi tarafı: `Mcp_mimarisi/docs/reference/api-semasi.md`
  (`POST /fatura/kontrol-et` şeması, bu servis onu birebir kullanır).
- model_eval tarafı: `model_eval/ENTEGRASYON.md` + (eklenince)
  `model_eval/PROJECT.md`'deki `predict_single_invoice` bölümü.
- Bu servisin kendi endpoint'i: `POST /fatura/isle` — girdi
  `{fatura_xml, satici_vkn, satici_nace_kodlari, onay, kur_secimi}`, çıktı
  `{asama, on_filtre_sonucu, kur_bilgisi, tdhp_tahmini, mesaj}` (tam alanlar
  için `app.py`'deki Pydantic modellerine bakın). `kur_secimi` sadece
  fatura yabancı para biriminde ve kur bilgisi taşıyorsa anlamlıdır
  (`"orijinal"` | `"tl"`).
- `POST /fatura/onayla` — girdi `{fatura_xml, satici_vkn, tdhp_tahmini}`,
  çıktı `{kaydedildi, mesaj}`. Bkz. aşağıdaki "Fatura onaylama" bölümü.

> ✅ **Uygulandı (2026-07-23):** Kullanıcı arayüzde TDHP tahmin tablosunun
> altındaki **"✓ Bu doğru, kaydet"** butonuna basınca `POST /fatura/onayla`
> çağrılır (`static/index.html::faturaOnayla()`) — sunucu tekrar LLM'e
> gitmez, önceki `/fatura/isle` cevabındaki `tdhp_tahmini`'ni aynen alıp
> iki yere yazar (`model_eval_koprusu.py::faturayi_onayla`):
> 1. **PostgreSQL** (`model_eval/core/reporting.py::append_result`,
>    `model_eval_sonuclar` tablosu, `file_label="entegrasyon_onaylandi"`) —
>    denetim/kayıt amaçlı. Aynı fatura birden fazla kez onaylanırsa
>    yinelenen kontrolü YAPILMAZ (kullanıcı kararı) — her onay ayrı bir
>    satır, ama `onaylandi_zamani` alanıyla birlikte kaydedilir ki ileride
>    geçmiş/yinelenen kayıtlar tarihe göre temizlenebilsin.
> 2. **RAG vektör DB'si** (`model_eval/rag_common.py::upsert_approved_invoice`)
>    — onaylanan tahmin, gelecekteki benzer faturalar için few-shot örneği
>    olarak kullanılabilsin diye ChromaDB koleksiyonuna eklenir/güncellenir
>    (`invoice_id` ile upsert, idempotent). Bu, `build_vector_db.py`'nin
>    "sadece Archive2/jsons ground-truth'u indeksle" kuralını BİLEREK
>    genişletiyor — kullanıcı onayı da bir tür ground-truth sayılıyor.
>    Hesap adları (`entries_json` içinde) `core/constants.py::TDHP_GLOSSARY`
>    sözlüğünden otomatik dolduruluyor — bu, tüm muhasebecilerin aynı TDHP
>    kodlarını kullandığı varsayımına dayanır; **ileride her muhasebeci için
>    ayrı bir kod→isim listesi eklenmesi planlanıyor** (bkz. `model_eval/CLAUDE.md`),
>    o zaman bu fonksiyon güncellenmeli.
>
> **Önkoşul:** Bu endpoint `DATABASE_URL` env var'ının entegrasyon servisine
> de verilmiş olmasını gerektirir (bkz. `PROJE_CALISTIRMA.md` §3) —
> `/fatura/isle` (tahmin) bu olmadan da çalışır, ama `/fatura/onayla`
> (kayıt) `DATABASE_URL` yoksa 500 döner. Gerçek bir faturayla
> (`AKL2025000000003`, tevkifatlı) uçtan uca test edildi: hem PostgreSQL
> satırı hem ChromaDB kaydı (`collection.get(ids=[...])`) doğrulandı.

## Kapsam dışı

- Auth (her iki alt sistemde de yok, bu katmanda da eklenmedi).
- Mcp_mimarisi'ye ulaşılamadığında retry/circuit-breaker — şu an tek
  deneme, hata olursa 502 ile kullanıcıya gösterilir.
- Sunucu tarafı toplu endpoint (`POST /fatura/coklu-isle` gibi). Arayüzde
  toplu işlem VAR (aşağıya bakın) ama istemci tarafında yönetiliyor — her
  faturayı sırayla mevcut `POST /fatura/isle`'ye gönderir, ayrı bir toplu
  endpoint eklenmedi.

## Arayüzde toplu işlem (2026-07-27)

> ✅ **Uygulandı (2026-07-27):** `static/index.html`'e "Tek Fatura" /
> "Toplu İşlem" sekmeleri eklendi. Toplu sekmesi birden çok XML seçimini
> (`<input type="file" multiple>` + çoklu sürükle-bırak) destekler; üstteki
> **tek ortak VKN + NACE** tüm faturalara uygulanır (kullanıcı kararı,
> 2026-07-27 — aynı şirketin faturaları işlendiği için VKN hep aynı).
>
> Akış (kullanıcı kararı, 2026-07-27 — "sistem durmasın"): faturalar sırayla
> `POST /fatura/isle`'ye gönderilir, arayüz HİÇ DURMAZ. Dönen `asama`
> `on_filtre_insan_incelemesi_bekliyor` veya `kur_onayi_bekliyor` ise o
> fatura **"⏳ Onay Bekleyenler"** kuyruğuna alınır (atlanmaz, kaybolmaz),
> kalanlar işlenmeye devam eder. Kullanıcı bekleyeni onayladığında
> (`onay=true` ya da `kur_secimi` ile) fatura tekrar `/fatura/isle`'ye
> gönderilir ve sonucu **sonuç tablosunun BAŞINA** eklenir (hafif sarı
> vurgu). Backend DEĞİŞMEDİ — `/fatura/isle` zaten `onay`/`kur_secimi`
> parametrelerini kabul ediyordu; bu tümüyle istemci tarafı bir eklentidir.
> "Tek Fatura" sekmesi eski davranışı birebir korur.
