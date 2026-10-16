# Fatura İşleme Kılavuzu — tek fatura, paralel istek ve toplu (zip) gönderim

Bu kılavuz, e-fatura XML'lerini sisteme gönderip **muhasebe kaydı** (hesap kodu, Borç/Alacak, tutar) almayı anlatır.
Üç yol vardır; ihtiyacınıza göre seçin:

| Yol | Ne zaman | Nasıl |
|---|---|---|
| **1. Tek fatura** | Az sayıda fatura, anlık cevap | `POST /fatura/isle` — cevap aynı istekte döner |
| **2. Paralel tek istekler** | Birkaç faturayı aynı anda göndermek | Yol 1'i aynı anda birden fazla çağırın (kuralları aşağıda) |
| **3. Toplu (zip)** | Onlarca/yüzlerce fatura | `POST /fatura/toplu-isle` — **tek zip**, arka planda işlenir, sonucu sorgularsınız |

Sunucu adresi (`<host>`) size ayrıca bildirilir. Her istekte: `Authorization: Bearer <API anahtarınız>`.

## Başlamadan önce

1. **Şirket sistemde kurulu olmalı.** Kurulu şirketleri görmek için: `GET /kayitli-sirketler`. Kurulu olmayan bir VKN ile istek
   atarsanız `404` alırsınız (yeni şirket ekleme için `MUSTERI-ONBOARD-ZIP-KILAVUZU.md`).
2. **API anahtarınız o şirket(ler) adına yetkili olmalı.** Yetkisiz VKN `403` alır.
3. İsteklerde `satici_vkn` alanına **kendi şirketinizin VKN'sini** yazın (faturadaki satıcının değil). Sistem faturanın size
   mi geldiği (alış / `inbox`) yoksa sizin mi kestiğiniz (satış / `outbox`) bunu XML'den kendisi anlar.

## Bir fatura sistemde nasıl işlenir?

```
fatura XML ─► yön tespiti (alış mı satış mı?)
                │
                ├─ SATIŞ (sizin kestiğiniz): önce KDV oranı kontrolü (mevzuata uygun mu?)
                │       uygunsa devam · uygun değilse DURUR → "insan incelemesi" (onay: true ile yeniden gönderin)
                └─ ALIŞ (size gelen): KDV kontrolü yapılmaz
                │
                ▼
          fatura döviz cinsindeyse → DURUR → "kur seçimi" (kur_secimi ile yeniden gönderin)
                │
                ▼
          muhasebe kaydı üretilir (yapay zekâ + şirketinizin geçmiş faturaları ve hesap planı)
                │
                ▼
          kurallı doğrulama (kodlar geçerli mi, borç = alacak mı, tutar faturayla uyumlu mu?)
                │
                ▼
          sonuç: records[] (muhasebe kayıtları) + approvable (onaylanabilir mi?)
```

Yapay zekâ **yalnızca muhasebe kaydını** üretir; KDV uygunluğu ve doğrulama kural tabanlıdır. Doğrulamadan geçmeyen kayıt
`approvable: false` gelir ve **onaylanamaz** (nedeni `validation_errors` içinde).

---

## Yol 1 — Tek fatura (`POST /fatura/isle`)

```bash
python3 -c "
import json
json.dump({'fatura_xml': open('fatura.xml', encoding='utf-8').read(), 'satici_vkn': '6677889900'},
          open('istek.json', 'w'), ensure_ascii=False)"

curl -s --max-time 600 -X POST http://<host>:8100/fatura/isle \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $API_ANAHTARI" \
  -d @istek.json
```

İhtiyacınız olan alan: **`tdhp_tahmini.dis_sema.records[]`**. Her kayıt: `account_code`, `account_description`, `debit_credit`
(`BORÇ`/`ALACAK`), `amount` ve kodun neden seçildiğini anlatan `account_code_reason`. Tam şema:
`API-KAYIT-SEMASI-REFERANS.md`.

`asama` alanı sonucun durumunu söyler:

| `asama` | Anlamı | Ne yapmalı |
|---|---|---|
| `tdhp_tahmini_tamamlandi` | ✅ Kayıt hazır ve doğrulamadan geçti | Kullanın / onaylayın |
| `tdhp_dogrulama_basarisiz` | Kayıt üretildi ama doğrulamadan geçemedi | `validation_errors`'a bakın; **onaylanamaz**, insan kontrolü gerekir |
| `on_filtre_insan_incelemesi_bekliyor` | Satış faturasında KDV oranı kontrolü uyarı verdi | Uyarıyı inceleyin, devam edecekseniz `"onay": true` ile **yeniden gönderin** |
| `kur_onayi_bekliyor` | Fatura döviz cinsinden | `"kur_secimi": "orijinal"` ya da `"tl"` ile **yeniden gönderin** |

