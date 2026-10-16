# Güncelleme — 2026-10-01

Daha önce elinizdeki belge/entegrasyon ile karşılaştırıldığında şu değişiklikler oldu. Bu dosya sadece **neyin değiştiğini** özetler — tam, güncel detay için ilgili belgenin kendisine bakın.

## 1. Kimlik doğrulama yöntemi değişti

**Eskiden:** Tek, paylaşılan bir `EFATURA_API_TOKEN` ile çalışıyordu.

**Şimdi:** Şirkete bağlı API anahtarı (`efk_` ile başlayan) kullanılıyor. Bu anahtar size ayrı ve güvenli bir kanaldan verilir, sadece sunucu tarafınızda saklanmalı. İstek başlığı aynı kalıyor (`Authorization: Bearer <anahtar>`), sadece token'ın kendisi değişti.

**Yeni davranışlar:**
- Anahtarın yetkisi olmayan bir `satici_vkn` ile istek atarsanız → **`403`**
- Geçersiz/iptal edilmiş anahtarla istek atarsanız → **`401`**
- `satici_vkn` sistemde hiç kayıtlı (onboard edilmemiş) değilse → **`404`** (hangi VKN'lerin kayıtlı olduğunu `GET /kayitli-sirketler` ile görebilirsiniz)

## 2. `satici_nace_kodlari` artık göndermenize gerek yok

**Eskiden:** Her `/fatura/isle` isteğinde satıcının NACE kodlarını (`satici_nace_kodlari`) göndermeniz gerekiyordu.

**Şimdi:** Bu alan **opsiyonel**. NACE kodları, şirket sisteme eklenirken (onboarding) bizim tarafımızda bir kere kaydediliyor, her istekte otomatik kullanılıyor. Alanı sadece kayıtlı NACE'yi geçici olarak override etmek isterseniz doldurursunuz — göndermezseniz hata almazsınız, sistem kayıtlı değeri kullanır.

## 3. İstek boyutu sınırı 10 MB'dan 30 MB'a çıkarıldı

Çok büyük/çok kalemli bir fatura XML'i gönderirken önceden 10 MB'ta kesiliyordu (`413` hatası), artık sınır **30 MB**.

## 4. Yeni belgeler eklendi

Daha önce sadece hızlı başlangıç kılavuzu (`API-ENTEGRASYON-KILAVUZU.md`) paylaşılmıştı. Artık paket şunları da içeriyor:

| Belge | İçerik |
|---|---|
| `API-KAYIT-SEMASI-REFERANS.md` | Tam teknik referans — `records[]` şemasının her alanı, hata kodlarının tamamı |
| `ONBOARDING-VERI-FORMATI.md` | Yeni şirket eklerken bize gönderdiğiniz 3 zorunlu + 1 opsiyonel dosyanın kesin formatı (VKN, fatura XML, mizan, yevmiye, NACE) |
| `yevmiye-sablonu-ornek.xlsx` | Yevmiye kaydı için gerçek, doğrulanmış bir örnek dosya |
| `README.md` | Bu paketin içindekiler listesi ve gönderim öncesi kontrol listesi (bizim kendi notumuz) |

## 5. Dikkat edilmesi gereken bir şey yok, geriye dönük uyumlu

Yukarıdaki değişikliklerin hiçbiri mevcut entegrasyonunuzu **bozmaz** — `satici_nace_kodlari` gönderiyor olsanız bile çalışmaya devam eder (artık sadece zorunlu değil), sadece token'ı yeni anahtarla değiştirmeniz gerekiyor.
