"""Fatura ayristirma: sayisal alan normalizasyonu, JSON (ground-truth'lu)
ve ham UBL XML (ground-truth'suz) fatura okuma."""

import io
import json
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

from .constants import DEFAULT_OWN_VKN, UBL_NS

_UNSET = object()


def to_float(value):
    """Sayisal bir alani (int/float ya da serbest metin) float'a cevirir.

    Serbest metin hali SADECE ground-truth veriden degil, modelin ürettigi
    JSON ciktisindaki "amount" alanindan da gelebilir (bkz. score_entries).
    Model "amount: sayi" talimatina uymayip "1.234,56" (TR) ya da "1,234.56"
    (EN) gibi binlik-ayracli bir string uretirse, virgulu direkt noktaya
    cevirip gerisini silen naif bir yaklasim bunu sessizce 0'a (ya da 1000
    kat yanlis bir degere, orn. "1,234" -> 1.234) dusurur - bu da balanced/
    self-correct metriklerini gozden kacan sekilde bozar. Bu yuzden hangi
    ayracin ondalik oldugunu (varsa) pozisyona gore tespit ediyoruz."""
    if value is None:
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    s = re.sub(r"[^\d,.\-]", "", str(value))
    if s in ("", "-", ".", ","):
        return 0.0
    if "," in s and "." in s:
        # Ikisi de var: en son gorulen ayrac ondalik ayracidir, digeri binliktir.
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    elif "," in s:
        # Sadece virgul var: tek virgul ve sonrasinda <=2 hane ise ondalik
        # ayraci say (orn. "41,57"), aksi halde binlik ayraci say (orn. "1,234").
        last = s.split(",")[-1]
        if s.count(",") == 1 and len(last) <= 2:
            s = s.replace(",", ".")
        else:
            s = s.replace(",", "")
    try:
        return float(s)
    except ValueError:
        return 0.0


def normalize_dc(raw):
    if raw is None:
        return None
    s = str(raw).strip().lower()
    if s.startswith("bor") or s in ("d", "debit", "dr"):
        return "Borc"
    if s.startswith("alac") or s in ("c", "credit", "cr"):
        return "Alacak"
    return None


def normalize_code3(raw):
    if raw is None:
        return None
    m = re.search(r"\d{3}", str(raw))
    return m.group(0) if m else None


def load_invoice_paths(data_dir, data_format="json"):
    ext = "xml" if data_format == "xml" else "json"
    return sorted(Path(data_dir).glob(f"*.{ext}"))


def parse_invoice(path):
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    invoice_id = data.get("header", {}).get("invoice_id", path.stem)
    direction = "outbox" if path.stem.endswith("-outbox") else "inbox"

    gt_entries = data.get("accounting_entries", [])
    gt_pairs = set()
    for e in gt_entries:
        code3 = normalize_code3(e.get("account_code"))
        dc = normalize_dc(e.get("dc"))
        if code3 and dc:
            gt_pairs.add((code3, dc))

    return {
        "path": path,
        "invoice_id": invoice_id,
        "direction": direction,
        "header": data.get("header", {}),
        "taxes": data.get("taxes", []),
        "lines": data.get("lines", []),
        "notes": data.get("notes", []),
        "gt_pairs": gt_pairs,
        "has_ground_truth": True,
    }


def _ubl_find_text(root, path):
    e = root.find(path, UBL_NS)
    return e.text if e is not None and e.text else None


def parse_invoice_xml(path, own_vkn=DEFAULT_OWN_VKN):
    """Ham UBL e-fatura XML'ini, parse_invoice() ile AYNI sozluk seklinde
    dondurur - ama bu faturalarda henuz muhasebe kaydi (accounting_entries)
    YOK, dolayisiyla gt_pairs her zaman bos ve has_ground_truth=False'tur.
    Bu, "referans/skorlama" degil "gercek tahmin" senaryosudur (bkz.
    docs/how-to/predict_new_invoices.md).

    Yon (inbox/outbox) dosya adindan degil, faturanin kendi
    AccountingSupplierParty/AccountingCustomerParty VKN'sinden tespit edilir:
    sirketin kendi VKN'si (own_vkn) alici tarafta ise inbox (biz aliciyiz),
    satici tarafta ise outbox (biz saticiyiz)."""
    tree = ET.parse(path)
    return _parse_invoice_xml_tree(tree, path, own_vkn)


