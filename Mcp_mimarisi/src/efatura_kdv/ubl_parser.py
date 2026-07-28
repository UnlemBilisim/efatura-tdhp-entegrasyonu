"""UBL-TR e-fatura XML ayrıştırıcısı.

Gerçek fatura (ubls/*.xml) yapısına dayanır (bkz. docs/reference/ubl-fatura-yapisi.md).
Fatura NACE kodu TAŞIMAZ — NACE, satıcının VKN'sine bağlı ayrı bir kaynaktan
(kullanıcı tarafından eklenecek) gelir; bu modül sadece faturayı ayrıştırır.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass, field, asdict

NS = {
    "cbc": "urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2",
    "cac": "urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2",
}


def _text(node, path):
    """Verilen XPath'teki elemanın metnini döner, yoksa None."""
    found = node.find(path, NS)
    return found.text.strip() if found is not None and found.text else None


def _decimal_text(node, path):
    """_text ile aynı, sonucu float'a çevirir."""
    val = _text(node, path)
    return float(val) if val is not None else None


@dataclass
class Party:
    vkn: str | None = None
    tckn: str | None = None
    unvan: str | None = None


@dataclass
class VergiKirilimi:
    """cac:TaxSubtotal — bir kalemin/faturanın tek bir vergi kırılımı.

    cac:TaxTotal altında KDV dışında Özel İletişim Vergisi (4081), Telsiz
    Kullanım Taksiti (8006) gibi başka vergi türleri de görülebiliyor
    (gerçek Turkcell faturasında doğrulandı) — bu yüzden `vergi_adi` ve
    `vergi_tipi_kodu` her zaman dolu tutulur; çağıran taraf KDV kırılımını
    `vergi_tipi_kodu == "0015"` ile ayırt eder, ismine güvenmez.
    """

    matrah: float | None = None
    tutar: float | None = None
    oran: float | None = None
    vergi_adi: str | None = None  # cac:TaxScheme/cbc:Name
    vergi_tipi_kodu: str | None = None  # cac:TaxScheme/cbc:TaxTypeCode (KDV=0015)
    tevkifat_kodu: str | None = None  # sadece WithholdingTaxTotal bağlamında dolu
    istisna_kodu: str | None = None  # cbc:TaxExemptionReasonCode
    istisna_aciklama: str | None = None  # cbc:TaxExemptionReason

    @property
    def kdv_mi(self) -> bool:
        """Bu kırılım KDV mi (vergi_tipi_kodu 0015) yoksa başka bir vergi türü mü."""
        return self.vergi_tipi_kodu == "0015"


@dataclass
class FaturaKalemi:
    sira_no: str | None = None
    kalem_adi: str | None = None
    aciklama: str | None = None
    miktar: float | None = None
    birim: str | None = None
    tutar: float | None = None
    # cac:TaxTotal kırılımları — KDV dışında (4081, 8006 gibi) vergi
    # türlerini de içerebilir, filtrelemek için kdv_kirilimlari kullan.
    vergi_kirilimlari: list[VergiKirilimi] = field(default_factory=list)
    tevkifat_kirilimlari: list[VergiKirilimi] = field(default_factory=list)

    @property
    def kdv_kirilimlari(self) -> list[VergiKirilimi]:
        """Kalemin vergi kırılımlarından sadece KDV olanları filtreler."""
        return [k for k in self.vergi_kirilimlari if k.kdv_mi]

    @property
    def kdv_oranlari(self) -> list[float]:
        """Kalemin KDV kırılımlarındaki oranların listesi."""
        return [k.oran for k in self.kdv_kirilimlari if k.oran is not None]

    @property
    def istisna_kodlari(self) -> list[str]:
        """Kalemin KDV kırılımlarındaki istisna kodlarının listesi."""
        return [
            k.istisna_kodu
            for k in self.kdv_kirilimlari
            if k.istisna_kodu is not None
        ]


