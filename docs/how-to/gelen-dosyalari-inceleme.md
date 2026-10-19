# Gelen dosyaları inceleme (izleme paneli)

Dış ekip "şu zip'i/faturayı gönderdik" dediğinde **elimizdeki dosyayı** indirip inceleyebilmek ve **bizim ne cevap verdiğimizi** görebilmek için.
Mac'teki izleme paneli, sunucudaki gelen-istek arşivini SSH ile okur.

> ✅ **Uygulandı** (2026-10-19): arşiv `entegrasyon/istek_arsivi.py`, panel `izleme/panel.py` + `izleme/arsiv.py` + `izleme/static/panel.js`.
> Henüz sunucuya dağıtılmadı: dağıtımdan önce panelde "Gelen dosyalar" boş görünür (eski sürümde arşiv yazılmıyor).

## Kullanım

```bash
python3 izleme/panel.py            # sunucuyu izler  →  http://127.0.0.1:8300
```

1. **Gelen dosyalar** sekmesi → son gelen istekler (zip ve tek fatura), yeniden eskiye. Satırdaki düğmelerle `gelen.zip` / `istek.xml` / `cevap.json` doğrudan indirilir.
2. Bir satıra tıklayınca **istek detayı** açılır:
   - **İstek:** zaman, tür, durum, hata nedeni, istemci (API anahtarı etiketi), IP, VKN(ler), iş kimliği, `request_id`
   - **Zip'in içindekiler:** dosya adları ve boyutları (örn. `6677889900/mizan.xlsx` var mı? kaç fatura geldi?)
   - **Bizim verdiğimiz cevap:** zip uçlarında 202 gövdesi ya da hata; tek faturada tam cevap (`records[]` dahil)
   - **Bu isteğin başlattığı iş:** onboarding iş kartı (şirket bazında durum) ya da toplu fatura ilerlemesi + **fatura başına verdiğimiz sonuçlar**
     (`sonuclar.jsonl` indirilebilir — büyük işlerde önizleme kısmidir)
   - **Bize gelen fatura XML'i** (tek faturada önizleme) ve **o isteğe ait loglar** (hata mesajı, stack trace)

Örnek: "mizanım eksik" şikâyeti → `/musteri/onboard` satırı → `gelen.zip`'i indir → `mizan.xlsx`'i aç, dosyanın kendisi mi eksikti yoksa okuyucu mu hesapları attı karşılaştır.

## Karar izi — bir fatura nasıl işlendi, kim karar verdi, neden

Tek fatura isteklerinde (`/fatura/isle`) istek detayında **"Karar izi"** bölümü görünür. İki parça:

1. **Nihai hesap kayıtları — kim karar verdi, neden:** her kayıt için hesap, ad, yön, tutar, **ana kodu kim seçti** (model, emsaller ve ipuçlarıyla), **alt kırılımı kim seçti** (kural: cari ad eşleştirme /
   kalem adı eşleştirme, ya da model; çözülemediyse "insan kontrolü") ve gerekçe.
2. **Adım adım zaman çizelgesi** (rozetler: Kural / Model (LLM) / Emsal (RAG) / Doğrulama / Sistem): istek alındı → şirket kaydı → yön tespiti (neden outbox/inbox) → KDV/NACE ön filtresi (veya neden atlandı) →
   fatura ayrıştırma → emsal arama (bulunan geçmiş faturalar, few-shot bloğu) → deterministik ipuçları (tevkifat/iade/ihraç) → **ana model** (modele giden **sistem ve kullanıcı istemi (prompt)**, modelin ham cevabı,
   süre) → öz düzeltme (tetiklendiyse neden) → her cari/gider/KDV kodu için alt kırılım kararı (cari: ünvan ↔ en benzer 5 kart, **her adayın neden kabul/ret edildiği**; gider/gelir: kalem adı eşleşmesi; KDV: model + oran
   düzeltmesi; modelin her seçiminin mizana karşı doğrulaması) → deterministik doğrulama (hangi kural başarısız → neden onaylanamaz) → sonuç. Uzun metinler (istemler, ham cevaplar) açılır bölümlerdedir.

