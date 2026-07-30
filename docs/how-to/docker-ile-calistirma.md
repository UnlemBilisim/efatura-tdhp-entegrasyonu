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

## 0. Kurumsal registry'ye push / oradan pull (sunucuya taşıma)

> ✅ **Uygulandı** (2026-07-29): Image `docker.unlemcloud.com/unlembilisim/efatura-kdv-tdhp-sistemi`
> adıyla kurumsal Docker registry'ye push edildi (`1.0.0` ve `latest` tag'leri,
> digest `sha256:b3476e79781b330c7e7ac097fafaa4275b8b18a0c3002d2fa7335ea537731238`).
> Gerçek pushta doğrulandı.

Bu, geliştirme makinesinde build edilen image'ı bir sunucuya taşımanın yolu —
`docker compose up` ile yerel build'in yerini almaz, onu tamamlar (build burada,
çalıştırma sunucuda).

**Push (geliştirme makinesinde, image build edildikten sonra):**

```bash
docker login docker.unlemcloud.com
docker build \
  -t docker.unlemcloud.com/unlembilisim/efatura-kdv-tdhp-sistemi:1.0.0 \
  -t docker.unlemcloud.com/unlembilisim/efatura-kdv-tdhp-sistemi:latest .
docker push docker.unlemcloud.com/unlembilisim/efatura-kdv-tdhp-sistemi:1.0.0
docker push docker.unlemcloud.com/unlembilisim/efatura-kdv-tdhp-sistemi:latest
```

**Pull (sunucuda):**

```bash
docker login docker.unlemcloud.com
docker pull docker.unlemcloud.com/unlembilisim/efatura-kdv-tdhp-sistemi:1.0.0
```

> ✅ **Uygulandı** (2026-07-29): `docker-compose.yml`'deki `app` servisine
> `image: docker.unlemcloud.com/unlembilisim/efatura-kdv-tdhp-sistemi:1.0.0`
> eklendi (`build: .` de kalıyor). Sunucuda `docker compose up -d` çalıştığında
> — image yerelde `docker pull` ile zaten çekildiyse — **yeniden build
> almadan** doğrudan o image kullanılır. Geliştirme makinesinde `docker
> compose build` çalıştırılırsa yerelden build edip aynı image adına
> etiketler (iki kullanım da aynı dosyada bir arada durur).

Sunucuda `docker-compose.yml` ile ayağa kaldırmak için, image'ın yanı sıra
**image'a dahil olmayan** şu destek dosyalarının da sunucuda olması gerekir
(scp/rsync ile taşınmalı — `Dockerfile`, `entegrasyon/`, `Mcp_mimarisi/`,
`model_eval/` kaynak kodu image içinde zaten var, tekrar taşınmasına gerek
yok):

```bash
scp docker-compose.yml <kullanıcı>@<sunucu>:/path/System/
scp -r docker/ <kullanıcı>@<sunucu>:/path/System/
```

`docker/systemd/efatura-llm-tunnel.service` bu şekilde taşınan dosyaların
içinde gelir — kurulumu için [`ssh-tunel-kurulumu.md`](ssh-tunel-kurulumu.md)'ye
bakın.