@dataclass
class Fatura:
    fatura_no: str | None = None
    uuid: str | None = None
    duzenleme_tarihi: str | None = None
    profil_id: str | None = None  # TEMELFATURA / TICARIFATURA / IHRACAT / EARSIVFATURA
    fatura_tipi: str | None = None  # SATIS / ISTISNA / TEVKIFAT / IADE / IHRACKAYITLI
    para_birimi: str | None = None
    satici: Party = field(default_factory=Party)
    alici: Party = field(default_factory=Party)
    kalemler: list[FaturaKalemi] = field(default_factory=list)
    genel_vergi_kirilimlari: list[VergiKirilimi] = field(default_factory=list)
    genel_tevkifat_kirilimlari: list[VergiKirilimi] = field(default_factory=list)

    @property
    def genel_kdv_kirilimlari(self) -> list[VergiKirilimi]:
        """Fatura genelindeki vergi kırılımlarından sadece KDV olanları filtreler."""
        return [k for k in self.genel_vergi_kirilimlari if k.kdv_mi]

    def to_dict(self) -> dict:
        """asdict() dataclass property'lerini (kdv_kirilimlari vb.) atlar —
        JSON çıktısında da KDV filtresi görünsün diye ayrıca ekleniyor."""
        d = asdict(self)
        d["genel_kdv_kirilimlari"] = [
            asdict(k) for k in self.genel_kdv_kirilimlari
        ]
        for kalem, kalem_dict in zip(self.kalemler, d["kalemler"]):
            kalem_dict["kdv_kirilimlari"] = [
                asdict(k) for k in kalem.kdv_kirilimlari
            ]
            kalem_dict["kdv_oranlari"] = kalem.kdv_oranlari
            kalem_dict["istisna_kodlari"] = kalem.istisna_kodlari
        return d


def _parse_party(node) -> Party:
    """AccountingSupplierParty/AccountingCustomerParty düğümünden VKN/TCKN/unvan çıkarır."""
    party = Party()
    for pid in node.findall("cac:Party/cac:PartyIdentification", NS):
        id_node = pid.find("cbc:ID", NS)
        if id_node is None:
            continue
        scheme = id_node.get("schemeID")
        value = (id_node.text or "").strip() or None
        if scheme == "VKN" and value:
            party.vkn = value
        elif scheme == "TCKN" and value:
            party.tckn = value
    party.unvan = _text(node, "cac:Party/cac:PartyName/cbc:Name")
    return party


def _parse_tax_subtotal(node, *, tevkifat_baglami: bool) -> VergiKirilimi:
    """Tek bir TaxSubtotal düğümünü VergiKirilimi'ne ayrıştırır."""
    kirilim = VergiKirilimi(
        matrah=_decimal_text(node, "cbc:TaxableAmount"),
        tutar=_decimal_text(node, "cbc:TaxAmount"),
        oran=_decimal_text(node, "cbc:Percent"),
        vergi_adi=_text(node, "cac:TaxCategory/cac:TaxScheme/cbc:Name"),
        vergi_tipi_kodu=_text(
            node, "cac:TaxCategory/cac:TaxScheme/cbc:TaxTypeCode"
        ),
        istisna_kodu=_text(node, "cac:TaxCategory/cbc:TaxExemptionReasonCode"),
        istisna_aciklama=_text(node, "cac:TaxCategory/cbc:TaxExemptionReason"),
    )
    # Tevkifat kodu SADECE cac:WithholdingTaxTotal bağlamında anlamlıdır.
    # cac:TaxTotal altında aynı TaxTypeCode alanı KDV dışında Özel İletişim
    # Vergisi (4081), Telsiz Kullanım Taksiti (8006) gibi tamamen farklı
    # vergi türlerini de taşıyabiliyor (gerçek Turkcell faturasında
    # görüldü) — o bağlamda vergi_tipi_kodu'nu tevkifat_kodu sanmak yanlış
    # sınıflandırmaya yol açar.
    if tevkifat_baglami:
        kirilim.tevkifat_kodu = kirilim.vergi_tipi_kodu
    return kirilim


