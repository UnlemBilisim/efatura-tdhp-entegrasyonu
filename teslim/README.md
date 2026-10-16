# Dış Ekibe Teslim Edilecek Belgeler

Bu klasördeki dosyalar, dış ekibe (arayüzü yazacak ekip) gönderilecek
paketin tamamıdır.

| Dosya | Ne işe yarar |
|---|---|
| [`DEGISIKLIK-NOTU-2026-10-16.md`](DEGISIKLIK-NOTU-2026-10-16.md) | **En güncel** — toplu fatura işleme (zip), paralel istek davranışı |
| [`FATURA-ISLEME-KILAVUZU.md`](FATURA-ISLEME-KILAVUZU.md) | **Yeni:** fatura işlemenin baştan sona anlatımı (tek fatura, paralel, toplu zip, onay, hata kodları, örnek kod) |
| [`DEGISIKLIK-NOTU-2026-10-06.md`](DEGISIKLIK-NOTU-2026-10-06.md) | Bir önceki güncelleme — 2026-10-02 paketine göre ne değişti (zip ile şirket yükleme, `onerilen_yeni_kod`, büyük XML düzeltmesi) |
| [`DEGISIKLIK-NOTU-2026-10-01.md`](DEGISIKLIK-NOTU-2026-10-01.md) | **Daha önce elinizdeki sürümle karşılaştırıldığında ne değişti** — önce bunu okuyun |
| [`API-ENTEGRASYON-KILAVUZU.md`](API-ENTEGRASYON-KILAVUZU.md) | Hızlı başlangıç — endpoint, örnek istek/cevap, cURL örneği |
| [`API-KAYIT-SEMASI-REFERANS.md`](API-KAYIT-SEMASI-REFERANS.md) | Tam referans — `records[]` şemasının her alanı, `account_code_reason` üretim kuralları, tüm hata kodları |
| [`MUSTERI-ONBOARD-ZIP-KILAVUZU.md`](MUSTERI-ONBOARD-ZIP-KILAVUZU.md) | **Yeni:** yeni şirketleri tek zip ile yükleme — uç nokta, zip yapısı, ilerleme sorgulama, hata kodları, örnek kod |
| [`ONBOARDING-VERI-FORMATI.md`](ONBOARDING-VERI-FORMATI.md) | Yeni şirket eklerken istediğimiz 3 dosya (VKN, fatura XML, mizan, yevmiye) formatı |
| [`yevmiye-sablonu-ornek.xlsx`](yevmiye-sablonu-ornek.xlsx) | Yevmiye kaydı için örnek dosya (gerçek, doğrulanmış bir kayıttan) |

## Kaynak / senkron notu

`API-KAYIT-SEMASI-REFERANS.md`, kod tabanındaki
[`entegrasyon/docs/reference/dis-ekip-api-kullanimi.md`](../entegrasyon/docs/reference/dis-ekip-api-kullanimi.md)
dosyasının **dış ekip için sadeleştirilmiş bir kopyasıdır** (2026-10-06: iç dosya yolları, "✅ Uygulandı" damgaları, iç şema/test anlatımları ve kırık bağlantılar çıkarıldı; sözleşme içeriği aynı). Eski kopya 2026-10-01 tarihliydi — orijinal orada kalmaya
devam eder (Diátaxis yapısının parçası, iç geliştirme sürecinde referans
alınır). Bu iki dosya **otomatik senkron değildir** — kaynak dosya
güncellenirse buradaki kopya da elle güncellenmeli, aksi halde dış ekibe
giden sürüm bayatlar. Yeni bir teslim öncesi kaynağı tekrar kopyalamak
en güvenli yol.

## Gönderim öncesi kontrol listesi

- [ ] `API-KAYIT-SEMASI-REFERANS.md` kaynak dosyayla güncel mi (yukarıdaki not)
- [ ] Endpoint IP'si güncel mi (`API-ENTEGRASYON-KILAVUZU.md` başındaki uyarı — DHCP, değişebilir)
- [ ] Zip ile şirket yükleyecek müşavirin anahtarına onboard yetkisi verildi mi (`api_anahtari_yonet.py onboard-yetkisi --etiket <müşavir>`)
- [ ] İlgili mali müşavir için API anahtarı hazır mı — yeni müşavirse
  `entegrasyon/api_anahtari_yonet.py olustur`, var olan bir müşavirin yeni
  müşterisiyse `... vkn-ekle --etiket <müşavir> --vkn <yeni-vkn>` (anahtar
  DEĞİŞMEZ) — ve ayrı/güvenli bir kanaldan iletilecek/teyit edilecek mi
  (belgenin kendisine anahtar YAZILMAZ)
