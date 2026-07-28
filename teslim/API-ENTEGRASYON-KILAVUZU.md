# e-Fatura → Muhasebe Kaydı API'si

**Endpoint:**

```
POST http://10.38.20.146:8100/fatura/isle
Content-Type: application/json
```

> ⚠️ Bu IP yerel ağdaki DHCP adresidir, **kalıcı değildir** — makine yeniden
> başlarsa değişebilir. Erişim sorunu yaşarsanız güncel adresi bize sorun.

## İstek

```json
{
  "fatura_xml": "<?xml version=\"1.0\"?><Invoice>...</Invoice>",
  "satici_vkn": "0460351893",
  "satici_nace_kodlari": ["25.40.04"],
  "onay": true
}
```

| Alan | Zorunlu | Açıklama |
|---|:---:|---|
| `fatura_xml` | ✅ | UBL-TR fatura XML'inin tamamı, ham metin |
| `satici_vkn` | ✅ | **Kendi şirketinizin VKN'si** (fatura üzerindeki satıcının değil) |
| `satici_nace_kodlari` | ❌ | Satıcının NACE kodları — noktalı/noktasız fark etmez |
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

`asama` dört değer alabilir:

| `asama` | Ne yapmalı |
|---|---|
| `tdhp_tahmini_tamamlandi` | ✅ `dis_sema` hazır, kullanın |
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
  'satici_nace_kodlari': ['25.40.04'],
  'onay': True
}, open('istek.json', 'w'), ensure_ascii=False)"

curl -s --max-time 600 -X POST http://10.38.20.146:8100/fatura/isle \
  -H "Content-Type: application/json" \
  -d @istek.json | jq '.tdhp_tahmini.dis_sema'
```

## Bilinmesi gerekenler

- **Timeout ≥ 600 saniye** — işlem 5-90 saniye sürebilir (yapay zekâ modeli çalışıyor)
- **Sağlık kontrolü:** `GET http://10.38.20.146:8100/durum` → `{"model_eval_hazir": true}`
- **Kimlik doğrulama yok** — sunucu-sunucu çağrı, tarayıcıdan çalışmaz (CORS yok)
- Boş `records[]` görürseniz önce `success` alanına bakın — `false` ise teknik hata var, "kayıt yok" değil