def parse_invoice_xml_string(xml_text, invoice_id_fallback="?", own_vkn=DEFAULT_OWN_VKN):
    """parse_invoice_xml() ile ayni, ama disk dosyasi yerine bellekteki bir
    XML string'i alir (henuz diske yazilmamis, entegrasyon katmanindan gelen
    ham UBL-TR metni icin - bkz. core/single.py). `path` alani sonuc
    sozlugunde None doner (kaynak bir dosya degil)."""
    tree = ET.parse(io.StringIO(xml_text))
    return _parse_invoice_xml_tree(tree, invoice_id_fallback, own_vkn, source_path=None)


def _parse_invoice_xml_tree(tree, path_or_fallback, own_vkn, source_path=_UNSET):
    """parse_invoice_xml()/parse_invoice_xml_string() arasinda paylasilan
    ortak govde. Dosya modunda (`source_path=_UNSET`) `path_or_fallback`
    gercek bir Path nesnesidir (eski davranis - `.stem`/`.name` kullanilir,
    sonuc sozlugundeki `path` alani da bu Path'tir). String modunda
    `path_or_fallback` dogrudan invoice_id fallback metnidir, `source_path`
    (None) sonuc sozlugundeki `path` alanina yazilir."""
    root = tree.getroot()
    if source_path is _UNSET:
        # Dosya modu: path_or_fallback gercek bir Path, invoice_id fallback'i
        # icin .stem kullanilir (eski davranis AYNEN korunur).
        fallback_id = path_or_fallback.stem
        path_field = path_or_fallback
        log_name = path_or_fallback.name
    else:
        # String modu: path_or_fallback dogrudan fallback metni.
        fallback_id = path_or_fallback
        path_field = source_path
        log_name = "(bellek ici XML string)"

    invoice_id = _ubl_find_text(root, "cbc:ID") or fallback_id
    issue_date = _ubl_find_text(root, "cbc:IssueDate")
    currency = _ubl_find_text(root, "cbc:DocumentCurrencyCode")
    invoice_type = _ubl_find_text(root, "cbc:InvoiceTypeCode")

    # Kur bilgisi (2026-07-23 eklendi): sadece dovizli faturalarda mevcut -
    # cac:PricingExchangeRate blogu yoksa exchange_rate None doner. Bu alan
    # SADECE bilgi/uyari amaclidir - parsing.py hicbir zaman kendi basina
    # TL'ye cevirmez (bkz. core/prompting.py "kur cevirimi yapma" kurali),
    # cevirme karari entegrasyon katmaninda kullaniciya sorulur.
    exchange_rate_raw = _ubl_find_text(root, "cac:PricingExchangeRate/cbc:CalculationRate")
    exchange_rate = to_float(exchange_rate_raw) if exchange_rate_raw else None
    exchange_source_currency = _ubl_find_text(root, "cac:PricingExchangeRate/cbc:SourceCurrencyCode")
    exchange_target_currency = _ubl_find_text(root, "cac:PricingExchangeRate/cbc:TargetCurrencyCode")

    supplier_vkn = _ubl_find_text(root, "cac:AccountingSupplierParty/cac:Party/cac:PartyIdentification/cbc:ID")
    customer_vkn = _ubl_find_text(root, "cac:AccountingCustomerParty/cac:Party/cac:PartyIdentification/cbc:ID")

    direction_uncertain = False
    if customer_vkn == own_vkn:
        direction = "inbox"
        counterparty_path = "cac:AccountingSupplierParty/cac:Party"
        counterparty_vkn = supplier_vkn
    elif supplier_vkn == own_vkn:
        direction = "outbox"
        counterparty_path = "cac:AccountingCustomerParty/cac:Party"
        counterparty_vkn = customer_vkn
    else:
        # Sirketin kendi VKN'si hicbir tarafta yok - beklenmedik durum,
        # varsayilan olarak inbox/tedarikci-karsi-taraf sayilir ama bu
        # faturayi ISARETLE ki kullanici fark etsin (direction_uncertain=True,
        # ayrica stderr'e uyari yazilir - asagida).
        direction = "inbox"
        counterparty_path = "cac:AccountingSupplierParty/cac:Party"
        counterparty_vkn = supplier_vkn
        direction_uncertain = True
        print(
            f"UYARI: {log_name} - own_vkn ({own_vkn}) ne alici ({customer_vkn}) "
            f"ne de satici ({supplier_vkn}) tarafinda bulundu. Yon varsayilan "
            f"olarak 'inbox' atandi, bu tahmin YANLIS olabilir - --own-vkn "
            f"degerini kontrol edin.",
            file=sys.stderr,
        )

    # Karsi taraf unvani (2026-07-27, kullanici karari - iki asamali secim):
    #
    # 1) IHRACAT ISTISNASI: Ihracat faturalarinda cac:AccountingCustomerParty
    #    gercek musteriyi DEGIL gumruk/araci tarafini ("Gumruk ve Ticaret
    #    Bakanligi") tasir; gercek yurt disi alici cac:BuyerCustomerParty'de
    #    bulunur. Eldeki 1933 faturanin 112'sinde (hepsi ihracat) bu iki blok
    #    FARKLI - parser eskiden hepsini "Gumruk Bakanligi" saniyordu, boylece
    #    mizandaki gercek musteriyi (ornek: R.C.JONES=120.03.00043, FORJAS
    #    IRIZAR, HEUER HEBETECHNIK...) hicbir zaman bulamiyordu. Bu yuzden
    #    BuyerCustomerParty varsa unvani ONCE oradan alinir.
    # 2) Her blokta once cac:PartyLegalEntity/cbc:RegistrationName (resmi unvan),
    #    o yoksa cac:PartyName/cbc:Name (gorunen ad) denenir - firmanin resmi
    #    unvani mizandaki isimlerle daha iyi eslesir (alt kirilim fuzzy eslemesi,
    #    core/single.py).
    #
    # BuyerCustomerParty yoksa (yurt ici faturalarin cogu) davranis degismez:
    # counterparty_path (yone gore satici/alici) uzerinden okunur.
    def _party_unvani(party_path):
        return (
            _ubl_find_text(root, f"{party_path}/cac:PartyLegalEntity/cbc:RegistrationName")
            or _ubl_find_text(root, f"{party_path}/cac:PartyName/cbc:Name")
        )

    account_title = None
    if direction == "outbox":
        account_title = _party_unvani("cac:BuyerCustomerParty/cac:Party")
    account_title = account_title or _party_unvani(counterparty_path) or "?"

    header = {
        "invoice_id": invoice_id,
        "issue_date": issue_date,
        "currency": currency,
        "invoice_type": invoice_type,
        "account_title": account_title.strip(),
        "account_tax_number": counterparty_vkn,
        "allowance_total": _ubl_find_text(root, "cac:LegalMonetaryTotal/cbc:AllowanceTotalAmount") or "0.00",
        "tax_exclusive": _ubl_find_text(root, "cac:LegalMonetaryTotal/cbc:TaxExclusiveAmount"),
        "tax_inclusive": _ubl_find_text(root, "cac:LegalMonetaryTotal/cbc:TaxInclusiveAmount"),
        "payable": _ubl_find_text(root, "cac:LegalMonetaryTotal/cbc:PayableAmount"),
        "exchange_rate": exchange_rate,
        "exchange_source_currency": exchange_source_currency,
        "exchange_target_currency": exchange_target_currency,
    }

    taxes = []
    # Normal vergiler (orn. KDV) - cac:TaxTotal
    for tt in root.findall("cac:TaxTotal", UBL_NS):
        for st in tt.findall("cac:TaxSubtotal", UBL_NS):
            taxes.append({
                "name": _ubl_find_text(st, "cac:TaxCategory/cac:TaxScheme/cbc:Name") or "?",
                "code": _ubl_find_text(st, "cac:TaxCategory/cac:TaxScheme/cbc:TaxTypeCode") or "?",
                "percent": _ubl_find_text(st, "cbc:Percent") or "0",
                "tax": _ubl_find_text(st, "cbc:TaxAmount") or "0.00",
                "exemption": {
                    "code": _ubl_find_text(st, "cac:TaxCategory/cbc:TaxExemptionReasonCode") or "",
                    "reason": _ubl_find_text(st, "cac:TaxCategory/cbc:TaxExemptionReason") or "",
                } if _ubl_find_text(st, "cac:TaxCategory/cbc:TaxExemptionReasonCode") else {},
            })
    # Tevkifat/stopaj - AYRI bir eleman: cac:WithholdingTaxTotal
    for wtt in root.findall("cac:WithholdingTaxTotal", UBL_NS):
        for st in wtt.findall("cac:TaxSubtotal", UBL_NS):
            taxes.append({
                "name": _ubl_find_text(st, "cac:TaxCategory/cac:TaxScheme/cbc:Name") or "?",
                "code": _ubl_find_text(st, "cac:TaxCategory/cac:TaxScheme/cbc:TaxTypeCode") or "?",
                "percent": _ubl_find_text(st, "cbc:Percent") or "0",
                "tax": _ubl_find_text(st, "cbc:TaxAmount") or "0.00",
                "exemption": {},
            })

    lines = []
    for line in root.findall("cac:InvoiceLine", UBL_NS):
        qty_el = line.find("cbc:InvoicedQuantity", UBL_NS)
        qty_text = qty_el.text if qty_el is not None else "?"
        unit_code = qty_el.attrib.get("unitCode", "") if qty_el is not None else ""
        lines.append({
            "product_name": _ubl_find_text(line, "cac:Item/cbc:Name") or "?",
            "quantity": f"{qty_text} {unit_code}".strip(),
            "total": _ubl_find_text(line, "cbc:LineExtensionAmount") or "0.00",
        })

    notes = [n.text for n in root.findall("cbc:Note", UBL_NS) if n.text]

    return {
        "path": path_field,
        "invoice_id": invoice_id,
        "direction": direction,
        "direction_uncertain": direction_uncertain,
        "header": header,
        "taxes": taxes,
        "lines": lines,
        "notes": notes,
        "gt_pairs": set(),
        "has_ground_truth": False,
    }


