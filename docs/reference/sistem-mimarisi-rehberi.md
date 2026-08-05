# Sistem Mimarisi Rehberi — Dosya Dosya Detaylı Referans

> **Tür:** reference (Diátaxis) — kesin teknik başvuru, dosya:satır referanslarıyla.
> Bu belge üç bileşenin (`Mcp_mimarisi`, `model_eval`, `entegrasyon`) hem tek
> tek hem birlikte nasıl çalıştığının **birincil, kapsamlı referansıdır.**
> Mimari kararların *neden* öyle verildiğinin üst düzey özeti için
> [`../../mimari.md`](../../mimari.md)'ye bakın — bu belge onu tekrar etmez,
> onun üzerine dosya/satır seviyesinde detay ekler.
>
> ✅ **Oluşturuldu** (2026-07-29): Üç bileşenin ayrı ayrı yapılmış detaylı kod
> analizleri + bileşenler-arası akış/sözleşme analizi birleştirilerek yazıldı.

---

## 1. Genel Özet

Sistem, bir e-Faturayı iki aşamada işler: önce **KDV mevzuatı açısından
denetler**, sonra **muhasebe kaydı (TDHP kodu + Borç/Alacak + tutar)
üretir**. Bu iki aşama, doğaları kökten farklı olduğu için iki ayrı bileşene
bölünmüştür:

- **`Mcp_mimarisi`** (port 8000): "Bu KDV oranı mevzuata uygun mu?" sorusuna
  cevap arar. Bu deterministik bir kural sorusudur — satıcının NACE kodu,
  hangi KDV oranlarına izin veriyor, beyan edilen oran bu havuzda mı. LLM
  **hiç kullanılmaz**; kural motoru + PostgreSQL referans tablosu yeterlidir.
  Çıktı yalnızca `uygun` veya `insan_incelemesi_gerekli` — kesin "uyumsuz"
  hiçbir zaman üretilmez (temkinli tasarım).
- **`model_eval`** (bağımsız süreç değil, **import** edilen kütüphane): "Bu
  fatura hangi hesaba, hangi yönde kaydedilir?" sorusuna cevap arar. Bu yorum
  gerektirir, geçmiş emsallere ihtiyaç duyar, kurala indirgenemez — bu yüzden
  LLM + RAG (ChromaDB) kullanılır.
- **`entegrasyon`** (port 8100): Yukarıdaki ikisini birleştiren orkestrasyon
  katmanı ve dış ekibe açılan tek kapı. Faturanın yönünü (inbox/outbox)
  tespit eder, outbox ise önce `Mcp_mimarisi`'ni HTTP ile çağırır, sonuç uygun
  bulunursa (veya insan onayı gelirse) `model_eval`'i import ile çağırıp TDHP
  tahminini üretir ve dış ekibin beklediği sabit şemaya (`records[]`/
  `dis_sema`) çevirir.

Bu üç bileşen arasındaki en dikkat çekici mimari asimetri, **`Mcp_mimarisi`
ile HTTP, `model_eval` ile import** üzerinden konuşulmasıdır. Bu tesadüf
değildir: `Mcp_mimarisi` bağımsız geliştirilen, kendi DB şeması ve yaşam
döngüsü olan ayrı bir servistir; HTTP arkasında olması onu ayrı deploy
edilebilir kılar. `model_eval` ise ChromaDB + embedding modeli + LLM
istemcileri gibi ağır bağımlılıklar taşır — HTTP arkasına koymak her istekte
modelin/koleksiyonun yeniden yüklenmesi riskini getirirdi; import ile
çağrılınca ChromaDB koleksiyonu process ömrü boyunca cache'lenir. Bu asimetri
"alt projeler birbirine kod olarak bağlanmaz" kuralını ihlal etmez, çünkü o
kural `Mcp_mimarisi` ↔ `model_eval` ilişkisi için var; `entegrasyon` üçüncü,
bağımsız bir bileşen olarak ikisine de kendi doğasına uygun şekilde bağlanır.

Bu asimetrinin somut, kod düzeyinde sonucu bir **değişmez kısıttır**:
`entegrasyon/` ve `model_eval/` aynı üst dizinde kardeş kalmalıdır, çünkü
`entegrasyon/model_eval_yolu.py` bunu varsayarak `sys.path`'e ekleme yapar.
Klasörleri ayırmak sistemi bozar (bkz. kök `System/CLAUDE.md`, Değişmez Kural
1).

---

## 2. Uçtan Uca Veri Akışı (Adım Adım)

**Adım 0 — Giriş.** Dış ekip `POST /fatura/isle` çağırır, gövde: `fatura_xml`
(ham UBL-TR string) + `satici_vkn` (**kendi VKN'imiz** anlamında, yanıltıcı
isim — fatura üzerindeki satıcı değil) + opsiyonel
`satici_nace_kodlari`/`onay`/`kur_secimi`.

**Adım 1 — Yön tespiti.** `model_eval/core/parsing.py::parse_invoice_xml_string`
XML'i ayrıştırıp `AccountingSupplierParty`/`AccountingCustomerParty`
VKN'lerini `satici_vkn` ile karşılaştırır → `outbox` ya da `inbox` kararı.
Veri hâlâ XML, ama yön artık bir dize (`"outbox"`/`"inbox"`) olarak akışın
geri kalanını dallandırır.

**Adım 2a — inbox dalı.** Ön filtreleme tamamen atlanır (`Mcp_mimarisi` hiç
çağrılmaz), doğrudan `tdhp_tahmini_yap()` çağrılır, `asama=
"tdhp_tahmini_tamamlandi"` döner. Gerekçe: başkasının kestiği faturanın
mevzuat sorumluluğu bizde değil.

**Adım 2b — outbox dalı, aşama 1 (KDV ön filtre).** `entegrasyon/app.py:313`
`fatura_kontrol_et()` üzerinden `Mcp_mimarisi`'ye **HTTP** ile
`POST /fatura/kontrol-et` gönderilir (XML hâlâ ham metin olarak taşınır).
`Mcp_mimarisi` kalem kalem NACE kodu → oran havuzu karşılaştırması yapıp
`genel_karar` (`"uygun"` / `"insan_incelemesi_gerekli"`) + `satir_sonuclari`
içeren bir dict/JSON döner.

`entegrasyon/app.py:333-335`'teki `devam_etsin` koşulu:
`genel_karar=="uygun"` veya (`"insan_incelemesi_gerekli"` VE
`istek.onay is True`). Değilse akış `asama=
"on_filtre_insan_incelemesi_bekliyor"` ile durur, `tdhp_tahmini=null` döner —
dış ekip aynı isteği `onay:true` ile tekrar göndermek zorundadır.

**Adım 3 — TDHP tahmini (model_eval, aynı process, Python import).**
`entegrasyon/model_eval_koprusu.py::tdhp_tahmini_yap` →
`model_eval/core/single.py::predict_single_invoice()` çağrılır. İç akış (bkz.
§4.1 için tam detay):
1. XML tekrar parse edilir → Python dict (`invoice` iç yapısı).
2. RAG: faturanın metinsel temsili `embeddinggemma` ile embed edilir, ChromaDB
   `tdhp_invoices` koleksiyonundan en benzer `k=3` geçmiş fatura çekilir →
   prompt'a few-shot örnek olarak eklenir.
3. LLM çağrısı (Ollama, uzak GPU'ya SSH tüneli üzerinden `11435`) → 3 haneli
   TDHP kodu + yön (`entries[]`, `dc="Borc"/"Alacak"` iç şemasında) + tutar.
4. Self-correction: emsalle çelişirse ikinci LLM çağrısı.
5. Mizan alt kırılımı: 3 haneli kodlar (`120`, `600`...) `mizan.xlsx`'e karşı
   ayrı bir LLM çağrısıyla (ya da önce deterministik fuzzy isim eşleşmesiyle)
   alt kırılıma (`120.01.00008`) çözülür.
6. Denge kontrolü (borç toplamı = alacak toplamı).

Bu noktada veri iç şemada: `entries[]` (her biri `account_code`, `dc`,
`amount` + iz bilgisi `secim_kaynagi`).

**Adım 4 — Dönüşüm (entries[] → records[]).**
`model_eval/core/disa_aktarim.py::faturayi_disa_aktar` (`kayitlari_disa_aktar`)
iç şemayı **tek yönlü** dış şemaya çevirir: `dc="Borc"/"Alacak"` →
`debit_credit="BORÇ"/"ALACAK"`, `secim_kaynagi` izinden deterministik
`account_code_reason` metni üretilir (LLM'e tekrar sorulmaz — post-hoc
rasyonalizasyon riskinden kaçınma), `CARI_HESAP_KODLARI` kümesinden
`account_code_type` (`C`/`G`) türetilir. İç şema (`entries[]`) hiç değişmez —
205 test, ChromaDB kayıtları ve `model_eval_sonuclar` tablosu ona bağlı.

**Adım 5 — Zarf ve cevap.** `disa_aktarim.py` 9 alanlı `dis_sema`'yı üretir
(`invoice_id`, `issue_date`, `currency`, `payable_amount`,
`customer`/`supplier` — yöne göre yerleşir, `records[]`, `success`,
`file_path`). `entegrasyon/app.py` bunu `TdhpTahminiCevabi` içine sarıp
`FaturaIsleCevabi(asama="tdhp_tahmini_tamamlandi", tdhp_tahmini=...)` olarak
dış ekibe döner. Dış ekibin ihtiyaç duyduğu tek alan:
`cevap["tdhp_tahmini"]["dis_sema"]`.

**Adım 6 (opsiyonel) — Onay geri beslemesi.** `POST /fatura/onayla` →
`model_eval_koprusu.py::faturayi_onayla` iki yere yazar: PostgreSQL
`model_eval_sonuclar` (append, denetim izi) ve ChromaDB `tdhp_invoices`
(upsert by `invoice_id`, emsal havuzu güncellenir) — bu döngü sistemi
"öğrenen" yapar.

---

## 3. `Mcp_mimarisi` — Detaylı Kod Referansı

Port 8000'de çalışan FastAPI servisi; kural tabanlı (LLM yok), PostgreSQL
destekli. Fatura XML'ini alır, satıcının bildirilen NACE kod(lar)ına göre
beyan edilen KDV oranının mevzuata uygun olup olmadığını kontrol eder.

### 3.1 `src/efatura_kdv/ubl_parser.py`

**Ne yapar:** UBL-TR e-fatura XML'ini `xml.etree.ElementTree` ile ayrıştırıp
yapılandırılmış Python dataclass'larına (`Fatura`, `FaturaKalemi`,
`VergiKirilimi`, `Party`) çevirir. Bu modül NACE ile hiç ilgilenmez, sadece
fatura içeriğini çıkarır (satır 4-5, 203-209).

**Girdi/Çıktı:** Girdi — XML dosya yolu (`parse_ubl_invoice`, satır 240-243)
ya da XML string'i (`parse_ubl_invoice_from_string`, satır 246-251, API'nin
kullandığı yol). Çıktı — bir `Fatura` nesnesi.

