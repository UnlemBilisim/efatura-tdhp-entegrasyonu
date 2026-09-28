# CLAUDE.md — Çalışan Sistem (e-Fatura KDV Doğrulama + TDHP Tahmini)

Bu dosya, `System/` altında çalışan Claude Code (ve diğer AI ajanları) için
rehberdir. Genel çalışma disiplini (docs güncelleme, hafıza kullanımı,
varsayım yapmama, güvenlik onayı) proje kök dizinindeki
[`../CLAUDE.MD`](../CLAUDE.MD)'de tanımlıdır — **bu dosya onu tekrar etmez**,
yalnızca bu üç bileşenin BİRLİKTE çalışmasına özgü bilgiyi içerir.

Tek bir bileşenin içinde çalışıyorsan onun kendi rehberi daha ayrıntılıdır:
- [`Mcp_mimarisi/CLAUDE.md`](Mcp_mimarisi/CLAUDE.md) — KDV/NACE ön filtreleme
- [`model_eval/CLAUDE.md`](model_eval/CLAUDE.md) — TDHP tahmini + RAG
- `entegrasyon/` — kendi CLAUDE.md'si yok; [`entegrasyon/README.md`](entegrasyon/README.md)

## Sistem nedir?

Üç bileşen + bir orkestrasyon katmanı. Fatura önce KDV mevzuatı açısından
denetlenir, sonra muhasebe kaydı (TDHP kodu + Borç/Alacak + tutar) üretilir.

| Bileşen | Port | Rol |
|---|---|---|
| `Mcp_mimarisi/` | 8000 | KDV/NACE ön filtreleme (kural tabanlı, PostgreSQL) |
| `model_eval/` | — | TDHP tahmini (LLM + RAG), **import ile** çağrılır |
| `entegrasyon/` | 8100 | Orkestrasyon + web arayüzü |

Mimarinin **neden** böyle kurulduğu: [`../mimari.md`](../mimari.md).
Çalıştırma adımları: [`proje-calistirma.md`](proje-calistirma.md).

## Dokümantasyon (Diátaxis)

