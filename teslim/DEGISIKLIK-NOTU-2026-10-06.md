# Güncelleme — 2026-10-06

2026-10-02 tarihli paketle karşılaştırıldığında **ne değişti ve ne yeni** — bu dosya yalnızca farkı özetler; ayrıntı için
ilgili belgenin kendisine bakın. **Mevcut entegrasyonunuzu bozan hiçbir değişiklik yoktur** (aşağıdaki "Geriye dönük uyumluluk" bölümüne bakın).

## Hangi dosyalar değişti?

| Dosya | Durum |
|---|---|
| `MUSTERI-ONBOARD-ZIP-KILAVUZU.md` | **YENİ** — yeni şirketleri zip ile yükleme |
| `API-KAYIT-SEMASI-REFERANS.md` | **Güncellendi** — yeni §9 (zip uç noktası), `records[]` için yeni 7. alan, uç nokta listesi |
| `ONBOARDING-VERI-FORMATI.md` | **Güncellendi** — yeni §0 (zip yapısı ve zorunlu dosya adları) |
| `API-ENTEGRASYON-KILAVUZU.md` | Değişmedi |
| `yevmiye-sablonu-ornek.xlsx` | Değişmedi |

Eski sürümlerin üzerine yenilerini koymanız yeterlidir.

## 1. YENİ: Yeni şirketleri zip ile toplu yükleme

Yeni müşterilerinizin (şirketlerin) verisini artık **tek bir zip** ile bize yükleyebilirsiniz; her şirket kurulur ve
sonrasında `POST /fatura/isle` ile fatura işleyebilirsiniz.

| | |
|---|---|
| **Yükleme** | `POST /musteri/onboard` — gövde: ham zip (`Content-Type: application/zip`), en çok 200 MB |
| **İlerleme** | `GET /musteri/isler/{is_id}` — **yüzde (`yuzde`)** ve şirket bazında sonuç |
| **Yetki** | Anahtarınızda **onboard yetkisi** olmalı — bizden talep edersiniz (aşağıya bakın) |

Zip'in kökünde her şirket için bir klasör bulunur; **klasör adı şirketin 10 haneli VKN'sidir** ve içinde tam olarak
`mizan.xlsx`, `faturalar/*.xml`, `yevmiye.xlsx` (ya da `.csv`) ve isteğe bağlı `nace.txt` yer alır.

- **İşlem arka planda yapılır:** yükleme hemen `202` ve bir `is_id` döner; sonucu bu numarayla sorgularsınız.
- **İlerleme yüzdesi:** cevaptaki `yuzde` (0–100) işin genel ilerlemesidir. Her şirketin kendi `yuzde` ve `adim` değeri de vardır
  (`sema` 25 → `mizan` 50 → `eslestirme` 75 → `rag` 100). Yüzde adım adım artar; fatura sayısı çoksa son adımlarda bir süre
  aynı değerde kalabilir (takılma değildir).
- **Mevcut şirketler değiştirilmez:** zaten sistemde kayıtlı bir VKN gönderirseniz o şirket `atlandi` olur, verisi olduğu gibi kalır.
  Bu uç nokta yalnızca **yeni** şirket kurmak içindir.
- **Bir şirkette hata olması diğerlerini durdurmaz.** Hata veren şirketin nedeni `ayrinti`'de gelir; düzeltip aynı zip'i
  yeniden gönderebilirsiniz (`kuruldu` olanlar `atlandi` ile geçilir, hatalı olan yeniden kurulur).
- **Kurulum başarılı olunca yeni şirketin VKN'si anahtarınızın kapsamına otomatik eklenir** — ayrıca bir işlem gerekmez.
- **Verileriniz iş bitince sunucudan silinir**; yalnızca kurulum sonucu kalır.
- Zip güvenli açılır: `../` içeren yollar, parola korumalı zip, aşırı büyük/aşırı sıkıştırılmış içerik reddedilir.

### Onboard yetkisini nasıl alırsınız?

Bu uç nokta, normal API anahtarından **ayrı bir yetki** ister ve kendiniz alamazsınız — bizden talep edersiniz.
Mevcut anahtarınıza yetki eklenir (anahtarınız değişmez) ya da size yetkili yeni bir anahtar ayrı ve güvenli bir kanaldan iletilir.
Yetkinizi zip göndermeden test edebilirsiniz: bilerek zip olmayan bir gövdeyle çağırın — `400` ("Gövde bir zip dosyası
değil") yetkiniz var, `403` yetkiniz yok demektir. Ayrıntı ve örnek: `MUSTERI-ONBOARD-ZIP-KILAVUZU.md` §1.

## 2. `records[]` — yeni 7. alan: `onerilen_yeni_kod`

Her `records[]` öğesine **`onerilen_yeni_kod`** alanı eklendi (`string` ya da `null`; alan **her kayıtta** bulunur).

- Bir cari hesap için mizanda eşleşen alt kırılım (cari kart) **hiç bulunamadığında** (`account_code` 3 haneli kaldığında),
  mizandaki mevcut kodlarla **çakışmayan** yeni bir alt kod önerir (örn. `"320.01.00967"`).
- **Yalnızca bir öneridir** — mizana hiçbir şey yazılmaz ve bu kayıt zaten onaysız kalır (muhasebeci karar verir).
- KDV hesaplarında (191/391) **hiç üretilmez** (oran mevzuata bağlıdır).
- Alt kırılım çözüldüyse ya da öneri üretilemediyse `null`'dır.

Şema artık **7 alanlıdır** (`API-KAYIT-SEMASI-REFERANS.md` §3.1).

## 3. Düzeltme: büyük fatura XML'i

Daha önce belgede "istek sınırı 30 MB" yazıyordu, ancak `fatura_xml` alanı **5 MB**'ı (karakter) aştığında
`413` yerine `422` ile reddediliyordu — gerçek sınır belgelenenden küçüktü. Artık `fatura_xml` en çok **30 MB**'a kadar
gerçekten kabul edilir; 30 MB'ı aşan istek `413` döner.

## Geriye dönük uyumluluk

- **`POST /fatura/isle`, `/fatura/onayla`, `/kayitli-sirketler`, `/durum`:** istek ve cevap biçimleri aynı. Tek ekleme,
  `records[]` içindeki yeni `onerilen_yeni_kod` alanıdır — bilinmeyen alanları yok sayıyorsanız hiçbir şey yapmanız gerekmez.
- **Anahtarlarınız** aynen çalışmaya devam eder; onboard yetkisi yalnızca talep ederseniz eklenir.
- Zip uç noktası **tamamen yeni**dir; kullanmazsanız hiçbir şey değişmez.

## Sizin yapmanız gerekenler

- [ ] Eski belgelerin üzerine yenilerini koyun (yukarıdaki tablo).
- [ ] Zip ile şirket yüklemek istiyorsanız anahtarınız için onboard yetkisi isteyin.
- [ ] `records[]` cevabını katı şemayla (bilinmeyen alanı reddeden) işliyorsanız `onerilen_yeni_kod` alanını ekleyin.