Bir istek **birkaç on saniye** sürebilir; zaman aşımını en az **600 saniye** yapın.

## Yol 2 — Paralel tek istekler

Yol 1'i aynı anda birden fazla kez çağırabilirsiniz. Bilmeniz gerekenler:

- Sunucu aynı anda **en fazla 2 faturayı** işler (şu anki ayar). Daha fazla istek gelirse fazlası **sırada bekler**;
  **reddedilmez** (`429` yok) ve gelen cevap normal cevaptır.
- Bu yüzden her istek, sıradaki bekleme süresi + kendi işlem süresi kadar uzayabilir. **Zaman aşımını yüksek tutun (≥ 600 sn).**
- **Öneri:** aynı anda en fazla 4–5 paralel istek gönderin; daha fazlası yalnızca sırayı uzatır, hızı artırmaz.
- Yüzlerce faturanız varsa paralel istek yerine **Yol 3'ü (toplu)** kullanın: bağlantı açık tutmanız gerekmez, zaman aşımı
  riski olmaz, ilerlemeyi yüzde olarak görürsünüz.

## Yol 3 — Toplu gönderim (`POST /fatura/toplu-isle`)

Birden fazla faturayı **tek bir zip dosyası** olarak gönderirsiniz; işlem arka planda yürür.

| | |
|---|---|
| **Yükleme** | `POST /fatura/toplu-isle` — gövde: ham zip (`Content-Type: application/zip`) |
| **İlerleme / özet** | `GET /fatura/toplu/{is_id}` |
| **Fatura bazında tam sonuç** | `GET /fatura/toplu/{is_id}/sonuclar` |
| **Sınırlar** | Zip en çok **200 MB**, en çok **2000 fatura**, tek XML en çok 30 MB |

### Zip yapısı — iki seçenek

**A) Tek şirketin faturaları** — `satici_vkn` parametresini verin; zip içindeki **tüm `.xml` dosyaları** o şirketin faturasıdır
(klasör düzeni önemli değil):

```
faturalar.zip
├── fatura-001.xml
├── fatura-002.xml
└── ...
```
```bash
curl -X POST "http://<host>:8100/fatura/toplu-isle?satici_vkn=6677889900" \
  -H "Authorization: Bearer $API_ANAHTARI" -H "Content-Type: application/zip" \
  --data-binary @faturalar.zip
```

**B) Birden fazla şirket** — `satici_vkn` vermeyin; kökte her şirket için **10 haneli VKN adında bir klasör** olsun:

```
faturalar.zip
├── 6677889900/
│   ├── fatura-001.xml
│   └── fatura-002.xml
└── 1122334455/
    └── fatura-101.xml
```
```bash
curl -X POST "http://<host>:8100/fatura/toplu-isle" \
  -H "Authorization: Bearer $API_ANAHTARI" -H "Content-Type: application/zip" \
  --data-binary @faturalar.zip
```

`.xml` olmayan dosyalar yok sayılır (cevapta `atlanan_dosya` olarak sayılır). Bir üst klasörle birlikte sıkıştırdıysanız sorun olmaz.

### Seçenekler (sorgu parametreleri)

| Parametre | Anlamı |
|---|---|
| `satici_vkn` | Tek şirket modu (yukarıda A). Verilmezse B düzeni beklenir |
| `onay=true` | Satış faturalarında KDV oranı uyarısı çıkarsa **yine de devam et**. Verilmezse o faturalar `onay_bekliyor` sonucuyla biter (hata değil) |
| `kur_secimi=orijinal` veya `tl` | Döviz faturalarına uygulanır. Verilmezse o faturalar `kur_bekliyor` sonucuyla biter |

> Toplu işte tek tek soru sorulamaz; bu iki seçenek **zip'teki tüm faturalara** uygulanır. Uyarı verenler ayrıca işaretlenir,
> sonra yalnızca onları doğru seçenekle yeniden gönderebilirsiniz.

### Yükleme cevabı

```json
{"is_id": "6047f013e94a412b992d200cd34f9dea", "durum": "kuyrukta", "toplam": 120,
 "vknler": ["1122334455", "6677889900"], "atlanan_dosya": 0}
```

Cevap **`202`** gelir ve **hemen** döner; `is_id`'yi saklayın. Yükleme sırasında şu kontroller yapılır — biri tutmazsa **hiçbir şey işlenmez**:
zip geçerli mi (`400`), içinde fatura var mı (`400`), zip'teki **her VKN** anahtarınıza yetkili mi (`403`), her şirket kurulu mu (`404`).

