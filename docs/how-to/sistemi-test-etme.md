# Sistemi Test Etme

> **Tür:** how-to — görev odaklı tarif.
> Kurulum/başlatma adımları için: [`../../proje-calistirma.md`](../../proje-calistirma.md).
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

Her bileşen kendi `sys.path` düzenini kurduğu için üç paket **ayrı ayrı**
çalıştırılır (proje kökünden):

```bash
python3 -m pytest Mcp_mimarisi/test -q          # 28 passed, 1 skipped
python3 -m pytest entegrasyon/tests -q          # 4 passed, 2 skipped
(cd model_eval && python3 -m pytest tests -q)   # 226 passed (PostgreSQL varsa)
```

| Durum | Anlamı |
|---|---|
| Mcp_mimarisi `1 skipped` | `test/test_kalem_nace.py` gerçek DB + fatura dosyası isteyen manuel bir script'tir, pytest altında bilerek atlanır (`python3 test/test_kalem_nace.py` ile elle çalıştırılır) |
| entegrasyon `2 skipped` | Auth 3 endpoint'te geçici olarak kapalı olduğu için iki auth testi bilerek skip'li (bkz. kök `CLAUDE.md` 🔴 notu) |
| model_eval `200 passed, 26 skipped` | PostgreSQL'e (`TEST_DATABASE_URL`) bağlanılamıyor — **hata değil**, `requires_postgres` marker'ı atlıyor |
| `No module named pytest` | Yanlış venv aktif; `/usr/bin/python3 -m pytest` ile sistem python'unu kullanın |

Prod veritabanına (`DATABASE_URL`) test verisi yazmayın; testler
`TEST_DATABASE_URL` kullanır (varsayılan:
`postgresql://efatura:efatura@localhost:5434/model_eval_test`).

> ✅ **Uygulandı** (2026-09-28): **CI eklendi** —
> [`.github/workflows/testler.yml`](../../.github/workflows/testler.yml)
> `main`'e her push'ta ve her PR'da üç paketi Python 3.11'de (Docker
> image'ıyla aynı sürüm) gerçek bir PostgreSQL servisiyle çalıştırır;
> böylece yerelde atlanan `requires_postgres` testleri de koşar. Ayrıca
> `log_ortak.py` ve `es_zamanli_sinir.py`'nin iki kopyasının birebir aynı
> olduğunu `diff` ile denetler (önceden bu kural sadece belgedeydi).
> Mcp_mimarisi'ye DB'siz çalışan gerçek pytest'ler eklendi:
> `test/test_kalem_nace_unit.py` (karar mantığı — havuz, istisna kodu,
> genel oran fallback'i, VKN uyuşmazlığı) ve `test/test_api.py` (HTTP
> katmanı — dahili token 401/503, DTD reddi, boyut sınırı, request-id).
> Adımların tamamı yerelde geçici bir `python:3.11-slim` container'ında
> birebir çalıştırılarak doğrulandı.

## 2. Arayüzden manuel test (en pratik yol)

Terminalde logu izlemeye başlayın:

```bash
cd docker/ && docker compose logs -f app | grep -A 45 "DIŞ EKİP JSON"
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
davranıştır — bkz. [`../../../mimari.md`](../../../mimari.md) §3.2.

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

- [ ] Üç test paketi geçiyor (§1) — push sonrası CI da yeşil
- [ ] Gerçek bir faturayla `POST /fatura/isle` çalıştırıldı
- [ ] Çıktı gözlemlendi (denge, `records[]`, `success`)
- [ ] İlgili `docs/` güncellendi + `> ✅ Uygulandı (TARİH)` notu eklendi
