# İstisna Kodları (GİB) Excel Referans Dosyası — Şema

`Istisna_Kodlari_GIB.xlsx`, GİB'in resmi **"e-Belge Uygulamaları - UBL-TR
(Kod Listeleri) Kılavuzu"** (Versiyon 1.42, 16.03.2026, ebelge.gib.gov.tr)
kaynağından alınmış, faturadaki `TaxExemptionReasonCode` alanında görülebilen
tüm istisna/özel-durum kodlarının tam listesidir. Kullanıcı tarafından
2026-07-20'de repoya eklendi.

## Sayfalar

| Sayfa | Kod aralığı | İçerik |
|---|---|---|
| `Özet` | — | Sayfa/kod aralığı/açıklama özeti |
| `Kısmi İstisna` | 201-250 | KDV Kanunu 17. madde kapsamındaki kısmi istisnalar (42 kod) |
| `Tam İstisna` | 301-351 | KDV Kanunu 11-13-14-15 vd. maddeler kapsamındaki tam istisnalar (46 kod) |
| `Diğer İşlem Türü` | 555 | KDV oran kontrolüne tabi olmayan satışlar |
| `ÖTV İstisna` | 101-151 | 4760 sayılı ÖTV Kanunu kapsamındaki istisnalar |
| `Konaklama Vergisi İstisna` | 001 | Konaklama vergisi diplomatik istisnası |
| `Özel Matrah` | 801-812 | Özel matrah şekline tabi teslim/hizmetler |
| `İhraç Kayıtlı Satışlar` | 701-704 | İhraç kayıtlı satışlar + DİİB + geçici kabul rejimi |

Her sayfada sütunlar: `Kodu, Açıklama`. Bazı kodlar `*` işaretli (ör.
`351*`, `151**`) — bu, kodun "gerçek bir istisna maddesi değil, özel kodu
olmayan durumlar için kullanılan genel kod" olduğunu belirtiyor.

## Gerçek istisna olmayan "dolgu" kodlar

Bazı kodlar mevzuat maddesine dayanmaz, sadece "0 oranlı fatura kesilmesi
gerekiyor ama özel bir istisna kodu yok" durumları için kullanılır:

- **`151`** — "ÖTV - İstisna Olmayan Diğer"
- **`250`** — "Diğerleri" (Kısmi İstisna)
- **`350`** — "Diğerleri" (Tam İstisna)
- **`351`** — "KDV - İstisna Olmayan Diğer"

Bu 4 kod, açıklama metninde "İstisna Olmayan" veya "Diğerleri" ifadesi
geçtiği için programatik olarak tespit edildi (bkz. aşağıdaki uygulama
notu) ve kod tarafında BİLİNÇLİ olarak istisna sayılmadı.

## Kodda kullanımı

> ✅ **Uygulandı (2026-07-20):** `src/efatura_kdv/kalem_nace_esleme.py`'deki
> `GENEL_ISTISNA_KODLARI` sabiti, bu dosyanın 7 kategorisinin TAMAMINDAN
> (yukarıdaki 4 dolgu kod HARİÇ) toplam **107 kod** içerecek şekilde
> güncellendi. Önceki sürüm sadece 4 kod (`301`, `302`, `311`, `701`)
> içeriyordu — web araştırmasıyla teyit edilmiş ama eksik bir alt kümeydi.
> Bu dosya sayesinde artık örneğin `235` (transit/gümrük antrepo, Kısmi
> İstisna) veya `801`-`812` (Özel Matrah, ör. ikinci el motorlu taşıt/
> taşınmaz) gibi kodlar da tespit edildiğinde `uygun` kararı veriliyor —
> önceden bunlar yanlışlıkla `insan_incelemesi_gerekli`ye düşüyordu.
>
> Liste, `openpyxl` ile dosya programatik olarak okunup (metinde "İstisna
> Olmayan" veya salt "Diğerleri" geçen 4 kod hariç tutularak) doğrulandı,
> ardından statik bir Python `set` olarak koda gömüldü (bu referans verisi
> NACE-oran tablosu gibi sık değişmiyor, dosyayı her çalıştırmada okumaya
> gerek yok). Gerçek fatura senaryolarıyla (`301` ihracat → uygun, `351`
> dolgu kod → hâlâ insan incelemesi gerekli, sentetik `701` ve `235` → uygun)
> test edildi.
>
> `_genel_istisna_dogrulamasi()` bu kodlardan biri tespit edilirse `uygun`
> döner; `_fatura_istisna_notu()` ise listede OLMAYAN (dolgu kodlar dahil)
> istisna kodlarında sadece bilgi notu ekler, karar değişmez.
