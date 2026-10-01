# Dış Ekibe Teslim Edilecek Belgeler

Bu klasördeki 4 dosya, dış ekibe (arayüzü yazacak ekip) gönderilecek
paketin tamamıdır.

| Dosya | Ne işe yarar |
|---|---|
| [`API-ENTEGRASYON-KILAVUZU.md`](API-ENTEGRASYON-KILAVUZU.md) | Hızlı başlangıç — endpoint, örnek istek/cevap, cURL örneği |
| [`API-KAYIT-SEMASI-REFERANS.md`](API-KAYIT-SEMASI-REFERANS.md) | Tam referans — `records[]` şemasının her alanı, `account_code_reason` üretim kuralları, tüm hata kodları |
| [`ONBOARDING-VERI-FORMATI.md`](ONBOARDING-VERI-FORMATI.md) | Yeni şirket eklerken istediğimiz 3 dosya (VKN, fatura XML, mizan, yevmiye) formatı |
| [`yevmiye-sablonu-ornek.xlsx`](yevmiye-sablonu-ornek.xlsx) | Yevmiye kaydı için örnek dosya (gerçek, doğrulanmış bir kayıttan) |

## Kaynak / senkron notu

`API-KAYIT-SEMASI-REFERANS.md`, kod tabanındaki
[`entegrasyon/docs/reference/dis-ekip-api-kullanimi.md`](../entegrasyon/docs/reference/dis-ekip-api-kullanimi.md)
dosyasının **2026-10-01 tarihli bir kopyasıdır** — orijinal orada kalmaya
devam eder (Diátaxis yapısının parçası, iç geliştirme sürecinde referans
alınır). Bu iki dosya **otomatik senkron değildir** — kaynak dosya
güncellenirse buradaki kopya da elle güncellenmeli, aksi halde dış ekibe
giden sürüm bayatlar. Yeni bir teslim öncesi kaynağı tekrar kopyalamak
en güvenli yol.

## Gönderim öncesi kontrol listesi

- [ ] `API-KAYIT-SEMASI-REFERANS.md` kaynak dosyayla güncel mi (yukarıdaki not)
- [ ] Endpoint IP'si güncel mi (`API-ENTEGRASYON-KILAVUZU.md` başındaki uyarı — DHCP, değişebilir)
- [ ] İlgili mali müşavir için API anahtarı hazır mı — yeni müşavirse
  `entegrasyon/api_anahtari_yonet.py olustur`, var olan bir müşavirin yeni
  müşterisiyse `... vkn-ekle --etiket <müşavir> --vkn <yeni-vkn>` (anahtar
  DEĞİŞMEZ) — ve ayrı/güvenli bir kanaldan iletilecek/teyit edilecek mi
  (belgenin kendisine anahtar YAZILMAZ)
