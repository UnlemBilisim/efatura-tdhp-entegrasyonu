# System/ Dokümantasyonu

Bu klasör, **üç bileşenin birlikte çalışmasına** ait belgeleri tutar. Tek bir
bileşenin içine ait belgeler o bileşenin kendi `docs/` klasöründedir:

- [`../Mcp_mimarisi/docs/`](../Mcp_mimarisi/docs/) — KDV/NACE ön filtreleme
- [`../model_eval/docs/`](../model_eval/docs/) — TDHP tahmini + RAG
- [`../entegrasyon/docs/`](../entegrasyon/docs/) — orkestrasyon + dış API

## Diátaxis yapısı

| Klasör | Ne için | Buradaki içerik |
|---|---|---|
| `tutorials/` | Öğrenme odaklı, adım adım | *(henüz yok)* |
| `how-to/` | Görev odaklı tarifler | [Sistemi test etme](how-to/sistemi-test-etme.md) |
| `reference/` | Kesin teknik başvuru | [Servis ve port envanteri](reference/servisler-ve-portlar.md) |
| `explanation/` | Bir kararın NEDEN öyle verildiği | [Güvenlik durumu](explanation/guvenlik-durumu-2026-07-27.md) |

## Klasör dışındaki üst düzey belgeler

Bunlar tarihsel olarak `System/` üstünde/kökünde duruyor, buraya taşınmadı:

| Belge | Tür | İçerik |
|---|---|---|
| [`../../MIMARI.md`](../../MIMARI.md) | explanation | Sistem mimarisi — bileşenler, akış, kararların gerekçesi |
| [`../PROJE_CALISTIRMA.md`](../PROJE_CALISTIRMA.md) | how-to | Çalıştırma kılavuzu, sık sorunlar |
| [`../CLAUDE.md`](../CLAUDE.md) | — | AI ajanları için rehber (Diátaxis dışı) |
| [`../../OKU-YAPI.md`](../../OKU-YAPI.md) | reference | Klasör yapısı haritası |

> ℹ️ `MIMARI.md` zaten kapsamlı bir explanation belgesidir; buradaki
> `explanation/` onu tekrar etmez, yalnızca ona sığmayan (tarihli, denetim
> niteliğinde) içeriği tutar.