> ⚠️ **Bilinen tuzak — `413 Payload Too Large` push sırasında:** Registry
> Cloudflare arkasında çalışıyor (`server: cloudflare` header'ı ile
> doğrulandı) ve tek istek gövdesi için bir üst limit uyguluyor. Bu projenin
> `entegrasyon/requirements.txt`'i `chromadb`+`ollama` içerdiği için (RAG
> özelliği — bkz. `model_eval_koprusu.py::faturayi_onayla`) o katman tek
> başına ~360 MB'a çıkıyor. Bunu azaltmak için `Dockerfile`'daki `pip
> install` üç ayrı `RUN` satırına bölündü (satır bazında bkz. Dockerfile
> yorumu) — böylece her bileşenin bağımlılığı ayrı bir katman/upload isteği
> olur. **Bu bölme + yeniden build sonrası push başarılı oldu**; kesin
> hangi faktörün (katman bölme mi, registry/Cloudflare tarafında geçici bir
> durum mu) çözümü sağladığı net değil — eğer push yine 413 verirse,
> registry yöneticisine Cloudflare'in bu subdomain için tek istek boyutu
> limitini artırıp artıramayacağını sorun.
>
> `model_eval/requirements.txt`'ten `pytest` çıkarılıp ayrı
> `model_eval/requirements-dev.txt`'e taşındı, `tests/` dizinleri
> `.dockerignore`'a eklendi (production image'da hiç kullanılmıyorlardı) —
> bu image boyutunu biraz küçültür ama asıl 413 sorununu tek başına çözmez
> (chromadb'nin transitive bağımlılıkları asıl ağırlık kaynağı).

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

**Sunucuda kalıcı kurulum için:** [`ssh-tunel-kurulumu.md`](ssh-tunel-kurulumu.md)
— `autossh` + `systemd` ile insan müdahalesi olmadan açık kalması sağlanır.

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

## 5.5. Vektör veritabanı (ChromaDB/RAG) ve Excel referans dosyaları

> ✅ **Uygulandı** (2026-07-29): `app` servisine `efatura-vector-db` adlı
> kalıcı bir volume eklendi (`/app/model_eval/vector_db`) — daha önce hiçbir
> volume'a bağlı değildi, container her yeniden oluşturulduğunda (image
> güncelleme, `down`+`up`) `/fatura/onayla` ile biriken RAG kayıtları
> sessizce sıfırlanıyordu.

**ChromaDB (vektör veritabanı) — image'a dahil DEĞİL, ayrıca taşınmalı:**

Yerelde `model_eval/vector_db/` altında biriken embedding verisi (hem
`build_vector_db.py`'nin indekslediği ground-truth hem kullanıcı onayıyla
`/fatura/onayla` üzerinden eklenen kayıtlar) `.gitignore`/`.dockerignore`'da
bilinçli olarak hariç tutulmuştur — image içine hiç girmez. Yeni sunucuda
mevcut RAG verisini taşımak için:

```bash
# Kaynak makinede (app container'ı ayaktayken)
docker cp <app-container>:/app/model_eval/vector_db ./vector_db_yedek

# Hedef makinede (docker compose up -d sonrası, volume oluştuktan sonra)
docker cp ./vector_db_yedek/. <yeni-app-container>:/app/model_eval/vector_db
docker restart <yeni-app-container>
```

Bu adım atlanırsa sistem **çalışmaya devam eder** (RAG'sız degrade mod değil,
sadece few-shot emsalsiz tahmin) — sessizce bozulmaz ama doğruluk oranı
düşer (bkz. `model_eval/CLAUDE.md` "En büyük tekil iyileştirme: RAG").

**Excel referans dosyaları (`Mcp_mimarisi/exceller/*.xlsx`,
`model_eval/exceller/mizan.xlsx`) — image'a GÖMÜLÜ, ayrıca taşınmaz ama
DONMUŞ:**

Bu dosyalar (NACE/KDV oran referansı, şirkete özel mizan) SQL/vektör
verisinin aksine `Dockerfile`'daki `COPY` ile image'ın içine gömülüdür —
build anındaki hâlleriyle sabitlenirler, ayrı bir taşıma adımı gerekmez.
**Ama bu aynı zamanda bir tuzaktır:** mizan güncellenirse (ör. yeni alt
kırılım kodları eklenirse, geçmişte "mizan_5" güncellemesinde olduğu gibi)
sunucudaki container bunu görmez — image'ın güncel Excel dosyasıyla
**yeniden build edilip push/pull edilmesi** gerekir. Container'a dosyayı
tek başına `docker cp` ile kopyalamak geçici bir çözümdür, container
yeniden oluşturulduğunda (kalıcı volume'a bağlı olmadığı için) kaybolur.

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
