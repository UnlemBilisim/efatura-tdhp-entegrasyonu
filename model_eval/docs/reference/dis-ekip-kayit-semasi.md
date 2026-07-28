# Dış Ekip Kayıt Şeması (`records[]` + tam zarf)

> **Tür:** reference — kesin teknik başvuru. Kodla birebir senkron olmalı.
> **Uygulayan:** [`core/disa_aktarim.py`](../../core/disa_aktarim.py),
> [`core/single.py::_entry_dicts_uygula`](../../core/single.py)
> **Servis eden:** `entegrasyon/app.py` → `POST /fatura/isle` →
> `tdhp_tahmini.records[]`
>
> ✅ **Uygulandı** (2026-07-27): Sözleşme kodda uygulandı ve test edildi
> (`tests/test_disa_aktarim.py`, 21 test). Toplam paket: 205 test geçiyor.
> **Canlı doğrulama:** SSH tüneli + Docker açıkken gerçek bir fatura
> (`AKA2025000000001`) `POST /fatura/isle` ile işlendi; 9 alanlı zarf gerçek
> LLM çıktısıyla üretildi, `records[]` alan kümesi karşı tarafın örnek
> JSON'uyla birebir eşleşti (eksik/fazla alan yok).

## Amaç

Dış ekip, muhasebe kayıtlarını kendi alan adlarıyla istiyor. `model_eval`'ın
iç şeması (`entries[]`) farklı — bu belge iki şema arasındaki **tek yönlü**
dönüşümü tanımlar.

**İç şema neden değişmedi:** `entries[]` ve `dc="Borc"/"Alacak"` değerlerine
198 test, ChromaDB RAG kayıtları ve `model_eval_sonuclar` tablosu bağlı. İç
şemayı değiştirmek bunların hepsini kırardı. Bunun yerine dışa aktarımda
tek yönlü dönüşüm yapılır: **iç şema serbest kalır, dış sözleşme sabitlenir.**

## Tam zarf (9 alan)

`POST /fatura/isle` cevabındaki `tdhp_tahmini.dis_sema` doğrudan karşı tarafa
gönderilebilir. Üreten: `core/disa_aktarim.py::faturayi_disa_aktar`.

| Alan | Kaynak |
|---|---|
| `invoice_id` | Fatura `cbc:ID` |
| `issue_date` | Fatura `cbc:IssueDate` |
| `currency` | Fatura para birimi |
| `payable_amount` | Fatura ödenecek tutar (float'a çevrilir) |
| `customer` / `supplier` | `{id, name}` — **yöne göre** belirlenir (aşağıya bakın) |
| `records` | Muhasebe kayıtları (6 alanlı, aşağıda) |
| `success` | `tdhp_tahmini.error is None` |
| `file_path` | Çağıran katmandan gelir; verilmezse `""` |

### customer/supplier neden yöne bağlı?

UBL'de karşı taraf **tek** bir alanda tutulur (`header.account_title` /
`account_tax_number`); hangi tarafta olduğu fatura yönüne bağlıdır:

- **outbox** (biz kestik) → karşı taraf `customer`, biz `supplier`
- **inbox** (bize geldi) → karşı taraf `supplier`, biz `customer`

Kendi unvanımız UBL'den okunmuyor (parser yalnızca karşı tarafı tutuyor), bu
yüzden bizim tarafta sadece `id` (VKN) dolu, `name` boş string kalır.

> **Bilinen sınır:** `file_path` şu an `entegrasyon` katmanından geçirilmiyor
> (boş string döner) — servis ham XML string alıyor, dosya yolu bilmiyor.
> Karşı taraf bu alanı kullanacaksa istek gövdesine eklenmesi gerekir.

## `records[]` şeması

Her `records[]` öğesi **tam olarak** şu 6 alanı taşır — eksik veya fazla alan yok:

| Alan | Tip | Açıklama |
|---|---|---|
| `account_code` | string | TDHP hesap kodu, alt kırılımlı (`"191.01.00020"`). Alt kırılım çözülemezse 3 haneli kalır (`"320"`). |
| `account_code_type` | string | `"C"` = cari hesap, `"G"` = diğer. Ana kod `CARI_HESAP_KODLARI` (120/320/340/440/159/420) içindeyse `C`. |
| `account_description` | string | Mizandaki HESAP ADI (`"%20 İndirilecek KDV"`). Bilinmiyorsa **boş string** — `null` değil. |
| `account_code_reason` | string | Kodun neden seçildiği. **Asla boş kalmaz.** |
| `amount` | number | Tutar — dönüşümde değiştirilmez. |
| `debit_credit` | string | `"BORÇ"` / `"ALACAK"` (iç şemadaki `"Borc"`/`"Alacak"`ın karşılığı). |

