# model_eval/ Dokümantasyonu

Bu klasör, `model_eval/`'a **özgü** belgeleri tutar (üç bileşenin birlikte
çalışmasına ait belgeler [`../../docs/`](../../docs/)'da).

## Diátaxis yapısı

| Klasör | Ne için | Buradaki içerik |
|---|---|---|
| `tutorials/` | Öğrenme odaklı, adım adım | *(henüz yok)* |
| `how-to/` | Görev odaklı tarifler | [Vektör veritabanı kurma ve RAG ile değerlendirme](how-to/build_and_use_vector_db.md) |
| `reference/` | Kesin teknik başvuru | [RAG vektör veritabanı — teknik referans](reference/vector_db.md) |
| `explanation/` | Bir kararın NEDEN öyle verildiği | [RAG/vektör veritabanı ile fatura kodlama gerekçesi](explanation/rag_retrieval.md), [Prompt'ta para birimi sabitleme](explanation/prompt_currency_fix.md), [Çok kullanıcılı MVP mimari denetimi (2026-07-22)](explanation/mimari-denetim-2026-07-22.md) |

## Klasör dışındaki üst düzey belgeler

| Belge | Tür | İçerik |
|---|---|---|
| [`../CLAUDE.md`](../CLAUDE.md) | — | AI ajanları için rehber |
| [`../project.md`](../project.md) | — | Mimari kararlar, deney sonuçları, faz durumu |
| `RESULTS.md`, `RAG_MODEL_COMPARISON.md` | — | Deney bulguları (Diátaxis dışı, `CLAUDE.md`/`project.md` içinde referans verilir) — ⚠️ bu dosyalar şu an repoda bulunamıyor, referans tarihsel |

Dış ekibe teslim edilen `records[]` API sözleşmesi burada değil —
[`../../entegrasyon/docs/reference/dis-ekip-api-kullanimi.md`](../../entegrasyon/docs/reference/dis-ekip-api-kullanimi.md)'de
(2026-08-05'te birleştirildi).
