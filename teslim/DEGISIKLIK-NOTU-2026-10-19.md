# Güncelleme — 2026-10-19

Bir önceki pakete (2026-10-16) göre **ne yeni**. Bu not yalnızca farkı özetler; ayrıntı ilgili belgelerdedir.

**Endpoint'ler, kimlik doğrulama ve mevcut alan adları DEĞİŞMEDİ.** Yalnızca alan eklendi, bir doğrulama hatası düzeltildi, mizan okuması
genişledi ve gönderdiğiniz dosyaların saklanma biçimi değişti (§4 — önceki belgelerdeki bir ifadeyi değiştiriyor, lütfen okuyun).

## Sizden beklenen iki kontrol

1. **İlerleme/bitiş:** İşin bittiğini iş düzeyindeki `durum == "bitti"` ile anlayın. Şirket durumlarından `kuruldu`, `guncellendi`, `degismedi`
   **başarılı** sayılmalı (§1). Kayıtlı bir şirkete veri gönderince `guncellendi` (fark varsa) ya da `degismedi` döner; arayüz bunları tanımazsa ekranda "devam ediyor" olarak kalır.
2. **Hesap kodu biçimi:** `records[].account_code` artık herhangi bir derinlikte olabilir (`600.01`, `120.1234`, `150.01.001`). Sabit biçim
   (`XXX.YY.ZZZZZ`) varsaymayın (§3).

## 1. Bitiş sinyali ve durum değerleri

`GET /musteri/isler/{is_id}` cevabında iki ayrı düzey vardır:

| Düzey | Alan | Değerler | Anlamı |
|---|---|---|---|
| **İş** | `durum` | `kuyrukta` → `calisiyor` → **`bitti`** | **Bitiş sinyali budur.** `bitti` görünce sorgulamayı bırakın |
| İş | `yuzde` | 0–100 | `bitti` iken her zaman **100**. Kendi yüzdenizi hesaplamayın, "99'da bekle" gibi bir tavan koymayın |
| **Şirket** | `sirketler.<vkn>.durum` | `bekliyor`, `calisiyor` | Sürüyor |
| Şirket | | **`kuruldu`** | Yeni şirket kuruldu ✅ |
| Şirket | | **`guncellendi`** | Kayıtlı şirkete gelen veride **fark vardı**, uygulandı ✅ |
| Şirket | | **`degismedi`** | Kayıtlı şirkete gelen veri mevcutla aynıydı, hiçbir şey yazılmadı ✅ |
| Şirket | | `atlandi` | Yapılmadı (örn. anahtarın o şirket üzerinde yetkisi yok) ⚠️ nedeni `ayrinti`'de |
| Şirket | | `hata` | Başarısız ❌ nedeni `ayrinti`'de |

Önerilen akış:

```python
while True:
    d = requests.get(f"{BASE}/musteri/isler/{is_id}", headers=HEADERS, timeout=30).json()
    if d["durum"] == "bitti":
        break
    time.sleep(5)

for vkn, s in d["sirketler"].items():
    if s["durum"] in ("kuruldu", "guncellendi", "degismedi"):
        ...  # başarılı
    elif s["durum"] == "atlandi":
        ...  # uyarı olarak göster: s["ayrinti"]
    else:    # "hata"
        ...  # hata olarak göster: s["ayrinti"]
```

