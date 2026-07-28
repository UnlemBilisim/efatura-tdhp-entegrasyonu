# UBL-TR E-Fatura XML Yapısı — Gerçek Faturalardan Doğrulanmış Şema

`ubls/` klasöründeki 1828 gerçek e-fatura XML'i (`*-inbox.xml` /
`*-outbox.xml`) incelenerek çıkarıldı (varsayım değil — python3 + ElementTree
ile programatik olarak doğrulandı, bkz. `src/efatura_kdv/ubl_parser.py`).

## Kritik gerçek: XML'de NACE kodu YOKTUR

1828 faturanın hiçbirinde NACE kodu geçmiyor (satıcı/alıcı bloklarında da,
kalemlerde de). NACE, satıcının VKN'sine bağlı **ayrı bir kaynaktan** gelecek
— bu kaynağı kullanıcı ayrıca ekleyecek (bkz. `PROJECT.md`, "sıradaki adım").
Fatura parser'ı NACE alanı döndürmez/beklemez.

## Kök yapı

Kök eleman `<Invoice>` (namespace `urn:oasis:names:specification:ubl:schema:xsd:Invoice-2`,
`cbc:`/`cac:` prefix'leriyle). `ext:UBLExtensions` bloğu dijital imza + bazen
büyük bir embedded XSLT şablonu (base64) taşır — 100KB+ olabilir, fatura
verisiyle ilgisizdir, parser bunu atlar.

Gözlenen alan dağılımı (1828 dosya):
- `cbc:ProfileID`: `TICARIFATURA` (1043), `TEMELFATURA` (686), `IHRACAT` (94), `EARSIVFATURA` (5)
- `cbc:InvoiceTypeCode`: `SATIS` (1612), `ISTISNA` (128), `TEVKIFAT` (45), `IADE` (30), `IHRACKAYITLI` (13)

## Fatura seviyesi alanlar

| Alan | XPath | Not |
|---|---|---|
| Fatura no | `cbc:ID` | |
| UUID | `cbc:UUID` | |
| Düzenleme tarihi | `cbc:IssueDate` | `YYYY-MM-DD` |
| Fatura tipi | `cbc:InvoiceTypeCode` | SATIS/ISTISNA/TEVKIFAT/IADE/IHRACKAYITLI |
| Para birimi | `cbc:DocumentCurrencyCode` | Çoğunlukla TRY, ihracat faturalarında EUR de var |

## Satıcı / Alıcı

`cac:AccountingSupplierParty` / `cac:AccountingCustomerParty` →
`cac:Party/cac:PartyIdentification/cbc:ID[@schemeID=...]`.

`schemeID` dağılımı (satıcı bloklarında, 1828 dosya): `VKN` (1754), `MERSISNO`
(1399), `TICARETSICILNO` (1006), `TCKN` (80 — şahıs firması), `SUBENO` (52),
`MUSTERINO` (9), `BAYINO` (6), `HIZMETNO` (4). **Kimlik anahtarı VKN, yoksa
TCKN.** Unvan: `cac:Party/cac:PartyName/cbc:Name`.

> `cac:PartyTaxScheme/cac:TaxScheme/cbc:Name` bir **vergi dairesi adıdır**
> (ör. "Büyük Mükellefler", "Uluçinar"), NACE veya kategori bilgisi DEĞİLDİR
> — karıştırılmamalı.

## Kalemler (`cac:InvoiceLine`)

| Alan | XPath | Not |
|---|---|---|
| Sıra no | `cbc:ID` | |
| Miktar | `cbc:InvoicedQuantity` (+ `unitCode` attr) | |
| Tutar | `cbc:LineExtensionAmount` | KDV hariç satır tutarı |
| Kalem adı | `cac:Item/cbc:Name` | Serbest metin, muğlak olabilir (bkz. CLAUDE.md) |
| Kalem açıklaması | `cac:Item/cbc:Description` | Bazı faturalarda dolu, bazılarında yok |

### Vergi kırılımı — kritik ayrım

Her `cac:InvoiceLine` (ve ayrıca fatura kökünde) **iki farklı vergi bloğu**
olabilir, ikisi de aynı iç yapıyı (`cac:TaxSubtotal` listesi) kullanır ama
anlamları taban tabana zıttır:

- **`cac:TaxTotal`**: KDV ve (bazı sektörlerde) **KDV dışı başka vergiler**.
  Gerçek örnek (Turkcell faturası): aynı `cac:TaxTotal` içinde 3 ayrı
  `cac:TaxSubtotal` — biri KDV (`TaxTypeCode=0015`, %20), biri Özel İletişim
  Vergisi (`TaxTypeCode=4081`, %10), biri Telsiz Kullanım Taksiti
  (`TaxTypeCode=8006`, %0). **`TaxTypeCode` her zaman kontrol edilmeli** —
  `0015` değilse bu KDV değildir, tevkifat da değildir, tamamen başka bir
  vergi türüdür.
- **`cac:WithholdingTaxTotal`**: Sadece tevkifatlı faturalarda (`InvoiceTypeCode=TEVKIFAT`)
  görülür. `cac:TaxCategory/cac:TaxScheme/cbc:TaxTypeCode` burada gerçek
  tevkifat kodunu taşır (ör. `627` = demir-çelik ürünleri teslimi,
  `cbc:Percent` = tevkifat oranı, ör. `50`).

Her `cac:TaxSubtotal` içinde: `cbc:TaxableAmount` (matrah), `cbc:TaxAmount`
(vergi tutarı), `cbc:Percent` (oran), `cac:TaxCategory/cbc:TaxExemptionReasonCode`
+ `cbc:TaxExemptionReason` (istisna kodu/açıklaması — sadece istisna
durumunda dolu).

> **İstisna kodu her zaman satır seviyesinde olmayabilir.** İhracat
> faturalarında (`InvoiceTypeCode=ISTISNA`) istisna kodu genelde satırlarda
> değil, faturanın **genel** (kök seviyesi) `cac:TaxTotal`'ında görülür (ör.
> istisna kodu `301` = "11/1-a Mal İhracatı"). Faz 1/Faz 2 mantığı hem satır
> hem genel seviyeyi kontrol etmeli.

> **Bazı faturalarda satır seviyesinde HİÇ vergi kırılımı yoktur** — sadece
> genel toplamda (kök `cac:TaxTotal`) birden fazla oran karışık halde
> bulunur, hangi kalemin hangi orana ait olduğu XML'den doğrudan çıkarılamaz
> (gerçek örnek: bazı Turkcell TEMELFATURA'ları — 4 kalem, kalemlerde vergi
> yok, kökte %20/%10/%0 karışık). Bu durumda satır bazında NACE/oran
> eşleştirmesi mümkün olmayabilir — bkz. `PROJECT.md` (açık risk).

## Parser

`src/efatura_kdv/ubl_parser.py` içindeki `parse_ubl_invoice(xml_path)`
fonksiyonu yukarıdaki şemayı okuyup bir `Fatura` dataclass'ı döndürür.
`VergiKirilimi.kdv_mi` property'si (`vergi_tipi_kodu == "0015"`) ile KDV
kırılımları KDV-dışı vergilerden ayrıştırılır; `kdv_kirilimlari` /
`genel_kdv_kirilimlari` property'leri bu filtreyi otomatik uygular.

> ✅ Uygulandı (2026-07-17): Şema `ubls/` altındaki 1828 gerçek faturanın
> tamamı üzerinde programatik olarak doğrulandı (hatasız parse). Kod:
> `src/efatura_kdv/ubl_parser.py`.