Üç bileşenin **birlikte** çalışmasına ait belgeler [`docs/`](docs/) altında
(bileşene özel olanlar o bileşenin kendi `docs/`'unda):

| Belge | Tür | İçerik |
|---|---|---|
| [`docs/reference/servisler-ve-portlar.md`](docs/reference/servisler-ve-portlar.md) | reference | Portlar, env değişkenleri, tablolar, endpoint envanteri |
| [`docs/how-to/sistemi-test-etme.md`](docs/how-to/sistemi-test-etme.md) | how-to | Testler, manuel test, uçtan uca doğrulama |
| [`docs/explanation/guvenlik-durumu-2026-07-27.md`](docs/explanation/guvenlik-durumu-2026-07-27.md) | explanation | Güvenlik taraması bulguları + bilinçli kararlar |

Yeni bir belge eklerken türüne göre doğru klasöre koy; `docs/README.md`
indeksini de güncelle.

## Değişmez kurallar

1. **`entegrasyon/` ve `model_eval/` aynı üst dizinde KARDEŞ kalmalı.**
   `entegrasyon/model_eval_yolu.py` bunu varsayarak `sys.path`'e ekleme yapar.
   Klasörleri ayırmak sistemi bozar.
2. **`Mcp_mimarisi` HTTP ile, `model_eval` import ile çağrılır.** Bu asimetri
   kasıtlıdır (gerekçe: mimari.md §2.1). `entegrasyon/` bu ikisinin koduna
   dokunmaz — onlara dışarıdan bağlanan üçüncü bir bileşendir.
   > ⚠️ **2026-08-05 kullanıcı kararıyla gevşetildi:** "İki bileşen birbirinin
   > koduna dokunmaz" ilkesi genel olarak KALKTI — `Mcp_mimarisi` artık
   > `model_eval`'ı doğrudan import edebilir (bkz.
   > `Mcp_mimarisi/scripts/tenant_onboarding.py`, `model_eval_yolu.py`
   > deseniyle `model_eval/core/db.py::_SCHEMA`'yı import ediyor — elle
   > kopyalanan bir SQL şemasının iki projede senkronsuz kalma riskini
   > gidermek için). Yukarıdaki HTTP/import asimetrisi hâlâ **entegrasyon/**
   > katmanı için geçerlidir (o hâlâ ikisine dışarıdan bağlanır) — değişen,
   > `Mcp_mimarisi`↔`model_eval` arasındaki "birbirine dokunmaz" sınırıdır.
3. **Ön filtreleme yalnızca outbox faturalara uygulanır.** inbox'ta
   `Mcp_mimarisi` HİÇ çağrılmaz (gerekçe: başkasının kestiği faturanın mevzuat
   sorumluluğu bizde değil). Yön, XML'den tespit edilir — kullanıcıya sorulmaz.
4. **İki bileşen aynı PostgreSQL'i paylaşır, farklı tabloları kullanır.**
   `nace_oranlari`/`gecmis_fatura_kalemleri` (Mcp_mimarisi) ve
   `model_eval_sonuclar` (model_eval) — birbirinin tablosuna dokunmazlar.
5. **KDV uygunluğu LLM'e sorulmaz.** Mevzuat kontrolü deterministik kalır;
   LLM yalnızca muhasebe kaydı için kullanılır.
6. **`records[]`/`dis_sema` dış sözleşmesi, iç şemadan TÜRETİLİR.** İç tarafta
   `entries[]` + `dc="Borc"/"Alacak"` kalır (model_eval testleri + DB + RAG buna bağlı);
   dönüşüm yalnızca `model_eval/core/disa_aktarim.py`'de yapılır. Dış ekibin
   tek kaynağı (API sözleşmesi + `records[]` şema detayı, 2026-08-05'te
   birleştirildi):
   [`entegrasyon/docs/reference/dis-ekip-api-kullanimi.md`](entegrasyon/docs/reference/dis-ekip-api-kullanimi.md).
   Bu belge dış sözleşmedir — değiştirirsen karşı taraf kırılır, önce sor.

## Çalıştırmak için gerekenler (sık atlanan)

> ✅ **Uygulandı** (2026-09-28, kullanıcı kararı): `baslat.sh` kaldırıldı,
> tek çalıştırma yolu `docker compose up` (bkz.
> [`docs/how-to/docker-ile-calistirma.md`](docs/how-to/docker-ile-calistirma.md)).

`docker compose up` üç dış bağımlılık ister; biri eksikse ilgili servis
sessizce çalışmaz, hata mesajı ilk bakışta yanıltıcı olabilir:

| Gereksinim | Eksikse ne olur |
|---|---|
| **Docker Desktop açık** | Hiçbir container ayağa kalkmaz |
| **SSH tüneli (11435)** | LLM'e erişilemez → TDHP tahmini boş `entries` döner |
| **Ollama container'ı (11434) + `embeddinggemma` modeli çekilmiş** | RAG embedding çalışmaz |

SSH tünel komutu [`çalıştırma.txt`](çalıştırma.txt) içinde. Tünel parola
istiyor — ajan açamaz, kullanıcı açmalı.

> ⚠️ **Tuzak:** LLM erişimi yoksa `predict_single_invoice` hata fırlatmaz;
> `error` alanı dolu, `entries` boş döner. `records: []` görünce "kodum
> bozuldu" sanmak yerine önce tüneli kontrol et (bu oturumda bir kez yaşandı).

## Test etme

```bash
python3 -m pytest Mcp_mimarisi/test -q          # 28 test
python3 -m pytest entegrasyon/tests -q          # 4 test (+2 bilinçli skip)
(cd model_eval && python3 -m pytest tests -q)   # 226 test
```

Üç paket ayrı ayrı çalıştırılır (her biri kendi `sys.path` düzenini kurar).
Ayrıntı ve skip'lerin anlamı: [`docs/how-to/sistemi-test-etme.md`](docs/how-to/sistemi-test-etme.md) §1.

- **CI** (`.github/workflows/testler.yml`, 2026-09-28): `main`'e her push'ta
  ve PR'da üç paketi Python 3.11 + gerçek PostgreSQL ile çalıştırır ve ikiz
  modüllerin (`log_ortak.py`, `es_zamanli_sinir.py`) birebir aynı olduğunu
  denetler. İkiz modüllerden birini değiştirip diğerini unutursan CI kırılır.
- **PostgreSQL kapalıysa** model_eval'de 26 test otomatik `skip` edilir
  (`requires_postgres` marker'ı) — bu bir hata değildir, CI'da koşarlar.
- Sistem `.venv` kullanıyorsa `pytest` bulunamayabilir; `/usr/bin/python3 -m
  pytest` ile sistem python'unu kullan.
- **Prod DB'sine (`DATABASE_URL`) test verisi yazma** — ayrı bir test
  veritabanı kullan.

Bir özelliği "tamamlandı" saymadan önce gerçekten çalıştır: `docker compose up`
+ `POST /fatura/isle` ile gerçek bir fatura işle. Kodu okuyup "böyle çalışması
lazım" demek yeterli değildir (kök CLAUDE.MD §3).

## Bilinen güvenlik durumu (2026-07-27 taraması)

Statik güvenlik taraması yapıldı; **düzeltmeler henüz uygulanmadı.** Yeni kod
yazarken bunları kötüleştirmemeye dikkat et:

> **Kapsam notu (2026-07-27, kullanıcı kararı):** Arayüzü **dış ekip yazacak**;
> biz yalnızca backend teslim ediyoruz. Çağrı **sunucu-sunucu** olacağı için
> CORS bilinçli olarak yapılandırılmamıştır (tarayıcıdan çağrı denenirse
> preflight 405 döner). `entegrasyon/static/index.html` bizim kendi manuel
> test aracımızdır — teslim kapsamında değil, ama bizde kalıyor.

**Güvenlik durumu (2026-09-11):** Dış/dahili Bearer token, loopback bind,
DTD/entity ve istek boyutu reddi, TDHP/mizan/tutar doğrulaması, sunucu
tarafı `prediction_id` onayı ve arayüz escape'i uygulanmıştır. Yeni iş
endpoint'leri auth bağımlılığı olmadan eklenmemeli; doğrulamadan geçmeyen
tahmin RAG'a yazılmamalıdır. Tarihsel tarama:
`docs/explanation/guvenlik-durumu-2026-07-27.md`.

> 🔴 **GEÇİCİ OLARAK GEVŞETİLDİ (2026-09-11, kullanıcı kararı — "token
> kısmını şimdilik aktif etme"):** `entegrasyon/app.py`'deki `/fatura/isle`,
> `/fatura/onayla`, `/kayitli-sirketler` endpoint'lerinden
> `Depends(require_api_token)` KALDIRILDI — bu üçü artık token OLMADAN
> çalışıyor, ağdaki (`BIND_HOST=0.0.0.0` ile açılmışsa herkesin erişebildiği)
> HERKES istek atabilir. Yerel ağda demo.html ile test ederken 401
> istenmediği için yapıldı, kalıcı bir karar DEĞİLDİR. `Mcp_mimarisi`
> tarafındaki `MCP_INTERNAL_API_TOKEN` kontrolü bundan ETKİLENMEDİ, hâlâ
> zorunlu. İlgili iki test (`test_business_endpoint_requires_token`,
> `test_wrong_token_is_rejected`, `entegrasyon/tests/test_api_security.py`)
> bilinçli olarak `@pytest.mark.skip` ile işaretlendi.
>
> **Geri almak için:** üç endpoint'e `dependencies=[Depends(require_api_token)]`
> geri ekle (import zaten `# noqa: F401` ile korunuyor,
> `entegrasyon/app.py` başında duruyor), iki test'teki `@pytest.mark.skip`
> dekoratörünü kaldır. Canlıya/paylaşılan bir ortama çıkmadan önce bu
> mutlaka geri alınmalı — aksi halde sistem tamamen açık kalır.

> ✅ **Uygulandı** (2026-09-11, kullanıcı isteği — canlıya çıkış hazırlığı,
> "önemli yerleri loglamak istiyorum"): Profesyonel/structured loglama
> eklendi. Yeni ortak modül `entegrasyon/log_ortak.py` (birebir kopyası
> `Mcp_mimarisi/src/efatura_kdv/log_ortak.py` — iki proje kod olarak
> birleştirilmediği için, bkz. üstteki değişmez kural #2, mantık ayrı ayrı
> tutulur ama birebir aynı kalmalı):
> - **JSON structured log** (varsayılan, `LOG_FORMAT=text` ile serbest metne
>   dönülebilir) — her satırda `zaman` (tarih dahil, önceden sadece saat
>   vardı), `seviye`, `logger`, `mesaj`, `request_id`.
> - **Request-ID korelasyonu** (`RequestIdMiddleware`, `contextvars` ile) —
>   her HTTP isteğine bir kimlik atanır, o istek boyunca çağrılan TÜM
>   logger'lara (httpx, core.mizan, vb.) otomatik taşınır, cevaba
>   `X-Request-ID` header'ı olarak eklenir. `entegrasyon` → `Mcp_mimarisi`
>   isteklerinde de aynı kimlik `X-Request-ID` header'ıyla taşınır
>   (`mcp_mimarisi_istemcisi.py::_auth_headers`) — iki servisin logları TEK
>   bir request_id ile birlikte aranabilir, gerçek testte doğrulandı.
> - **Log rotasyonu** — `LOG_DIR` verildiğinde `log_ortak.py::loglamayi_kur`
>   `RotatingFileHandler` (10MB x 5 dosya) ekler.
>   > ✅ **Düzeltildi** (2026-09-28, bu notun kendisi bayatlamıştı —
>   > kullanıcı kararıyla `baslat.sh` artık kullanılmıyor, sadece Docker):
>   > önceki metin "host modunda `baslat.sh` `.calistirma`'yı kullanır"
>   > diyordu ama bu YANLIŞTI — `baslat.sh` `LOG_DIR`'ı hiçbir zaman set
>   > ETMEMİŞTİ, bu yüzden `RotatingFileHandler` host modunda hiç
>   > kurulmuyordu; `.calistirma/*.log` dosyaları uygulamanın kendi
>   > rotasyonundan değil, `baslat.sh`'ın shell yönlendirmesinden
>   > (`>> .calistirma/....log`) geliyordu ve gerçekten sınırsız büyüyordu
>   > (bu, "önceden düzeltildi" denilen sorunun ta kendisiydi). Docker
>   > tarafında (`docker/supervisord.conf`) `LOG_DIR` de hiç set edilmez —
>   > bilinçli, uygulama sadece stdout'a JSON basar, container'da rotasyon
>   > sorumluluğu Docker'ın kendi log sürücüsündedir. Ama
>   > `docker-compose.yml`'de de rotasyon tanımlı DEĞİLDİ (varsayılan
>   > `json-file` sürücüsü sınırsız büyür) — `postgres`/`ollama`/`app`
>   > servislerinin üçüne de `logging: {driver: json-file, max-size: 10m,
>   > max-file: "5"}` (`x-log-rotasyonu` anchor'ı ile, `docker/
>   > docker-compose.yml`) eklenerek gerçek bir rotasyon sağlandı —
>   > `restart: unless-stopped` ile sürekli çalışan servislerin disk
>   > doldurmaması için. `baslat.sh`/host modu artık kullanılmadığından bu
>   > yol için ayrıca düzeltme yapılmadı.
> - **Tüm beklenmeyen hatalarda stack trace** — `entegrasyon/app.py`'ye
>   `Mcp_mimarisi/api.py`'deki gibi bir global `@app.exception_handler(Exception)`
>   eklendi (önceden yoktu, FastAPI'nin varsayılan 500'üne bırakılmıştı);
>   `except Exception` bloklarında `exc_info=True` eklendi.
> - **Auth reddi loglanıyor** (`auth.py`, her iki serviste) — token'ın
>   kendisi DEĞİL, sha256 parmak izinin ilk 8 karakteri loglanır (log
>   dosyası sızarsa token sızmasın diye).
> - **Audit log** (`entegrasyon.audit` logger'ı, `_audit_logla()`) — her
>   `/fatura/isle`/`/fatura/onayla` çağrısı için istemci IP + VKN +
>   invoice_id + yön + karar, ayrı JSON satırı olarak. Ham fatura XML'i
>   veya token bu satıra ASLA yazılmaz.
>
> ✅ **Uygulandı** (2026-09-28, kullanıcı kararı — "yerel ağım güvenli, IP
> adreslerini ve dosyaları loglarsak sorun olmaz, log kısmı sağlam olsun"):
> `_audit_logla()`'ya (`entegrasyon/app.py`) `dosya_adi` alanı eklendi —
> önceden bu bilgi SADECE `_test_kaydini_logla`'nın yazdığı Excel
> test-kayıt dosyasında vardı, asıl JSON audit satırında yoktu; "hangi
> dosyanın işlendiği" audit log'dan tek başına cevaplanamıyordu. Bu, auth'ın
> 3 endpoint'te (`/fatura/isle`, `/fatura/onayla`, `/kayitli-sirketler`)
> hâlâ GEÇİCİ olarak kapalı olduğu (yukarıdaki 🔴 not) bir dönemde IP+dosya
> izlenebilirliğini güçlendirmek için — kullanıcı, auth'u yerel ağda
> demo/test bitene kadar kapalı tutmayı, bunun yerine loglamayı
> sağlamlaştırmayı tercih etti. **Bu bir güvenlik ikamesi DEĞİLDİR** —
> loglama sadece SONRADAN "kim/ne zaman/hangi dosya" sorusuna cevap verir,
> isteği baştan ENGELLEMEZ; auth'suz geçen bir kötüye kullanım audit
> log'da görülür ama önlenmez. Auth'un canlıya çıkmadan önce geri
> eklenmesi gerekliliği (yukarıdaki 🔴 not) bundan ETKİLENMEDİ.
>
> **Otomatik yedekleme** (`scripts/otomatik-yedekleme.sh`, kullanıcı onayıyla
> crontab'a eklendi — her gün 03:00) — PostgreSQL (`pg_dump -F c`) +
> ChromaDB (`docker cp` ile `app` container'ından, tar.gz) `db-yedek/`
> altına tarih damgalı dosya olarak yazılır, 14 günden eski yedekler
> otomatik silinir. Önceden sadece elle alınmış TEK bir dump vardı,
> tekrarlanan/zamanlanmış yedekleme yoktu. Gerçek çalıştırmayla doğrulandı
> (`pg_restore --list` ile dump bütünlüğü teyit edildi).
>
> ✅ **Düzeltildi** (2026-09-28, `baslat.sh` kaldırılınca fark edildi):
> ChromaDB yedeği önceden host'taki `model_eval/vector_db/` dizininden
> alınıyordu — bu, `baslat.sh` (host modu) döneminde biriken bir kopyaydı.
> Sistem artık sadece Docker ile çalıştığından güncel/gerçek RAG verisi
> host dizininde DEĞİL, `docker-compose.yml`'deki `efatura-vector-db` named
> volume'ünde birikiyor (bkz. `docker-ile-calistirma.md` §5.5); host
> dizini yedeklemeye devam etmek sessizce **bayat/yanlış veriyi
> yedeklemek** anlamına geliyordu. Script artık `docker cp` ile
> `app` container'ının içinden (`com.docker.compose.service=app`
> etiketiyle bulunur, container adı proje dizin adına göre değişebildiği
> için isim yerine etiket kullanılır) kopyalıyor.
>
> **Kapsam dışı bırakıldı (kullanıcı kararı, ayrı ele alınabilir):** rate
> limiting, container başlarken otomatik `alembic upgrade head`, Prometheus/
> metrics endpoint'i, CI entegrasyonu — bkz. 2026-09-11 prod-readiness
> denetimi (konuşma geçmişi).

> ✅ **Uygulandı** (2026-09-11, kullanıcı kararı — "işlemleri sıraya alalım,
> hepsini aynı anda işlemeyelim"): Eş zamanlı fatura işleme sınırlaması
> eklendi. Yeni ortak modül `entegrasyon/es_zamanli_sinir.py` (birebir
> kopyası `Mcp_mimarisi/src/efatura_kdv/es_zamanli_sinir.py`) —
> `threading.Semaphore` tabanlı (endpoint'ler sync fonksiyon olduğu için
> `asyncio.Semaphore` DEĞİL). `MAX_ESZAMANLI_ISLEM` env var'ı ile ayarlanır
> (varsayılan 2). `entegrasyon/app.py::fatura_isle` ve
> `Mcp_mimarisi/api.py::fatura_kontrol_et`/`fatura_coklu_kontrol` artık
> `with fatura_isle_sirasi():` bloğu içinde çalışıyor — limiti aşan istekler
> **reddedilmez**, semaphore serbest kalana kadar bekler (rate limiting
> değil, kuyruklama). Gerçek threading testiyle doğrulandı (5 istek, her
> biri 0.5s, limit=2 → toplam ~1.5s, sınırsız olsaydı ~0.5s olurdu).
>
> **Gönderen kullanıcı bilgisi** (aynı kullanıcı isteği — "ilerde kaç fatura
> işlediğini loglarız"): `FaturaIsleIstegi`'ye opsiyonel `gonderen_kullanici`
> alanı eklendi (dış ekibin arayüzü login'den sonra doldurup gönderecek —
> **sistem bu bilgiyi doğrulamaz**, sadece `entegrasyon.audit` logger'ına
> işler). Henüz aktif kullanılmıyor (dış ekip entegrasyonu bekleniyor),
> sadece alan/loglama altyapısı hazır. Şema: `entegrasyon/docs/reference/
> dis-ekip-api-kullanimi.md`.

**Temiz çıkanlar** (bozmayın): SQL injection yok (tüm sorgular parametrize),
unsafe deserialization yok, gömülü API anahtarı yok, `sys.path` manipülasyonu
güvenli.

> ✅ **Uygulandı** (2026-09-25, bu notun kendisi bayatlamıştı — düzeltildi):
> `model_eval/core/single.py::_normalize_entries` hâlâ yalnızca format
> normalizasyonu yapıyor (kod/dc normalize, borç=alacak toplamı) — LLM'in
> verdiği 3 haneli kodu `TDHP_GLOSSARY`'ye karşı doğrulamıyor, tutarı
> faturanın `payable` değeriyle karşılaştırmıyor. AMA bu doğrulama artık
> **ayrı bir modülde var ve pipeline'a bağlı**: `model_eval/core/validation.py
> ::validate_prediction` (kod formatı, `TDHP_GLOSSARY` üyeliği, alt kod
> mizanda var mı, dc geçerliliği, borç=alacak, **ve `payable` ile borç
> toplamının uyuşması** dahil) — bunu `single.py` değil,
> `entegrasyon/model_eval_koprusu.py:182-186`'daki `faturayi_disa_aktar`
> sonrası çağırıyor ve sonucu `sonuc["approvable"]` bayrağına yazıyor. Bu
> bayrak `entegrasyon/app.py:555-559`'da `/fatura/onayla`'yı SUNUCU
> TARAFINDA reddediyor (`approvable=False` ise onaylanamaz; DB sorgusunda da
> `AND approvable = TRUE` şartı var, `model_eval_koprusu.py:302`). Yani
> disiplin ilk aşamada (`single.py`) yok ama sisteme bir bütün olarak
> (`entegrasyon` katmanı üzerinden) bağlı — sadece `model_eval/` tek başına
> incelenirse "hiç çağrılmıyor" gibi görünüyor, asıl çağıran taraf
> `entegrasyon`'dur.

> Not: Prompt injection yapısal olarak mümkün görünüyor (fatura not alanı
> prompt'a çitlemesiz giriyor) ama canlı LLM ile iki saldırı denendi, ikisi de
> başarısız oldu. "Güvenli" demek için yeterli kanıt yok; savunma modelin
> direncine bırakılmamalı.

## Bu oturumda öğrenilen pratik notlar

- **`arsiv/` klasörü bilinçli bir arşivdir**, çöp değil. Oradan bir şey
  silmeden önce sor.
- **Kök `CLAUDE.MD` ham bir prompt metnidir** (başlığı "Yeni Claude sohbetine
  yapıştırılacak prompt"). İçeriği geçerli, formatı düzensiz — yeniden
  yazılması gerekirse kullanıcıya sor.
- Belgeler arasında **`proje-calistirma.md` güncel olan**; `Mcp_mimarisi`
  altındaki eski kopyalar `arsiv/eski-dokuman/`'a taşındı (bayat yollar
  içeriyordu).
