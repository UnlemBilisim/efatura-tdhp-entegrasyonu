# Güvenlik Durumu ve Tarama Bulguları (2026-07-27)

> **Tür:** explanation — bulguların NEDEN böyle değerlendirildiği ve hangi
> kararların bilinçli alındığı.
>
> **Kapsam:** 30 Python dosyası (~6.100 satır) + web arayüzü, 5 odak alanında
> statik inceleme. Metodoloji:
> [anthropics/defending-code-reference-harness](https://github.com/anthropics/defending-code-reference-harness)
> `/vuln-scan` skill'i.
>
> ⚠️ **Bu belge bir durum kaydıdır, düzeltme raporu değildir.** Aşağıdaki
> açıklar 2026-07-27 itibarıyla **giderilmemiştir.**

## Neden bu tarama yapıldı

Sistem gerçek şirket mali verisi işliyor (1.829 gerçek fatura, gerçek VKN'ler,
şirkete özel hesap planı). Dış ekibe API verilmesi gündeme gelince,
"iç geliştirme aracı" varsayımının hâlâ geçerli olup olmadığı sorgulandı.

## Doğrulanmış açıklar

Bunların hepsi **çalıştırılarak** doğrulandı, kod okumasına dayanmıyor.

### 1. XSS — test arayüzünde (YÜKSEK, kapsam dışı bırakıldı)

`entegrasyon/static/index.html` untrusted fatura alanlarını escape'siz
`innerHTML`'e yazıyor — 16 kullanım, tek bir escape fonksiyonu yok.

Kanıt (parser çıktısı gözlemlendi):

```
XML'de:  &lt;img src=x onerror=alert(1)&gt;
parser:  '<img src=x onerror=alert(1)>'      ← ham HTML
index.html:311 üretir:  <td><img src=x onerror=alert(1)></td>
```

**Karar (kullanıcı, 2026-07-27):** Düzeltilmedi. Arayüzü dış ekip yazacak; bu
dosya bizim yerel test aracımız. **Dayandığı varsayım:** yalnızca yerel
kullanım. Bu varsayım çökerse (arayüz birine gösterilirse/dağıtılırsa) açık
gerçek hale gelir.

Dış ekibe bu risk açıkça bildirildi
([`../../entegrasyon/docs/reference/dis-ekip-api-kullanimi.md`](../../entegrasyon/docs/reference/dis-ekip-api-kullanimi.md) §0)
— aynı hatayı tekrarlamamaları için.

### 2. XML entity expansion (YÜKSEK)

Her iki parser da korumasız `xml.etree.ElementTree` kullanıyor:
`Mcp_mimarisi/src/efatura_kdv/ubl_parser.py:249` ve
`model_eval/core/parsing.py:130`.

Ölçüm (bu makinede, Python 3.9.6 / expat 2.2.8):

| Girdi | Çıktı | Çarpan |
|---|---|---|
| 463 byte | 1.000.000 karakter | **2.159x** |

**XXE ise YOK** — bunu ayrıca test ettim: `SYSTEM "file:///etc/passwd"`
denemesi `ParseError: undefined entity` veriyor. ElementTree harici entity
çözmüyor. Bu ayrım önemli: rapor "XXE var" derse yanlış olurdu.

İkinci sink daha kritik: `parsing.py` `/fatura/isle`'nin **ilk** işi olan yön
tespitinde çağrılıyor, yani Mcp_mimarisi hiç devreye girmeden tetiklenir ve
inbox akışında tek koruma katmanı bile yok.

### 3. Kimlik doğrulama yok (YÜKSEK)

8 endpoint'in (Mcp 4 + entegrasyon 4) hiçbirinde auth yok —
`Depends|APIKey|HTTPBearer|Authorization` araması boş döndü. Üstelik
`baslat.sh` ikisini de `0.0.0.0`'a bind ediyor.

İkisi kalıcı veri yazıyor: `/fatura/coklu-kontrol` (PostgreSQL) ve
`/fatura/onayla` (PostgreSQL + ChromaDB RAG).

### 4. `/fatura/onayla` istemci verisini doğrulamıyor (YÜKSEK)

Gönderilen `tdhp_tahmini`'nin sunucu tarafından üretildiği teyit edilmiyor —
imza, nonce, sunucu tarafı oturum yok. `balanced`/`borc_toplam` da istemcinin
iddiası, yeniden hesaplanmıyor.

**Bu, en sinsi olan:** LLM'i kandırmaya gerek yok, bu yol LLM'i tamamen
atlıyor. Yazılan kayıt RAG havuzuna girdiği için sonraki tahminleri kalıcı
olarak yönlendirir.

### 5. Gömülü DB parolası (ORTA) — ✅ Düzeltildi (2026-07-28)

> ✅ **Uygulandı** (2026-07-28): `baslat.sh:15`'teki gömülü `efatura:efatura`
> parolası kaldırıldı. `POSTGRES_PASSWORD` artık zorunlu env var
> (`: "${POSTGRES_PASSWORD:?...}"`) — tanımlı değilse script açıkça hata
> verip durur, gömülü/varsayılan bir parolaya düşmez. `docker/docker-compose.yml`
> tarafında bu disiplin zaten baştan uygulanmıştı. Gerçek testte doğrulandı:
> env var olmadan `POSTGRES_PASSWORD env var tanımlı olmalı` hatasıyla
> durdu, doğru parolayla servisler sağlıklı ayağa kalktı.

Aşağıdaki metin, düzeltme öncesi durumu tarihsel kayıt olarak korur:

~~`baslat.sh:15` — `efatura:efatura` (parola = kullanıcı adı), env'den geleni
koşulsuz eziyor. Postgres `-p 5434:5432` ile tüm arayüzlere açık.~~

**Uygulama kodu bu konuda zaten doğru yazılmıştı** — üç modül de
`DATABASE_URL`'i env'den okuyup yoksa `RuntimeError` veriyordu, gömülü
fallback yoktu. Zafiyet yalnızca başlatma scriptindeydi, artık orası da
düzeltildi.

## Prompt injection: yapısal açık var, sömürü gösterilemedi

Fatura not alanı (`cbc:Note`), kalem adı ve karşı taraf unvanı LLM prompt'una
**çitlemesiz** giriyor (`prompting.py:313`) ve prompt'un kendisi `###` başlık
yapısı kullanıyor — yani saldırgan sahte bölüm açabilir.

Canlı LLM ile (`gemma4:31b-cloud`, tünel açık) iki saldırı denendi:

| Varyant | Sonuç |
|---|---|
| Sahte `### SISTEM GUNCELLEMESI` + hazır JSON (250.000 TL) | Model **direndi** |
| Sahte `[GUCLU ESLESME]` emsal bloğu + kalem adına yönlendirme | Model **direndi** |

İkisinde de doğru kodlar üretildi. Bu yüzden bulgu **PLAUSIBLE**, CONFIRMED
değil — ve severity düşürüldü.

**Ama "güvenli" demek için yeterli kanıt yok:** iki denemenin başarısız olması
sistematik bir savunma olduğunu kanıtlamaz. Başka model, başka payload veya
prompt'un ilerideki bir değişikliği sonucu değiştirebilir. **Savunma modelin
direncine bırakılmamalı** — asıl kontrol §"Eksik savunma"da.

## Eksik savunma: çıktı doğrulaması

`model_eval/core/single.py::_normalize_entries` LLM'in verdiği 3 haneli kodu
`TDHP_GLOSSARY`'ye karşı **doğrulamıyor** (`normalize_code3` sadece ilk 3
rakamı regex ile çekiyor) ve tutarı faturanın `payable` değeriyle
karşılaştırmıyor. Tek kontrol `borç == alacak` — o da modelin kendi sayılarını
birbiriyle karşılaştırıyor.

