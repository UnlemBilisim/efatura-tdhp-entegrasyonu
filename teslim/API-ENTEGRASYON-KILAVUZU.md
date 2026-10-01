# e-Fatura → Muhasebe Kaydı API'si

**Endpoint:**

```
POST http://10.38.20.146:8100/fatura/isle
Content-Type: application/json
Authorization: Bearer <token>
```

> ⚠️ Bu IP yerel ağdaki DHCP adresidir, **kalıcı değildir** — makine yeniden
> başlarsa değişebilir. Erişim sorunu yaşarsanız güncel adresi bize sorun.

## İstek

```json
{
  "fatura_xml": "<?xml version=\"1.0\"?><Invoice>...</Invoice>",
  "satici_vkn": "0460351893",
  "onay": true
}
```

| Alan | Zorunlu | Açıklama |
|---|:---:|---|
| `fatura_xml` | ✅ | UBL-TR fatura XML'inin tamamı, ham metin |
| `satici_vkn` | ✅ | **Kendi şirketinizin VKN'si** (fatura üzerindeki satıcının değil) |
| `satici_nace_kodlari` | ❌ | **Normalde göndermenize gerek yok** — şirketin NACE kodları onboarding sırasında bizim tarafımızda bir kere kaydedilir, sistem otomatik kullanır. Sadece kayıtlı NACE'yi override etmek isterseniz doldurun. |
| `onay` | ❌ | KDV uyarısına rağmen devam et |
| `kur_secimi` | ❌ | `"orijinal"` \| `"tl"` — döviz faturasında |

## Yanıt

İhtiyacınız olan alan: **`tdhp_tahmini.dis_sema`**

```json
{
  "asama": "tdhp_tahmini_tamamlandi",
  "tdhp_tahmini": {
    "dis_sema": {
      "records": [
        { "account_code": "120.01.00189", "debit_credit": "BORÇ",   "amount": 1019823.40, "account_description": "..." },
        { "account_code": "600.01.00005", "debit_credit": "ALACAK", "amount": 849852.83,  "account_description": "..." },
        { "account_code": "391.01.00020", "debit_credit": "ALACAK", "amount": 169970.57,  "account_description": "..." }
      ],
      "success": true
    },
    "balanced": true
  }
}
```

`asama` beş değer alabilir:

| `asama` | Ne yapmalı |
|---|---|
| `tdhp_tahmini_tamamlandi` | ✅ `dis_sema` hazır, kullanın |
| `tdhp_dogrulama_basarisiz` | Tahmin gösterilebilir ama onaylanamaz; `validation_errors` alanını inceleyin |
| `on_filtre_insan_incelemesi_bekliyor` | `onay: true` ekleyip **tekrar gönderin** |
| `kur_onayi_bekliyor` | `kur_secimi: "tl"` veya `"orijinal"` ekleyip **tekrar gönderin** |
| `model_eval_hazir_degil` | Sistem hatası, tekrar denemeyin, bize bildirin |

## cURL örneği

```bash
python3 -c "
import json
json.dump({
  'fatura_xml': open('fatura.xml', encoding='utf-8').read(),
  'satici_vkn': '0460351893',
  'onay': True
}, open('istek.json', 'w'), ensure_ascii=False)"

curl -s --max-time 600 -X POST http://10.38.20.146:8100/fatura/isle \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $API_ANAHTARI" \
  -d @istek.json | jq '.tdhp_tahmini.dis_sema'
```

## Bilinmesi gerekenler

- **Timeout ≥ 600 saniye** — işlem 5-90 saniye sürebilir (yapay zekâ modeli çalışıyor)
- **Sağlık kontrolü:** `GET http://10.38.20.146:8100/durum` → `{"model_eval_hazir": true}`
- **API anahtarı zorunlu** — `efk_` ile başlayan anahtar size ayrı ve güvenli bir kanaldan verilir; yalnızca sunucu tarafınızda saklayın
- Anahtar belirli şirket(ler) adına yetkilidir — yetkisiz `satici_vkn` **`403`**, geçersiz/iptal edilmiş anahtar **`401`** döner
- Onay için `/fatura/isle` cevabındaki `prediction_id`, aynı anahtarla `/fatura/onayla` endpoint'ine gönderilir
- Boş `records[]` görürseniz önce `success` alanına bakın — `false` ise teknik hata var, "kayıt yok" değil
- **`404`** — `satici_vkn` için sistemde kayıtlı şirket yok; önce şirketin onboard edilmesi gerekir. Hazır VKN'ler: `GET /kayitli-sirketler`
- **NACE kodlarını her istekte göndermenize gerek yok** — onboarding sırasında (bkz. `ONBOARDING-VERI-FORMATI.md`) şirketin NACE kodlarını bizim tarafımıza bir kere bildirirsiniz, sistem her istekte otomatik kullanır
- **`413`** — istek gövdesi izin verilen boyutu aşıyor. Sınır **30 MB** — çok büyük/çok kalemli bir fatura XML'i bu sınıra takılırsa bize bildirin
