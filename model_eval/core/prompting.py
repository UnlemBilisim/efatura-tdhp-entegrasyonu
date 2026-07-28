"""Prompt olusturma: glossary system prompt, IADE/tevkifat deterministik
ipuclari, yon metni ve nihai kullanici prompt'u."""

from .constants import SYSTEM_PROMPT, TDHP_GLOSSARY
from .parsing import render_tax_line, to_float


def build_glossary_system_prompt():
    lines = [f"{code}: {name}" for code, name in sorted(TDHP_GLOSSARY.items())]
    glossary_block = "\n".join(lines)
    return SYSTEM_PROMPT + f"""
Ayrica, bu veri setinde gecebilecek TDHP ana hesap kodlarinin referans listesi:
{glossary_block}

Bu liste referans amaclidir - faturaya uygun olani sen sec, listede olmayan
baska bir TDHP kodu da gerekiyorsa onu da kullanabilirsin."""


def compute_iade_hint(invoice):
    """IADE (fatura iadesi) faturalarinda ters kayit mantigini LLM'e
    ciktirtmak yerine burada deterministik olarak hesaplar.

    Archive2/jsons'daki 20 IADE faturasinin TAMAMINI inceleyerek dogrulanmis
    kural (bkz. model_eval/RESULTS.md SS6.1-6.3):
    - outbox + IADE = ALISTAN IADE (tedarikciye mal/hizmet iade ediyoruz):
      karsi taraf (320 vb.) BORC, KDV hesabi 391 (Alistan Iade KDV) ALACAK,
      iade edilen mal/hizmet hesabi ALACAK.
    - inbox + IADE = SATISTAN IADE (musteri bize mal/hizmet iade ediyor):
      karsi taraf (320/120 vb.) ALACAK, KDV hesabi 191 (Satistan Iade KDV)
      BORC, iade alinan mal/hizmet hesabi BORC.
    Yani orijinal islemin (alis/satis) TAM TERSI yonde kaydedilir VE KDV
    hesap kodu degisir (normal alista 191, alistan iadede 391; normal
    satista 391 benzeri hesaplanan KDV, satistan iadede 191). 20 faturanin
    hepsinde bu yon/kod kurali istisnasiz dogrulandi - degisken olan tek
    sey KARSI TARAF hesabinin (120 mi 320 mu) ve mal/hizmet hesabinin HANGI
    KOD oldugu; bunlar hala modelin/RAG'in belirlemesi gereken siniflandirma
    karari, burada override edilmiyor - sadece tutar ve yon onceden verilir.
    """
    if (invoice["header"].get("invoice_type") or "").upper() != "IADE":
        # Bu hint SADECE IADE faturalari icindir - normal bir alis/satis
        # faturasinda tetiklenirse yon/KDV-kodu YANLIS (ters) bir hesaplama
        # dayatir (compute_tevkifat_hint'in aksine, burada payable>0/tax>0
        # her faturada dogru oldugu icin bu kontrol OLMADAN her faturada
        # tetiklenirdi).
        return None

    h = invoice["header"]
    tax_exclusive = to_float(h.get("tax_exclusive"))
    payable = to_float(h.get("payable")) or to_float(h.get("tax_inclusive"))
    tax_total = sum(to_float(t.get("tax")) for t in invoice["taxes"])
    if tax_total <= 0 or payable <= 0:
        return None

    if invoice["direction"] == "outbox":
        return f"""### IADE FATURASI HESAPLAMASI (ALISTAN IADE - onceden hesaplanmis, sadece dogru hesaba yerlestir)
Bu fatura bir ALISTAN IADEDIR: sirketimiz daha once satin aldigi bir mal/hizmeti
tedarikciye GERI VERIYOR. Kayit, orijinal ALIS kaydinin TAM TERSI yondedir:
- Karsi tarafin hesabina (320 Saticilar vb. - hangi kod oldugunu SEN belirle) BORC yazilacak tutar: {payable:.2f} TRY
- 391 (Alistan Iade KDV) hesabina ALACAK yazilacak tutar: {tax_total:.2f} TRY
- Iade edilen mal/hizmetin hesabina (150/152/730/770 vb. - hangi kod oldugunu SEN belirle) ALACAK yazilacak tutar: {tax_exclusive:.2f} TRY
Bu tutarlari/yonleri TEKRAR HESAPLAMANA GEREK YOK, sadece hangi mal/hizmet hesabini kullanacagina karar ver ve yerlestir."""
    else:
        return f"""### IADE FATURASI HESAPLAMASI (SATISTAN IADE - onceden hesaplanmis, sadece dogru hesaba yerlestir)
Bu fatura bir SATISTAN IADEDIR: musteri, sirketimizden daha once satin aldigi
bir mal/hizmeti GERI VERIYOR. Kayit, orijinal SATIS kaydinin TAM TERSI yondedir:
- Karsi tarafin hesabina (320/120 vb. - hangi kod oldugunu SEN belirle) ALACAK yazilacak tutar: {payable:.2f} TRY
- 191 (Satistan Iade KDV) hesabina BORC yazilacak tutar: {tax_total:.2f} TRY
- Iade alinan mal/hizmetin hesabina (150/152/730/770 vb. - hangi kod oldugunu SEN belirle) BORC yazilacak tutar: {tax_exclusive:.2f} TRY
Bu tutarlari/yonleri TEKRAR HESAPLAMANA GEREK YOK, sadece hangi mal/hizmet hesabini kullanacagina karar ver ve yerlestir."""


