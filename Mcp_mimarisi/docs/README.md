# Dokümantasyon Haritası — Diátaxis

Bu proje dokümanlarını 4 türe ayırır. Her tür **tek bir soru türüne** cevap
verir; bir belge yazarken önce hangi soruya cevap verdiğini belirle, o seni
doğru klasöre götürür.

| Klasör | Soru | Örnek |
|---|---|---|
| 🎓 `tutorials/` | "Bunu ilk kez nasıl öğrenirim?" | "Sıfırdan ortam kurulumu" |
| 🔧 `how-to/` | "Şu görevi nasıl yaparım?" | "Yeni bir X nasıl eklenir", "nasıl deploy edilir" |
| 📖 `reference/` | "X'in tam/kesin şekli ne?" | "API sözleşmesi", "env değişkenleri listesi" |
| 💡 `explanation/` | "Neden böyle karar verildi?" | "Şu mimari karar neden alındı, alternatifler nelerdi" |

## Kurallar

- **Her commit, [`CHANGELOG.md`](CHANGELOG.md)'ye tek satır ekler.** Ne
  değişti + neden (bir cümle).
- Bir belge kodla çelişiyorsa (bayat env var adı, kaldırılmış bir tool,
  yanlış model önerisi) fark edildiği anda düzelt — ayrı onay bekleme.
- Kritik bir değişiklik (davranış, güvenlik sınırı, env var, mimari akış)
  yapıldığında ilgili belge **aynı görevde** güncellenir, ayrı bir adım
  değildir. Güncellenen bölüme tarih damgası ekle:
  `> ✅ Uygulandı (TARİH): ...` — böylece bir okuyucu belgenin kodla senkron
  olduğunu görür.
- `designs/` (varsa) tarihsel tasarım notlarıdır — **kodun doğruluk kaynağı
  değildir**, sadece "o zaman neden böyle düşünülmüş" arşivi.