### Örnek

```json
{
  "account_code": "320.01.00376",
  "account_code_type": "C",
  "account_description": "Mehmet Kozcağız",
  "account_code_reason": "Karşı taraf unvanı mizandaki 'Mehmet Kozcağız' kaydıyla eşleşti (isim benzerliği %94); aynı cari hesap kullanıldı.",
  "amount": 1700.0,
  "debit_credit": "ALACAK"
}
```

## `account_code_reason` nasıl üretilir?

**Deterministik üretilir — LLM'e sorulmaz** (kullanıcı kararı, 2026-07-27).

Gerekçe, kodun gerçekten nereden geldiğinin izinden (`secim_kaynagi`,
`core/single.py::_entry_dicts_uygula` tarafından eklenir) türetilir:

| Durum (`secim_kaynagi.kaynak`) | Üretilen gerekçe |
|---|---|
| `"fuzzy"` | "Karşı taraf unvanı mizandaki '…' kaydıyla eşleşti (isim benzerliği %N); aynı cari hesap kullanıldı." |
| `"llm"` + `oran_duzeltildi=True` | "Hesap türü geçmiş emsal faturalara göre seçildi; alt kırılım, faturadaki gerçek KDV oranına göre … olarak düzeltildi." |
| `"llm"` + `emsal_sayisi>0` | "Aynı tedarikçi/müşteri ile yapılan N geçmiş benzer faturada kullanılan hesap kırılımı esas alındı." |
| `"llm"` (emsalsiz) | "Faturadaki kalem açıklaması ve mizandaki alt kırılım adları eşleştirilerek seçildi." |
| Kod 3 hanede kaldı + `uyari` var | "… için mizanda eşleşen alt kırılım (cari kart) bulunamadı; ana hesap kodunda bırakıldı — yeni müşteri/tedarikçi olabilir." |
| Kod 3 hanede kaldı, uyarı yok | "… ana hesap kodu kullanıldı; mizanda bu kod için seçilebilecek bir alt kırılım bulunamadı." |
| İz yok | "Faturadaki kalem bilgisi ile mizandaki hesap planı eşleştirilerek seçildi." |

**Neden LLM'e sorulmuyor:** Modele "bu kodu neden seçtin" diye sormak
*post-hoc rasyonalizasyon* riski taşır — model kodu bir sebeple seçip
tamamen başka bir sebep yazabilir. Deterministik gerekçe, gerçekten olan
işlemi anlatır ve ek LLM çağrısı maliyeti yoktur.

## `uyari` alanının dış şemadaki karşılığı

Dış şemada ayrı bir uyarı alanı **yok**. İç şemadaki `uyari` (karşı taraf
mizanda bulunamadı) bilgisi kaybolmasın diye gerekçenin sonuna `UYARI: …`
olarak eklenir. Gerekçe zaten bu durumu anlatıyorsa (3 hanede kalma
senaryosu) **tekrar eklenmez.**

## Değişmez kurallar

1. **İç şema (`entries[]`, `dc="Borc"/"Alacak"`) değiştirilmez.** Dönüşüm
   yalnızca `core/disa_aktarim.py`'de yapılır.
2. **Dönüşüm `amount` ve `account_code` değerlerini değiştirmez** — sadece
   alan adlarını çevirir ve türetilmiş alanları ekler.
3. **`account_description` bilinmiyorsa boş string döner, `null` değil** —
   dış ekip tip tutarlılığı bekliyor.
4. **Ayrı bir cari-hesap listesi tutulmaz** — `account_code_type` mevcut
   `CARI_HESAP_KODLARI` kümesinden türetilir (kök `CLAUDE.md`: "var olan
   sınıflandırma yapısına ekle, paralel ikinci liste oluşturma").

## Bilinen sınır

`emsal_sayisi` parametresi şu an `entegrasyon/model_eval_koprusu.py`'den
**geçirilmiyor** (varsayılan `0`), çünkü RAG'ın kaç emsal kullandığı bilgisi
`predict_single_invoice` çıktısında dönmüyor. Bu yüzden "N geçmiş benzer
faturada kullanılan…" gerekçesi henüz üretilmiyor; onun yerine emsalsiz LLM
gerekçesi yazılıyor. Emsal sayısını çıktıya eklemek ayrı bir görev.
