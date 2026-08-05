# SSH Tünelini Sunucuda Kalıcı Hale Getirme

> **Tür:** how-to — görev odaklı tarif.
> Mimari gerekçe (neden bu tünel container'a alınmadı): [`../../mimari.md`](../../mimari.md) §5.1.
> Genel Docker çalıştırma: [`docker-ile-calistirma.md`](docker-ile-calistirma.md).

## Neden gerekli

`gemma4:31b-cloud` gibi büyük LLM modelleri yerelde/sunucuda çalışmıyor —
uzak bir GPU sunucusunda (`10.34.10.112`) çalışıyor. `model_eval_koprusu.py`
LLM çağrılarını `localhost:11435`'e yapıyor; bu port bir SSH tüneli
üzerinden uzak sunucudaki gerçek Ollama'ya (`localhost:11434`) yönlendirilir.

Geliştirme makinesinde bu tünel elle açılıyordu:

```bash
ssh -N -L 11435:localhost:11434 unlem-gx10-01@10.34.10.112
```

**Sunucuda bu komutu elle çalıştıran bir insan olmayacak** — bu yüzden tünel
`autossh` + `systemd` ile kalıcı bir sistem servisi haline getirilir: bağlantı
koparsa otomatik yeniden kurulur, sunucu yeniden başlarsa otomatik açılır.

> ⚠️ **Tünel koparsa sistem sessizce bozulmaz.** LLM'e erişilemediğinde
> `POST /fatura/isle` çağrısı `success: false` + `error` alanında
> `"Network is unreachable"` gibi açık bir mesajla döner (bkz.
> [`docker-ile-calistirma.md`](docker-ile-calistirma.md), gerçek testte
> doğrulandı). Yine de erken fark etmek için §4'teki health-check önerisini
> uygulayın.

## 1. Ön koşullar

```bash
# Sunucuda autossh kurulu olmalı
sudo apt-get install -y autossh   # Debian/Ubuntu
# veya: sudo yum install -y autossh   # RHEL/CentOS
```

## 2. Tünel için ayrı, kısıtlı bir sistem kullanıcısı oluştur

Tüneli root ya da uygulama kullanıcısıyla değil, tek işi bu olan ayrı bir
kullanıcıyla çalıştırın (en az yetki ilkesi):

```bash
sudo useradd --system --no-create-home --shell /usr/sbin/nologin efatura-tunnel
sudo mkdir -p /home/efatura-tunnel/.ssh
sudo chown efatura-tunnel:efatura-tunnel /home/efatura-tunnel/.ssh
sudo chmod 700 /home/efatura-tunnel/.ssh
```

## 3. Parolasız SSH anahtarı üret ve uzak sunucuya tanıt

Systemd servisi parola giremeyeceği için **anahtar tabanlı, parolasız**
kimlik doğrulama şart:

```bash
sudo -u efatura-tunnel ssh-keygen -t ed25519 -f /home/efatura-tunnel/.ssh/id_ed25519 -N ""

# Genel anahtarı uzak GPU sunucusuna (10.34.10.112) yetkilendirin:
sudo -u efatura-tunnel ssh-copy-id -i /home/efatura-tunnel/.ssh/id_ed25519.pub \
    unlem-gx10-01@10.34.10.112
```

`ssh-copy-id` uzak sunucunun parolasını bir kez soracak (elle girilir) —
sonrasında anahtar kalıcı olarak yetkilendirilmiş olur, bir daha parola
istenmez.

Bağlantıyı elle doğrulayın (systemd'e geçmeden önce):

```bash
sudo -u efatura-tunnel ssh -o BatchMode=yes unlem-gx10-01@10.34.10.112 echo "bağlantı OK"
```

`BatchMode=yes` parola/passphrase istemeyi engeller — eğer bu komut parola
sormadan `bağlantı OK` yazdırıyorsa anahtar doğru kurulmuş demektir.

## 4. systemd servisini kur

Bu repodaki hazır servis dosyasını kullanın:
[`../../docker/systemd/efatura-llm-tunnel.service`](../../docker/systemd/efatura-llm-tunnel.service)

```bash
sudo cp docker/systemd/efatura-llm-tunnel.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now efatura-llm-tunnel
```

Durumu kontrol edin:

```bash
sudo systemctl status efatura-llm-tunnel
sudo journalctl -u efatura-llm-tunnel -f   # canlı log izleme
```

Port gerçekten dinliyor mu:

```bash
ss -tlnp | grep 11435
```

## 5. Docker Compose ile bağlantı

`docker/docker-compose.yml`'deki `app` servisi bu tünele
`http://host.docker.internal:11435` üzerinden erişir — tünel yukarıdaki
adımlarla host'ta systemd servisi olarak çalıştığı sürece **ek bir
yapılandırma gerekmez**, `docker compose up` sonrası otomatik çalışır.

## 6. Servis dosyasındaki güvenlik ayarları (özet)

| Ayar | Neden |
|---|---|
| `ServerAliveInterval=15`, `ServerAliveCountMax=3` | Kopan bağlantıyı ~45 saniyede tespit edip yeniden kurar |
| `ExitOnForwardFailure=yes` | Port yönlendirme kurulamazsa (örn. port zaten dolu) sessizce yarım kalmak yerine süreç sonlanır, systemd `Restart=always` ile tekrar dener |
| `Restart=always` + `RestartSec=5` | Sunucu yeniden başlasa/bağlantı sürekli kopsa da tünel kendini toparlar |
| Ayrı `efatura-tunnel` sistem kullanıcısı | Tünel süreci uygulama kullanıcısının veya root'un diğer yetkilerini taşımaz |

## 7. Sorun giderme

| Belirti | Olası sebep | Kontrol |
|---|---|---|
| `systemctl status` → `failed` | SSH anahtarı yetkilendirilmemiş | `sudo -u efatura-tunnel ssh -o BatchMode=yes ...` ile elle test edin (§3) |
| Servis çalışıyor ama `/fatura/isle` hâlâ `"Network is unreachable"` veriyor | Uzak GPU sunucusundaki Ollama kapalı, ya da güvenlik duvarı 10.34.10.112'ye giden bağlantıyı engelliyor | Uzak sunucuda `ollama` sürecinin ayakta olduğunu, sunucudan `nc -zv 10.34.10.112 22` ile SSH portuna erişimi doğrulayın |
| `ss -tlnp \| grep 11435` boş dönüyor | Tünel hiç kurulmamış | `journalctl -u efatura-llm-tunnel` ile hata logunu inceleyin |
