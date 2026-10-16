# Yeni Şirket Ekleme API'si — Zip ile Toplu Yükleme

Yeni müşterilerinizin (şirketlerin) verisini **tek bir zip dosyası** ile bize yüklersiniz; biz her şirketi
sisteme kurarız. Kurulumdan sonra o şirketler için `POST /fatura/isle` ile fatura işleyebilirsiniz.

Bu belge yalnızca bu uç noktayı anlatır. Fatura işleme için `API-ENTEGRASYON-KILAVUZU.md`,
yüklenecek dosyaların içeriği için `ONBOARDING-VERI-FORMATI.md` belgesine bakın.

## Özet

| | |
|---|---|
| **Yükleme** | `POST http://<host>:8100/musteri/onboard` — gövde: ham zip |
| **İlerleme** | `GET http://<host>:8100/musteri/isler/{is_id}` |
| **Kimlik** | `Authorization: Bearer <API anahtarı>` — anahtarınızda **onboard yetkisi** olmalı |
| **Çağrı şekli** | Sunucu-sunucu (tarayıcıdan doğrudan çağrılamaz) |
| **Zip boyutu** | En çok **200 MB** |
| **İşlem** | Arka planda; yükleme hemen `202` döner, sonucu `is_id` ile sorgularsınız |

> `<host>` bir yer tutucudur — gerçek adres ayrı bir kanaldan bildirilir.

## 1. Yetki

Bu uç nokta, normal API anahtarının **dışında ayrı bir yetki** ister. Bu yetkiyi kendiniz alamazsınız;
**bizden talep edersiniz.** İki yol vardır:

- **Mevcut anahtarınıza yetki eklenir** — anahtarınız değişmez, yalnızca izin eklenir. Elinizdeki anahtarı kullanmaya devam edersiniz.
- **Size yetkili yeni bir anahtar verilir** — ayrı ve güvenli bir kanaldan iletilir; yalnızca sunucu tarafınızda saklayın.

**Yetkiniz var mı, nasıl anlarsınız?** Zip göndermeden, bilerek geçersiz bir gövdeyle deneyin (hiçbir şey kurulmaz):

```bash
curl -s -X POST http://<host>:8100/musteri/onboard \
  -H "Authorization: Bearer $API_ANAHTARI" -H "Content-Type: application/zip" \
  --data-binary "deneme"
```

| Cevap | Anlamı |
|---|---|
| `400` — "Gövde bir zip dosyası değil" | ✅ Anahtarınız geçerli **ve** onboard yetkiniz var |
| `403` — "onboard yetkisi yok" | Anahtar geçerli ama yetki yok — bizden isteyin |
| `401` | Anahtar geçersiz ya da iptal edilmiş |

Kurulum başarılı olunca yeni şirketin VKN'si **anahtarınızın kapsamına otomatik eklenir** — ayrıca bir işlem
gerekmez. Ardından o VKN ile `POST /fatura/isle` çağırabilirsiniz. Kurulu şirketleri `GET /kayitli-sirketler` ile görebilirsiniz.
Anahtarınız başlangıçta hiçbir şirkete yetkili olmayabilir (yalnızca yeni şirket kurmak için verilmiş olabilir); bu normaldir.

## 2. Zip yapısı

Zip'in kökünde **her şirket için bir klasör** bulunur. **Klasör adı şirketin 10 haneli VKN'sidir.**

```
yukleme.zip
├── 6677889900/                  ← şirketin VKN'si (10 hane, sadece rakam)
│   ├── mizan.xlsx               zorunlu
│   ├── faturalar/               zorunlu
│   │   ├── fatura-1.xml         son 6 aya ait UBL-TR fatura XML'leri (dosya adı önemsiz)
│   │   └── ...
│   ├── yevmiye.xlsx             zorunlu (ya da yevmiye.csv)
│   └── nace.txt                 opsiyonel
└── 1122334455/                  ← ikinci şirket
    └── ...
```

- Dosya adları **tam olarak** böyle olmalıdır (`mizan.xlsx`, `faturalar/`, `yevmiye.xlsx` veya `yevmiye.csv`,
  `nace.txt`); büyük/küçük harf fark etmez.
- Bu adların dışındaki dosyalar **yok sayılır** (hata vermez, cevapta `atlanan_dosya` olarak sayılır).
- Kökte VKN olmayan bir klasör varsa o klasör işlenmez ve cevapta `gecersiz_klasorler` içinde listelenir.
- Zip'i bir üst klasörle birlikte sıkıştırdıysanız (örn. `yukleme/6677889900/...`) sorun olmaz; **tek** bir
  sarmalayıcı klasör kabul edilir.