### İlerlemeyi takip etme

```bash
curl -s -H "Authorization: Bearer $API_ANAHTARI" "http://<host>:8100/fatura/toplu/<is_id>"
```

```json
{
  "is_id": "6047f0...", "durum": "calisiyor", "yuzde": 40, "toplam": 120, "tamamlanan": 48,
  "sayilar": {"hazir": 40, "onaysiz": 5, "onay_bekliyor": 1, "kur_bekliyor": 0, "hata": 2},
  "faturalar": {"sayfa": 1, "boyut": 100, "toplam_kayit": 48, "kayitlar": [
     {"sira": 1, "dosya": "fatura-001.xml", "vkn": "6677889900", "sonuc": "hazir", "fatura_no": "F2026001",
      "approvable": true, "prediction_id": "9f1c...", "red_kodlari": [], "mesaj": "..."},
     {"sira": 7, "dosya": "fatura-007.xml", "vkn": "6677889900", "sonuc": "hata", "http_durum": 400,
      "hata": "Geçersiz XML — belge ayrıştırılamadı"}
  ]}
}
```

İşin `durum` değeri: `kuyrukta` → `calisiyor` → **`bitti`**. `yuzde`, işlenen fatura sayısına göredir (bitince 100).

Her faturanın **`sonuc`** değeri:

| `sonuc` | Anlamı | Ne yapmalı |
|---|---|---|
| `hazir` | ✅ Kayıt hazır, doğrulamadan geçti (`approvable: true`) | Kaydı alın, onaylayın |
| `onaysiz` | Kayıt üretildi ama doğrulamadan geçemedi | `red_kodlari`/tam sonuca bakın; **onaylanamaz**, insan kontrolü |
| `onay_bekliyor` | KDV oranı uyarısı verdi, `onay` verilmediği için durdu | İnceleyip `onay=true` ile yeniden gönderin |
| `kur_bekliyor` | Döviz faturası, `kur_secimi` verilmediği için durdu | `kur_secimi` ile yeniden gönderin |
| `hata` | Fatura işlenemedi (bozuk XML vb.); nedeni `hata` alanında | Faturayı düzeltip yeniden gönderin |

Listeyi süzmek için: `?sonuc=hata` (ya da `onaysiz`, `onay_bekliyor`, `kur_bekliyor`, `hazir`). Sayfalama: `?sayfa=2&boyut=100` (en çok 500).

### Muhasebe kayıtlarını (records[]) alma

Özet liste `records[]` içermez (hafif kalsın diye). Faturaların **tam sonucunu** (her biri tek istekteki cevapla aynı biçimde) şuradan alırsınız:

```bash
curl -s -H "Authorization: Bearer $API_ANAHTARI" "http://<host>:8100/fatura/toplu/<is_id>/sonuclar?sayfa=1&boyut=20"
```

Her kayıtta `cevap.tdhp_tahmini.dis_sema.records[]` bulunur. Sayfa boyutu en çok 100'dür; `?sonuc=hazir` ile yalnızca hazır olanları alabilirsiniz.

### Önemli kurallar

- **Hata, diğer faturaları durdurmaz.** Bozuk bir XML yalnızca kendi satırını `hata` yapar.
- **Yeniden gönderme güvenlidir ama aynı faturayı tekrar işler.** Yalnızca düzeltilmesi gereken faturaları yeni bir zip'e koyup gönderin.
- **Sunucu yeniden başlarsa iş kaldığı yerden devam eder**; işlenmiş faturalar tekrar işlenmez.
- **Gönderdiğiniz ham XML'ler iş bitince sunucudan silinir.** Sonuçlar **14 gün** saklanır; sonra silinir. Sonuçlarınızı bu süre içinde alın.
- Başka bir anahtarın işini sorgularsanız `404` alırsınız. Aynı anda en fazla 5 bekleyen toplu iş olabilir (`429`).
- Hız: fatura başına genelde 10–30 sn; toplu iş şu an **bir faturayı işler**, tek istekler için yer bırakır.
  Yani saatte kabaca 120–360 fatura. 2000 faturalık bir zip saatler sürebilir; ilerlemeyi `yuzde` ile izleyin.

## Onaylama (isteğe bağlı ama önerilir) — `POST /fatura/onayla`

Muhasebeci bir kaydı doğru bulursa onaylar; onaylanan kayıt kalıcı olarak saklanır ve sistemin **sonraki benzer faturalarda daha iyi
tahmin üretmesini** sağlar. Onay için kayıtlardaki `prediction_id` kullanılır:

```bash
curl -s -X POST http://<host>:8100/fatura/onayla \
  -H "Content-Type: application/json" -H "Authorization: Bearer $API_ANAHTARI" \
  -d '{"prediction_id": "9f1c..."}'
```

- Yalnızca `approvable: true` kayıtlar onaylanabilir (`422` aksi halde). Onay **otomatik yapılmaz**, sizin kararınızdır.
- **Süre:** Tek istekle alınan tahminler **30 dakika**, toplu işle alınanlar **24 saat** onaylanabilir; sonra `409` döner
  (faturayı yeniden işlemeniz gerekir).
- Aynı kayıt ikinci kez onaylanamaz (`409`). Başka şirketin kaydı `404` döner.

## Python örneği (toplu)

```python
import os, time, requests

BASE = "http://<host>:8100"
H = {"Authorization": f"Bearer {os.environ['API_ANAHTARI']}"}

# 1) Zip'i yükle (tek şirket)
with open("faturalar.zip", "rb") as f:
    r = requests.post(f"{BASE}/fatura/toplu-isle", params={"satici_vkn": "6677889900"},
                      headers={**H, "Content-Type": "application/zip"}, data=f, timeout=600)
r.raise_for_status()
is_id = r.json()["is_id"]
print("toplam fatura:", r.json()["toplam"])

# 2) Bitene kadar bekle
while True:
    d = requests.get(f"{BASE}/fatura/toplu/{is_id}", headers=H, timeout=60).json()
    print(f"%{d['yuzde']}  {d['tamamlanan']}/{d['toplam']}  {d['sayilar']}")
    if d["durum"] == "bitti":
        break
    time.sleep(30)

# 3) Hazır olanların tam sonuçlarını sayfa sayfa al
sayfa = 1
while True:
    s = requests.get(f"{BASE}/fatura/toplu/{is_id}/sonuclar", headers=H,
                     params={"sonuc": "hazir", "sayfa": sayfa, "boyut": 50}, timeout=60).json()
    for k in s["kayitlar"]:
        dis_sema = k["cevap"]["tdhp_tahmini"].get("dis_sema") or {}
        records = dis_sema.get("records", [])
        print(k["dosya"], "→", len(records), "kayıt")
    if sayfa * s["boyut"] >= s["toplam_kayit"]:
        break
    sayfa += 1

# 4) Sorunlu faturaları listele
for k in requests.get(f"{BASE}/fatura/toplu/{is_id}", headers=H, params={"sonuc": "hata"}, timeout=60).json()["faturalar"]["kayitlar"]:
    print("HATA:", k["dosya"], k["hata"])
```

## Hata kodları (yükleme ve sorgu istekleri)

| Kod | Anlamı |
|---|---|
| `400` | Zip bozuk/zip değil, güvensiz dosya yolu (`../`), parolalı zip, zip içinde fatura (.xml) yok, fatura sayısı/boyut sınırı aşıldı |
| `401` | API anahtarı yok, geçersiz ya da iptal edilmiş |
| `403` | Anahtar, zip'teki (ya da `satici_vkn` ile verilen) VKN'lerden birine yetkili değil — **hiçbir fatura işlenmez** |
| `404` | VKN için kayıtlı şirket yok (önce kurulmalı) · iş bulunamadı / başka anahtara ait |
| `413` | Zip 200 MB sınırını aşıyor |
| `422` | Parametre biçimi hatalı (`satici_vkn` 10 hane olmalı; `kur_secimi` yalnızca `orijinal`/`tl`) |
| `429` | Çok fazla bekleyen toplu iş; biri bitince tekrar deneyin |

> Windows'ta zip hazırlarken `tar -a -c -f faturalar.zip <klasör>` ya da 7-Zip kullanın; eski "sıkıştır" araçları dosya yollarında
> `\` kullanır ve güvenlik nedeniyle reddedilir (`400`).

## Kontrol listesi

- [ ] Şirket kurulu mu (`GET /kayitli-sirketler`) ve anahtarınız o VKN'ye yetkili mi?
- [ ] Faturalar UTF-8 UBL-TR XML mi? Zip'te yalnızca `.xml` var mı?
- [ ] Zaman aşımı ≥ 600 sn (tek istek) — ya da çok fatura için toplu yol?
- [ ] Döviz/satış faturaları için `onay` ve `kur_secimi` kararını verdiniz mi?
- [ ] Sonuçları 14 gün içinde aldınız mı, onaylanacak kayıtları onay süresi dolmadan onayladınız mı?
