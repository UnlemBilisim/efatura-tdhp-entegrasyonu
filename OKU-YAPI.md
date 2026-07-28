# Proje Klasör Yapısı (2026-07-27 düzenlemesi)

Kök dizin sadeleştirildi. Çalışan sistem `System/` altına, gereksiz dosyalar
`arsiv/` altına taşındı.

## System/ — ÇALIŞAN SİSTEM (e-fatura KDV doğrulama + TDHP tahmini)

```
System/
├── Mcp_mimarisi/     KDV/mevzuat ön filtreleme API (port 8000)
├── model_eval/       TDHP hesap kodu tahmini + RAG (import ile çağrılır)
├── entegrasyon/      orkestrasyon servisi + web arayüzü (port 8100)
├── Archive2/         model_eval RAG kaynağı (jsons/ = ground-truth faturalar)
├── .calistirma/      loglar, pid'ler, izole venv (baslat.sh yönetir)
├── baslat.sh         tüm sistemi başlatır
├── durdur.sh         servisleri durdurur
└── PROJE_CALISTIRMA.md  çalıştırma kılavuzu
```

**entegrasyon/ ve model_eval/ aynı üst dizinde (System/) KARDEŞ kalmalı** —
`entegrasyon/model_eval_yolu.py` bunu varsayar. Ayırmayın.

## Başlatma

Kök dizinden (eski alışkanlık korundu — ince sarmalayıcılar System/'e yönlendirir):

```bash
./baslat.sh      # -> System/baslat.sh
./durdur.sh      # -> System/durdur.sh
```

ya da doğrudan:

```bash
cd System && ./baslat.sh
```

> **İlk başlatmada** `baslat.sh` venv'leri (`.calistirma/mcp_venv`,
> `entegrasyon/.venv`) yeniden kurar — 2026-07-27 taşımasında eski venv'ler
> mutlak yol içerdiği için silindi. Bu birkaç dakika + internet ister,
> sonraki başlatmalar hızlıdır. `model_eval/.venv` de silindiği için
> geliştirme/test yaparken onu elle yeniden kurun (bkz. PROJE_CALISTIRMA.md).

## Kökte kalanlar (System dışı)

- `preprocessing/` — KDV sistemiyle ilgisiz ayrı alt-proje.
- `docs/`, `CLAUDE.MD`, `PROJECT.md`, `sunucu-yönlendirme.md` — aktif dokümanlar.
- `arsiv/` — çalışan sistemin kullanmadığı eski/gereksiz dosyalar (bkz.
  `arsiv/README.md`).

> ✅ **Uygulandı** (2026-07-27): Kullanılmayan dosyalar temizlendi (~1.4 GB).
> Silinenler: `Archive2/ubls/` (`Mcp_mimarisi/ubls/` ile birebir kopyaydı),
> `Mcp_mimarisi/Archive/`, kök `Archive/`, `Mcp_mimarisi/yargi-mcp/` (yalnızca
> incelenmişti, koda entegre değildi), `model_eval/.venv`, excel yedekleri,
> `Archive2/mizan_1..5.xlsx` + `real_description_2..4.csv` (hiçbir kodda
> referanslı değil), cache/`.DS_Store` artıkları. `arsiv/eski-dokuman/`'a
> taşınanlar: `Mcp_mimarisi/PROJE_ÇALIŞTIRMA.{md,txt}` (bayat yollar içeriyordu;
> güncel kılavuz `System/PROJE_CALISTIRMA.md`), kök `çalıştırma.txt`.
> `arsiv/tamamlanmis-gorevler/`'e: `DEVIR_PROMPT.md`, `GOREV_MIMARI_DUZELTME.md`.
> Temizlik sonrası sistem uçtan uca doğrulandı: gerçek bir UBL faturası
> `POST /fatura/isle` ile işlendi → ön filtreleme (`nace_kural_kontrolu.py`,
> PostgreSQL) + TDHP tahmini (`core/single.py` + RAG + `exceller/mizan.xlsx`)
> çalıştı, kayıt dengeli döndü.