- Her dosyanın içeriği (mizan sütunları, yevmiye 5 sütunlu formatı, XML gereksinimleri):
  `ONBOARDING-VERI-FORMATI.md`.

## 3. Yükleme

```bash
curl -X POST http://<host>:8100/musteri/onboard \
  -H "Authorization: Bearer $API_ANAHTARI" \
  -H "Content-Type: application/zip" \
  --data-binary @yukleme.zip
```

Başarılı cevap **`202 Accepted`**:

```json
{
  "is_id": "bb45a020e67d4701a24655d04217cf59",
  "durum": "kuyrukta",
  "sirketler": ["1122334455", "6677889900"],
  "atlanan_dosya": 0,
  "gecersiz_klasorler": []
}
```

`is_id`'yi saklayın; sonucu bununla sorgularsınız. `sirketler`, zip'ten işlenmek üzere kabul edilen VKN'lerdir.

## 4. İlerlemeyi sorgulama

```bash
curl -H "Authorization: Bearer $API_ANAHTARI" \
  http://<host>:8100/musteri/isler/bb45a020e67d4701a24655d04217cf59
```

```json
{
  "is_id": "bb45a020e67d4701a24655d04217cf59",
  "durum": "calisiyor",
  "yuzde": 63,
  "sirketler": {
    "6677889900": {
      "durum": "kuruldu",
      "yuzde": 100,
      "adim": "rag",
      "ayrinti": null,
      "ozet": { "mizan_satir_sayisi": 21, "fatura_eslesme": "2/2", "yon_belirsiz": 0, "nace_kodlari": ["107101"] }
    },
    "1122334455": {
      "durum": "calisiyor",
      "yuzde": 25,
      "adim": "sema",
      "ayrinti": null,
      "ozet": null
    }
  }
}
```

**İlerleme yüzdesi:** `yuzde` (0–100) işin genel ilerlemesidir (şirketlerin ortalaması); her şirketin de kendi `yuzde` ve
`adim` değeri vardır: `sema` (25) → `mizan` (50) → `eslestirme` (75) → `rag` (100). Yüzde **basamaklıdır**: bir adım bitince
artar, fatura sayısı çoksa son adımlarda uzun süre aynı değerde kalabilir (takılma değildir). `kuruldu` ve `atlandi`
şirketler 100'dür; `hata` veren şirketin `adim` değeri hatanın hangi adımda olduğunu gösterir. İş `bitti` olunca `yuzde` 100'dür.

**İşin durumu** (`durum`): `kuyrukta` → `calisiyor` → `bitti`. İş `bitti` olduğunda her şirketin nihai durumu belli olur.

**Şirket durumu** (`sirketler.<vkn>.durum`):

| Durum | Anlamı | Ne yapmalısınız |
|---|---|---|
| `bekliyor` | Sırada | Beklemeye devam edin |
| `calisiyor` | Şu an kuruluyor | Beklemeye devam edin |
| `kuruldu` | Şirket kuruldu, VKN anahtarınıza eklendi | `POST /fatura/isle` için hazır |
| `atlandi` | Şirket **zaten kurulu**; hiçbir şey değiştirilmedi | Normal; mevcut şirketin verisi bu yolla güncellenemez |
| `hata` | Bu şirket kurulamadı; nedeni `ayrinti` alanında | Düzeltip yeniden yükleyin (bkz. §6) |

Şirketler **sırayla** işlenir; birinde hata olması diğerlerini durdurmaz.

**`ozet` alanını okuma** (`kuruldu` durumunda):

| Alan | Anlamı |
|---|---|
| `mizan_satir_sayisi` | Yüklenen mizan satırı sayısı |
| `fatura_eslesme` | `eşleşen/toplam` — kaç faturanın yevmiye kaydıyla eşleştiği. **Düşükse** yevmiyedeki `fatura_no` değerleri XML'deki fatura numarasıyla (`cbc:ID`) birebir aynı olmayabilir |
| `yon_belirsiz` | VKN'nin ne alıcı ne satıcı olarak bulunamadığı fatura sayısı. **0'dan büyükse** klasör adındaki VKN yanlış olabilir (o faturalar öğrenmeye alınmaz) |
| `nace_kodlari` | Kaydedilen NACE kodları (`nace.txt` verdiyseniz) |

`kuruldu` bir şirketin sonucunda `ayrinti` doluysa, şirket kurulmuş ancak anahtar kapsamına eklenememiştir; bize bildirin.

## 5. Önemli kurallar

- **Mevcut şirket asla değiştirilmez.** Zaten sistemde kayıtlı bir VKN gönderirseniz `atlandi` olur, verisi olduğu gibi kalır.
  Bu uç nokta yalnızca **yeni** şirket kurmak içindir.