IHRAC_KAYITLI_ISTISNA_KODLARI = {"701", "702", "703", "704"}


def compute_ihrac_kayitli_hint(invoice):
    """Ihrac kayitli satislarda (istisna kodu 701-704) KDV'nin 192/391
    araciligiyla nasil netlendigini LLM'e hesaplatmak yerine burada
    deterministik olarak hesaplar.

    Kullanici tarafindan dogrulanmis muhasebe akisi (2026-07-23): satis
    aninda hesaplanan KDV once 192 (Diger KDV, donen varlik) hesabina BORC
    yazilir; ihracat gerceklestiginde/tecil-terkin ile ayni tutar 391
    (Hesaplanan KDV) hesabina ALACAK olarak aktarilip iki hesap birbirini
    netler - satici bu satis icin KDV odemez (tecil-terkin mantigi). Bu,
    SADECE ihrac kayitli istisnalarda (701-704) gecerlidir - diger istisna
    kodlarinda (ör. dogrudan mal ihracati, kod 301) bu 192/391 aktarimi
    uygulanmaz, KDV zaten hic hesaplanmaz.

    Not: compute_tevkifat_hint/compute_iade_hint'in aksine bu, henuz
    Archive2/jsons uzerinde n>1 bir deneyle olcülmedi - kullanicinin
    dogrudan onayladigi bir muhasebe kurali olarak eklendi. Ileride yanlis
    ciktigi gozlenirse (RESULTS.md'ye benzer bir bulgu ile) gozden gecirilmeli.
    """
    exemption_codes = {
        (t.get("exemption") or {}).get("code")
        for t in invoice["taxes"]
    }
    if not (exemption_codes & IHRAC_KAYITLI_ISTISNA_KODLARI):
        return None

    kdv_entries = [t for t in invoice["taxes"] if t.get("code") == "0015"]
    kdv_tutar = sum(to_float(t.get("tax")) for t in kdv_entries)
    if kdv_tutar <= 0:
        return None

    return f"""### IHRAC KAYITLI SATIS KDV HESAPLAMASI (onceden hesaplanmis, sadece dogru hesaba yerlestir)
Bu fatura ihrac kayitli bir satistir (istisna kodu 701-704). Hesaplanan KDV,
tecil-terkin mantigiyla NETLENIR - satici bu satis icin KDV odemez:
- 192 (Diger KDV) hesabina BORC yazilacak tutar: {kdv_tutar:.2f} TRY
- 391 (Hesaplanan KDV) hesabina ALACAK yazilacak tutar: {kdv_tutar:.2f} TRY
Bu tutarlari TEKRAR HESAPLAMANA GEREK YOK, sadece bu iki hesaba yerlestir."""