Gerçek bir cevap (10:44'te gönderdiğiniz güncelleme, özet kısaltıldı):

```json
{
  "is_id": "b0403bd841544cd59d9681ff7b512379", "durum": "bitti", "yuzde": 100,
  "sirketler": {
    "7610928437": { "durum": "guncellendi", "yuzde": 100, "adim": "rag", "ayrinti": null,
                    "ozet": { "mod": "guncelleme", "degisiklik_var": true,
                              "mizan": { "eklenen": 2618, "degisen": 0, "silinen": 0, "uygulandi": true, "toplam": 2635 },
                              "rag":   { "yeni": 32, "degisen": 0, "ayni": 985, "taranan": 1017 } } }
  }
}
```

Bu iş sunucumuzda 10:44'te 8 saniyede bitti; sonraki sorgularınızın hepsi `durum: "bitti"`, `yuzde: 100` döndü.

## 2. Mizan: her derinlikteki hesap artık okunuyor

**Ne olmuştu:** Mizandaki hesap kodlarının yalnızca tam 3 parçalı olanları (`150.01.001`) alınıyor, `600.01` ya da `120.1234` gibi **2 parçalı hesaplar
uyarı verilmeden atlanıyordu.** İlk gönderdiğiniz mizandan bu yüzden yalnızca 17 hesap (hepsi `150.01.*`) kaydedilmişti. Dosyanız eksik değildi; eksik olan
bizim okuyucumuzdu.

**Düzeltme:** Mizan şimdi şu kuralla okunur:

- Alınır: ilk parçası 3 haneli ana kod olan, **en az 2 parçalı** ve dosyada **altında başka hesap bulunmayan** her kod (`600.01`, `120.1234`, `150.01.001`, 4 parçalı da olur).
- Alınmaz: `320` gibi yalnızca ana kod satırları; altında hesap bulunan üst gruplar (örn. `150.01` altında `150.01.001` varsa).
- Yalnızca **ilk sayfa** okunur. HESAP KODU hücresi **metin** biçiminde olmalı.

Sizin mizanınızla sonuç (19 Ekim, 10:44 güncellemesi): dosyada 2935 kodlu satır → **2635 hesap** alındı (2618'i yeni eklendi, 17'si zaten vardı); 299 ana kod satırı ve 1 üst grup (`150.01`)
atlandı. Hesaplar 43 ana koda dağıldı (örn. `120` altında 2090 müşteri, `320` altında 262 tedarikçi). Yevmiyenizdeki hesap satırlarının %99,1'i artık mizanda tam kodla bulunuyor
(kalanlar `100`, `335`, `361`, `780`, `196` gibi alt hesabı olmayan ana kodlar).

### Yeni alan: `ozet.mizan_okuma` (yeni şirket) / `ozet.mizan.okuma` (kayıtlı şirket güncellemesi)

Mizan dosyasında ne bulunduğunu ve neyin neden alınmadığını söyler (yalnızca **ekleme**; mevcut alanlar aynı):

```json
"okuma": {
  "okunan_satir": 2935, "kabul_edilen": 2635,
  "derinlik": { "2": 2618, "3": 17 },
  "atlanan": { "ana_kod": 299, "ust_grup": 1, "sayi_bicimli": 0, "gecersiz_kod": 0, "tekrar": 0 },
  "atlanan_ornek": { "ust_grup": ["150.01"] },
  "okunmayan_sayfalar": [],
  "uyari": []
}
```

`uyari` doluysa kullanıcıya gösterin; her madde ne yapılması gerektiğini söyler (örn. "ilk sayfadan başka sayfa var", "HESAP KODU hücresi sayı biçiminde — atlandı"). `uyari` boş ve
`kabul_edilen` beklediğiniz hesap sayısına yakınsa mizan tam okunmuştur.

### Yalnızca mizanı yeniden göndermek

Kayıtlı bir şirket için zip'te yalnızca `mizan.xlsx` göndermeniz yeterlidir (`<VKN>/mizan.xlsx`); `faturalar/` ve yevmiye göndermeniz gerekmez. Mizan **tam hesap planı** sayılır:
dosyada olmayan hesap silinir (eski değeri kayıtta kalır). Dosya boşsa ya da mevcut hesapların yarısından fazlası silinecekse mizan **değiştirilmez** ve `uyari` döner. Ayrıntı:
`MUSTERI-ONBOARD-ZIP-KILAVUZU.md`, `ONBOARDING-VERI-FORMATI.md`.

## 3. Hesap kodu biçimi ve `/fatura/isle` sonuçları

- **Düzeltilen hata:** Sonuç doğrulaması hesap kodunu yalnızca `XXX.YY.ZZZZZ` (ortası 2, sonu 5 hane) biçiminde kabul ediyordu. Farklı biçimli bir hesap planında (sizinki gibi) geçerli alt hesaplar
  `validation_errors` içinde `INVALID_ACCOUNT_FORMAT` ile reddediliyor, kayıt `approvable: false` çıkıyordu. Artık hesap kodu ana kod + herhangi sayıda `.parça` olabilir.
  Alt hesabın **şirket mizanında bulunması** şartı aynen sürer (aksi halde `SUBACCOUNT_NOT_IN_LEDGER`).
- **`records[].account_code` artık her derinlikte olabilir**, örnekler: `600.01`, `120.1234`, `150.01.001`, `120.ZED` (harf içerebilir). Ana kod her zaman ilk 3 hanedir. Hesap kodunu
  `.` ile bölerek okuyun; parça sayısı ya da genişliği için sabit kural koymayın.
- `onerilen_yeni_kod`: sıra numarasının genişliği artık o hesap grubundaki mevcut kodlardan alınır (3 haneli dolgu kullanan planda `150.01.016`; 2 parçalı planda `600.10`).
- KDV oranı düzeltmesi (fatura oranıyla çelişen KDV alt kodunun aynı tür içinde düzeltilmesi) 2 parçalı hesap planlarında da çalışır.
- **Müşteri/tedarikçi (cari) hesabı yalnızca ad eşleşmesiyle bağlanır.** Karşı taraf mizanda yoksa `account_code` 3 haneli kalır (`120`), `validation_errors` içinde
  `UNRESOLVED_COUNTERPARTY` döner, `records[].onerilen_yeni_kod` yeni cari kart numarası önerir ve `approvable: false` olur — bu kayıt `/fatura/onayla` ile onaylanamaz, muhasebe kontrolü gerekir.
  Önceden model, mizanda olmayan bir müşteri için en yakın isimli **başka** bir müşteri kartını seçebiliyordu; bu artık yapılmıyor.
  **Kartı bulma kuralı:** Faturadaki ünvan ile mizandaki cari kart adı; büyük/küçük harf, Türkçe karakter ve şirket eki farkları (`A.Ş.` / `Anonim Şirketi`, `Ltd.Şti.` / `Limited Şirketi`) yok sayılarak
  karşılaştırılır. Kart adı ünvanın **noktalı kısaltması ya da kesilmiş hali** ise de bulunur (`TAHA KALIP MAKİNA OTOM.LTD.ŞTİ.`, `GENÇBEY HAYVANCILIK VE TAR.LTD.ŞTİ.`). Kişi adı ile ticari ad birlikte
  yazılmışsa (`MEHMET ALİ ŞAHİN - ŞAHİN TAKOGRAF`) tireden önceki kısım karta uyuyorsa bulunur. **Bulunmaz:** ayırt edici bir kelimesi farklıysa (`FARUK KARAGÖZ` ≠ `FARUK KARAMAN`, `ANADOLU FIRIN A.Ş.` ≠
  `ANADOLU UN A.Ş.`), hukuki form farklıysa (`Ltd.Şti.` ≠ `A.Ş.`) ya da noktasız kısaltma varsa. **Aynı adlı birden fazla kart varsa** (mükerrer cari kart) hangisinin kullanılacağı belirsizdir: kart seçilmez,
  `UNRESOLVED_COUNTERPARTY` döner, uyarıda aday kartlar listelenir ve yeni kart önerilmez. Gerçek verinizle ölçüm (faturalarınızdaki 990 cari satır): kartı doğru bulma %83, yanlış karta bağlama ~%0,
  geri kalan %17 muhasebe kontrolüne düşer. Mükerrer kartları mizanda tekilleştirirseniz belirsiz sonuçlar da çözülür. Yeni kart açıldıktan sonra mizanı yeniden gönderin (§2), fatura bir sonraki işlemede kartı bulur.
- KDV ve gider/gelir alt hesap seçimi, model cevabını farklı biçimde yazdığında bazen çözülemiyordu; düzeltildi.

## 4. DEĞİŞİKLİK: Gönderdiğiniz dosyaların saklanması

**Önceki belgelerdeki "ham dosyalarınız iş bitince sunucudan silinir" ifadesi bu notla değişmiştir.** İşleme sırasındaki çalışma kopyası eskisi gibi iş bitince silinir. **Ek olarak**,
sorun çıktığında (örn. "mizan eksik görünüyor") gönderdiğiniz dosyaya bakabilmemiz için bir kopya ayrı bir arşivde **sınırlı süre** tutulur:

| | |
|---|---|
| **Ne saklanır** | Geçerli API anahtarıyla gelen isteklerin: `/musteri/onboard` ve `/fatura/toplu-isle` için gelen **zip**, `/fatura/isle` için **fatura XML'i**; her üçü için bizim verdiğimiz **cevap** ve istek bilgisi (zaman, anahtar etiketi, IP, VKN, durum, hata nedeni). Hata alan istekler de (geçersiz zip, yetkisiz VKN gibi) hata nedenini incelemek için saklanır |
| **Ne kadar süre** | **7 gün**, sonra otomatik silinir (toplam boyut 2 GB'ı aşarsa en eskiler daha erken silinir) |
| **Kim görebilir** | **Yalnızca** sunucuya erişimi olan operatörlerimiz. API'de arşive erişen **bir uç nokta yoktur**; sizin de bu arşive erişiminiz yoktur |
| **Ne saklanmaz** | Geçerli anahtarı olmayan (`401`) istekler. API anahtarınız düz metin olarak saklanmaz ya da loglanmaz (yalnızca geri döndürülemeyen özeti tutulur) |

Bu süre bizim tarafımızda ayarlanabilir (kapatılabilir ya da kısaltılabilir). Müşteri verisi içeren dosyalar için farklı bir saklama ihtiyacınız ya da itirazınız varsa bize bildirin.
Değişmeyenler: toplu fatura **sonuçları** 14 gün saklanır (`GET /fatura/toplu/{is_id}/sonuclar`); `/fatura/onayla` ile onayladığınız kayıtlar kalıcıdır.

## 5. Sorun bildirirken

Şunları iletirseniz dosyanızı yeniden göndermenize gerek kalmadan (7 gün içinde) isteği sunucuda bulabiliriz:

- `POST` cevabındaki **`is_id`** (kaydetmeyi unutmayın; sorgu ve arama anahtarıdır — iş listeleyen bir uç nokta yoktur),
- cevabın **`X-Request-ID`** başlığı,
- VKN ve isteği gönderdiğiniz yaklaşık saat.

## Değişmeyenler

Endpoint adresleri, `Authorization: Bearer` doğrulaması, istek gövdeleri, `records[]` alan adları ve anlamları, `approvable` / `validation_errors` yapısı, onay süreleri ve
sınırlar (zip ≤ 200 MB vb.) aynıdır. Eklenenler: `ozet.mizan_okuma` / `ozet.mizan.okuma` (§2). Gerekli tek entegrasyon değişikliği §1'deki bitiş/durum kontrolüdür.
