# Proje Çalıştırma

> **Amaç:** Ön filtreleme (Mcp_mimarisi) → TDHP tahmini (model_eval) akışını
> baştan sona ayağa kaldırmak. Mimari/tasarım kararları için `PROJECT.md`'ye,
> entegrasyonun kendisi için `entegrasyon/README.md`'ye bakın.

## Hızlı yol — tek komut

```bash
./baslat.sh
```

Bu, aşağıdaki 3 adımı (PostgreSQL, Mcp_mimarisi API, entegrasyon servisi)
otomatik sırayla yapar: zaten çalışan servisleri atlar, eksik olanları
arka planda başlatır, sağlık kontrolü yapar ve sana `http://localhost:8100`
adresini verir. Loglar `.calistirma/` altında (`mcp_mimarisi_api.log`,
`entegrasyon.log`) — bir şey beklediğin gibi çalışmazsa önce oraya bak.

> ✅ **Uygulandı (2026-07-23):** Log dosyaları artık her `./baslat.sh`
> çalıştırmasında **üzerine yazılmıyor** (`baslat.sh` — `>` yerine `>>` ile
> append). Her yeni oturum başladığında dosyanın sonuna
> `--- TARİH SAAT yeni oturum başladı ---` satırı ekleniyor, böylece eski
> ve yeni çalıştırmaların logları aynı dosyada birbirinden ayırt edilebilir.
> Dosyalar zamanla büyüyeceği için gerekirse elle temizle (`> dosya` ile
> sıfırlamak veya `rm` ile silmek serbest — script bir sonraki
> çalıştırmada dosyayı yoksa/boşsa sorunsuz yeniden oluşturur/ekler).

Durdurmak için:

```bash
./durdur.sh
```

(PostgreSQL container'ını ve Ollama'yı bilerek durdurmaz — onlar başka
işler için de kullanılıyor olabilir; gerekirse `durdur.sh`'ın çıktısındaki
komutları elle çalıştır.)

### Her adımı canlı terminalde izlemek

