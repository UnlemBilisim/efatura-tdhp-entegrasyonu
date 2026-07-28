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
3. **Ön filtreleme yalnızca outbox faturalara uygulanır.** inbox'ta
   `Mcp_mimarisi` HİÇ çağrılmaz (gerekçe: başkasının kestiği faturanın mevzuat
   sorumluluğu bizde değil). Yön, XML'den tespit edilir — kullanıcıya sorulmaz.
4. **İki bileşen aynı PostgreSQL'i paylaşır, farklı tabloları kullanır.**
   `nace_oranlari`/`gecmis_fatura_kalemleri` (Mcp_mimarisi) ve
   `model_eval_sonuclar` (model_eval) — birbirinin tablosuna dokunmazlar.
5. **KDV uygunluğu LLM'e sorulmaz.** Mevzuat kontrolü deterministik kalır;
   LLM yalnızca muhasebe kaydı için kullanılır.
6. **`records[]`/`dis_sema` dış sözleşmesi, iç şemadan TÜRETİLİR.** İç tarafta
   `entries[]` + `dc="Borc"/"Alacak"` kalır (205 test + DB + RAG buna bağlı);
   dönüşüm yalnızca `model_eval/core/disa_aktarim.py`'de yapılır. Şema
   sözleşmesi:
   [`model_eval/docs/reference/dis-ekip-kayit-semasi.md`](model_eval/docs/reference/dis-ekip-kayit-semasi.md).
   Dış ekibin API kullanımı (istek/cevap, onay akışı):
   [`entegrasyon/docs/reference/dis-ekip-api-kullanimi.md`](entegrasyon/docs/reference/dis-ekip-api-kullanimi.md).
   Bu iki belge dış sözleşmedir — değiştirirsen karşı taraf kırılır, önce sor.

## Çalıştırmak için gerekenler (sık atlanan)

`./baslat.sh` üç dış bağımlılık ister; biri eksikse ilgili adım sessizce
çalışmaz, hata mesajı ilk bakışta yanıltıcı olabilir:

| Gereksinim | Eksikse ne olur |
|---|---|
| **Docker Desktop açık** | PostgreSQL başlamaz → ön filtreleme çalışmaz |
| **SSH tüneli (11435)** | LLM'e erişilemez → TDHP tahmini boş `entries` döner |
| **Ollama (11434)** | RAG embedding çalışmaz |

SSH tünel komutu [`çalıştırma.txt`](çalıştırma.txt) içinde. Tünel parola
istiyor — ajan açamaz, kullanıcı açmalı.

> ⚠️ **Tuzak:** LLM erişimi yoksa `predict_single_invoice` hata fırlatmaz;
> `error` alanı dolu, `entries` boş döner. `records: []` görünce "kodum
> bozuldu" sanmak yerine önce tüneli kontrol et (bu oturumda bir kez yaşandı).

## Test etme

```bash
cd model_eval && python3 -m pytest tests/ -q     # 205 test
```

- **PostgreSQL kapalıysa** 22 test otomatik `skip` edilir
  (`requires_postgres` marker'ı) — bu bir hata değildir.
- Sistem `.venv` kullanıyorsa `pytest` bulunamayabilir; `/usr/bin/python3 -m
  pytest` ile sistem python'unu kullan.
- **Prod DB'sine (`DATABASE_URL`) test verisi yazma** — ayrı bir test
  veritabanı kullan.

Bir özelliği "tamamlandı" saymadan önce gerçekten çalıştır: `./baslat.sh` +
`POST /fatura/isle` ile gerçek bir fatura işle. Kodu okuyup "böyle çalışması
lazım" demek yeterli değildir (kök CLAUDE.MD §3).

## Bilinen güvenlik durumu (2026-07-27 taraması)

Statik güvenlik taraması yapıldı; **düzeltmeler henüz uygulanmadı.** Yeni kod
yazarken bunları kötüleştirmemeye dikkat et:

> **Kapsam notu (2026-07-27, kullanıcı kararı):** Arayüzü **dış ekip yazacak**;
> biz yalnızca backend teslim ediyoruz. Çağrı **sunucu-sunucu** olacağı için
> CORS bilinçli olarak yapılandırılmamıştır (tarayıcıdan çağrı denenirse
> preflight 405 döner). `entegrasyon/static/index.html` bizim kendi manuel
> test aracımızdır — teslim kapsamında değil, ama bizde kalıyor.

**Doğrulanmış açıklar:**
- **XSS** — `entegrasyon/static/index.html` untrusted fatura alanlarını
  escape'siz `innerHTML`'e yazıyor (16 kullanım, escape fonksiyonu yok).
  Teslim kapsamı dışı olduğu için düzeltilmedi (kullanıcı kararı), ama
  **yalnızca yerel test kullanımı** varsayımına dayanıyor: kötü niyetli bir
  faturayı bu arayüzde açmak riskli. Yeni bir alanı arayüze taşırken escape et.
- **XML entity expansion** — hem `Mcp_mimarisi/src/efatura_kdv/ubl_parser.py`
  hem `model_eval/core/parsing.py` korumasız `ET` kullanıyor (463 byte → 1 MB
  ölçüldü). XXE **yok** (harici entity çözülmüyor, test edildi).
- **Kimlik doğrulama yok** — 8 endpoint'in (Mcp 4 + entegrasyon 4) hiçbirinde
  auth yok, üstelik `baslat.sh` ikisini de `0.0.0.0`'a bind ediyor.
- **`/fatura/onayla` istemci verisini doğrulamıyor** — gönderilen tahmini
  sunucu kendisinin ürettiğini teyit etmeden PostgreSQL + RAG'a yazıyor.
- **`baslat.sh`'te gömülü DB parolası** (`efatura:efatura`). Uygulama kodu
  doğru yazılmış (env'den okur, yoksa hata verir) — sorun sadece scriptte.

**Temiz çıkanlar** (bozmayın): SQL injection yok (tüm sorgular parametrize),
unsafe deserialization yok, gömülü API anahtarı yok, `sys.path` manipülasyonu
güvenli.

**Eksik savunma:** `model_eval/core/single.py::_normalize_entries` LLM'in
verdiği 3 haneli kodu `TDHP_GLOSSARY`'ye karşı doğrulamıyor ve tutarı faturanın
`payable` değeriyle karşılaştırmıyor. Alt kırılım adımı bunu doğru yapıyor
(`single.py:460` mizana karşı allowlist) — aynı disiplin ilk aşamada yok.

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
