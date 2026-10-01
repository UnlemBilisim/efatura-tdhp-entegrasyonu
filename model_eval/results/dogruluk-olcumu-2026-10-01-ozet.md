# Sistem Doğruluk Ölçümü — Özet (2026-10-01)

## Ne yapıldı

Sistemimizin ürettiği muhasebe kayıtlarının gerçek doğruluğunu ölçmek için,
elimizdeki **1.646 gerçek, zaten muhasebeleşmiş fatura** (Akyüzlü'nün son
dönem fatura arşivi) sisteme yeniden işletildi ve çıkan sonuç, muhasebecinin
**gerçekte kaydettiği** kayıtla birebir karşılaştırıldı.

## Sonuç

| Ölçüm | Sayı |
|---|---|
| Test edilen fatura | 1.646 |
| Başarıyla tamamlanan | 1.635 (11 tanesi teknik/ağ hatası nedeniyle ölçüme girmedi) |
| **Tamamen hatasız üretilen fatura oranı** | **%81,4** |
| Borç/Alacak dengesi tutan fatura oranı | %98,96 |

**Nasıl okunmalı:** "%81,4" rakamı en katı ölçüm — bir faturanın bu orana
girmesi için **tüm kalemlerinin, tüm hesap kodlarının ve tüm Borç/Alacak
yönlerinin** gerçek muhasebeci kaydıyla birebir aynı olması gerekiyor. Tek
bir kalemde ufak bir sapma olsa bile o fatura bu orana girmiyor — yani bu,
"iyimser" değil "gerçekçi" bir sayı.

## Sınırlar — reklamda/sunumda belirtilmesi gereken noktalar

1. **Bu ölçüm tek bir şirketin (mevcut müşterimiz) verisiyle yapıldı.**
   Farklı sektör/muhasebe alışkanlığına sahip yeni bir müşteride oran
   değişebilir — düşük veya yüksek.
2. **Sistem zaten "emin olmadığı" kayıtları otomatik onaylamıyor** — hatalı
   çıkma ihtimali yüksek faturalar ayrıca bir doğrulama katmanından geçip
   insana (muhasebeciye) bırakılıyor. Yani üretimde kullanıcı gördüğü kayıt
   bu ham %81,4'ten daha güvenilir olabilir, çünkü riskli olanlar zaten
   ayrıca işaretleniyor.
3. **Bu, bağımsız/dış bir denetim değil, kendi iç ölçümümüz.**

## Kaynak

Ölçüm script'i ve ham sonuçlar: `model_eval/results/summary.json`
(2026-10-01 tarihli koşu, model: `gemma4:31b-cloud`, RAG + öz-düzeltme +
tevkifat/iade ipucu modülleri açık).