Bir fatura işlerken arka planda ne olduğunu (Mcp_mimarisi'ne giden istek,
NACE kontrolü, model_eval'a giden çağrı, LLM cevabı) adım adım, gerçek
zamanlı görmek için iki log dosyasını birlikte izle:

```bash
tail -f .calistirma/mcp_mimarisi_api.log .calistirma/entegrasyon.log
```

Arayüzde (`http://localhost:8100`) bir fatura gönderdiğinde bu terminalde
sırayla şu adımları göreceksin:

```
[MCP 1/3] İSTEK — satici_vkn=..., xml_boyutu=... byte
[MCP 1/3] AYRIŞTIRILDI — fatura_no=..., kalem_sayisi=...
[MCP 2/3] NACE KURAL KONTROLÜ ÇALIŞTIRILIYOR
  KALEM #1 (...): beyan edilen oran(lar)=[...] | havuz=[...] | ...
[MCP 3/3] SONUÇ — genel_karar=..., satir_sayisi=...
                                                    ↓ (entegrasyon.log'a geçiş)
[1/4] İSTEK ALINDI — ...
[2/4] MCP_MIMARISI'NE GÖNDERİLİYOR
[2/4] MCP_MIMARISI CEVABI (0.02s) — genel_karar=...
[3/4] KARAR: DEVAM / DURDURULDU
[4/4] MODEL_EVAL'A GÖNDERİLİYOR — (RAG + LLM, uzun sürebilir)
[4/4] MODEL_EVAL CEVABI (X.XXs) — kalem_sayisi=..., balanced=...
TAMAMLANDI — toplam süre X.XXs
```

Her adımın süresi (`X.XXs`) yanında yazıyor — hangi adımın yavaş olduğunu
buradan görebilirsin (örn. model_eval adımı 40s+ sürüyorsa muhtemelen SSH
tüneli/model erişiminde bir sorun var, bkz. "Sık karşılaşılan sorunlar").

**İlk çalıştırmada** `baslat.sh` kendi izole bir Python ortamı kurar
(`.calistirma/mcp_venv`, `entegrasyon/.venv`) — bu birkaç dakika sürebilir,
sonraki çalıştırmalarda anında başlar. PostgreSQL container'ı hiç
oluşturulmamışsa (ilk kurulum) script sana NACE verisini yüklemen gereken
tek seferlik komutu gösterir (`Mcp_mimarisi/scripts/excel_to_postgres.py`).

---

## Manuel adımlar (`baslat.sh` içeride ne yapıyor)

Aşağıdaki adımları `baslat.sh` senin yerine otomatik yapıyor — ama bir
sorunu elle teşhis etmen gerekirse veya script'siz çalıştırmak istersen
diye adım adım da yazıldı.

Sistem 3 ayrı süreçten oluşur, bu sırayla başlatılmalı:

```
1. PostgreSQL (Docker)          — Mcp_mimarisi'nin NACE/oran verisini tutar
2. Mcp_mimarisi API (port 8000) — KDV/mevzuat ön filtreleme
3. entegrasyon servisi (port 8100) — ön filtre + TDHP tahmini orkestrasyonu + arayüz
```

`model_eval` ayrı bir süreç DEĞİLDİR — `entegrasyon` servisi onu doğrudan
Python import ile çağırır, ayrıca başlatmana gerek yok. Ama `model_eval`'ın
RAG özelliği kullanılıyorsa (varsayılan öyle) **Ollama**'nın da yerelde
çalışıyor olması gerekir (adım 2.5).

---

## 0. Önce mevcut durumu kontrol et

Bir şeyi zaten çalışıyor olabilir (özellikle Docker container'ı kapatıp
açmıyorsan sürekli açık kalır). Sıfırdan başlatmadan önce kontrol et:

```bash
# PostgreSQL container ayakta mı?
docker ps --filter "name=efatura-kdv-postgres" --format "{{.Names}}: {{.Status}}"

# Mcp_mimarisi API (port 8000) çalışıyor mu?
lsof -i :8000 | grep LISTEN

# entegrasyon servisi (port 8100) çalışıyor mu?
lsof -i :8100 | grep LISTEN

# Ollama (port 11434) çalışıyor mu?
lsof -i :11434 | grep LISTEN
```

Bir satır dönüyorsa o servis zaten ayakta — o adımı atlayabilirsin.
Hiçbir şey dönmüyorsa aşağıdaki adımlarla sıfırdan başlat.

---

## 1. PostgreSQL'i ayağa kaldır (Mcp_mimarisi'nin veritabanı)

Container daha önce hiç oluşturulmadıysa:

```bash
docker run --name efatura-kdv-postgres \
    -e POSTGRES_USER=efatura \
    -e POSTGRES_PASSWORD=efatura \
    -e POSTGRES_DB=efatura_kdv \
    -p 5434:5432 \
    -d postgres:16
```

> ⚠️ Port **5434** kullanılıyor, 5432 değil — bu makinede 5432/5433 zaten
> başka PostgreSQL kurulumları tarafından kullanılıyor. Docker kurulu
> değilse `brew install --cask docker`, sonra Docker Desktop'ı aç (ilk
> kurulum izinlerini tamamla, "manually paused" ise unpause et).

Container daha önce oluşturulduysa ama şu an durduysa, tekrar `docker run`
ETME (aynı isimde container zaten var, hata verir) — bunun yerine:

```bash
docker start efatura-kdv-postgres
```

**Bağlantı bilgisini env var olarak ayarla** (Mcp_mimarisi API'sinin
ihtiyacı var):

```bash
export DATABASE_URL="postgresql://efatura:efatura@localhost:5434/efatura_kdv"
```

**İlk kurulumda** (veritabanı boşsa) NACE/oran verisini yükle:

```bash
cd Mcp_mimarisi
python3 -m pip install -r requirements.txt
python3 scripts/excel_to_postgres.py
```

Bu betik idempotent — tekrar çalıştırmak veriyi bozmaz, güvenle tekrar
doldurur. Geçmiş fatura çapraz kontrolü de kullanılacaksa (opsiyonel):

```bash
python3 scripts/gecmis_faturalari_yukle.py
```

Detay: `Mcp_mimarisi/docs/how-to/postgres-kurulum.md`.

---

## 2. Mcp_mimarisi API'sini başlat (port 8000)

```bash
cd Mcp_mimarisi
export DATABASE_URL="postgresql://efatura:efatura@localhost:5434/efatura_kdv"
python3 -m uvicorn efatura_kdv.api:app --app-dir src --host 0.0.0.0 --port 8000
```