def compute_tevkifat_hint(invoice):
    """Tevkifatli faturalarda KDV'nin oransal bolunmesini (satici payi / tevkif
    edilen pay) LLM'e hesaplatmak yerine burada deterministik olarak hesaplar.
    Ana KDV (kod 0015) disindaki herhangi bir vergi satiri (627, 616, vb. -
    tevkifat kodu fatura tipine gore degisiyor) tevkifat tutari sayilir.
    Tum gerekli sayilar zaten faturanin kendi vergi verisinde mevcut - sadece
    doğru sekilde toplanip/cikarilmasi gerekiyor, ki LLM'ler bunu sik sik
    yanlis yapiyor (bkz. tevkifat testinde balanced%=9.5).

    YON'E GORE FARKLI HESAP SETI (2026-07-23 duzeltmesi, kullanici tarafindan
    saglanan iki gercek muhasebe kaydiyla dogrulandi - bkz. model_eval/CLAUDE.md
    "Kritik gercekler"): eski surum yonden bagimsiz TEK bir formul (191 Borc
    tam KDV / 360 Alacak tevkifat / 320 Alacak net) oneriyordu - bu SADECE
    alista (inbox) dogruydu, satista (outbox) yanlisti (391/600/120 yerine
    191/360/320 oneriyordu).

    - inbox (biz aliciyiz): 191 (Indirilecek KDV) hesabina TAM KDV Borc
      yazilir; 360 (Odenecek KDV) hesabina SADECE tevkif edilen pay Alacak
      yazilir; karsi tarafa (320 vb.) net (tevkifat dusulmus) tutar Alacak
      yazilir. Gercek ornek: nakliye faturasi, KDV 20.000/tevkifat 4.000 ->
      191 Borc 20.000, 360 Alacak 4.000, 320 Alacak 116.000 (=120.000-4.000).
    - outbox (biz saticiyiz): 391 (Hesaplanan KDV) hesabina SADECE NET
      (KDV - tevkifat) tutar Alacak yazilir - tevkif edilen kisim saticiya
      hic ulasmadigi icin ayri bir hesaba YAZILMAZ. Karsi taraftan (120 vb.)
      alacagimiz tutar da net (tevkifat dusulmus) olur. Gercek ornek: Nuret
      Akali/Demas faturasi, KDV 5.950/tevkifat 1.190 -> 391 Alacak 4.760
      (=5950-1190), 120 Borc 34.510 (=29750+4760).

    NOT (ileride yapilacak): su an sadece 3 haneli ana hesap kodu (191/360/
    320/391/120) oneriliyor, alt/muavin hesap kirilimi (orn. 191'in net+
    tevkif payi icin IKI ayri alt satira bolunmesi, gercek muhasebe
    kayitlarinda goruldugu gibi) BILEREK yapilmiyor - SYSTEM_PROMPT'un
    "sadece 3 haneli ana kod, alt hesap uydurma" kuraliyla tutarli kalmak
    icin. Raporlama/detay ihtiyaci dogarsa alt kirilim ayri bir gorev olarak
    ele alinmali (bkz. model_eval/CLAUDE.md)."""
    taxes = invoice["taxes"]
    if len(taxes) < 2:
        return None
    kdv_entries = [t for t in taxes if t.get("code") == "0015"]
    other_entries = [t for t in taxes if t.get("code") != "0015"]
    if not kdv_entries or not other_entries:
        return None

    kdv_tutar = sum(to_float(t.get("tax")) for t in kdv_entries)
    tevkifat_tutar = sum(to_float(t.get("tax")) for t in other_entries)
    if tevkifat_tutar <= 0 or tevkifat_tutar > kdv_tutar:
        return None

    net_kdv = kdv_tutar - tevkifat_tutar
    tax_exclusive = to_float(invoice["header"].get("tax_exclusive"))

    if invoice["direction"] == "outbox":
        payable_from_counterparty = tax_exclusive + net_kdv
        return f"""### TEVKIFAT HESAPLAMASI (SATIS - onceden hesaplanmis, sadece dogru hesaba yerlestir)
Bu fatura tevkifatli bir SATIS faturasidir - tevkif edilen kisim saticiya
hic ulasmaz, bu yuzden ayri bir hesaba YAZILMAZ:
- 391 (Hesaplanan KDV) hesabina ALACAK yazilacak NET tutar (tevkifat dusulmus): {net_kdv:.2f} TRY
- Karsi taraftan (120 vb.) ALACAGIMIZ tutar (Borc yazilacak, tevkifat dusulmus): {payable_from_counterparty:.2f} TRY
Bu hesaplamalari TEKRAR YAPMANA GEREK YOK, sadece dogru hesap koduna yerlestir."""

    payable_to_counterparty = tax_exclusive + kdv_tutar - tevkifat_tutar
    return f"""### TEVKIFAT HESAPLAMASI (ALIS - onceden hesaplanmis, sadece dogru hesaba yerlestir)
Bu fatura tevkifatli bir ALIS faturasidir:
- 191 (Indirilecek KDV) hesabina Borc yazilacak TAM KDV tutari: {kdv_tutar:.2f} TRY
- Tevkif edilip beyan edilecek KDV (360 hesabina Alacak yazilacak tutar): {tevkifat_tutar:.2f} TRY
- Karsi tarafa/saticiya ODEYECEGIMIZ net tutar (320 vb. hesaba Alacak yazilacak tutar): {payable_to_counterparty:.2f} TRY
Bu hesaplamalari TEKRAR YAPMANA GEREK YOK, sadece dogru hesap koduna yerlestir."""