def convert_invoice_to_try(invoice):
    """Yabanci para birimli bir faturanin (parse_invoice_xml_string ciktisi)
    tum parasal alanlarini, XML'in kendi cac:PricingExchangeRate/CalculationRate
    orani ile TL (TRY) karsiligina cevirir - yeni bir invoice sozlugu doner,
    girdiyi degistirmez (orijinali her zaman geri donulebilir kalsin diye).

    SADECE kullanicinin acikca "TL'ye cevir" secimiyle cagrilir (bkz.
    entegrasyon/app.py) - varsayilan akiste asla otomatik tetiklenmez, cunku
    core/prompting.py::build_user_prompt SYSTEM_PROMPT'ta modele "kur cevirimi
    yapma, fatura kendi para biriminde kal" talimati veriyor (bkz. RESULTS.md
    ile celismesin diye kur cevirisi LLM'e degil, burada acik bir kullanici
    talebiyle koda yaptirilir).

    invoice["header"]["exchange_rate"] None ise (kur bilgisi XML'de yoksa)
    ValueError firlatir - cagiran taraf (entegrasyon) bu durumu kullaniciya
    once sormadan cevirmeye calismamali."""
    rate = invoice["header"].get("exchange_rate")
    if not rate:
        raise ValueError(
            "Bu faturada kur bilgisi (cac:PricingExchangeRate/CalculationRate) yok - "
            "TL'ye cevrilemez."
        )

    def _cevir(deger):
        if deger is None:
            return deger
        return f"{to_float(deger) * rate:.2f}"

    new_header = dict(invoice["header"])
    for alan in ("allowance_total", "tax_exclusive", "tax_inclusive", "payable"):
        new_header[alan] = _cevir(new_header.get(alan))
    new_header["currency"] = new_header.get("exchange_target_currency") or "TRY"

    new_taxes = []
    for t in invoice["taxes"]:
        yeni_t = dict(t)
        yeni_t["tax"] = _cevir(t.get("tax"))
        new_taxes.append(yeni_t)

    new_lines = []
    for ln in invoice["lines"]:
        yeni_ln = dict(ln)
        yeni_ln["total"] = _cevir(ln.get("total"))
        new_lines.append(yeni_ln)

    new_invoice = dict(invoice)
    new_invoice["header"] = new_header
    new_invoice["taxes"] = new_taxes
    new_invoice["lines"] = new_lines
    return new_invoice


def render_tax_line(t):
    parts = [f"{t.get('name', '?')} (kod {t.get('code', '?')}) %{t.get('percent', '0')}", f"tutar {t.get('tax', '?')}"]
    exemption = t.get("exemption") or {}
    if exemption:
        parts.append(f"muafiyet: {exemption.get('code', '')} - {exemption.get('reason', '')}")
    return " - ".join(parts)
