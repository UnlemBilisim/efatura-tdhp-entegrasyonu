# Güncelleme — 2026-10-16

Bir önceki pakete (2026-10-06) göre **ne yeni**. Bu not yalnızca farkı özetler; ayrıntı ilgili belgelerdedir.
**Mevcut entegrasyonunuzu bozan hiçbir değişiklik yoktur.**

## Yeni belge

| Dosya | Durum |
|---|---|
| `FATURA-ISLEME-KILAVUZU.md` | **YENİ** — fatura işlemenin baştan sona anlatımı: tek fatura, paralel istekler ve toplu (zip) gönderim |
| `API-KAYIT-SEMASI-REFERANS.md` | **Güncellendi** — yeni §10 (toplu fatura işleme), uç nokta listesi |

## 1. YENİ: Birden fazla faturayı tek zip ile işleme

Artık yüzlerce faturayı tek bir **zip dosyası** olarak gönderebilirsiniz; işlem arka planda yürür, bağlantı açık tutmanız ve zaman aşımı
yönetmeniz gerekmez.

- `POST /fatura/toplu-isle` — gövde: ham zip. Tek şirket için `?satici_vkn=...` verin (zip'teki tüm `.xml` dosyaları o şirketin faturasıdır);
  birden fazla şirket için `satici_vkn` vermeyin, zip'in kökünde `<10 haneli VKN>/` klasörleri olsun.
- `GET /fatura/toplu/{is_id}` — ilerleme (**yüzde**), sonuç sayıları ve fatura bazında kısa durum.
- `GET /fatura/toplu/{is_id}/sonuclar` — fatura bazında **tam sonuç** (`records[]` dahil), sayfalı.
- Seçenekler `onay` ve `kur_secimi` zip'teki tüm faturalara uygulanır; verilmezse ilgili faturalar `onay_bekliyor` / `kur_bekliyor` sonucuyla biter (hata değildir).
- Bozuk bir fatura yalnızca kendi satırını `hata` yapar, diğerleri işlenir. Sınırlar: zip ≤ 200 MB, ≤ 2000 fatura.
- **Onaylama otomatik yapılmaz.** Toplu işte üretilen tahminler `POST /fatura/onayla` için **24 saat** (tek istekte 30 dakika) saklanır.
- Gönderdiğiniz ham XML'ler iş bitince sunucudan silinir; sonuçlar 14 gün saklanır.

## 2. Paralel tek istekler hakkında açıklama

`POST /fatura/isle` aynı anda birden fazla kez çağrılabilir (bu daha önce de böyleydi, belgelenmemişti): sunucu aynı anda **en fazla 2** faturayı işler,
fazlası **sırada bekler** (reddedilmez, `429` yoktur). Bu yüzden zaman aşımınızı en az **600 saniye** tutun; aynı anda 4–5'ten fazla paralel istek
göndermeniz hızı artırmaz. Çok sayıda fatura için toplu yolu kullanın.

## Geriye dönük uyumluluk

Mevcut uç noktaların istek/cevap biçimleri **aynı**. Yeni uç noktaları kullanmazsanız hiçbir şey değişmez; anahtarlarınız aynen çalışır
(toplu işleme için ayrı bir yetki gerekmez, normal anahtarınız yeterlidir).