def build_direction_text(invoice):
    """IADE faturalari icin normal alis/satis cerceevesi YANILTICIDIR: outbox
    bir IADE, 'biz saticiyiz' degil, tam tersine tedarikciye mal iade
    ettigimiz (yani ALIS'in tersi) bir islemdir - ve bunun tersi de gecerli.
    Bu yanlis cerceve, modelin IADE'de normal alis/satis yon mantigini
    uygulamasina (ve 320/391 gibi hesaplari ters kullanmasina) yol aciyordu
    (bkz. RESULTS.md SS6.1-6.3)."""
    is_iade = (invoice["header"].get("invoice_type") or "").upper() == "IADE"
    if invoice["direction"] == "inbox":
        if is_iade:
            return (
                "Bu fatura, sirketimizin ONCEDEN YAPTIGI BIR SATISIN IADESIDIR: "
                "musteri bize mal/hizmet iade ediyor, bu iade faturasini biz ALDIK."
            )
        return "Bu fatura sirketimizin ALDIGI bir ALIS faturasidir (biz aliciyiz)."
    if is_iade:
        return (
            "Bu fatura, sirketimizin ONCEDEN YAPTIGI BIR ALISIN IADESIDIR: "
            "biz tedarikciye mal/hizmet iade ediyoruz, bu iade faturasini biz KESTIK."
        )
    return "Bu fatura sirketimizin KESTIGI bir SATIS faturasidir (biz saticiyiz)."


ALT_KIRILIM_SYSTEM_PROMPT = """Sen deneyimli bir Serbest Muhasebeci Mali Musavir (SMMM) yapay zeka asistanisin.
Gorevin, bir onceki adimda belirlenmis 3 haneli TDHP ana hesap kodlarinin,
bu SIRKETE OZEL mizan'daki hangi alt kirilima (muavin hesaba) karsilik geldigini secmek.

Kurallar:
- Her ana kod icin, sadece o kodun ALTINDA listelenen seçeneklerden birini seç.
  Listede olmayan bir alt kod UYDURMA.
- Vergi/gider hesaplarinda (ör. 191, 391, 360) alt kirilimi genelde ORAN/TEVKIFAT
  bilgisine (fatura baglaminda verilir) göre seç - ör. "%20 5/10 Tevkifatli KDV"
  gibi bir isim, faturadaki tevkifat oranina uyuyorsa onu seç.
- Cari hesaplarda (ör. 120 Alicilar, 320 Saticilar) alt kirilimi KARSI TARAFIN
  unvanina EN YAKIN ismi bularak seç - faturadaki karsi taraf unvanini kontrol et.
- Uygun bir alt kirilim bulamazsan (hiçbir seçenek uymuyorsa, ör. yeni bir
  musteri/tedarikçi ise) o ana kodu ATLA (ciktida o kod icin hiçbir seyi
  degistirme) - alt kirilim uydurmaktansa ana kodda birakmak daha dogrudur.
- Cevabini SADECE su JSON semasina uygun ver, baska hiçbir metin ekleme:

{"secimler": [{"ana_kod": "3 haneli kod", "alt_kod": "secilen tam alt kirilim kodu"}]}
"""