- **Verileriniz iş bitince sunucudan silinir.** Yüklediğiniz ham dosyalar kurulum sonrası saklanmaz; yalnızca kurulum sonucu kalır.
- **Sadece sizin işiniz görünür.** Başka bir anahtarın `is_id`'sini sorgularsanız `404` alırsınız.
- **Aynı anda en fazla 5 bekleyen iş** kabul edilir; fazlası `429` döner.
- **Zip sınırları:** en çok 200 MB; 20.000'den fazla dosya, tek dosyada 100 MB üstü, açılmış toplamda 1 GB üstü ya da
  aşırı yüksek sıkıştırma oranı reddedilir. Parola korumalı zip desteklenmez.
- **Güvenlik:** `../` içeren ya da mutlak yollu dosya adları bulunan zip **tamamen reddedilir**.
- Anahtarınızı yalnızca sunucu tarafınızda saklayın; tarayıcıya ya da istemci koduna koymayın.

## 6. Hata kodları ve çözümler

| Kod | Anlamı | Çözüm |
|---|---|---|
| `400` | Zip bozuk ya da zip değil; güvensiz dosya yolu; parola korumalı; sınır aşıldı; **işlenecek şirket klasörü yok** | Mesaj (`detail`) nedeni söyler. Zip yapısını §2'ye göre kontrol edin |
| `401` | API anahtarı yok, geçersiz ya da iptal edilmiş | Anahtarınızı kontrol edin |
| `403` | Anahtarınızda onboard yetkisi yok | Bize başvurup yetki isteyin |
| `404` | (`/musteri/isler/{id}` için) iş yok ya da başka anahtara ait | `is_id`'yi kontrol edin |
| `413` | Zip 200 MB sınırını aşıyor | Şirketleri birkaç zip'e bölün |
| `429` | Çok fazla bekleyen iş | Bir iş bitince tekrar deneyin |

**Bir şirket `hata` verdiyse:** `ayrinti` nedeni söyler (örn. eksik dosya, bozuk mizan). Düzeltip **aynı zip'i
(ya da yalnızca hatalı şirketi içeren yeni bir zip'i) aynı anahtarla yeniden gönderin.** Daha önce `kuruldu` olan şirketler
`atlandi` olarak geçilir, hata veren şirket yeniden kurulur (kurulum tekrarlanabilir şekilde tasarlandı); yani tüm zip'i yeniden göndermek güvenlidir.

**İş yarıda kalırsa:** sistem iş sürerken yeniden başlarsa, bitmemiş şirketler `hata` ("iş yarıda kaldı") olarak işaretlenir;
zip'i yeniden yükleyin.

## 7. Örnek kod (Python)

```python
import os
import time
import requests

BASE = "http://<host>:8100"
HEADERS = {"Authorization": f"Bearer {os.environ['API_ANAHTARI']}"}

# 1) Yükle
with open("yukleme.zip", "rb") as f:
    r = requests.post(
        f"{BASE}/musteri/onboard",
        headers={**HEADERS, "Content-Type": "application/zip"},
        data=f,                      # dosyayı akıtır, belleğe almaz
        timeout=600,
    )
r.raise_for_status()                 # 202
is_id = r.json()["is_id"]
print("Kabul edilen şirketler:", r.json()["sirketler"])

# 2) Bitene kadar sorgula
while True:
    d = requests.get(f"{BASE}/musteri/isler/{is_id}", headers=HEADERS, timeout=30).json()
    if d["durum"] == "bitti":
        break
    print(f"%{d['yuzde']} tamamlandı")
    time.sleep(10)                   # kısa aralıkla başlayıp gerekirse artırın

# 3) Sonuçları işle
for vkn, s in d["sirketler"].items():
    print(vkn, s["durum"], s["ayrinti"] or "")
    if s["durum"] == "kuruldu":
        print("   özet:", s["ozet"])
```

## 8. Gönderim öncesi kontrol listesi

- [ ] Anahtarınızda onboard yetkisi var mı?
- [ ] Zip'in kökünde `<10 haneli VKN>/` klasörleri var mı?
- [ ] Her klasörde `mizan.xlsx`, `faturalar/*.xml` ve `yevmiye.xlsx` (ya da `.csv`) var mı?
- [ ] Mizandaki HESAP KODU hücreleri **metin** biçiminde mi? (sayı biçimindeki satırlar sessizce atlanır — bkz. `ONBOARDING-VERI-FORMATI.md`)
- [ ] Yevmiyedeki `fatura_no`, XML'deki `cbc:ID` ile birebir aynı mı?
- [ ] Klasör adındaki VKN, faturalardaki şirket VKN'siyle (alıcı ya da satıcı) uyuşuyor mu?
- [ ] Zip 200 MB'ın altında mı?