**Namespace'ler ve path'ler** (satır 13-16):
```python
NS = {
    "cbc": "urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2",
    "cac": "urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2",
}
```
- Fatura kimliği: `cbc:ID` → `fatura_no`, `cbc:UUID` → `uuid`, `cbc:IssueDate`
  → `duzenleme_tarihi`, `cbc:ProfileID` → `profil_id`, `cbc:InvoiceTypeCode`
  → `fatura_tipi`, `cbc:DocumentCurrencyCode` → `para_birimi` (satır
  210-217).
- Taraflar: `cac:AccountingSupplierParty` / `cac:AccountingCustomerParty`
  altında `cac:Party/cac:PartyIdentification/cbc:ID` (schemeID="VKN" veya
  "TCKN") ve `cac:Party/cac:PartyName/cbc:Name` (satır 132-146, 219-225).
- Kalemler: kök altındaki her `cac:InvoiceLine` (satır 232-235) → sıra no
  (`cbc:ID`), `cac:Item/cbc:Name`, `cac:Item/cbc:Description`,
  `cbc:InvoicedQuantity` (miktar + `unitCode` özniteliği birim),
  `cbc:LineExtensionAmount` (satır 185-200).
- Vergi kırılımları: hem satır hem fatura genelinde
  `cac:TaxTotal/cac:TaxSubtotal` (KDV ve diğer vergiler) ve
  `cac:WithholdingTaxTotal/cac:TaxSubtotal` (tevkifat) ayrı ayrı ayrıştırılır
  (satır 173-182). Her `TaxSubtotal`'dan: `cbc:TaxableAmount` (matrah),
  `cbc:TaxAmount` (tutar), `cbc:Percent` (oran),
  `cac:TaxCategory/cac:TaxScheme/cbc:Name` (vergi adı),
  `cac:TaxCategory/cac:TaxScheme/cbc:TaxTypeCode` (vergi tipi kodu),
  `cac:TaxCategory/cbc:TaxExemptionReasonCode`/`cbc:TaxExemptionReason`
  (istisna kodu/açıklaması) (satır 149-170).

**Kritik iş kuralı — KDV ayrımı:** `cac:TaxTotal` KDV dışında Özel İletişim
Vergisi (4081), Telsiz Kullanım Taksiti (8006) gibi başka vergiler de
taşıyabilir (gerçek Turkcell faturasında doğrulanmış, satır 44-46, 162-167).
Bu yüzden `VergiKirilimi.kdv_mi` property'si `vergi_tipi_kodu == "0015"`
kontrolüyle KDV'yi ayırt eder (satır 58-61); `kdv_kirilimlari`/
`kdv_oranlari`/`istisna_kodlari` property'leri (satır 77-94) her zaman bu
filtreden geçer. Tevkifat kodu SADECE `WithholdingTaxTotal` bağlamında dolu
tutulur (satır 162-170) — aynı alan (`TaxTypeCode`) farklı bağlamda farklı
anlam taşıdığı için yanlış sınıflandırmayı önler.

**Ana fonksiyonlar:**
- `_text(node, path)` / `_decimal_text` (satır 19-28): XPath ile
  metin/ondalık çıkarma yardımcıları, eleman yoksa `None`.
- `_parse_party`, `_parse_tax_subtotal`, `_parse_tax_total`,
  `_parse_invoice_line`, `_parse_root` (satır 132-237): sırasıyla taraf, tek
  vergi kırılımı, vergi kırılım listesi, tek kalem ve tüm kök XML'i
  ayrıştırır — dosyadan/string'den bağımsız ortak mantık `_parse_root`'ta
  toplanmış.
- `Fatura.to_dict()` (satır 116-129): `asdict()` dataclass property'lerini
  (KDV filtreleri) otomatik yakalamadığı için manuel olarak JSON çıktısına
  ekler.

### 3.2 `src/efatura_kdv/nace_kural_kontrolu.py`

**Ne yapar:** Tek bir NACE kodu için, PostgreSQL'deki `nace_oranlari`
tablosundan izin verilen KDV oranlarını sorgular ve beyan edilen oranla
karşılaştırır. Oran **üretmez**, sadece "beyan edilen oran, bu NACE'nin izin
verdiği listede mi" eşleşmesi yapar (satır 1-6).

**Girdi/Çıktı:** Girdi — NACE kodu (string), beyan edilen oran (float),
`NaceOranTablosu` örneği. Çıktı — `KontrolSonucu` dataclass'ı (karar
`KararTuru.UYGUN`/`INSAN_INCELEMESI_GEREKLI`, nace_kodu, beyan_edilen_oran,
izin_verilen_oranlar, gerekçe metni, satır 55-63).

**Ana fonksiyonlar/sınıflar:**
- `_nace_kodu_normalize_et` (satır 36-45): NACE kodundan noktaları siler
  (`"25.40.04"` → `"254004"`). 2026-07-28'de gerçek bir faturada
  (AKL2026000000211) noktalı/noktasız uyuşmazlığı sessizce "bulunamadı"ya yol
  açtığı için eklendi.
- `NaceOranTablosu` (satır 66-123): uygulama başlarken (FastAPI lifespan) BİR
  KEZ kurulur, `nace_oranlari` tablosunun tamamını
  `{nace_kodu: [izin_verilen_oranlar]}` sözlüğüne (satır 100-110) belleğe
  yükler. `DATABASE_URL` env var'ından bağlanır, yoksa `RuntimeError`
  fırlatır (satır 78-84). Bir NACE'nin birden fazla oran sütunu
  (`kdv_0`/`kdv_1`/`kdv_10`/`kdv_20`) TRUE olabilir — "çok oranlı NACE"
  durumu (tarım, gayrimenkul gibi), bu yüzden değer tekil değil liste.
  `izin_verilen_oranlar(nace_kodu)` (satır 112-123) sorgu metodu; `None`
  (NACE hiç yok) ile `[]` (NACE var ama hiç oran işaretli değil) bilinçli
  olarak ayrı tutuluyor, ama `kontrol_et` şu an ikisini de aynı şekilde ele
  alıyor.
- `kontrol_et(nace_kodu, beyan_edilen_oran, tablo)` (satır 126-185): 3 adımlı
  mantık — (1) NACE tabloda yoksa → insan incelemesi (satır 141-152); (2)
  beyan edilen oran izin verilenler içindeyse → uygun (satır 158-168); (3)
  değilse → insan incelemesi, çünkü fark bir istisna/tevkifattan kaynaklanıyor
  olabilir ve bu modül bunu bilmiyor (satır 170-185).

### 3.3 `src/efatura_kdv/kalem_nace_esleme.py`

**Ne yapar:** `nace_kural_kontrolu.kontrol_et()`'in TEK NACE için yaptığı
kontrolün, satıcının **BİRDEN FAZLA** NACE koduna genelleştirilmiş halidir;
ayrıca kalem (satır) bazında oran kontrolü ve istisna kodu doğrulaması ekler.
**Kritik mimari karar (2026-07-20):** kalem metnine hiç bakılmaz, LLM
kullanılmaz — eski sürümdeki `kalem_nace_esle()`, `_llm_nace_sec()`,
`NaceCozumTipiTablosu`, `EslemeGuveni` tamamen kaldırılmış (satır 8-14).

**Girdi/Çıktı:** Girdi — `Fatura` (ubl_parser çıktısı), `SaticiNaceBilgisi`
(vkn + nace_kodlari listesi — dışarıdan gelir, VKN→NACE lookup YOK, satır
85-90), `NaceOranTablosu`. Çıktı — `FaturaSatirBazliSonuc`: her kalem için
`SatirKontrolSonucu` listesi + `genel_karar` property'si.

**İş kuralı — NACE havuzu:** `_izin_verilen_oranlar_havuzu` (satır 135-158):
satıcının TÜM NACE kodlarının izin verdiği oranları TEK bir kümede (havuz)
birleştirir. Örnek: NACE-A sadece %20, NACE-B %1/%10/%20 destekliyorsa havuz
= {1, 10, 20} olur. Kalemin oranı bu havuzda VARSA hangi NACE'ye ait olduğu
aranmadan `uygun` sayılır — kalem içeriği hiç okunmaz.

**Ana fonksiyonlar:**
- `SaticiVknUyusmazligiHatasi` (satır 74-82, `ValueError` alt sınıfı):
  `satir_bazli_kontrol_et`'e verilen `satici_nace.vkn`, faturanın gerçek
  satıcı VKN'siyle uyuşmazsa fırlatılır (satır 301-306) — "bu fatura bize ait
  değil, yanlış NACE ile eşleştirilmesin" güvenlik kontrolü. `api.py` bunu
  yakalayıp 400 döner.
- `_kalem_beyan_edilen_oranlari` (satır 247-282): kalem seviyesinde KDV oranı
  yoksa (bazı gerçek faturalarda — özellikle TEMELFATURA/telekom, Turkcell
  örneği — satır seviyesinde hiç `TaxTotal` yok) fatura genelindeki
  BENZERSİZ oran sayısına bakar: tam 1 farklıysa o oranı kullanır, 0 ya da
  2+ ise tahmin etmez, insan incelemesine düşürür.
- `GENEL_ISTISNA_KODLARI` (satır 46-69): GİB'in resmi
  `Istisna_Kodlari_GIB.xlsx` (V1.42, Mart 2026) kılavuzundan türetilmiş 107
  kod — 7 kategori (Konaklama, ÖTV, Kısmi/Tam İstisna, Diğer İşlem Türü,
  İhraç Kayıtlı, Özel Matrah). Dolgu kodlar (151, 250, 350, 351 —
  "Diğerleri"/"İstisna Olmayan Diğer") bilinçli olarak dışarıda bırakılmış
  çünkü gerçek bir mevzuat maddesine dayanmıyorlar.
- `_genel_istisna_dogrulamasi` (satır 203-223): kalemde/faturada
  `GENEL_ISTISNA_KODLARI`'ndan biri varsa, oran havuzla uyuşmasa bile karar
  `uygun`'a çevrilir.
- `_fatura_istisna_notu` (satır 226-244): genel listede OLMAYAN bir istisna
  kodu varsa sadece bilgi notu ekler, karar değişmez (temkinli kalır).
- `kalem_istisna_kodlari` (satır 179-200, public): kalemde yoksa faturanın
  genel toplamına düşer — istisna kodu genelde ihracat faturalarında kalemde
  değil genel toplamda bulunur. `scripts/gecmis_faturalari_yukle.py` da bunu
  kullanıyor (tek kaynak).
- `satir_bazli_kontrol_et(fatura, satici_nace, oran_tablosu)` (satır
  285-427): ana orkestrasyon — (1) VKN güvenlik kontrolü, (2) havuz hesabı
  (fatura başına bir kez), (3) her kalem için: oran belirsizse → insan
  incelemesi; NACE hiç bulunamadıysa → insan incelemesi; oran havuzdaysa →
  uygun (gerekçede TAM OLARAK hangi NACE'nin desteklediği
  `_nace_gerekce_metni` ile belirtilir, satır 161-176); oran havuzda değilse
  → önce genel istisna kontrolü, varsa uygun, yoksa insan incelemesi + varsa
  bilgi notu.

