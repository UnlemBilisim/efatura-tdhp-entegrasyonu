# İzleme Paneli

Mac'te çalışan, **salt okunur** bir web paneli: sunucuya SSH ile bağlanıp gelen istekleri, hata mesajlarını ve
onboarding (zip ile şirket kurma) işlerinin ilerlemesini gösterir; ayrıca **bize gelen dosyaları indirip incelemeni** ve **verdiğimiz cevabı görmeni** sağlar.

```bash
python3 izleme/panel.py            # sunucuyu izler  →  http://127.0.0.1:8300
python3 izleme/panel.py --yerel    # bu Mac'teki Docker'ı izler
```

Ek kurulum gerekmez (yalnızca Python 3 standart kütüphanesi). Sunucuya **parolasız SSH** erişimi olmalı
(`ssh unlem-gx10-01@10.34.10.112` parola sormadan açılmalı). Ayarlar: `IZLEME_SSH`, `IZLEME_CONTAINER`, `IZLEME_PORT`.

## Neler gösterir

| Sekme | İçerik |
|---|---|
| **İstekler** | Zaman, yöntem+yol, durum kodu, süre, istemci (API anahtarı etiketi) / IP, **hata mesajı**. Satıra tıklayınca tüm alanlar açılır |
| **Gelen dosyalar** | Sunucunun arşivlediği gelen istekler (zip / tek fatura): indirme düğmeleri; satıra tıklayınca zip içeriği, **bizim verdiğimiz cevap**, başlatılan iş (toplu işte fatura başına sonuçlar), o isteğe ait loglar. Ayrıntı: [`docs/how-to/gelen-dosyalari-inceleme.md`](../docs/how-to/gelen-dosyalari-inceleme.md) |
| **Onboarding işleri** | Her iş için yüzde çubuğu; şirket bazında durum (`kuruldu`/`atlandi`/`hata`), adım ve hata nedeni; **mizan okuma raporu** (dosyada kaç satır vardı, kaçı alındı, atlananların sebebi, ek sayfa/geçersiz kod uyarıları) |
| **Hata logları** | Uyarı/hata satırları (yetki reddi, beklenmeyen hata, Python hata izi) |
| **Ham log** | Son satırlar, filtresiz |

Üstte zaman penceresi, "yalnızca hatalar", "sağlık kontrollerini göster" ve otomatik yenileme (5 sn) var.

## Hata MESAJLARI için sunucuda ne gerekir?

Sunucu eski sürümde (yalnız `uvicorn` erişim logu) çalışırken panel her isteğin **durum kodunu** görür ama
**nedenini** (örn. `Güvensiz dosya yolu`) göremez. Nedenin görünmesi için sunucuda `entegrasyon/istek_gunlugu.py`
(her isteği hata mesajıyla tek JSON satırı olarak loglar) bulunmalı — yeni imaj dağıtılınca otomatik açılır.
Gövde, sorgu parametreleri ve `Authorization` başlığı **asla** loglanmaz; 422 hatalarında girdi değeri yansıtılmaz.

## Güvenlik

- Yalnızca `127.0.0.1`'e bağlanır; sunucuda **yeni port açmaz**, hiçbir şeyi değiştirmez (yalnızca `docker logs`, iş dosyalarını ve gelen-istek arşivini okur).
- Uzak komutlar sabit şablondur; değişkenler yalnızca doğrulanmış değerlerdir: zaman penceresi (tamsayı, 1–1440), arşiv `request_id`'si (12–32 hex, `fullmatch`) ve dosya adı (sabit beyaz liste: `gelen.zip`, `istek.xml`, `cevap.json`, `meta.json`, toplu işin `sonuclar.jsonl`'ı). Geçersiz değer `400` alır ve uzak komut hiç çalışmaz.
- Sunucudan gelen her metin (hata mesajı, şirket adı) arayüzde `textContent` ile basılır; katı CSP uygulanır.
- Test: `python -m pytest izleme/tests -q`.
