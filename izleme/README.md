# İzleme Paneli

Mac'te çalışan, **salt okunur** bir web paneli: sunucuya SSH ile bağlanıp gelen istekleri, hata mesajlarını ve
onboarding (zip ile şirket kurma) işlerinin ilerlemesini gösterir.

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
| **Onboarding işleri** | Her iş için yüzde çubuğu; şirket bazında durum (`kuruldu`/`atlandi`/`hata`), adım ve hata nedeni |
| **Hata logları** | Uyarı/hata satırları (yetki reddi, beklenmeyen hata, Python hata izi) |
| **Ham log** | Son satırlar, filtresiz |

Üstte zaman penceresi, "yalnızca hatalar", "sağlık kontrollerini göster" ve otomatik yenileme (5 sn) var.

## Hata MESAJLARI için sunucuda ne gerekir?

Sunucu eski sürümde (yalnız `uvicorn` erişim logu) çalışırken panel her isteğin **durum kodunu** görür ama
**nedenini** (örn. `Güvensiz dosya yolu`) göremez. Nedenin görünmesi için sunucuda `entegrasyon/istek_gunlugu.py`
(her isteği hata mesajıyla tek JSON satırı olarak loglar) bulunmalı — yeni imaj dağıtılınca otomatik açılır.
Gövde, sorgu parametreleri ve `Authorization` başlığı **asla** loglanmaz; 422 hatalarında girdi değeri yansıtılmaz.

## Güvenlik

- Yalnızca `127.0.0.1`'e bağlanır; sunucuda **yeni port açmaz**, hiçbir şeyi değiştirmez (yalnızca `docker logs` ve iş dosyalarını okur).
- Uzak komutlar sabit şablondur; tek değişken (zaman penceresi) tamsayıya çevrilip 1–1440 ile sınırlanır.
- Sunucudan gelen her metin (hata mesajı, şirket adı) arayüzde `textContent` ile basılır; katı CSP uygulanır.
- Test: `python -m pytest izleme/tests -q`.