> Not: `uvicorn` komutu doğrudan PATH'te değilse ("command not found")
> `python3 -m uvicorn ...` şeklini kullan (yukarıdaki komut zaten bunu
> yapıyor).

Başladığında doğrula:

```bash
curl -s http://localhost:8000/saglik
```

Beklenen cevap: `{"durum":"ayakta","nace_tablosu_yuklu":true}`. `false`
dönerse veya bağlantı hatası alırsan adım 1'e (DATABASE_URL / migrasyon)
geri dön.

### 2.5. Ollama'yı çalıştır (RAG için gerekli — model_eval tarafı)

`entegrasyon` servisi TDHP tahmini için varsayılan olarak RAG'ı (`rag=True`)
kullanır, bu da yerel bir Ollama sunucusu gerektirir:

```bash
ollama serve
```

(Genelde arka planda zaten çalışıyor olabilir — `lsof -i :11434` ile
kontrol et, dönüyorsa bu adımı atla.)

Detay: `Mcp_mimarisi/docs/how-to/api-calistirma.md`.

### 2.6. Bulut modeli (gemma4:31b-cloud) kullanılıyorsa: SSH tüneli gerekir

TDHP tahmininde varsayılan model `gemma4:31b-cloud` — bu, Ollama'nın kendi
**bulut** modeli (ollama.com hesabına bağlı), yerel Ollama'da (port 11434)
DEĞİL, uzak GPU sunucusunda (`unlem-gx10-01`) çalışıyor. Erişim için SSH
tüneli açık olmalı:

```bash
ssh -N -L 11435:localhost:11434 unlem-gx10-01@10.34.10.112
```

(Detay: `sunucu-yönlendirme.md`, `çalıştırma.txt`.) `entegrasyon/
model_eval_koprusu.py` bu tüneli varsayılan olarak kullanır
(`http://localhost:11435`); farklı bir port/tünel kullanıyorsan
`MODEL_EVAL_OLLAMA_HOST` env var'ı ile override et.

Tünel açık değilse TDHP tahmini adımında `401 Kimlik dogrulama hatasi`
alırsın — ön filtreleme (Mcp_mimarisi) bundan etkilenmez, sadece TDHP
tahmini adımı hata döner.

---

## 3. entegrasyon servisini başlat (port 8100)

Bu, ön filtreleme + TDHP tahmini akışını birleştiren servis — test
arayüzü de burada.

**İlk kurulumda** bağımlılıkları kur (model_eval'ın kendi bağımlılıkları da
dahil, çünkü bu servis model_eval'ı doğrudan import eder):

```bash
cd entegrasyon
python3 -m venv .venv
./.venv/bin/pip install -r requirements.txt
```

**Başlat:**

```bash
cd entegrasyon
DATABASE_URL="postgresql://efatura:efatura@localhost:5434/efatura_kdv" \
  ./.venv/bin/uvicorn app:app --host 0.0.0.0 --port 8100
```

> ✅ **Uygulandı (2026-07-23):** `DATABASE_URL` artık entegrasyon servisi
> için de ZORUNLU — `POST /fatura/onayla` (kullanıcının "bu doğru, kaydet"
> onayı) `model_eval/core/reporting.py::append_result` üzerinden
> `model_eval_sonuclar` tablosuna yazıyor (`file_label="entegrasyon_onaylandi"`).
> `DATABASE_URL` verilmezse `/fatura/isle` (tahmin üretme) gayet çalışır,
> ama `/fatura/onayla` çağrıldığında `RuntimeError` ile 500 döner —
> `baslat.sh` bunu otomatik geçiyor, sadece manuel başlatmada unutma.

Başladığında doğrula:

```bash
curl -s http://localhost:8100/durum
```

Beklenen: `{"model_eval_hazir":true,"model_eval_mesaj":"hazır"}`.
`model_eval_hazir: false` dönerse mesajı oku — hangi dosya/paket eksik
olduğunu açıkça söyler (örn. bir Python paketi kurulu değil).

---

## 4. Tarayıcıda arayüzü aç

```
http://localhost:8100
```

Adımlar:
1. Bir UBL-TR XML fatura dosyası seç (örn. `Mcp_mimarisi/ubls/` altındaki
   `*-outbox.xml` dosyalarından biri — bunlar gerçek, kestiğimiz faturalar).
2. Satıcının VKN'sini gir (şirketin kendi VKN'si, örn. `0460351893`).
3. Satıcının NACE kod(lar)ını gir (virgülle ayrılmış, örn. `251106`).
4. "Ön Filtreden Geçir"e bas.
5. Sonuç `uygun` ise otomatik olarak TDHP tahmini (hesap kodu + Borç/Alacak
   + tutar tablosu) gösterilir. `insan_incelemesi_gerekli` ise bir uyarı
   çıkar — "yine de devam et" ile onaylayıp TDHP tahminine geçebilir ya da
   iptal edebilirsin.