**Mimari gözlem:** Doğru desen zaten kodda mevcut. Alt kırılım adımı
(`single.py:460`) LLM'in seçimini mizana karşı allowlist'e sokuyor ve
halüsinasyonu atıyor. Aynı disiplin ilk aşamada uygulanmamış. Bu, prompt
injection dahil tüm LLM-kaynaklı hataları sınırlayan **tek gerçek kontrol**
olurdu.

## Temiz çıkanlar (bozmayın)

Bunların yokluğu da bir bulgudur — doğru yapılmış:

| Kontrol | Sonuç |
|---|---|
| SQL injection | **Yok** — ~15 sorgunun hepsi parametrize (`%s` + tuple), untrusted XML alanları dahil |
| XXE | **Yok** — test edildi, harici entity çözülmüyor |
| Unsafe deserialization | **Yok** — `pickle`/`yaml.load`/`eval`/`exec`/`subprocess` hiç yok |
| Gömülü API anahtarı | **Yok** — hepsi env'den okunuyor |
| `sys.path` manipülasyonu | **Güvenli** — yol `__file__` türevli, dizin yazılabilir değil, stdlib çakışması yok |
| Path traversal | **Yok** — hiçbir kullanıcı girdisi `open()`'a ulaşmıyor |

## Öncelik sırası (öneri)

Kapsam "backend teslimi + sunucu-sunucu çağrı" olduğu için sıralama:

1. **Auth + `127.0.0.1` bind** — en yüksek etki, en az iş. Dış ekip
   entegrasyonu için de gerekli (token başlığı).
2. **`_normalize_entries` allowlist + tutar mutabakatı** — LLM çıktısını
   disiplin altına alır; desen zaten kodda var.
3. **`/fatura/onayla` sunucu tarafı doğrulama** — RAG zehirlenmesini kapatır.
4. **`defusedxml`** — iki dosyada birer satır.
5. **`baslat.sh` parolası** — env'den okuma + `127.0.0.1` bind.

XSS, arayüz teslim kapsamı dışı olduğu için listede yok — ama yerel kullanım
varsayımı değişirse birinci sıraya çıkar.

## Bağlama bağlı iki bulgu

Bunların ciddiyeti **sistemin çok müşteriye hizmet verip vermeyeceğine** bağlı;
bu soru 2026-07-27 itibarıyla yanıtlanmadı:

- **`islenmis_faturalar` tenant-scoped değil** (`gecmis_kontrol.py:227`) —
  claim tablosu `fatura_no TEXT PRIMARY KEY`, ama koruduğu veri `satici_vkn`
  bazlı. Tek şirkette etki düşük (kaza eseri numara çakışması), çok müşteride
  yüksek (bir müşteri diğerinin geçmiş kontrolünü bozabilir).
- **`/fatura/gecmis-kontrol` keyfi VKN sorgusu** (`api.py:308`) — VKN'ler
  Türkiye'de kamuya açık; çok müşterili kurulumda rakip firma verisi okunabilir.
