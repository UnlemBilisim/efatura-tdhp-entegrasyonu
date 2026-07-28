# Sistemi Test Etme

> **Tür:** how-to — görev odaklı tarif.
> Kurulum/başlatma adımları için: [`../../PROJE_CALISTIRMA.md`](../../PROJE_CALISTIRMA.md).
> Bu belge "çalıştığını nasıl doğrularım" sorusuna cevap verir.

## Önce: dört bağımlılık ayakta mı?

Biri eksikse hata mesajı **yanıltıcı olabilir** — özellikle SSH tüneli.

```bash
# Servisler
curl -s http://localhost:8000/saglik   # {"durum":"ayakta","nace_tablosu_yuklu":true}
curl -s http://localhost:8100/durum    # {"model_eval_hazir":true,...}

# SSH tüneli (LLM erişimi) — AÇIK olmalı
lsof -i :11435 | grep LISTEN

# PostgreSQL
docker ps --filter name=efatura-kdv-postgres --format '{{.Status}}'
```

> ⚠️ **En sık tuzak:** SSH tüneli kapalıysa `predict_single_invoice` **hata
> fırlatmaz** — `error` alanı dolu, `entries` boş döner. `records: []` görünce
> "kodum bozuldu" sanmak yerine önce tüneli kontrol edin. (Bu, 2026-07-27'de
> bir kez yanlış teşhise yol açtı.)

Tünel komutu [`../../çalıştırma.txt`](../../çalıştırma.txt) içinde; parola
istediği için elle açılmalı.

## 1. Birim testleri

```bash
cd model_eval && python3 -m pytest tests/ -q
```

Beklenen: **205 passed**.

| Durum | Anlamı |
|---|---|
| `183 passed, 22 skipped` | PostgreSQL kapalı — **hata değil**, `requires_postgres` marker'ı atlıyor |
| `No module named pytest` | Yanlış venv aktif; `/usr/bin/python3 -m pytest` ile sistem python'unu kullanın |

Prod veritabanına (`DATABASE_URL`) test verisi yazmayın; testler
`TEST_DATABASE_URL` kullanır.

## 2. Arayüzden manuel test (en pratik yol)

Terminalde logu izlemeye başlayın:

```bash
tail -f .calistirma/entegrasyon.log | grep -A 45 "DIŞ EKİP JSON"
```

Tarayıcıdan http://localhost:8100 açıp fatura yükleyin. Dış ekibe gidecek JSON
terminalde akar (~10-30 sn sonra).

## 3. HTTP ile uçtan uca test

```bash
# İstek gövdesini kur (ubls/ içinden örnek bir fatura ile)
python3 - <<'EOF'
import json, glob
f = sorted(glob.glob("Mcp_mimarisi/ubls/*outbox.xml"))[0]
json.dump({"fatura_xml": open(f, encoding="utf-8").read(),
           "satici_vkn": "0460351893", "onay": True},
          open("/tmp/istek.json", "w"))
print("fatura:", f)
EOF

# Gönder (LLM çağrısı uzun sürer, timeout cömert olmalı)
curl -s --max-time 600 -X POST http://localhost:8100/fatura/isle \
  -H "Content-Type: application/json" -d @/tmp/istek.json \
| python3 -c 'import json,sys; d=json.load(sys.stdin); \
print(json.dumps(d["tdhp_tahmini"]["dis_sema"], ensure_ascii=False, indent=2))'
```

### Neye bakılmalı

| Kontrol | Beklenen |
|---|---|
| `asama` | `tdhp_tahmini_tamamlandi` |
| `success` | `true` |
| Denge | `borc_toplam == alacak_toplam` |
| `records[]` | Boş olmamalı; her kayıtta 6 alan dolu |
| `account_code` | Nokta içermeli (`120.01.00295`) — noktasızsa alt kırılım çözülememiş |

**`onay: true` göndermezseniz** outbox faturalarda akış ön filtrede durur ve
`dis_sema` gelmez (`asama: on_filtre_insan_incelemesi_bekliyor`). Bu doğru
davranıştır — bkz. [`../../../MIMARI.md`](../../../MIMARI.md) §3.2.

## 4. Sadece TDHP tahminini test etme (Docker'sız)

PostgreSQL kapalıysa ön filtreleme çalışmaz, ama TDHP tahmini **çalışır** —
onun DB'ye ihtiyacı yok. Servisleri atlayıp doğrudan köprüyü çağırın:

```bash
cd entegrasyon && python3 -c "
import sys, json, glob; sys.path.insert(0, '.')
from model_eval_koprusu import tdhp_tahmini_yap
f = sorted(glob.glob('../Mcp_mimarisi/ubls/*outbox.xml'))[0]
s = tdhp_tahmini_yap(open(f, encoding='utf-8').read(), own_vkn='0460351893')
print(json.dumps(s.get('dis_sema'), ensure_ascii=False, indent=2))
"
```

## 5. Bir değişikliği "tamamlandı" saymadan önce

Kök `CLAUDE.MD` §3 gereği: kodu okuyup "böyle çalışması lazım" demek yeterli
değildir.

- [ ] `pytest` geçiyor (205)
- [ ] Gerçek bir faturayla `POST /fatura/isle` çalıştırıldı
- [ ] Çıktı gözlemlendi (denge, `records[]`, `success`)
- [ ] İlgili `docs/` güncellendi + `> ✅ Uygulandı (TARİH)` notu eklendi
