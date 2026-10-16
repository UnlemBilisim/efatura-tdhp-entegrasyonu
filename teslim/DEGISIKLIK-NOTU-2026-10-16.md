# Güncelleme — 2026-10-16

Bir önceki pakete (2026-10-06) göre **ne yeni**. Bu not yalnızca farkı özetler; ayrıntı ilgili belgelerdedir.
**Mevcut `/fatura/isle` entegrasyonunuzu bozan bir değişiklik yoktur.** (Zip ile şirket yükleme akışında kayıtlı VKN davranışı değişti, bkz. §2.)

## Yeni belge

| Dosya | Durum |
|---|---|
| `FATURA-ISLEME-KILAVUZU.md` | **YENİ** — fatura işlemenin baştan sona anlatımı: tek fatura, paralel istekler ve toplu (zip) gönderim |
| `API-KAYIT-SEMASI-REFERANS.md` | **Güncellendi** — yeni §10 (toplu fatura işleme), §9'da kayıtlı şirket güncelleme kuralları |
| `MUSTERI-ONBOARD-ZIP-KILAVUZU.md` | **Güncellendi** — `guncellendi` / `degismedi` durumları, kısmi güncelleme |
| `ONBOARDING-VERI-FORMATI.md` | **Güncellendi** — §0: yeni şirket ve kayıtlı şirket güncelleme farkı |

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

## 2. DEĞİŞİKLİK: Kayıtlı şirket artık zip ile GÜNCELLENEBİLİR

Önceki paketteki davranış değişti: zip'te **zaten kayıtlı bir VKN** geldiğinde artık `atlandi` olmaz (anahtarınız o şirket adına yetkiliyse).
Gelen veri sistemdeki mevcut veriyle **karşılaştırılır**:

- **Aynıysa hiçbir şey yazılmaz** → şirket sonucu `degismedi`.
- **Fark varsa yalnızca değişen kısım güncellenir** → `guncellendi` (`ozet` neyin değiştiğini söyler); eski değer ve güncellenme zamanı sistemde kayıt altında tutulur.
- Anahtarınız o şirket adına yetkili değilse `atlandi` (başka müşavirin verisi korunur).
- **Zip'te yalnızca değişen dosyaları gönderebilirsiniz** (örn. sadece yeni `mizan.xlsx` ya da sadece `nace.txt`); `faturalar/*.xml` ile `yevmiye` birlikte gelmeli.
- **Mizan tam hesap planı sayılır:** dosyada artık olmayan hesap silinir (eski değeri kayıtta kalır). Dosya boşsa ya da mevcut hesapların yarısından fazlası
  silinecekse eksik dosya şüphesiyle mizan **değiştirilmez** ve cevapta `uyari` döner. Emsaller (faturalar + yevmiye) yalnızca eklenir/güncellenir, **silinmez**.

Ayrıntı: `MUSTERI-ONBOARD-ZIP-KILAVUZU.md` (§4, §5) ve `ONBOARDING-VERI-FORMATI.md` §0. Yeni şirket kurma davranışı değişmedi.

## 3. Paralel tek istekler hakkında açıklama

`POST /fatura/isle` aynı anda birden fazla kez çağrılabilir (bu daha önce de böyleydi, belgelenmemişti): sunucu aynı anda **en fazla 2** faturayı işler,
fazlası **sırada bekler** (reddedilmez, `429` yoktur). Bu yüzden zaman aşımınızı en az **600 saniye** tutun; aynı anda 4–5'ten fazla paralel istek
göndermeniz hızı artırmaz. Çok sayıda fatura için toplu yolu kullanın.

## Geriye dönük uyumluluk

Mevcut uç noktaların istek/cevap biçimleri **aynı**. Yeni uç noktaları kullanmazsanız hiçbir şey değişmez; anahtarlarınız aynen çalışır
(toplu işleme için ayrı bir yetki gerekmez, normal anahtarınız yeterlidir).
