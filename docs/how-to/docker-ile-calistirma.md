# Docker İle Çalıştırma

> **Tür:** how-to — görev odaklı tarif.
> Yerel (Docker'sız) çalıştırma için: [`../../proje-calistirma.md`](../../proje-calistirma.md).
> Mimari gerekçe (neden tek image, neden SSH tünel container dışında):
> [`../../mimari.md`](../../mimari.md).

> ✅ **Doğrulandı** (2026-07-28): Aşağıdaki adımlar gerçek sistemde
> çalıştırılarak test edildi — image build edildi, üç container (postgres,
> ollama, app) ayağa kalktı, PostgreSQL yedeği geri yüklendi, gerçek bir
> faturayla `/fatura/isle` çağrıldı. KDV ön filtreleme + RAG embedding
> container içinde doğru çalıştı; LLM adımı SSH tüneli bu makinede açık
> olmadığı için beklendiği gibi açık bir hatayla durdu (sessiz başarısızlık
> yok).

## Neden bu yapı

- **Tek `Dockerfile`, tüm Python kodu bir arada** (Mcp_mimarisi + entegrasyon
  + model_eval) — `entegrasyon/model_eval_yolu.py` model_eval'i kardeş dizin
  (`../model_eval`) olarak `sys.path`'e ekliyor; iki servisi ayrı image'lara
  bölmek bu ilişkiyi bozar.
- **`supervisord`** iki uvicorn sürecini (Mcp_mimarisi:8000, entegrasyon:8100)
  tek container içinde yönetir (`docker/supervisord.conf`).
- **PostgreSQL ve Ollama ayrı servisler** (`docker-compose.yml`) — resmi
  image'lar, named volume ile veri kalıcı.
- **SSH tünel (uzak GPU'daki LLM için) container'da DEĞİL.** Uzak makineye
  (`10.34.10.112`) gittiği için container içine alınamaz; host/sunucu
  seviyesinde ayrı bir servis (elle veya systemd, bkz. §3) olarak kalır.
  `app` container'ı buna `host.docker.internal:11435` üzerinden erişir.

## 1. Gereksinimler

- Docker + Docker Compose (bu ortamda test edildi: Docker 29.6.2, Compose v5.3.1)
- Güçlü bir PostgreSQL parolası (aşağıda `POSTGRES_PASSWORD` olarak geçecek)

## 2. Başlatma

```bash
cd System/
POSTGRES_PASSWORD="<güçlü-parola>" docker compose up -d
```

`POSTGRES_PASSWORD` **zorunludur** — tanımlı değilse `docker compose` açıkça
hata verip durur, gömülü/varsayılan bir parolaya düşmez.

İlk çalıştırmada `ollama` container'ında embedding modeli **kurulu değildir**
— RAG kullanmadan önce bir kere çekilmesi gerekir:

```bash
docker exec <ollama-container-adı> ollama pull embeddinggemma
```

## 3. SSH tünel (LLM erişimi — host'ta, container dışında)

`docker-compose.yml`'deki `app` servisi, LLM çağrıları için
`http://host.docker.internal:11435`'e bağlanmayı bekler. Bu adres, host
makinedeki bir SSH tüneline karşılık gelir:

```bash
ssh -N -L 11435:localhost:11434 <kullanıcı>@10.34.10.112
```

Bu tünel container içinde **çalışmaz** (uzak makineye gidiyor) — host'ta
elle açılmalı ya da kalıcı bir sistem servisi (systemd + autossh) olarak
kurulmalı. Tünel kapalıyken LLM adımı **sessizce başarısız olmaz** —
`tdhp_tahmini.error` alanında `"Network is unreachable"` gibi açık bir mesaj
döner, `success: false` olur.

## 4. Sağlık kontrolü

```bash
curl http://localhost:8000/saglik   # {"durum":"ayakta","nace_tablosu_yuklu":true}
curl http://localhost:8100/durum    # {"model_eval_hazir":true,...}
```

`nace_tablosu_yuklu: false` ya da Mcp_mimarisi container'ı sürekli yeniden
başlıyorsa (`docker logs <app-container>` içinde
`psycopg2.errors.UndefinedTable: relation "nace_oranlari" does not exist`),
PostgreSQL'de henüz veri yok — §5'e bakın.

## 5. Mevcut PostgreSQL verisini geri yükleme

Yerelde `./baslat.sh` ile biriktirilmiş veriyi (NACE-KDV tablosu, geçmiş
fatura kalemleri) yeni bir Docker PostgreSQL'e taşımak için:

```bash
# Kaynak makinede yedek al (zaten alınmışsa db-yedek/ altında duruyor olabilir)
docker exec <postgres-container> pg_dump -U efatura -d efatura_kdv -F c -f /tmp/yedek.dump
docker cp <postgres-container>:/tmp/yedek.dump ./db-yedek/efatura_kdv_yedek.dump

# Hedef makinede (Docker Compose ayaktayken) geri yükle
docker cp db-yedek/efatura_kdv_yedek.dump <yeni-postgres-container>:/tmp/yedek.dump
docker exec <yeni-postgres-container> pg_restore -U efatura -d efatura_kdv --clean --if-exists /tmp/yedek.dump
```

`db-yedek/` klasörü `.gitignore`'dadır — gerçek fatura verisi içerir, git'e
gömülmez, sunucuya ayrı/güvenli bir kanaldan (scp/rsync) taşınmalı.

Doğrulama:

```bash
docker exec <postgres-container> psql -U efatura -d efatura_kdv -t -c "
SELECT 'nace_oranlari', count(*) FROM nace_oranlari
UNION ALL SELECT 'gecmis_fatura_kalemleri', count(*) FROM gecmis_fatura_kalemleri;"
```

Beklenen (bu sistemdeki mevcut veri): `nace_oranlari` 2138 satır,
`gecmis_fatura_kalemleri` 1120 satır.

## 6. `app` container'ı veri geldikten sonra ayağa kalkmıyorsa

`Mcp_mimarisi`, PostgreSQL'de `nace_oranlari` tablosu olmadan başlayamaz ve
`supervisord`'un `startretries` sınırına takılıp `FATAL` durumuna düşebilir
(veri geri yüklenmeden önce container ilk kez başlatıldıysa). Veri geri
yüklendikten sonra container'ı yeniden başlatın:

```bash
docker restart <app-container-adı>
```

## 7. Durdurma

```bash
POSTGRES_PASSWORD="<aynı-parola>" docker compose down
```

`down` komutu da `POSTGRES_PASSWORD`'ü ister (compose dosyasını yeniden
parse eder) — `up` sırasında kullandığınız değeri tekrar verin. Veriler
named volume'larda kalıcıdır (`docker compose down -v` **vermediğiniz**
sürece silinmez).

## İlgili belgeler

- Port/env değişkeni envanteri: [`../reference/servisler-ve-portlar.md`](../reference/servisler-ve-portlar.md)
- Güvenlik durumu (auth eksikliği, `0.0.0.0` bind): [`../explanation/guvenlik-durumu-2026-07-27.md`](../explanation/guvenlik-durumu-2026-07-27.md)
- Dış ekip API sözleşmesi: [`../../entegrasyon/docs/reference/dis-ekip-api-kullanimi.md`](../../entegrasyon/docs/reference/dis-ekip-api-kullanimi.md)