### 3.4 `src/efatura_kdv/gecmis_kontrol.py`

**Ne yapar:** "Emsal kontrolü": bir (satıcı VKN, kalem adı) çifti için geçmiş
outbox faturalarda bu kalemin hangi oran(lar)la kesildiğini gösterir. **KARAR
ÜRETMEZ** — sadece bilgi/uyarı notu. Ana NACE kural kontrolünün ürettiği
karar bu sinyale göre değiştirilmez (satır 1-24). Bu, "geçmiş veri
sınıflandırmada kullanılmaz" kuralını ihlal etmiyor çünkü kategori
öğrenmiyor, sadece insana gösterilen bir çapraz kontrol.

**Girdi/Çıktı:** Sorgu tarafı — satıcı VKN + kalem adı + beyan edilen
oranlar → `GecmisKontrolSonucu` (geçmiş oranlar listesi, kaç kez görüldüğü,
son görülme tarihi, `gecmisle_uyusuyor_mu` bool/None, insan-okunur
`bilgi_notu`). Yazma tarafı — bir faturanın kalemlerini
`gecmis_fatura_kalemleri` tablosuna kaydeder.

**Ana fonksiyonlar/sınıflar:**
- `normalize_kalem_adi` (satır 39-45): küçük harfe çevirip fazla boşlukları
  temizler — yazma ve okuma tarafında BİREBİR aynı mantık (kod tekrarı
  `scripts/gecmis_faturalari_yukle.py`'de de var, senkron tutulmalı).
- `GecmisOranOzeti` / `GecmisKontrolSonucu` (satır 48-104):
  `gecmisle_uyusuyor_mu` — geçmiş veri yoksa `None` (bilinmiyor, ne uyumlu ne
  uyumsuz); `bilgi_notu` property'si insana gösterilecek Türkçe metni üretir
  (uyum varsa nötr, yoksa "UYARI" ön ekiyle).
- `GecmisFaturaDeposu` (satır 107-169): `NaceOranTablosu`'nun aksine tüm
  veriyi belleğe yüklemez (veri büyüyebilir), her sorgu
  `ThreadedConnectionPool` üzerinden DB'ye gider (2026-07-22'de eklendi,
  önceden her sorgu ayrı TCP bağlantısı açıyordu). `gecmis_oranlari_getir` —
  `satici_vkn` + normalize edilmiş kalem adına göre
  `GROUP BY oran, istisna_kodu` sorgusu (satır 139-169).
- `gecmis_kontrol_et` (satır 172-185): tek kalem için sorguyu çalıştırıp
  sonucu döner.
- `faturayi_gecmise_kaydet` (satır 188-265): fatura kalem-oran satırlarını
  yazar. **Yarış durumu koruması** (2026-07-22): önce `islenmis_faturalar`
  claim tablosuna `INSERT ... ON CONFLICT DO NOTHING RETURNING` ile atomik
  "kazanan tek istek" deseni kurulur — satır dönerse asıl kalemler aynı
  transaction'da yazılır, dönmezse (biri önce commit etmiş) hiçbir şey
  yazmadan `False` döner. Eskiden "SELECT var mı → yoksa INSERT" iki
  adımlıydı, lock yoktu, çift sayım riski taşıyordu.
- `fatura_kalemlerini_kayit_icin_hazirla` (satır 268-293): kalemin sayısal
  oranı varsa onu kullanır (istisna_kodu=None); yoksa ama istisna kodu varsa
  oran %0 + istisna_kodu dolu kaydedilir (2026-07-22 düzeltmesi — önceden
  istisna faturaları hiç geçmiş tabloya girmiyordu).

### 3.5 `src/efatura_kdv/api.py` — HTTP API ve 4 Endpoint

**Genel mimari:** FastAPI uygulaması; `_lifespan` (satır 67-81) başlangıçta
`NaceOranTablosu` (bellek-içi, bir kez yüklenir) ve `GecmisFaturaDeposu`
(connection pool, her sorguda DB'ye gider) kurar, paylaşılan `_state`
sözlüğünde tutar; kapanışta pool'u kapatır. Üç exception handler (satır
94-133): `psycopg2.OperationalError` → 503 (DB kapalı, ham hata client'a
sızmaz), `PoolError` → 503 (pool tükendi), genel `Exception` → 500 (generic
mesaj, ham exception client'a hiç gitmez — önceden dosya yolu/şema gibi iç
detaylar sızıyordu).

**`GET /saglik`** (satır 240-244): Servis ayakta mı ve `oran_tablosu` yüklü
mü döner — yük dengeleyici/sağlık kontrolü için. DB'ye sorgu atmaz, sadece
`_state` içeriğine bakar.

**`POST /fatura/kontrol-et`** (satır 298-305) — akış:
1. İstek gövdesi: `fatura_xml` (ham UBL-TR string), `satici_vkn`,
   `satici_nace_kodlari` (liste).
2. `_tek_fatura_kontrol_et` (satır 247-295, ortak mantık) çağrılır:
   - `[MCP 1/3]` XML `parse_ubl_invoice_from_string` ile ayrıştırılır;
     `ET.ParseError` veya genel parse hatası → HTTP 400.
   - `SaticiNaceBilgisi` oluşturulur.
   - `[MCP 2/3]` `satir_bazli_kontrol_et` çağrılır; `SaticiVknUyusmazligiHatasi`
     (ValueError alt sınıfı) yakalanırsa → HTTP 400.
   - `[MCP 3/3]` Sonuç ve her kalemin kararı loglanır.
3. `FaturaKontrolCevabi.from_dataclass(sonuc)` ile response modeline
   çevrilip döner — `fatura_no`, `uuid`, `satici_vkn`, `genel_karar`, kalem
   başına `SatirSonucCevabi` (kalem adı, beyan edilen oranlar, kontrol
   edilen NACE'ler, izin verilen oran havuzu, karar, gerekçe).

**`POST /fatura/gecmis-kontrol`** (satır 308-323) — akış:
1. İstek: `satici_vkn` + `kalemler` listesi (kalem_adi + beyan_edilen_oranlari).
2. Her kalem için `gecmis_kontrol_et` çağrılır, `_state["gecmis_depo"]`
   kullanılır.
3. Sonuç: `GecmisKontrolSonucCevabi` listesi (karar üretmez, sadece bilgi
   notu). Ayrı bir endpoint — ana kontrol akışıyla otomatik tetiklenmez,
   istemci isterse ayrıca çağırır.

**`POST /fatura/coklu-kontrol`** (satır 326-389) — akış: Aynı satıcı VKN +
NACE kod(lar)ıyla BİRDEN FAZLA fatura XML'i topluca işlenir (muhasebecinin
tek oturumda tek şirketin tüm faturalarını yüklemesi senaryosu):
1. Her `fatura_xml` için `_tek_fatura_kontrol_et` çağrılır; `HTTPException`
   fırlarsa o fatura `basarili=False` + hata mesajıyla işaretlenir, DÖNGÜ
   DEVAM EDER (tüm istek düşmez).
2. Başarılı olan fatura için her kalem `gecmis_kontrol_et` ile geçmişe karşı
   kontrol edilir.
3. `fatura_kalemlerini_kayit_icin_hazirla` + `faturayi_gecmise_kaydet` ile
   kalemler otomatik olarak `gecmis_fatura_kalemleri` tablosuna kaydedilir —
   bu güvenlidir çünkü `satir_bazli_kontrol_et` zaten VKN eşleşmesini garanti
   etmiştir (buraya kadar gelen her fatura kullanıcının kendi kestiği outbox
   faturadır).
4. Sonuç: `CokluKontrolFaturaSonucu` listesi (dosya_index, basarili, hata,
   fatura_kontrol, gecmis_kontrolleri, gecmise_kaydedildi).

**Pydantic modelleri** (satır 136-238): İstek — `FaturaKontrolIstegi`,
`GecmisKontrolIstegi` (+`GecmisKontrolIstegiKalemi`), `CokluKontrolIstegi`.
Cevap — `SatirSonucCevabi`, `FaturaKontrolCevabi`, `GecmisOranOzeticevabi`,
`GecmisKontrolSonucCevabi`, `CokluKontrolFaturaSonucu` — hepsi
`from_dataclass` classmethod'uyla iç dataclass'lardan
(ubl_parser/nace_kural_kontrolu/kalem_nace_esleme/gecmis_kontrol)
türetiliyor, iş mantığı burada tekrarlanmıyor.

### 3.6 PostgreSQL Şeması (`alembic/versions/`)

**Migration 1 — `9846b14dc658` (2026-07-22): ilk şema.** Bu migration
Alembic'ten ÖNCE elle (`scripts/excel_to_postgres.py`,
`scripts/gecmis_faturalari_yukle.py`) kurulmuş mevcut şemayı olduğu gibi
kaydeder — yeni bir şey eklemez, mevcut tabloları Alembic zincirine dahil
eder. Production'da tablolar zaten varsa bu migration çalıştırılmaz,
`alembic stamp head` kullanılır (satır 6-11).

**`nace_oranlari`** (satır 33-41):

| Sütun | Tip | Açıklama |
|---|---|---|
| `nace_kodu` | Text, PK | Noktasız NACE kodu (ör. "254004") |
| `kdv_0`, `kdv_1`, `kdv_10`, `kdv_20` | Boolean, default false | Bu NACE'nin izin verdiği oran bayrakları — birden fazlası TRUE olabilir |
| `kaynak_satir` | JSONB, nullable | Excel'deki orijinal satır (izlenebilirlik) |

**`gecmis_fatura_kalemleri`** (satır 43-59):

| Sütun | Tip | Açıklama |
|---|---|---|
| `id` | Integer, PK, autoincrement | |
| `satici_vkn` | Text, not null | |
| `kalem_adi_normalize` | Text, not null | Küçük harf + tek boşluk (eşleşme anahtarı) |
| `kalem_adi_orijinal` | Text, not null | Görüntüleme için orijinal metin |
| `oran` | Numeric, not null | |
| `istisna_kodu` | Text, nullable | %0/istisna kaynaklıysa dolu |
| `fatura_no` | Text, not null | |
| `fatura_tarihi` | Date, nullable | |
| `kaynak_dosya` | Text, not null | Hangi yükleme/kaynaktan geldiği |

İndeks: `idx_gecmis_eslesme` üzerinde (`satici_vkn`, `kalem_adi_normalize`) —
`gecmis_kontrol_et` sorgusunu hızlandırır.

**Migration 2 — `7ec7f9c705a3` (2026-07-22): race condition düzeltmesi.**

**`islenmis_faturalar`** (satır 30-39):

| Sütun | Tip | Açıklama |
|---|---|---|
| `fatura_no` | Text, PK | Claim/kilit anahtarı |
| `islenme_zamani` | TIMESTAMP(tz), not null, default now() | |

Bu tablo, `faturayi_gecmise_kaydet`'teki "SELECT var mı → yoksa INSERT"
mantığının transaction/lock olmadan çalışıp iki eşzamanlı isteğin aynı
faturayı çift yazabilmesi riskini PostgreSQL'in PRIMARY KEY constraint
garantisiyle atomik olarak kapatır (bkz. §3.4).