def _parse_tax_total(node, tag="cac:TaxTotal") -> list[VergiKirilimi]:
    """Verilen düğümdeki TaxTotal/WithholdingTaxTotal altındaki tüm TaxSubtotal'ları ayrıştırır."""
    tax_total = node.find(tag, NS)
    if tax_total is None:
        return []
    tevkifat_baglami = tag == "cac:WithholdingTaxTotal"
    return [
        _parse_tax_subtotal(sub, tevkifat_baglami=tevkifat_baglami)
        for sub in tax_total.findall("cac:TaxSubtotal", NS)
    ]


def _parse_invoice_line(node) -> FaturaKalemi:
    """Tek bir InvoiceLine düğümünü FaturaKalemi'ne ayrıştırır."""
    item = node.find("cac:Item", NS)
    kalem = FaturaKalemi(
        sira_no=_text(node, "cbc:ID"),
        kalem_adi=_text(item, "cbc:Name") if item is not None else None,
        aciklama=_text(item, "cbc:Description") if item is not None else None,
        miktar=_decimal_text(node, "cbc:InvoicedQuantity"),
        tutar=_decimal_text(node, "cbc:LineExtensionAmount"),
        vergi_kirilimlari=_parse_tax_total(node, "cac:TaxTotal"),
        tevkifat_kirilimlari=_parse_tax_total(node, "cac:WithholdingTaxTotal"),
    )
    qty_node = node.find("cbc:InvoicedQuantity", NS)
    if qty_node is not None:
        kalem.birim = qty_node.get("unitCode")
    return kalem


def _parse_root(root) -> Fatura:
    """Kök XML elemanından Fatura nesnesi üretir — dosyadan mı yoksa
    string'ten mi ayrıştırıldığından bağımsız, ortak mantık burada.
    NACE kodu döndürmez — fatura XML'i NACE taşımıyor (bkz.
    docs/reference/ubl-fatura-yapisi.md). NACE, satıcı VKN'sine bağlı
    ayrı bir kaynaktan sonradan eşlenecek.
    """
    fatura = Fatura(
        fatura_no=_text(root, "cbc:ID"),
        uuid=_text(root, "cbc:UUID"),
        duzenleme_tarihi=_text(root, "cbc:IssueDate"),
        profil_id=_text(root, "cbc:ProfileID"),
        fatura_tipi=_text(root, "cbc:InvoiceTypeCode"),
        para_birimi=_text(root, "cbc:DocumentCurrencyCode"),
    )

    supplier = root.find("cac:AccountingSupplierParty", NS)
    if supplier is not None:
        fatura.satici = _parse_party(supplier)

    customer = root.find("cac:AccountingCustomerParty", NS)
    if customer is not None:
        fatura.alici = _parse_party(customer)

    fatura.genel_vergi_kirilimlari = _parse_tax_total(root, "cac:TaxTotal")
    fatura.genel_tevkifat_kirilimlari = _parse_tax_total(
        root, "cac:WithholdingTaxTotal"
    )

    fatura.kalemler = [
        _parse_invoice_line(line)
        for line in root.findall("cac:InvoiceLine", NS)
    ]

    return fatura


def parse_ubl_invoice(xml_path: str) -> Fatura:
    """Bir UBL-TR e-fatura XML dosyasını diskten ayrıştırır."""
    tree = ET.parse(xml_path)
    return _parse_root(tree.getroot())


def parse_ubl_invoice_from_string(xml_metni: str) -> Fatura:
    """Bir UBL-TR e-fatura XML'ini string'den ayrıştırır (API girdisi için —
    dosya yoluna ihtiyaç duymaz)."""
    root = ET.fromstring(xml_metni)
    return _parse_root(root)