Neden/kim sorusunun örnekleri: *"120 neden çözülmedi?"* → cari adım: aday kartlar ve her birinin ret nedeni ("faturadaki KARAGOZ kartta yok…", "hukuki form farklı…"); *"391 hangi orana göre seçildi?"* → alt kırılım modeli adımı:
modelin seçimi + "KDV oranı faturadaki orana göre düzeltildi"; *"model neden 320 dedi?"* → ana model adımı: istem + ham cevap + bulunan emsaller.

**Sınırlar:** yalnızca tek fatura (`/fatura/isle`); toplu fatura (zip) ve onboarding işleri için karar izi henüz yok; dağıtımdan önce işlenen isteklerde `iz.json` yoktur. İz, **dış API cevabında YOKTUR** (istemler iç bilgidir),
yalnızca bu arşivde durur ve aynı süre (`GELEN_ARSIV_GUN`) sonra silinir. İstemler fatura içeriğini (karşı taraf adı, kalemler) içerir — arşivdeki XML ile aynı gizlilik düzeyi. İz toplanması sonucu değiştirmez,
hatası işlemi bozmaz; arşiv kapalıysa (`GELEN_ARSIV_GUN=0`) toplanmaz. Ham dosya: `iz.json` indirme düğmesi.

## Ne kadar süre saklanır?

| Ayar (env, sunucu) | Varsayılan | Anlamı |
|---|---|---|
| `GELEN_ARSIV_GUN` | `7` | Bu günden eski kayıtlar silinir. `0` = arşiv tamamen kapalı |
| `GELEN_ARSIV_MAX_MB` | `2048` | Toplam boyut aşılınca en eski kayıtlar silinir |

Temizlik, yeni bir istek arşivlendikçe en çok 5 dakikada bir çalışır. Arşiv `efatura-onboarding` volume'ünde (`ONBOARD_DATA_DIR/arsiv/<request_id>/`) durur.
Süre değiştirmek için `docker/docker-compose.yml`'de `app` servisine ilgili env'i ekleyip `docker compose up -d app` (imaj yeniden derlenmez).

## Neyin arşivlendiği (ve neyin arşivlenmediği)

- **Arşivlenir:** kimliği doğrulanmış **ve** ilgili VKN'ye yetkili istekler: `/musteri/onboard`, `/fatura/toplu-isle` (zip, geçersiz/reddedilen zip'ler dahil —
  hata ayıklamak için) ve `/fatura/isle` (XML + cevap; 400/404/500 de nedeniyle).
- **Arşivlenmez:** anahtarsız/geçersiz anahtarlı (401) ve yetkisiz VKN (403, tek fatura) istekler — anonim biri diske yazdıramaz. Arşivleme hatası isteği bozmaz (yalnızca uyarı loglanır).
- Aynı `request_id` (istemci `X-Request-ID` ile verebilir) ikinci kez gelirse mevcut kaydın **üzerine yazılmaz**.

## Gizlilik ve dış ekibe verilen söz

Arşiv müşteri verisi (fatura içeriği, karşı taraf adları, mizan) içerir. API'den **erişilemez**; yalnızca SSH erişimi olan operatör paneli okur.
Dış ekibe verilen belgelerdeki "ham dosyalar iş bitince silinir" ifadesi bu arşivle **birebir doğru değildir** (kopya `GELEN_ARSIV_GUN` gün kalır):
sunucuya dağıtmadan önce dış ekip belgeleri güncellenmeli ve ekibe bildirilmelidir.

## Panel güvenliği

Tarayıcıdan gelen tek iki değer uzak komuta ulaşır — `request_id` (12–32 hex, `fullmatch`) ve dosya adı (`gelen.zip`, `istek.xml`, `cevap.json`, `meta.json`,
ya da toplu işin `sonuclar.jsonl`'ı): ikisi de `izleme/arsiv.py`'de katı beyaz listeyle doğrulanır, geçmeyen istek `400` alır ve uzak komut hiç çalışmaz.
`sonuclar.jsonl`'ın yolu istemciden değil, arşiv kaydındaki `is_id`'den (yeniden doğrulanarak) türetilir. Dosyalar belleğe alınmadan akıtılır
(`Content-Disposition: attachment`, `nosniff`, `CSP: sandbox`); panel yalnızca `127.0.0.1`'e bağlanır.
Test: `python3 -m pytest izleme/tests entegrasyon/tests/test_istek_arsivi.py -q`.