### 3.7 Özet: Mcp_mimarisi İç Akışı

```
XML string → ubl_parser.parse_ubl_invoice_from_string() → Fatura
    → kalem_nace_esleme.satir_bazli_kontrol_et(fatura, SaticiNaceBilgisi, NaceOranTablosu)
        → (iç çağrı) nace_kural_kontrolu mantığı, çoklu-NACE havuzuna genelleştirilmiş
        → GENEL_ISTISNA_KODLARI kontrolü (istisna varsa uygun'a çevir)
    → FaturaSatirBazliSonuc (genel_karar: uygun / insan_incelemesi_gerekli)
    → (opsiyonel, ayrı endpoint) gecmis_kontrol.gecmis_kontrol_et() — bilgi notu, karara dokunmaz
    → (coklu-kontrol'de) faturayi_gecmise_kaydet() — outbox faturayı geleceğe emsal olarak kaydet
```

**İlgili dosya yolları:**
- `Mcp_mimarisi/src/efatura_kdv/api.py`
- `Mcp_mimarisi/src/efatura_kdv/ubl_parser.py`
- `Mcp_mimarisi/src/efatura_kdv/nace_kural_kontrolu.py`
- `Mcp_mimarisi/src/efatura_kdv/kalem_nace_esleme.py`
- `Mcp_mimarisi/src/efatura_kdv/gecmis_kontrol.py`
- `Mcp_mimarisi/alembic/versions/9846b14dc658_ilk_sema_nace_oranlari_ve_gecmis_fatura_.py`
- `Mcp_mimarisi/alembic/versions/7ec7f9c705a3_islenmis_faturalar_claim_tablosu_race_.py`

---

## 4. `model_eval` — Detaylı Kod Referansı

`model_eval`, ayrı bir servis olarak çalışmaz — `entegrasyon` tarafından
**import** edilen bir Python kütüphanesidir. LLM + RAG (ChromaDB) ile TDHP
muhasebe kaydı tahmini üretir.

### 4.1 `predict_single_invoice()` — Adım Adım Akış (`core/single.py`, satır 180-365)

Bu, `entegrasyon/`'un import ettiği, DB'ye dokunmayan, tek fatura için
senkron tahmin fonksiyonudur — sistemin en kritik yolu.

**1. Ayrıştırma:** `parse_invoice_xml_string()` ile ham XML string → invoice
sözlüğü. `convert_to_try=True` ise (varsayılan `False`)
`convert_invoice_to_try()` ile TL'ye çevrilir.

**2. RAG (varsayılan açık):** `rag_common.retrieve_similar()` ile en benzer 3
geçmiş fatura bulunur (önce aynı VKN, sonra genel benzerlik),
`format_few_shot_block()` ile prompt bloğuna çevrilir.

**3. Prompt inşası:** `build_user_prompt()` — tevkifat/iade/ihraç-kayıtlı
hint'leri (hepsi varsayılan açık) + RAG bloğu eklenir.

**4. Ana LLM çağrısı:** `call_model()`. Hata olursa `entries=[]`,
`error=<mesaj>` ile hemen döner — **güvenlik kontrolü:** hiçbir
fallback/tahmin uydurulmaz.

**5. JSON parse:** `parse_model_output()`. Başarısızsa yine `entries=[]` +
`error` ile döner.

