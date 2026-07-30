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
| `how-to/` | Görev odaklı tarifler | [Sistemi test etme](how-to/sistemi-test-etme.md), [Docker ile çalıştırma](how-to/docker-ile-calistirma.md), [SSH tünel kurulumu](how-to/ssh-tunel-kurulumu.md) |
| `reference/` | Kesin teknik başvuru | [Servis ve port envanteri](reference/servisler-ve-portlar.md), [Sistem mimarisi rehberi (dosya dosya)](reference/sistem-mimarisi-rehberi.md) |
| `explanation/` | Bir kararın NEDEN öyle verildiği | [Güvenlik durumu](explanation/guvenlik-durumu-2026-07-27.md) |

## Klasör dışındaki üst düzey belgeler

Bunlar tarihsel olarak `System/` üstünde/kökünde duruyor, buraya taşınmadı:

| Belge | Tür | İçerik |
|---|---|---|
| [`../PROJE-HARITASI.md`](../PROJE-HARITASI.md) | — | **Projeye ilk bakan biri için giriş noktası** — ne yapar, dosya haritası, nereden başlanır |
| [`../mimari.md`](../mimari.md) | explanation | Sistem mimarisi — bileşenler, akış, kararların gerekçesi |
| [`../proje-calistirma.md`](../proje-calistirma.md) | how-to | Çalıştırma kılavuzu, sık sorunlar |
| [`../CLAUDE.md`](../CLAUDE.md) | — | AI ajanları için rehber (Diátaxis dışı) |

> ℹ️ `mimari.md` zaten kapsamlı bir explanation belgesidir; buradaki
> `explanation/` onu tekrar etmez, yalnızca ona sığmayan (tarihli, denetim
> niteliğinde) içeriği tutar.
>
> ✅ **Düzeltildi** (2026-07-28): `OKU-YAPI.md` referansı kaldırıldı — bu
> dosya `System/` temizliği sırasında silindi (bayat kök düzeyi planlama
> notuydu, kod/ürün belgesi değildi). `mimari.md` yolu da düzeltildi
> (`System/mimari.md`'dir, `../../` değil `../` ile erişilir).