def build_alt_kirilim_user_prompt(invoice, entries, alt_kirilimlar_by_code):
    """Ana modelin urettigi entries listesindeki HER BENZERSIZ 3 haneli kod
    icin, core/mizan.py::get_alt_kirilimlar()'dan gelen alt kirilim
    secenklerini goesterip dogru alt kirilimi sectiren prompt'u olusturur.

    alt_kirilimlar_by_code: {"191": [("191.05.00005", "%20 5/10 Tevkifatli KDV"), ...], ...}
    - sadece entries'te GECEN kodlar icin dolu olmasi beklenir (cagiran taraf
    core/single.py bu filtrelemeyi yapar, gereksiz kod icin mizan aranmaz)."""
    h = invoice["header"]
    kod_bloklari = []
    for ana_kod, secenekler in alt_kirilimlar_by_code.items():
        secenek_satirlari = "\n".join(f"  - {kod}: {ad}" for kod, ad in secenekler)
        kod_bloklari.append(f"### {ana_kod} icin alt kirilim secenekleri:\n{secenek_satirlari}")

    entries_text = ", ".join(f"{e['account_code']} ({e['dc']})" for e in entries)

    return f"""### FATURA BAGLAMI
- Karsi Taraf: {h.get('account_title', '?')} (VKN/TCKN: {h.get('account_tax_number', '?')})
- Fatura Tipi: {h.get('invoice_type', '?')}

### BIR ONCEKI ADIMDA BULUNAN HESAP KODLARI
{entries_text}

{chr(10).join(kod_bloklari)}

### TALIMAT
Yukaridaki her ana kod icin, kendi alt kirilim secenekleri listesinden
faturaya en uygun olani sec. Sadece istenen JSON formatinda cevap ver.
"""


def build_user_prompt(invoice, sector, tevkifat_hint=False, rag_block="", iade_hint=False, ihrac_kayitli_hint=False):
    h = invoice["header"]
    direction_text = build_direction_text(invoice)

    lines_txt = []
    for i, ln in enumerate(invoice["lines"], 1):
        lines_txt.append(
            f"{i}. {ln.get('product_name', '?')} - Miktar: {ln.get('quantity', '?')} - Tutar: {ln.get('total', '?')}"
        )
    if not lines_txt:
        lines_txt.append("(satir kalemi bilgisi yok)")

    taxes_txt = [render_tax_line(t) for t in invoice["taxes"]] or ["(vergi bilgisi yok)"]
    notes_txt = "\n".join(invoice["notes"]) if invoice["notes"] else "(not yok)"

    tevkifat_block = ""
    if tevkifat_hint:
        hint = compute_tevkifat_hint(invoice)
        if hint:
            tevkifat_block = "\n" + hint + "\n"

    iade_block = ""
    if iade_hint:
        hint = compute_iade_hint(invoice)
        if hint:
            iade_block = "\n" + hint + "\n"

    ihrac_kayitli_block = ""
    if ihrac_kayitli_hint:
        hint = compute_ihrac_kayitli_hint(invoice)
        if hint:
            ihrac_kayitli_block = "\n" + hint + "\n"

    return f"""### SIRKET BAGLAMI
Bu defter, su sektorde faaliyet gosteren bir sirkete aittir: {sector}.
{direction_text}

### FATURA BILGILERI
- Fatura No: {h.get('invoice_id', '?')}
- Fatura Tarihi: {h.get('issue_date', '?')}
- Fatura Tipi: {h.get('invoice_type', '?')}
- Karsi Taraf: {h.get('account_title', '?')} (VKN/TCKN: {h.get('account_tax_number', '?')})
- Para Birimi: {h.get('currency', '?')}
- Vergiler Haric Tutar: {h.get('tax_exclusive', '?')}
- Iskonto: {h.get('allowance_total', '?')}
- Vergiler Dahil Tutar: {h.get('tax_inclusive', '?')}
- Odenecek/Alinacak Tutar: {h.get('payable', '?')}

### VERGILER
{chr(10).join('- ' + t for t in taxes_txt)}

### FATURA SATIR KALEMLERI
{chr(10).join(lines_txt)}

### NOTLAR
{notes_txt}
{tevkifat_block}
{iade_block}
{ihrac_kayitli_block}
{rag_block}
### TALIMAT
Yukaridaki fatura icin gerekli muhasebe kaydini (yevmiye maddesini) olustur.
onemli: tutarlari kesinlikle faturanin "Para Birimi" alaninda belirtilen para biriminde,
yukarida verilen sayisal degerleriyle BIREBIR AYNI yaz. Kur cevirimi yapma, TL karsiligini
hesaplama, faturada verilen sayiyi ("Vergiler Haric Tutar", "Odenecek/Alinacak Tutar" vb.)
farkli bir birime cevirip kullanma. Fatura EUR ise kayittaki tutarlar da EUR, TL ise TL olmali.
Sadece istenen JSON formatinda cevap ver.
"""