**6. Normalize:** `_normalize_entries()` — `amount` alanı KORUNUR
(`score_entries`'in aksine), `code3`/`dc` normalize edilir, geçersiz girdiler
atlanır, Borç=Alacak toplamı `balanced` olarak hesaplanır.

**7. Self-correct (varsayılan açık, sadece Ollama):**
   - Dengesizse (`not balanced`) → `build_balance_correction_request()` ile
     düzeltme isteği.
   - Dengeliyse ama RAG'a güçlü bir emsal (`distance < 0.15`) düştüyse ve
     model ona uymadıysa → `strongest_precedent()` +
     `build_precedent_correction_request()` ile hatırlatma.
   - Düzeltme isteği varsa `self_correct_ollama()` ile tek seferlik ikinci
     çağrı; başarılıysa `entry_dicts`/`totals` güncellenir,
     `self_corrected=True`.

**8. Alt kırılım (varsayılan açık) — `_alt_kirilim_uygula()`:**
   - `get_alt_kirilimlar()` ile mizan'dan (şirkete özel Excel) tüm alt
     kırılım seçenekleri çekilir (process-ömrü cache'li).
   - **a) Deterministik fuzzy eşleme** (LLM'den ÖNCE, sadece cari kodlar
     120/320/340/440/159/420): `_cari_fuzzy_esles()` karşı taraf ünvanını
     `difflib.SequenceMatcher` ile mizandaki isimlerle karşılaştırır
     (`_unvan_normalize()` ile Türkçe karakter/kısaltma normalizasyonu).
     Benzerlik ≥%85 ise LLM'e HİÇ SORULMADAN o kod seçilir — **halüsinasyon
     reddi burada yapısal olarak imkânsız** çünkü kod zaten mizanda var olan
     bir seçenekten geliyor.
   - **b) LLM alt kırılım adımı** (fuzzy'nin çözemediği kodlar için):
     `build_alt_kirilim_user_prompt()` ile ikinci bir LLM çağrısı
     (`ALT_KIRILIM_SYSTEM_PROMPT`, "listede olmayan bir alt kod UYDURMA").
     **1 kez otomatik retry** (ilk deneme hata verirse veya hiç geçerli
     seçim yoksa). Dönen her seçim `gecerli_alt_kodlar` kümesine karşı
     DOĞRULANIR — mizanda olmayan bir kod LLM tarafından üretilirse
     **sessizce reddedilir**, 3 haneli kodda kalınır (halüsinasyon reddi #2).
   - **c) KDV oran düzeltmesi:** `_kdv_oranini_duzelt()` — seçilen KDV alt
     kodunun oranı faturadaki gerçek KDV oranıyla çelişiyorsa, aynı tür
     grubu içinde (`391.02` gibi) doğru orana deterministik çevrilir; tür
     LLM'in seçimi olarak korunur.
   - **Hata toleransı:** Bu adımın tamamı (LLM hatası, parse hatası, mizan
     boş) başarısız olursa entry'ler 3 haneli olarak DEĞİŞMEDEN döner —
     `result["error"]` etkilenmez, ana tahmin başarısız sayılmaz.
   - Cari kod 3 haneli kalırsa (`_entry_dicts_uygula`) `uyari` alanı
     eklenir: "karşı taraf mizanda bulunamadı".

**9. Sonuç:** `entries` (her biri `account_code`, `dc`, `amount`, opsiyonel
`account_description`/`secim_kaynagi`/`uyari`), `balanced`,
`borc_toplam`/`alacak_toplam`, `self_corrected`, `raw_response`,
`error=None`.

### 4.2 `core/parsing.py` (352 satır)

**Ne yapar:** Fatura ayrıştırma (JSON ground-truth'lu ve ham UBL XML) +
sayısal alan normalizasyonu.

**Girdi/Çıktı:**
- `parse_invoice(path)`: Archive2/jsons formatındaki JSON dosyası → standart
  sözlük (`header`, `taxes`, `lines`, `notes`, `gt_pairs`,
  `has_ground_truth=True`).
- `parse_invoice_xml(path)` / `parse_invoice_xml_string(xml_text)`: ham
  UBL-TR XML (dosya ya da bellek string'i) → aynı şekilli sözlük ama
  `gt_pairs=set()`, `has_ground_truth=False`.

**Ana fonksiyonlar:**
- `to_float()` (satır 16-51): TR (`1.234,56`) ve EN (`1,234.56`)
  formatlarını, hangi ayracın son geçtiğine bakarak ayırt eder — modelin
  ürettiği serbest metin `amount` alanı için.
- `normalize_dc()` / `normalize_code3()`: model çıktısındaki serbest
  yön/kod metnini standardize eder ("Borç"/"D"/"debit" → `"Borc"`; regex ile
  ilk 3 haneli sayıyı yakalar).
- `_parse_invoice_xml_tree()` (satır 134-291): asıl XML ayrıştırma gövdesi,
  hem dosya hem string modu paylaşır.
  - **Yön tespiti** (173-196): `own_vkn` alıcıda ise inbox, satıcıda ise
    outbox; hiçbirinde değilse `direction_uncertain=True` işaretlenir +
    stderr uyarısı basılır (varsayılan olarak inbox sayılır ama YANLIŞ
    olabileceği belirtilir).
  - **Karşı taraf ünvanı** (198-224): ihracat istisnası —
    `BuyerCustomerParty` varsa (gerçek yurt dışı alıcı) önce oradan, yoksa
    `PartyLegalEntity/RegistrationName` → `PartyName/Name` sırasıyla okunur
    (2026-07-27 düzeltmesi, 112/1933 faturayı etkiledi).
  - **Kur bilgisi** (159-167): `cac:PricingExchangeRate/CalculationRate`
    sadece bilgi amaçlı okunur, otomatik çevrim YAPILMAZ.
  - Vergiler: normal KDV (`cac:TaxTotal`) ve tevkifat/stopaj
    (`cac:WithholdingTaxTotal`) AYRI XML elemanlarından, ikisi de aynı
    `taxes[]` listesine eklenir.
- `convert_invoice_to_try()` (294-343): SADECE kullanıcı açıkça isterse
  çağrılır, XML'in kendi kur oranıyla tüm parasal alanları TL'ye çevirir,
  orijinali mutate etmez; kur bilgisi yoksa `ValueError`.

### 4.3 `core/prompting.py` (325 satır)

**Ne yapar:** LLM'e gidecek system/user prompt'larını ve deterministik
muhasebe ipuçlarını (hint) inşa eder.

**Ana fonksiyonlar:**
- `build_glossary_system_prompt()`: `--with-glossary` modu için
  `TDHP_GLOSSARY`'yi system prompt'a ekler (varsayılan KAPALI — amaç
  modelin kendi bilgisini ölçmek).
- `compute_iade_hint(invoice)` (19-69): IADE faturalarında ters kayıt yönünü
  ve KDV kodunu (391 alıştan-iade / 191 satıştan-iade) önceden hesaplar;
  yalnızca `invoice_type=="IADE"` ise tetiklenir.
- `compute_ihrac_kayitli_hint(invoice)` (75-111): istisna kodu 701-704 ise
  KDV'nin 192 (Borç)/391 (Alacak) ile tecil-terkin netlemesini hesaplar.
- `compute_tevkifat_hint(invoice)` (114-180): yöne göre FARKLI hesap seti
  önerir (inbox: 191 tam KDV Borç / 360 tevkifat Alacak / 320 net Alacak;
  outbox: 391 SADECE net Alacak / 120 net Borç) — kullanıcı onaylı iki
  gerçek kayıtla doğrulanmış.
- `build_direction_text()` (183-203): IADE faturalarda normal alış/satış
  çerçevesinin YANILTICI olduğunu düzeltir (outbox+IADE = "biz tedarikçiye
  iade ediyoruz", "biz satıcıyız" değil).
- `build_alt_kirilim_user_prompt()` (227-255): alt kırılım (muavin hesap)
  seçimi için ikinci LLM çağrısının prompt'unu kurar — sadece ilgili
  kodların seçenekleri gösterilir.
- `build_user_prompt()` (258-325): tüm blokları (yön metni, satırlar,
  vergiler, notlar, hint'ler, RAG bloğu) birleştirip nihai kullanıcı
  prompt'unu üretir; sonunda "kur çevirimi yapma, faturanın kendi para
  biriminde kal" talimatı sabit olarak eklenir.

**Hint fonksiyonları neden var:** Üçü de ortak mantıkla çalışır — **LLM'in
zayıf olduğu aritmetik/kural işlemini Python'da önceden hesaplayıp promptta
"sadece yerleştir" olarak sunar**, LLM'e sadece sınıflandırma (hangi hesap
kodu) kararı bırakılır.
- `compute_tevkifat_hint`: bu hint tek başına balanced oranını %9.5→%95.1'e
  çıkardı — sorun modelin kavramsal bilgisi değil aritmetiği.
- `compute_iade_hint`: IADE doğruluğu %0→%70'e çıktı; kök neden "biz
  satıcıyız/alıcıyız" çerçevesinin IADE'de ters kayıt yönüyle çelişmesiydi.
- `compute_ihrac_kayitli_hint`: diğer ikisinden farklı olarak henüz n>1
  deneyle ölçülmedi, sadece kullanıcı onaylı bir kural olarak eklendi.

### 4.4 `core/providers.py` (251 satır)

**Ne yapar:** Model spec ayrıştırma + 5 farklı sağlayıcıya
(Ollama/OpenAI/Anthropic/Google/OpenAI-uyumlu) HTTP çağrısı.

**Ana fonksiyonlar:**
- `parse_model_spec(spec, default_ollama_host)`: `"ollama:model"`,
  `"openai:model"`, `"openai-compat:url|model|API_KEY_ENV"` gibi string'leri
  dict spec'e çevirir; önek yoksa/tanınmıyorsa Ollama sayılır (geriye dönük
  uyumluluk).
- `call_ollama_messages()` / `call_ollama()`: Ollama `/api/chat`'e istek,
  `PERMANENT_HTTP_ERRORS` (404/403/401) için retry YAPMAZ (zaman kaybı), 429
  için `Retry-After` header'ına göre bekler, diğer hatalarda exponential
  backoff ile 3 deneme.
- `call_openai_style()`: OpenAI-uyumlu şema konuşan her servis için ortak
  çağrı; `response_format=json_object` 400 dönerse otomatik olarak JSON modu
  kapatılıp tekrar denenir (bazı 3. parti servisler desteklemiyor).
- `call_openai/call_anthropic/call_google`: her biri kendi API key env
  var'ını okur, yoksa hata mesajıyla döner (exception fırlatmaz).
- `build_balance_correction_request()` / `build_correction_messages()` /
  `self_correct_ollama()`: dengesiz cevap için düzeltme mesajı inşa edip
  modele ikinci şans veren multi-turn çağrı.
- `call_model(spec, ...)`: dispatch fonksiyonu, provider'a göre doğru
  `call_*`'ı çağırır.

### 4.5 `core/runner.py` (170 satır)

**Ne yapar:** Tek bir model spec'i için TOPLU fatura kümesini eşzamanlı
(`ThreadPoolExecutor`) işleyip PostgreSQL'e yazar. `single.py::
predict_single_invoice`'in çoklu-fatura karşılığı.

**Ana akış (`run_model`, 17-170):**
1. `result_label()` ile deney kolu etiketi kurulur (`+glossary`,
   `+tevkifathint`, vb.).
2. `--overwrite` değilse `load_done_ids()` ile resume — daha önce hatasız
   işlenmiş faturalar atlanır.
3. `--rag` ise `rag_common` lazy-import edilir, `get_collection()`
   process-ömrü singleton döner.
4. Her fatura için `process(inv)`: prompt kurulur → `call_model()` →
   `parse_model_output()` → `score_entries()` (ground-truth varsa) →
   self-correct tetikleyicileri (`balance` veya `precedent_mismatch`) →
   sonuç `append_result()` ile DB'ye INSERT edilir (her insert kendi
   transaction'ı, thread-safe).
5. `has_ground_truth=False` (XML modu) ise `fp_pairs`/`exact_pair_match`
   gibi yanıltıcı karşılaştırma alanları YAZILMAZ, sadece
   `predicted_entries` + `balanced`.

### 4.6 `core/reporting.py` (220 satır) + `core/db.py` (84 satır)

**Ne yapar:** PostgreSQL tabanlı sonuç deposu (`model_eval_sonuclar`
tablosu), resume takibi, özet/rapor üretimi.

- `db.py::get_pool()`: process-ömrü `ThreadedConnectionPool` (min 2, max
  10), ilk çağrıda `CREATE TABLE IF NOT EXISTS` şemayı doğrular.
  `DATABASE_URL` yoksa `RuntimeError`.
- `reporting.py::result_label()`: her deney kolu (glossary/tevkifat-hint/
  iade-hint/self-correct/rag) için ayrı suffix — kolların sonuçları asla
  birbirini ezmez.
- `load_done_ids()`: `DISTINCT ON (invoice_id) ... ORDER BY invoice_id, id
  DESC` ile her fatura için EN SON kaydı esas alır, sadece hatasız olanlar
  "done" sayılır.
- `append_result()`: tek satır INSERT, PostgreSQL'in kendi kilitlemesine
  dayanır (eski dosya-tabanlı `threading.Lock`'un yerini aldı).
- `summarize_model()`: `_latest_records()` üzerinden micro precision/
  recall/F1 (pair ve code bazında), exact-match oranları, balanced oranı, en
  çok kaçırılan/halüsinasyon yapılan kodlar hesaplanır. "Teknik hata"
  (n_hard_errors, API/parse başarısızlığı) ile "kod hatası" (fp+fn, yanlış
  ama üretilmiş kod) AYRI metrikler.

### 4.7 `core/scoring.py` (98 satır)

**Ne yapar:** Model çıktısını JSON'a çevirme + ground-truth'a karşı
skorlama.

- `extract_json_block(text)`: markdown code fence'leri temizler, direkt
  `json.loads` dener, olmazsa `{`...`}` veya `[`...`]` arası en dıştaki
  bloğu bulup tekrar dener (LLM'in ek metin eklediği durumlar için tolerans).
- `parse_model_output(raw_text)`: `{"entries": [...]}` şemasını bekler;
  yoksa dict içindeki ilk list-tipli alanı dener; başarısızsa
  `"json_parse_error"` / `"no_entries_field"` döner.
- `score_entries(gt_pairs, entries)`: `(code3, dc)` çiftleri kümesi olarak
  tp/fp/fn hesaplar, kod-bazında (yöne bakmadan) ayrı bir tp/fp/fn seti daha
  tutar, `exact_pair_match`/`exact_code_match`, `balanced` (Borç=Alacak
  toleransı 0.01), `pred_pairs` döner.

### 4.8 `core/constants.py` (324 satır)

**Ne yapar:** Sabitler — yol/host varsayılanları, UBL namespace'leri,
`SYSTEM_PROMPT`, `TDHP_GLOSSARY` (271 hesap kodu tam listesi).

- `SYSTEM_PROMPT` (33-45) bilinçli olarak hiçbir örnek 3 haneli kod
  içermiyor — eski sürümde örnekler modele önyargı bindiriyordu (770
  örnekte vardı, 730/760 yoktu, model sürekli 770'i halüsinasyon yapıyordu).
- `TDHP_GLOSSARY`: yalnızca `--with-glossary` modunda kullanılır, varsayılan
  akışı etkilemez; ayrıca `upsert_approved_invoice`'da hesap adı doldurmak
  için kullanılır (geçici çözüm, tek-şirket varsayımı).
- `DEFAULT_OWN_VKN = "0460351893"`: şirketin (Akyüzlü) kendi VKN'si,
  inbox/outbox tespiti için.

### 4.9 `core/cli.py` (264 satır)

**Ne yapar:** argparse tanımları + `main()` — toplu değerlendirme/tahmin
komut satırı girişi.

Akış: `--models` parse → `--data-dir`'den fatura yükle (`json`
ground-truth modu ya da `xml` tahmin modu) → `--invoice-type`/
`--sample-size` filtreleri → `--dry-run` ise sadece prompt yazdırıp çık →
`--model-parallelism` ile tek/çoklu model paralel çalıştırma (`run_model()`)
→ sonuçta `xml` modunda sadece "N fatura tahmin edildi" mesajı (skor YOK),
`json` modunda `print_summary_table()`.

### 4.10 `rag_common.py` — ChromaDB Kullanımı

- **`get_collection()`** (67-76): `(persist_dir, embed_model, ollama_host)`
  anahtarına göre process-ömrü singleton — aynı SQLite tabanlı ChromaDB
  dizinine birden fazla `PersistentClient`'ın aynı anda bağlanması "Could
  not connect to tenant" hatasına yol açıyordu, cache bunu önler.
- **`retrieve_similar()`** (188-213): önce aynı VKN'nin geçmişinden arar
  (`where={"vkn": vkn}`), yetmezse genel benzerlikle k'ya tamamlar; kendi
  invoice_id'sini hariç tutar, mesafeye göre sıralar.
- **`strongest_precedent()`** (274-281): mesafesi
  `STRONG_MATCH_MAX_DISTANCE=0.15` altındaki en yakın emsali döner (yoksa
  `None`) — self-correct'in precedent-mismatch tetikleyicisi için.
- **`upsert_approved_invoice()`** (140-186): kullanıcının arayüzde
  onayladığı bir LLM tahminini RAG koleksiyonuna ekler/günceller —
  `build_vector_db.py`'nin "sadece ground-truth indeksle" kuralını
  genişletir, idempotent (`invoice_id` ile upsert). Hesap adları
  `TDHP_GLOSSARY`'den dolduruluyor (geçici, tek-şirket varsayımı).
- **`format_few_shot_block()`** (236-271): benzer faturaları kademeli
  dille etiketler — `[GÜÇLÜ EŞLEŞME]` (aynı kodu kullanması istenir) vs
  `[referans]` (sadece ilham) — çünkü tek-düzey "referans amaçlıdır" dili
  modelin doğru emsali görse bile görmezden gelmesine yol açıyordu (16
  hatanın 10'u).

### 4.11 `core/mizan.py` — Şirkete Özel Alt Kırılım Listesi

`get_alt_kirilimlar(mizan_path=None)` (satır 44-69): `model_eval/exceller/
mizan.xlsx`'i `openpyxl` ile okur (`_mizan_satirlarini_oku`, satır 7'den
itibaren, A=HESAP KODU/B=HESAP ADI), yalnızca 3-seviyeli kodları
(`XXX.YY.ZZZZZ`) alıp 3 haneli ana koda göre gruplar:
`{"191": [("191.05.00005", "%20 5/10 Tevkifatli KDV"), ...]}`. Process-ömrü
`threading.Lock` korumalı cache (`rag_common.get_collection` ile aynı
desen) — Excel her istekte yeniden okunmaz. `TDHP_GLOSSARY`'den farkı: bu
liste TEK bir şirkete (Akyüzlü) özeldir, genelleştirilemez.

### 4.12 `core/disa_aktarim.py` — İç Şema ↔ Dış Şema Dönüşümü

`kayitlari_disa_aktar()` (satır 92-127), iç `entries[]` (`account_code`,
`dc="Borc"/"Alacak"`, `amount`) listesini dış ekibin `records[]` şemasına
çevirir:

- `account_code_type`: `_hesap_turu()` — ana kod `CARI_HESAP_KODLARI`'nda mı
  diye bakılır (`"C"` cari / `"G"` genel), **ayrı bir paralel liste
  TUTULMAZ**, mevcut sınıflandırmadan türetilir.
- `debit_credit`: `DC_DIS_KARSILIGI = {"Borc": "BORÇ", "Alacak": "ALACAK"}`
  ile büyük harfli Türkçe karşılığa çevrilir; iç tarafta `"Borc"/"Alacak"`
  AYNEN kalır (205 test + DB + RAG buna bağlı).
- `account_code_reason`: **deterministik üretilir, LLM'e sorulmaz**
  (`_gerekce_uret`, satır 40-89) — `entry["secim_kaynagi"]` izine göre
  (fuzzy/llm/3-hanede-kalma) insan-okur bir cümle kurulur; post-hoc
  rasyonalizasyon riskinden kaçınmak için bilinçli tercih.
- `faturayi_disa_aktar()` (satır 152-178): tam zarfı (`currency`,
  `customer`, `supplier`, `records`, `success`, vb.) kurar; iç şemayı
  değiştirmez, sadece görünüm üretir.

### 4.13 Genel Gözlem: Güvenlik/Doğruluk Disiplini Örüntüsü

Tüm pipeline'da tekrar eden bir desen var: **her ek karar noktasında ya
deterministik hesaplama (hint'ler, KDV oran düzeltmesi, fuzzy eşleme)
LLM'in yerini alır, ya da LLM'in çıktısı bilinen bir referans kümesine
(mizan, TDHP_GLOSSARY) karşı doğrulanıp geçersizse sessizce güvenli tarafa
(3 haneli kod) düşülür.** Halüsinasyon reddi hiçbir yerde "modele güven" ile
değil, whitelisting (`gecerli_alt_kodlar`, `TDHP_GLOSSARY`) ile sağlanıyor.

**Tek zayıf nokta** (model_eval/CLAUDE.md'de de not edilmiş):
`_normalize_entries` LLM'in verdiği 3 haneli kodu `TDHP_GLOSSARY`'ye karşı
doğrulamıyor ve tutarı faturanın `payable` değeriyle karşılaştırmıyor — ana
kod seviyesinde whitelisting yok, sadece alt kırılım seviyesinde var.

**İlgili dosya yolları:**
- `model_eval/core/{parsing,prompting,providers,runner,reporting,db,
  scoring,single,mizan,disa_aktarim,constants,cli}.py`
- `model_eval/rag_common.py`

---

## 5. `entegrasyon` — Detaylı Kod Referansı

`entegrasyon/`, `Mcp_mimarisi` (HTTP, port 8000) ile `model_eval`'ı (import)
birleştiren, port 8100'de çalışan FastAPI orkestrasyon katmanıdır.

### 5.1 `app.py` (464 satır) — Ana FastAPI uygulaması

**Ne yapar:** 4 endpoint tanımlar (`/`, `/durum`, `/fatura/onayla`,
`/fatura/isle`), Pydantic şemalarını (istek/cevap) tutar, yön tespiti → ön
filtre → kur onayı → TDHP tahmini akışını orkestre eder.

**Girdi/Çıktı:** İstemciden ham UBL-TR XML + own_vkn (`satici_vkn` adında
ama artık "kendi VKN'imiz" anlamında, satır 85-88) alır; `FaturaIsleCevabi`
zarfı döner.

**Ana fonksiyonlar/endpoint'ler:**
- `GET /` (satır 204-206) — `static/index.html`'i döner (test arayüzü).
- `GET /durum` (satır 209-215) — `model_eval_hazir_mi()` çağırıp
  `{model_eval_hazir, model_eval_mesaj}` döner; model_eval tarafı henüz
  eklenmemişse arayüz sessizce mock veri göstermez.
- `POST /fatura/onayla` (satır 218-245) — Kullanıcı "bu doğru, kaydet"
  dediğinde çağrılır. Sunucu **tekrar LLM'e gitmez**: istekteki
  `tdhp_tahmini` aynen `faturayi_onayla()`'ya geçirilir. `model_eval` hazır
  değilse `NotImplementedError` → HTTP 501'e çevrilir (satır 237-239).
  Başarılıysa `{kaydedildi: true, mesaj: "..."}` döner.
- `POST /fatura/isle` (satır 248-398) — asıl orkestrasyon; ayrıntı §5.6'da.
- `_kur_onayi_gerekiyor_mu()` (satır 401-434) — yardımcı fonksiyon, hem
  inbox hem outbox dalında çağrılır.
- `_log_model_eval_cevabi()` (satır 437-463) — model_eval cevabını loglar,
  `dis_sema`'yı JSON olarak terminale basar (satır 454-459).

**Önemli tasarım notları koddan:**
- v2 API (satır 75-79) tasarlandı ama **iptal edildi** (2026-07-28 kullanıcı
  kararı) — `v2_api.py` router'ı `app.py`'ye hiç `include_router`
  edilmemiş, kod repoda duruyor ama bağlı değil.
- `FaturaOnaylaIstegi.tdhp_tahmini` alanı (satır 169-171) — istemcinin
  `/fatura/isle` cevabından aynen geri gönderdiği tahmin; sunucu buna
  güvenir, yeniden hesaplamaz (bu, "istemci verisini doğrulamıyor"
  zafiyetinin kaynağı, bkz. §6).
- `ET.ParseError` özel olarak yakalanıp 400'e çevriliyor (satır 263-271) —
  2026-07-27 düzeltmesi, önceden 500 dönüyordu.

### 5.2 `yon_tespiti.py` (42 satır) — Yön tespiti

**Ne yapar:** Faturanın `own_vkn`'e göre inbox mı outbox mı olduğunu
belirler; `Mcp_mimarisi` çağrılmadan önce çalışır.

**Girdi/Çıktı:** `fatura_xml: str`, `own_vkn: str` → `"inbox"` ya da
`"outbox"` string'i.

**Ana fonksiyonlar:**
- `fatura_yonunu_tespit_et()` (satır 28-41) — Kendi XML parser'ı **yazmaz**;
  `model_eval_yolunu_ekle()` ile `sys.path`'e model_eval'ı ekleyip
  `core.parsing.parse_invoice_xml_string(fatura_xml, own_vkn=own_vkn)`'i
  çağırır. Dönen `invoice["direction"]`'ı kullanır.
- `FaturaYonuBelirsizHatasi` (satır 19-25) — `parse_invoice_xml_string`
  `direction_uncertain=True` işaretlediğinde (own_vkn ne satıcı ne alıcı
  VKN'sine eşit) fırlatılır. Alt modül sessizce "inbox" varsayardı;
  entegrasyon katmanı bunu **açıkça** hataya çevirir çünkü bu,
  `Mcp_mimarisi`'nin çağrılıp çağrılmayacağını belirleyen kritik dallanma
  noktasıdır (satır 23-25).

Karşılaştırma mantığı: `AccountingSupplierParty` VKN'si `own_vkn`'e eşitse
outbox, `AccountingCustomerParty` VKN'si eşitse inbox — ama bu
karşılaştırmanın kendisi `model_eval/core/parsing.py`'de, entegrasyon sadece
sonucu tüketir.

### 5.3 `mcp_mimarisi_istemcisi.py` (68 satır) — Mcp_mimarisi HTTP istemcisi

**Ne yapar:** `Mcp_mimarisi`'nin gerçek FastAPI'sine (ayrı süreç, port 8000)
HTTP isteği atar. `Mcp_mimarisi`'nin koduna **hiç dokunmaz/import etmez**.

**Girdi/Çıktı:** `fatura_kontrol_et(fatura_xml, satici_vkn,
satici_nace_kodlari)` → `Mcp_mimarisi`'nin `FaturaKontrolCevabi` şemasıyla
birebir aynı sözlük.

**Ana fonksiyonlar:**
- `fatura_kontrol_et()` (satır 29-55) —
  `httpx.post(f"{MCP_MIMARISI_BASE_URL}/fatura/kontrol-et", json={...},
  timeout=30.0)`. Üç hata yolu ayrı ele alınır:
  - `httpx.RequestError` (ağ/timeout) → `McpMimarisiErisilemezHatasi` (satır
    44-47) — sessizce "uygun" ya da "insan incelemesi gerekli" varsayılmaz,
    açık hata.
  - HTTP 400 → `Mcp_mimarisi`'nin kendi `detail` mesajı `ValueError` olarak
    yukarı taşınır (satır 49-53, bozuk XML/VKN uyuşmazlığı).
  - Diğer hata kodları → `resp.raise_for_status()` ile fırlatılır.
- `saglik_kontrolu()` (satır 58-67) — `GET /saglik`, kullanılmıyor gibi
  görünüyor (app.py'de çağrılmıyor), muhtemelen manuel/gelecekteki kullanım
  için.
- `MCP_MIMARISI_BASE_URL` env var'ı (satır 17), varsayılan
  `http://localhost:8000`.

### 5.4 `model_eval_koprusu.py` (205 satır) — model_eval köprüsü

**Ne yapar:** `model_eval`'ı **import** ile çağırır (ayrı süreç değil — bu
asimetri kasıtlı, `Mcp_mimarisi` ↔ `model_eval` arasındaki HTTP kuralı
burada geçerli değil çünkü entegrasyon zaten model_eval'ın "çalışma
alanının parçası" sayılıyor, satır 4-8).

**Ana fonksiyonlar:**
- `model_eval_hazir_mi()` (satır 40-53) — `core/single.py` dosyasının
  varlığını ve `predict_single_invoice`'in import edilebilirliğini kontrol
  eder; import hatasını yutmaz, gerçek eksik dosya/fonksiyon adını döner.
- `tdhp_tahmini_yap()` (satır 56-131) — asıl tahmin fonksiyonu:
  1. `model_eval_hazir_mi()` kontrolü, değilse `NotImplementedError`.
  2. `core.single.predict_single_invoice(fatura_xml, own_vkn=own_vkn,
     ollama_host=DEFAULT_MODEL_EVAL_OLLAMA_HOST,
     convert_to_try=convert_to_try)` çağrılır.
  3. **SSH tünel / Ollama host ayrımı** (satır 30-37, 88-95) — en kritik
     detay:
     - `DEFAULT_MODEL_EVAL_OLLAMA_HOST` (`MODEL_EVAL_OLLAMA_HOST` env
       var'ından, varsayılan `http://localhost:11435`) → **LLM tahmini
       için**, `predict_single_invoice`'e `ollama_host=` olarak geçirilir.
       Bulut modeli (`gemma4:31b-cloud`) yerelde yok, SSH tüneli (`ssh -N
       -L 11435:localhost:11434 ...`) üzerinden `unlem-gx10-01` sunucusuna
       gider.
     - RAG embedding (`embeddinggemma`) için **ayrı** bir host env var'ı
       (`OLLAMA_HOST`) **kasıtlı olarak buraya geçirilmez** —
       `rag_ollama_host=None` bırakılır, `rag_common`'ın kendi yerel
       varsayılanına (11434) düşer. Gerekçe: embeddinggemma yerelde zaten
       kurulu, tünelden göndermek "Connection reset by peer" hatasına yol
       açmıştı (gerçek testte ölçüldü, satır 88-95).
  4. Dış ekip şeması üretimi (satır 103-130): `sonuc["records"] =
     kayitlari_disa_aktar(sonuc)`, sonra `parse_invoice_xml_string` ile
     fatura **yeniden ayrıştırılır** (predict_single_invoice üst
     bilgileri taşımadığı için) ve `faturayi_disa_aktar()` ile `dis_sema`
     üretilir. `convert_to_try=True` ise zarf da TL'ye çevrilir (satır
     117-124 — 2026-07-27 düzeltmesi, önceden 53 kat tutarsızlık
     bulunmuştu: records TL, zarf EUR kalıyordu). Zarf üretimi başarısız
     olursa (`except Exception`, satır 126) sadece uyarı loglanır, ana
     `records[]` etkilenmez.
- `faturayi_onayla()` (satır 134-186) — `/fatura/onayla`'nın arkasındaki
  fonksiyon, **iki yere yazar**:
  1. **PostgreSQL** — `core.reporting.append_result("entegrasyon_onaylandi",
     kayit)`, `model_eval_sonuclar` tablosuna. Aynı fatura tekrar
     onaylanırsa yeniden kontrol yapılmaz, her onay ayrı satır birikir
     (kullanıcı kararı, satır 140-143).
  2. **ChromaDB RAG koleksiyonu** —
     `rag_common.upsert_approved_invoice(collection, invoice, entries)`.
     `invoice_id` ile **upsert** (PostgreSQL'in aksine burada çoğalma yok,
     güncellenir). Bu, normalde sadece "Archive2/jsons ground-truth"unu
     indeksleyen kurala bilinçli bir istisna (satır 147-152).
- `fatura_kur_bilgisi()` (satır 188-204) — faturanın `currency`/
  `exchange_rate`/`exchange_target_currency` bilgisini, TDHP tahminine
  geçmeden önce kontrol için döner; kendi parser yazmaz,
  `parse_invoice_xml_string`'i kullanır.

### 5.5 `model_eval_yolu.py` (25 satır) — sys.path yardımcısı

**Ne yapar:** `model_eval` bir pip paketi olmadığı için (kardeş klasör),
`core.*` import edilmeden önce dizininin `sys.path`'e eklenmesi gerekir. Bu,
önceden üç yerde ayrı ayrı tekrarlanan bir desendi, 2026-07-23'te tek
kaynağa çekildi.

**Ana fonksiyonlar:**
- `MODEL_EVAL_DIR = Path(__file__).resolve().parent.parent / "model_eval"`
  (satır 16) — `entegrasyon/`'un **kardeşi** olarak `model_eval/`'ı bulur.
  Bu, kök `System/CLAUDE.md`'deki "değişmez kural 1"in (entegrasyon ve
  model_eval aynı üst dizinde kardeş kalmalı) doğrudan kod karşılığıdır —
  klasörler ayrılırsa bu satır kırılır.
- `model_eval_yolunu_ekle()` (satır 19-24) — idempotent: `sys.path`'te
  zaten yoksa başına ekler.

### 5.6 `/fatura/isle` — Adım Adım Akış Diyagramı

```
POST /fatura/isle {fatura_xml, satici_vkn(own_vkn), satici_nace_kodlari, onay, kur_secimi}
  │
  ├─[1/5] İSTEK LOGLANIR (own_vkn, nace, xml_boyutu, onay)             app.py:252-255
  │
  ├─[2/5] YÖN TESPİTİ — fatura_yonunu_tespit_et(xml, own_vkn)          app.py:259
  │        │                                                            yon_tespiti.py:28
  │        ├─ ET.ParseError → HTTP 400 "Geçersiz XML"                  app.py:263-271
  │        └─ FaturaYonuBelirsizHatasi → HTTP 400                      app.py:260-262
  │
  ├─ yon == "inbox" ─────────────────────────────────────────────┐
  │   [3/5] ÖN FİLTRE ATLANDI (Mcp_mimarisi hiç çağrılmaz)        │  app.py:279
  │   [4/5] model_eval_hazir_mi() kontrolü                        │  app.py:281
  │        └─ değilse → asama="model_eval_hazir_degil", DUR       │  app.py:282-287
  │   _kur_onayi_gerekiyor_mu() — kur bilgisi var + kur_secimi    │  app.py:289
  │   yoksa → asama="kur_onayi_bekliyor", DUR (kullanıcıya sor)   │  app.py:401-434
  │   [4/5] tdhp_tahmini_yap(xml, own_vkn, convert_to_try=...)    │  app.py:296
  │        └─ core.single.predict_single_invoice(...) (RAG+LLM)  │  model_eval_koprusu.py:56
  │   [5/5] asama="tdhp_tahmini_tamamlandi" DÖN                   │  app.py:306-310
  │                                                                 │
  └─ yon == "outbox" ──────────────────────────────────────────────┘
      │
      [3/5] Mcp_mimarisi POST /fatura/kontrol-et                      app.py:313-325
           │                                                            mcp_mimarisi_istemcisi.py:29
           ├─ McpMimarisiErisilemezHatasi → HTTP 502                   app.py:319-321
           └─ ValueError (400 bozuk XML/VKN) → HTTP 400                app.py:322-325
      │
      genel_karar = on_filtre["genel_karar"]                          app.py:327
      devam_etsin = (genel_karar=="uygun") OR
                    (genel_karar=="insan_incelemesi_gerekli" AND onay==True)
                                                                        app.py:334-336
      │
      ├─ devam_etsin == False ─────────────────────────────────
      │    [4/5] asama="on_filtre_insan_incelemesi_bekliyor" DUR      app.py:343-352
      │         (kullanıcı onay=true ile tekrar göndermeli)
      │
      └─ devam_etsin == True ──────────────────────────────────
           [5/5] model_eval_hazir_mi() kontrolü                        app.py:359
                └─ değilse → asama="model_eval_hazir_degil", DUR       app.py:360-369
           _kur_onayi_gerekiyor_mu() — kur onayı yoksa DUR             app.py:371-373
           [5/5] tdhp_tahmini_yap(xml, own_vkn, convert_to_try=...)    app.py:378
           asama="tdhp_tahmini_tamamlandi" DÖN                         app.py:393-398
```

Her iki dalda da **kur onayı kontrolü** (`_kur_onayi_gerekiyor_mu`)
model_eval çağrısından hemen önce, ayrı bir "dur ve sor" noktası olarak
araya girer — fatura yabancı para biriminde ve kur bilgisi taşıyorsa
(`kur_secimi` henüz belirtilmemişse) `asama="kur_onayi_bekliyor"` ile durur,
kullanıcı `"orijinal"` veya `"tl"` seçip isteği tekrar atmalıdır.

**Sonrasında ayrı bir çağrı olarak `/fatura/onayla`:** İstemci
`/fatura/isle` cevabındaki `tdhp_tahmini`'ni aynen geri gönderir; sunucu
LLM'e gitmez, `faturayi_onayla()` PostgreSQL (`model_eval_sonuclar`,
`file_label="entegrasyon_onaylandi"`) + ChromaDB RAG koleksiyonuna (upsert)
yazar.

### 5.7 `is_deposu.py` — v2'nin PostgreSQL iş deposu (ölü kod, v2 ile birlikte)

**Ne yapar:** v2 API için kalıcı iş (job) deposu — `api_jobs` tablosu
(`job_id`, `status`, `request` JSONB, `result`, `error`). Asenkron desende
XML'in tekrar gönderilmemesi için istek gövdesi saklanır. `app.py`'ye bağlı
değil, sadece `v2_api.py` tarafından kullanılıyor (o da bağlı değil).

### 5.8 `v2_api.py` (268 satır) ve `v2_semalar.py` (157 satır) — İptal edilmiş v2 API

**2026-07-27'de tasarlanmış, 2026-07-28'de kullanıcı kararıyla iptal
edilmiş** asenkron API (`POST /api/v1/invoices` → 202 + job_id, `GET
.../{job_id}`, `POST .../{job_id}/approve`). `app.py` bu router'ı **hiç
import/include etmiyor** (app.py:75-79'daki yorum bunu doğruluyor) —
dolayısıyla ölü kod, dış ekibe teslim edilen v1 (`/fatura/isle`)
değişmiyor.

Dikkat çekici bir ayrıntı: `v2_api.py:209`'da `OTOMATIK_ONAY = True` adında
**geçici** bir bayrak var — KDV uyarısı olsa bile insan onayı beklemeden
otomatik devam ediyor, `auto_approved: true` + uyarı ekleyerek. Ancak bu kod
zaten **çalışmıyor** (router bağlı değil), sadece ileride v2 geri
getirilirse dikkat edilmesi gereken bir not.

`v2_semalar.py`, iç şemadan (`dc="Borc"/"Alacak"`,
`account_code_type="C"/"G"`) v2'nin İngilizce şemasına
(`side="debit"/"credit"`, `account_type="receivable"/"general"`) çeviri
yapan saf fonksiyonlar içeriyor — yine kullanılmıyor.

### 5.9 Ek gözlem (çelişki değil, not edilmeye değer)

`model_eval_koprusu.py:167`'de `import rag_common` var — bu modülün
`model_eval/` kökünde olduğu varsayılıyor (sys.path'e eklenen dizinin
doğrudan altında). Bu, statik okuma ile bir varsayımdır; gerçek bir
`/fatura/onayla` çağrısıyla test edilmiş olduğu README.md'deki 2026-07-23
notunda doğrulanır (`AKL2025000000003` faturasıyla hem PostgreSQL hem
ChromaDB doğrulanmış).

**İncelenen dosyalar:**
- `entegrasyon/app.py`
- `entegrasyon/yon_tespiti.py`
- `entegrasyon/mcp_mimarisi_istemcisi.py`
- `entegrasyon/model_eval_koprusu.py`
- `entegrasyon/model_eval_yolu.py`
- `entegrasyon/is_deposu.py`
- `entegrasyon/v2_api.py`
- `entegrasyon/v2_semalar.py`
- `entegrasyon/README.md`

---

## 6. Bileşenler Arası Sözleşmeler

### 6.1 Neden bu mimari (özet gerekçe)

Sistem tek bir sorunu çözmüyor, iki farklı doğa taşıyan sorunu çözüyor ve bu
farklılık her mimari kararın gerekçesi (`mimari.md:20-34`):

- **Sorun 1 — "Bu KDV oranı mevzuata uygun mu?"** Deterministik bir kural
  sorusu (NACE kodu → izin verilen oran havuzu). "Mevzuat uygunluğu
  deterministik bir kural sorusudur, LLM'e sorulmaz" (`mimari.md:33-34`).
- **Sorun 2 — "Bu fatura hangi hesaba, hangi yönde kaydedilir?"** Yorum
  gerektirir, kurala indirgenemez; geçmiş emsal kararlara ihtiyaç duyar.

Bu ayrım, **neden biri HTTP diğeri import** olduğunu doğurur
(`mimari.md:65-86`):
- `Mcp_mimarisi` bağımsız geliştirilen, kendi DB şeması ve yaşam döngüsü
  olan bir servistir; HTTP arkasında olması onu ayrı deploy edilebilir, ayrı
  ekibe açık kılar.
- `model_eval` ise ChromaDB + embedding modeli + LLM istemcileri gibi ağır
  bilimsel bağımlılık taşır. HTTP arkasına koymak her istekte modelin/
  koleksiyonun yeniden yüklenmesi riskini getirirdi; import ile çağrılınca
  ChromaDB koleksiyonu **process ömrü boyunca cache'lenir**
  (`model_eval/CLAUDE.md`'deki 2026-07-22 mimari denetiminde de aynı
  gerekçeyle process-ömrü singleton yapıldığı doğrulanıyor).

Bu asimetri "alt projeler birbirine kod olarak bağlanmaz" kuralını ihlal
etmiyor, çünkü o kural `Mcp_mimarisi` ↔ `model_eval` arasındaki ilişki için
var; `entegrasyon/` üçüncü, bağımsız bir bileşen olup ikisine de kendi
doğasına uygun şekilde bağlanıyor. `entegrasyon/model_eval_koprusu.py:1-9`
docstring'i bunu teyit eder: "model_eval'ın kendi çalışma alanının bir
parçası… entegrasyon iki tarafı bir araya getiren üçüncü bir bileşen."

Bu asimetrinin somut sonucu **değişmez kısıt** haline geliyor: `entegrasyon/`
ve `model_eval/` aynı üst dizinde kardeş kalmalı, çünkü
`entegrasyon/model_eval_yolu.py` bunu varsayarak `sys.path`'e ekleme yapıyor
(`mimari.md:83-85`, kök `System/CLAUDE.md` Değişmez Kural 1 ile birebir
aynı).

### 6.2 Dış ekip sözleşmesi

Kaynak: `entegrasyon/docs/reference/dis-ekip-api-kullanimi.md` (2026-08-05'ten
itibaren `records[]` şema detayını da §3.1'de içeriyor — dış ekibe teslim
edilen tek dosya).

Tek gerçek ihtiyaç `tdhp_tahmini.dis_sema`. `records[]`'in her öğesi **tam 6
alan** taşır:

| Alan | Tip | Not |
|---|---|---|
| `account_code` | string | 3 haneli ya da alt kırılımlı |
| `account_code_type` | `"C"`/`"G"` | Cari ya da genel hesap |
| `account_description` | string | Bilinmiyorsa boş string, **asla `null`** |
| `account_code_reason` | string | **Asla boş** — deterministik üretilir |
| `amount` | number | |
| `debit_credit` | `"BORÇ"`/`"ALACAK"` | Büyük harf Türkçe |

Zarf 9 alan: yukarıdakilere ek `invoice_id`, `issue_date`, `currency`,
`payable_amount`, `customer`/`supplier` (yöne göre yerleşir), `success`,
`file_path` (şu an her zaman `""`).

Sözleşmenin garantisi: iç şema (`entries[]`/`Borc`/`Alacak`) serbestçe
değişebilir, `model_eval/core/disa_aktarim.py` dışındaki hiçbir yer bu
dönüşümü tekrarlamaz — "paralel ikinci liste oluşturma" kuralına (kök
`CLAUDE.md`) doğrudan bağlanıyor. Kimlik doğrulama yok, çağrı
sunucu-sunucu, CORS bilinçli olarak yapılandırılmamış (bkz.
`docs/explanation/guvenlik-durumu-2026-07-27.md`).

### 6.3 PostgreSQL paylaşımı

Tek sunucu (`:5434`), tablolar net sahiplik sınırıyla ayrılmış:

| Tablo | Sahip | Amaç |
|---|---|---|
| `nace_oranlari` | Mcp_mimarisi | Referans veri (NACE → izinli oranlar) |
| `gecmis_fatura_kalemleri` | Mcp_mimarisi | Emsal (geçmiş kalem-oran) |
| `islenmis_faturalar` | Mcp_mimarisi | Race-condition claim tablosu |
| `model_eval_sonuclar` | model_eval | Tahmin + onay denetim izi |

Hiçbiri diğerinin tablosuna dokunmaz (`mimari.md:87-97`, kök
`System/CLAUDE.md` Değişmez Kural 4).

### 6.4 inbox/outbox dallanması (sistem geneli)

Yön kararı tek bir yerde (XML parse, `model_eval/core/parsing.py`) verilir
ve tüm akışı ikiye böler:

- **outbox** → `Mcp_mimarisi` HTTP çağrısı zorunlu, `onay` alanı anlamlı,
  `asama` değerleri arasında `on_filtre_insan_incelemesi_bekliyor` mümkün.
- **inbox** → `Mcp_mimarisi` hiç çağrılmaz, `onay` gereksiz, `asama`
  doğrudan `tdhp_tahmini_tamamlandi`'ye gider.

Gerekçe (`mimari.md:110-122`): başkasının kestiği faturanın mevzuat
sorumluluğu bizde değil. `dis-ekip-api-kullanimi.md:149-158`'deki not, bunun
`entegrasyon/app.py` satır 333-397 ile birebir kod düzeyinde doğrulandığını
belirtiyor.

### 6.5 Docker/supervisord birlikte çalışma

`docker/Dockerfile:4-7` açıkça gerekçelendiriyor — `entegrasyon/model_eval_yolu.py`
`model_eval`'i `../model_eval` kardeş dizini olarak `sys.path`'e eklediği
için iki servis ayrı image'lara bölünemez; üç bileşen (`Mcp_mimarisi`,
`entegrasyon`, `model_eval`) tek image'a kopyalanıp kardeş dizin ilişkisi
korunur, `supervisord` iki HTTP servisini (8000, 8100) aynı container
içinde ayrı process olarak yönetir.

PostgreSQL ve Ollama ise **ayrı servis** olarak `docker/docker-compose.yml`'de
kalır çünkü:
1. Kendi veri kalıcılığı/volume yaşam döngüleri var
   (`efatura-kdv-pgdata`, `efatura-ollama-data`).
2. `app` container'ı yeniden oluşturulduğunda (image güncelleme) bu verinin
   kaybolmaması gerekiyor.
3. Postgres `healthcheck` ile `app`'in `depends_on: condition:
   service_healthy` şartına bağlanmış — sıralı başlatma garantisi.

SSH tüneli (uzak GPU LLM'e) container'a hiç girmiyor — host seviyesinde
systemd servisi, `host.docker.internal` üzerinden `MODEL_EVAL_OLLAMA_HOST`
env var'ıyla erişiliyor (`docker/docker-compose.yml:1-13,70-90`).

**Kaynak belgeler:** `../../mimari.md`, `entegrasyon/docs/reference/
dis-ekip-api-kullanimi.md`, `entegrasyon/app.py:311-390`,
`entegrasyon/model_eval_koprusu.py:1-19`, `../../docker/docker-compose.yml`,
`../../docker/Dockerfile`.

---

## 7. En Kritik 10 Dosya — Özet Tablo

| Dosya | Ne işe yarar | Neden kritik |
|---|---|---|
| `model_eval/core/single.py` | `predict_single_invoice()` — tek fatura için RAG+LLM+alt kırılım tam akışı | `entegrasyon`'un çağırdığı tek fonksiyon; sistemin TDHP tahmin çekirdeği, tüm halüsinasyon-reddi mimarisi burada toplanır |
| `entegrasyon/app.py` | `/fatura/isle` orkestrasyonu — yön tespiti, ön filtre, kur onayı, TDHP tahmini akışını birleştirir | Dış ekibin gördüğü tek giriş noktası; inbox/outbox dallanması ve tüm "dur ve sor" noktaları burada |
| `model_eval/core/disa_aktarim.py` | İç şema (`entries[]`) → dış şema (`records[]`/`dis_sema`) tek yönlü dönüşüm | Dış ekiple olan sözleşmenin TEK üretildiği yer; 205 test + DB + RAG iç şemaya bağlı, burada bozulursa dış ekip kırılır |
| `Mcp_mimarisi/src/efatura_kdv/kalem_nace_esleme.py` | Çoklu NACE oran havuzu + istisna kodu doğrulaması ile kalem bazlı KDV kararı | Ön filtrenin asıl karar mantığı; VKN güvenlik kontrolü de burada (`SaticiVknUyusmazligiHatasi`) |
| `Mcp_mimarisi/src/efatura_kdv/ubl_parser.py` | UBL-TR XML → `Fatura` dataclass, KDV/tevkifat/istisna ayrımı | Mcp_mimarisi'nin girdi kapısı; KDV vs. diğer vergi (Özel İletişim Vergisi vb.) ayrımı burada yanlış olursa tüm kontrol zinciri bozulur |
| `model_eval/core/parsing.py` | Fatura XML/JSON ayrıştırma + **yön tespiti** (inbox/outbox) | Tüm sistemin dallanma kararı (`direction`) burada üretilir; hem `entegrasyon/yon_tespiti.py` hem `model_eval` bunu kullanır |
| `entegrasyon/model_eval_koprusu.py` | model_eval'e import köprüsü; SSH tünel/Ollama host ayrımı; onay akışının PostgreSQL+ChromaDB yazımı | LLM erişiminin (tünel) yanlış yapılandırılması burada sessiz hataya yol açar (`entries=[]` ama `error` dolu) — CLAUDE.md'de "bir kez yaşandı" notu var |
| `model_eval/rag_common.py` | ChromaDB koleksiyon yönetimi, benzer fatura arama, onaylı faturayı RAG'a ekleme | RAG'ın "öğrenen sistem" özelliğinin tamamı burada; process-ömrü singleton deseni, güçlü/zayıf emsal ayrımı |
| `Mcp_mimarisi/src/efatura_kdv/gecmis_kontrol.py` | Emsal kontrolü + race-condition korumalı kalıcı kayıt | Yarış durumu düzeltmesi (`islenmis_faturalar` claim tablosu) burada; yanlış implementasyon çift-sayım riski taşır |
| `entegrasyon/model_eval_yolu.py` | `sys.path`'e `model_eval`'i kardeş dizin olarak ekleyen tek kaynak | Sistemin "değişmez kural 1"inin (entegrasyon/model_eval kardeş kalmalı) doğrudan kod karşılığı; en ufak dizin değişikliği burayı kırar |

---

## Kaynak raporlar

Bu belge, üç bileşenin ayrı ayrı yapılmış detaylı kod analizleri ile
bileşenler-arası akış/sözleşme analizinin birleştirilmesiyle oluşturulmuştur
(2026-07-29). Ham raporlar bu birleştirme sırasında tekrarları giderilerek
yeniden yazılmıştır; dosya:satır referansları korunmuştur.
