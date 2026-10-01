# Proje Çalıştırma

> **Amaç:** Ön filtreleme (Mcp_mimarisi) → TDHP tahmini (model_eval) akışını
> baştan sona ayağa kaldırmak. Mimari/tasarım kararları için `PROJECT.md`'ye,
> entegrasyonun kendisi için `entegrasyon/README.md`'ye bakın.

> ✅ **Uygulandı** (2026-09-28, kullanıcı kararı — "baslat.sh'ı kaldırabilir
> miyiz artık, docker konteynırım çalışınca otomatik başlasın herşey"):
> `baslat.sh`/`durdur.sh` (host modunda üç süreci elle ayağa kaldıran
> script'ler) **kaldırıldı**. Tek çalıştırma yolu artık Docker — detaylı
> adımlar: [`docs/how-to/docker-ile-calistirma.md`](docs/how-to/docker-ile-calistirma.md).
> `docker-compose.yml`'deki `restart: unless-stopped` sayesinde Docker
> Desktop/daemon her açıldığında üç servis (postgres, ollama, app) otomatik
> ayağa kalkar — ayrıca bir script çalıştırmaya gerek yok.

## Hızlı yol — Docker

```bash
cd docker/
cp ../.env.example ../.env
# .env içindeki sırları (POSTGRES_PASSWORD, MCP_INTERNAL_API_TOKEN)
# güçlü ve benzersiz değerlerle değiştirin
POSTGRES_PASSWORD="<parola>" MCP_INTERNAL_API_TOKEN="<token>" docker compose up -d

# İlk kurulumda arayüz/istemci için bir API anahtarı üretin
# (değer yalnızca bir kez gösterilir, arayüzdeki "API anahtarı" alanına girin):
docker compose exec app python3 /app/entegrasyon/api_anahtari_yonet.py \
  olustur --etiket yerel-demo --tum-sirketler
```

Ayrıntılı adımlar (registry'den image çekme, PostgreSQL/ChromaDB verisini
geri yükleme, SSH tünel kurulumu, sağlık kontrolü, sorun giderme):
[`docs/how-to/docker-ile-calistirma.md`](docs/how-to/docker-ile-calistirma.md).

Durdurmak için:

```bash
cd docker/
POSTGRES_PASSWORD="<aynı-parola>" docker compose down
```

### Her adımı canlı terminalde izlemek

```bash
docker compose logs -f app
```

Bir fatura işlerken arka planda ne olduğunu (Mcp_mimarisi'ne giden istek,
NACE kontrolü, model_eval'a giden çağrı, LLM cevabı) adım adım, gerçek
zamanlı görmek için bu komutla container loglarını izle. Aynı isteğin
Mcp_mimarisi ve entegrasyon taraflarındaki log satırları `request_id` alanı
üzerinden birbirine bağlanabilir (bkz. `CLAUDE.md` "Audit log" notu).

Arayüzde (`http://localhost:8100`) bir fatura gönderdiğinde şu adımları
göreceksin:

```
[MCP 1/3] İSTEK — satici_vkn=..., xml_boyutu=... byte
[MCP 1/3] AYRIŞTIRILDI — fatura_no=..., kalem_sayisi=...
[MCP 2/3] NACE KURAL KONTROLÜ ÇALIŞTIRILIYOR
  KALEM #1 (...): beyan edilen oran(lar)=[...] | havuz=[...] | ...
[MCP 3/3] SONUÇ — genel_karar=..., satir_sayisi=...
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

---

## Bileşenler

Sistem 3 ayrı süreçten oluşur (Docker'da tek `app` container'ı içinde
`supervisord` ile birlikte yönetilir, bkz. `docker/supervisord.conf`):

```
1. PostgreSQL (Docker)          — Mcp_mimarisi'nin NACE/oran verisini tutar
2. Mcp_mimarisi API (port 8000) — KDV/mevzuat ön filtreleme
3. entegrasyon servisi (port 8100) — ön filtre + TDHP tahmini orkestrasyonu + arayüz
```

`model_eval` ayrı bir süreç DEĞİLDİR — `entegrasyon` servisi onu doğrudan
Python import ile çağırır. `model_eval`'ın RAG özelliği kullanılıyorsa
(varsayılan öyle) **Ollama**'nın da çalışıyor olması gerekir — Docker
Compose'da ayrı bir servis (bkz. `docker/docker-compose.yml`).

### Bulut modeli (gemma4:31b-cloud) kullanılıyorsa: SSH tüneli gerekir

TDHP tahmininde varsayılan model `gemma4:31b-cloud` — bu, Ollama'nın kendi
**bulut** modeli (ollama.com hesabına bağlı), yerel/container Ollama'da
DEĞİL, uzak GPU sunucusunda (`unlem-gx10-01`) çalışıyor. Bu tünel container
içinde **çalışmaz** (uzak makineye gittiği için) — host/sunucu seviyesinde
ayrı bir servis (systemd + autossh) olarak kurulmalı. Detay:
[`docs/how-to/ssh-tunel-kurulumu.md`](docs/how-to/ssh-tunel-kurulumu.md).

Tünel açık değilse TDHP tahmini adımında `tdhp_tahmini.error` alanında açık
bir hata mesajı döner (sessiz başarısızlık yok) — ön filtreleme
(Mcp_mimarisi) bundan etkilenmez, sadece TDHP tahmini adımı hata döner.

---

## Tarayıcıda arayüzü aç

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
   - tutar tablosu) gösterilir. `insan_incelemesi_gerekli` ise bir uyarı
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

## Sık karşılaşılan sorunlar

| Belirti                                             | Muhtemel sebep                                                               | Çözüm                                                                               |
| --------------------------------------------------- | ---------------------------------------------------------------------------- | ----------------------------------------------------------------------------------- |
| `entegrasyon`'da `/fatura/isle` → 502               | Mcp_mimarisi API (port 8000) çalışmıyor                                      | `docker compose ps` ile container durumunu kontrol et                               |
| `/fatura/isle` → 500, TDHP tahmini adımında         | Ollama çalışmıyor / model indirilmemiş                                       | `docker exec <ollama-container> ollama pull embeddinggemma`                         |
| `tdhp_tahmini.error`: `401 Kimlik dogrulama hatasi` | `gemma4:31b-cloud` bulut modeli, SSH tüneli kapalı/uzak sunucuya bağlı değil | `ssh -N -L 11435:localhost:11434 unlem-gx10-01@10.34.10.112` tünelini aç            |
| `/durum` → `model_eval_hazir: false`                | `entegrasyon` image'ında model_eval'ın bağımlılıkları eksik                  | Image'ı yeniden build et (`docker compose build`)                                   |
| Mcp_mimarisi API başlarken `RuntimeError`           | `DATABASE_URL` set değil / PostgreSQL'de veri yok                            | [`docs/how-to/docker-ile-calistirma.md`](docs/how-to/docker-ile-calistirma.md) §5-6 |
| `docker compose up` → "address already in use"      | Port 5434/8000/8100/11434 başka bir şey tarafından kullanılıyor              | Çakışan süreci durdur ya da `docker/docker-compose.yml`'deki host portunu değiştir  |

---

## İlgili belgeler

- Docker ile çalıştırma (ayrıntılı): [`docs/how-to/docker-ile-calistirma.md`](docs/how-to/docker-ile-calistirma.md)
- Genel workspace haritası: [`PROJECT.md`](PROJECT.md)
- Entegrasyon servisinin kendi detayı: [`entegrasyon/README.md`](entegrasyon/README.md)
- Mcp_mimarisi API detayı: [`Mcp_mimarisi/docs/how-to/api-calistirma.md`](Mcp_mimarisi/docs/how-to/api-calistirma.md)
- PostgreSQL kurulumu detayı: [`Mcp_mimarisi/docs/how-to/postgres-kurulum.md`](Mcp_mimarisi/docs/how-to/postgres-kurulum.md)