### Toplu (çoklu) fatura işlemek

Arayüzün üstündeki **"Toplu İşlem"** sekmesine geç (2026-07-27 eklendi):

1. Birden çok `.xml` dosyası seç (ya da hepsini birden sürükle-bırak).
2. Tek ortak VKN + NACE gir — **tüm** faturalara uygulanır (aynı şirketin
   faturaları işlendiği için VKN hep aynıdır).
3. "Toplu İşle"ye bas. Sistem hiç durmadan tüm faturaları sırayla işler,
   sonuçları tek bir tabloda gösterir (dosya · yön · ön filtre · durum ·
   TDHP özeti).
4. İnsan incelemesi ya da kur seçimi gereken faturalar **"⏳ Onay
   Bekleyenler"** bölümüne alınır (atlanmaz). Oradaki butonla onayladığında
   (yine de devam / kur seç) o fatura hesaplanıp sonuç tablosunun **başına**
   eklenir. Detay: `entegrasyon/README.md` "Arayüzde toplu işlem".

---

## Servisleri durdurma

```bash
# entegrasyon ve Mcp_mimarisi API'sini durdurmak için: terminalde Ctrl+C
# (arka planda başlattıysan) çalışan process'i bul ve durdur:
lsof -i :8100 | grep LISTEN   # PID'i not al
kill <PID>
lsof -i :8000 | grep LISTEN
kill <PID>

# PostgreSQL container'ını durdurmak (veriyi SİLMEZ, sadece durdurur):
docker stop efatura-kdv-postgres
```

> Container'ı `docker rm` ile SİLME — içindeki NACE/geçmiş-fatura verisi
> gider, tekrar migrasyon çalıştırman gerekir. Sadece `docker stop`/
> `docker start` kullan.

---

## Sık karşılaşılan sorunlar

| Belirti | Muhtemel sebep | Çözüm |
|---|---|---|
| `entegrasyon`'da `/fatura/isle` → 502 | Mcp_mimarisi API (port 8000) çalışmıyor | Adım 2'yi tekrarla |
| `/fatura/isle` → 500, TDHP tahmini adımında | Ollama çalışmıyor / model indirilmemiş | `ollama serve` çalıştır, `ollama pull gemma4:31b-cloud` (veya kullanılan model) |
| `tdhp_tahmini.error`: `401 Kimlik dogrulama hatasi` | `gemma4:31b-cloud` bulut modeli, SSH tüneli (adım 2.6) kapalı/uzak sunucuya bağlı değil | `ssh -N -L 11435:localhost:11434 unlem-gx10-01@10.34.10.112` tünelini aç |
| `/durum` → `model_eval_hazir: false` | `entegrasyon/.venv`'de model_eval'ın bağımlılıkları eksik | `./.venv/bin/pip install -r requirements.txt` (entegrasyon dizininde) tekrar çalıştır |
| Mcp_mimarisi API başlarken `RuntimeError` | `DATABASE_URL` set değil | Adım 1'deki `export DATABASE_URL=...` komutunu çalıştır |
| `docker run` → "address already in use" | Port 5434 başka bir şey tarafından kullanılıyor | `Mcp_mimarisi/docs/how-to/postgres-kurulum.md`'deki port notuna bak, gerekirse farklı bir host portu seç |

---

## İlgili belgeler

- Genel workspace haritası: [`PROJECT.md`](PROJECT.md)
- Entegrasyon servisinin kendi detayı: [`entegrasyon/README.md`](entegrasyon/README.md)
- Mcp_mimarisi API detayı: [`Mcp_mimarisi/docs/how-to/api-calistirma.md`](Mcp_mimarisi/docs/how-to/api-calistirma.md)
- PostgreSQL kurulumu detayı: [`Mcp_mimarisi/docs/how-to/postgres-kurulum.md`](Mcp_mimarisi/docs/how-to/postgres-kurulum.md)
