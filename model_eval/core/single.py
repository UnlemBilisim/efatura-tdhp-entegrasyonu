"""Tek bir fatura icin senkron, DB'ye dokunmayan TDHP tahmin fonksiyonu.

`entegrasyon/` klasorunun (Mcp_mimarisi'nin HTTP API'sinden "uygun" karari
alinan faturalari bu pipeline'a verecek ayri bir proje - bkz. entegrasyon.md)
import edecegi ince bir katman. `core/runner.py::run_model()`'in aksine:
- Toplu degil, TEK fatura isler.
- Es zamanlilik/ThreadPoolExecutor yok.
- PostgreSQL'e (core/reporting.py) HICBIR SEY yazmaz - saf hesaplama+LLM
  cagrisidir, cagiran taraf sonucu kendi tercih ettigi sekilde saklar.
- Ham XML STRING alir (henuz diske yazilmamis fatura) - dosya yolu degil.

Mantigin cogu (RAG/self-correct tetikleyicileri, prompt insasi, model
cagrisi) core/runner.py::run_model() icindeki process()'le AYNI modulleri
kullanir; ayni akis burada TEK fatura icin tekrarlanir (paylasilan bir ic
yardimciya cikarmak, run_model()'in test edilmis davranisini bozma riski
tasidigi icin bilincli olarak yapilmadi - bkz. GOREV_MIMARI_DUZELTME
benzeri gorev notunda birakilan tercih)."""

from .constants import DEFAULT_OLLAMA_HOST, DEFAULT_OWN_VKN, DEFAULT_SECTOR, SYSTEM_PROMPT
from .parsing import (
    convert_invoice_to_try,
    normalize_code3,
    normalize_dc,
    parse_invoice_xml_string,
    to_float,
)
from .mizan import get_alt_kirilimlar
from .prompting import (
    ALT_KIRILIM_SYSTEM_PROMPT,
    build_alt_kirilim_user_prompt,
    build_glossary_system_prompt,
    build_user_prompt,
)
from .providers import (
    build_balance_correction_request,
    call_model,
    parse_model_spec,
    self_correct_ollama,
)
from .scoring import extract_json_block, parse_model_output

DEFAULT_MODEL_SPEC_STR = "ollama:gemma4:31b-cloud"

# Cari (karsi taraf) hesap kodlari: bu 3 haneli kodlar bir MUSTERI/TEDARIKCI'yi
# temsil eder, gider/stok turunu degil. Alt kirilim adiminda bu kodlardan biri
# 3 haneli KALIRSA (mizanda eslesen karsi taraf bulunamadi), bu "yeni bir
# musteri/tedarikci, henuz cari kart acilmamis" sinyalidir - entry'ye bir
# `uyari` alani eklenir (2026-07-24, kullanici karari). Gider/stok hesaplari
# (150/770 gibi) bu listede DEGIL - onlarin 3 haneli kalmasi farkli bir sebep
# (belirsiz semantik eslesme), "yeni karsi taraf" degil.
CARI_HESAP_KODLARI = {"120", "320", "340", "440", "159", "420"}

# Cari hesap alt kirilimini karsi taraf unvanina gore ISIM BENZERLIGIYLE
# esleme esigi (2026-07-27, kullanici karari - bkz. memory alt-kirilim-fuzzy-esleme).
# Mizandaki unvanlarda yazim/kisaltma farki olsa bile ("San.Tic.Ltd.Sti" vs
# "Sanayi Ve Ticaret Limited Sirketi") dogru alt kirilimi bulabilmek icin, LLM'e
# sormadan ONCE deterministik bir fuzzy esleme denenir. Benzerlik bu esigin
# ustundeyse otomatik secilir; altindaysa o kod normal LLM alt kirilim adimina
# birakilir (yanlis eslemeyi onlemek icin YUKSEK esik). difflib standart
# kutuphanede - ek bagimlilik yok.
CARI_FUZZY_ESIK = 0.85


def _unvan_normalize(s):
    """Turkce unvanlari karsilastirma icin normalize eder: buyuk harfe cevirir,
    Turkce karakterleri ASCII'ye indirger, yaygin sirket eki kisaltmalarini
    ("SAN", "TIC", "LTD", "STI", "AS" ...) tam bicimine acar ki "San.Tic.Ltd.Sti"
    ile "Sanayi Ve Ticaret Limited Sirketi" yuksek benzerlik alsin, noktalama/
    fazla bosluklari temizler."""
    if not s:
        return ""
    s = s.upper()
    for a, b in [("İ", "I"), ("Ş", "S"), ("Ğ", "G"), ("Ü", "U"), ("Ö", "O"), ("Ç", "C"), ("I", "I")]:
        s = s.replace(a, b)
    # noktalama -> bosluk
    s = "".join(ch if ch.isalnum() else " " for ch in s)
    kelimeler = s.split()
    kisaltma = {
        "SAN": "SANAYI", "TIC": "TICARET", "LTD": "LIMITED", "STI": "SIRKETI",
        "STİ": "SIRKETI", "AS": "ANONIM", "A": "ANONIM", "S": "SIRKETI",
        "INS": "INSAAT", "ITH": "ITHALAT", "IHR": "IHRACAT", "MUH": "MUHENDISLIK",
        "NAK": "NAKLIYE", "HIZM": "HIZMETLERI", "END": "ENDUSTRIYEL",
        "VE": "VE",
    }
    kelimeler = [kisaltma.get(k, k) for k in kelimeler]
    return " ".join(kelimeler)


def _cari_fuzzy_esles(karsi_taraf_unvani, alt_secenekler):
    """Karsi taraf unvanini, verilen (kod, ad) alt kirilim secenekleriyle isim
    benzerligine gore karsilastirir. En yuksek benzerlikli aday CARI_FUZZY_ESIK
    (0.85) uzerindeyse (kod, oran) doner; degilse (None, en_iyi_oran) doner.

    Ek bagimlilik yok - difflib.SequenceMatcher (standart kutuphane) kullanilir."""
    from difflib import SequenceMatcher

    if not karsi_taraf_unvani or not alt_secenekler:
        return None, 0.0
    hedef = _unvan_normalize(karsi_taraf_unvani)
    if not hedef:
        return None, 0.0
    en_iyi_kod, en_iyi_oran = None, 0.0
    for kod, ad in alt_secenekler:
        oran = SequenceMatcher(None, hedef, _unvan_normalize(ad)).ratio()
        if oran > en_iyi_oran:
            en_iyi_oran, en_iyi_kod = oran, kod
    if en_iyi_oran >= CARI_FUZZY_ESIK:
        return en_iyi_kod, en_iyi_oran
    return None, en_iyi_oran


def _fatura_kdv_oranlari(invoice):
    """Faturadaki KDV oranlarini tam sayi kume olarak doner (ornek: {10} ya da
    {10, 20}). `invoice['taxes']` icinde name=KDV olan satirlarin 'percent'
    alanindan alinir (bkz. core/parsing.py - '10.00' gibi string). KDV disi
    vergiler (stopaj vb.) atlanir."""
    oranlar = set()
    for t in invoice.get("taxes", []):
        ad = (t.get("name") or "").upper()
        if "KDV" not in ad:
            continue
        p = t.get("percent")
        if p is None:
            continue
        try:
            oranlar.add(int(round(float(p))))
        except (TypeError, ValueError):
            continue
    return oranlar


def _kdv_orani_isimden(ad):
    """Bir KDV alt kirilim adindan oran (%N) cikarir: '%10 Alistan Iade KDV'
    -> 10, '% 8 Ihrac Kayitli KDV' -> 8. Oran yoksa None (gider/cari adlari)."""
    import re

    m = re.match(r"\s*%\s*(\d+)", ad or "")
    return int(m.group(1)) if m else None


def _kdv_oranini_duzelt(secilen_kod, ana_kod_secenekleri, fatura_oranlari):
    """LLM'in sectigi bir KDV alt kodunun ORANI faturadaki KDV oraniyla
    celisiyorsa, AYNI TUR GRUBU icinde (kodun ilk iki seviyesi, ornek '391.02')
    faturadaki orana uyan kodu doner - yoksa secimi OLDUGU GIBI birakir
    (2026-07-27, kullanici karari: "sadece orani duzelt, turu LLM secsin").

    Deterministik oran duzeltmesi Degismez Kural 1 ile tutarli: oran LLM'in
    serbest tahmininden DEGIL, faturadan gelir. Tur (Indirilecek/Alistan Iade/
    Hesaplanan/Tevkifatli...) LLM'in secimi olarak KORUNUR - sadece ayni tur
    icinde yanlis oran duzeltilir.

    Ornek: LLM 391.02.00020 ('%20 Alistan Iade KDV') sectiyse ama fatura %10 ise,
    ayni grup 391.02 icinde '%10 Alistan Iade KDV' = 391.02.00010'a cevrilir.

    secilen_kod KDV oran kodu degilse (isimde %N yoksa) ya da oran zaten
    faturayla uyumluysa hicbir sey degistirmez."""
    ad_by_kod = {kod: ad for kod, ad in ana_kod_secenekleri}
    secilen_ad = ad_by_kod.get(secilen_kod)
    secilen_oran = _kdv_orani_isimden(secilen_ad)
    if secilen_oran is None or not fatura_oranlari:
        return secilen_kod  # KDV oran kodu degil ya da fatura orani bilinmiyor
    if secilen_oran in fatura_oranlari:
        return secilen_kod  # oran zaten dogru

    # Tur grubu = kodun ilk iki noktali seviyesi ('391.02.00020' -> '391.02').
    parcalar = secilen_kod.split(".")
    if len(parcalar) < 2:
        return secilen_kod
    grup_oneki = ".".join(parcalar[:2]) + "."

    # Ayni grupta, faturadaki oranlardan birine uyan kod var mi?
    for kod, ad in ana_kod_secenekleri:
        if not kod.startswith(grup_oneki):
            continue
        if _kdv_orani_isimden(ad) in fatura_oranlari:
            return kod
    return secilen_kod  # ayni grupta uygun oran yok - guvenli tarafta kal


def predict_single_invoice(
    invoice_xml,
    model=DEFAULT_MODEL_SPEC_STR,
    ollama_host=None,
    sector=DEFAULT_SECTOR,
    own_vkn=DEFAULT_OWN_VKN,
    rag=True,
    self_correct=True,
    tevkifat_hint=True,
    iade_hint=True,
    ihrac_kayitli_hint=True,
    with_glossary=False,
    rag_k=3,
    rag_collection=None,
    rag_persist_dir=None,
    rag_embed_model=None,
    rag_ollama_host=None,
    temperature=0.0,
    timeout=180.0,
    convert_to_try=False,
    alt_kirilim=True,
    parsed_invoice=None,
):
    """Ham bir UBL-TR XML faturasi (string) icin TDHP tahmini uretir.

    parsed_invoice (opsiyonel, 2026-07-29 eklendi): cagiran taraf ayni XML'i
    zaten kendi amaci icin (orn. yon tespiti) parse_invoice_xml_string() ile
    parse ettiyse, sonucu buraya vererek fonksiyonun XML'i TEKRAR parse
    etmesini onler (entegrasyon/app.py -> yon_tespiti.py -> burada -> ve
    dis_sema uretiminde ayni XML 3 kez parse ediliyordu). Verilmezse
    (varsayilan) davranis DEGISMEZ: fonksiyon invoice_xml/own_vkn ile kendi
    parse eder - mevcut tum cagiranlar (core/cli.py, tests/test_single.py)
    etkilenmez. Verilirse invoice_xml/own_vkn SADECE convert_to_try=True
    durumunda tutarlilik kontrolu icin kullanilir (own_vkn parsed_invoice
    uretilirken kullanilanla ayni olmali - cagiran tarafin sorumlulugundadir,
    burada ayrica dogrulanmaz).

    `model`, ya `parse_model_spec()` cikisiyla ayni sekilli bir dict (spec)
    ya da ham bir model string'i ("ollama:gemma4:31b-cloud" gibi,
    core.cli --models ile ayni sozdizimi) olabilir - ikincisi verilirse
    fonksiyon icinde parse_model_spec() ile spec'e cevrilir.

    Varsayilan bayraklar (rag/self_correct/tevkifat_hint/iade_hint=True),
    RESULTS.md'deki en iyi dogrulanmis kombinasyona (n=500, 0.817->0.956
    pair_F1) karsilik gelir - bkz. model_eval/RESULTS.md SS6, CLAUDE.md
    "Kritik gerceklecr". ihrac_kayitli_hint=True (2026-07-23 eklendi) bu
    olcumun DISINDA - kullanici tarafindan onaylanmis bir muhasebe kurali
    (192 Borc / 391 Alacak netleme, sadece istisna kodu 701-704) ama henuz
    RESULTS.md'ye benzer n>1 bir deneyle olculmedi (bkz. core/prompting.py
    compute_ihrac_kayitli_hint docstring'i).

    DB'ye (PostgreSQL/core.reporting) HICBIR SEY yazmaz - cagiran taraf
    donen sozlugu kendi tercih ettigi sekilde saklar/iletir.

    convert_to_try=False (varsayilan, 2026-07-23 eklendi): fatura yabanci
    para biriminde (EUR/USD vb.) olsa bile hicbir cevirme yapilmaz, kayit
    faturanin kendi para biriminde uretilir (mevcut/onceki davranis AYNEN
    korunur). True verilirse, LLM'e gitmeden ONCE core/parsing.py::
    convert_invoice_to_try() ile tum tutarlar XML'in kendi kur oraniyla
    (cac:PricingExchangeRate/CalculationRate) TL'ye cevrilir ve tahmin TL
    uzerinden uretilir. Faturada kur bilgisi yoksa ValueError firlatir -
    cagiran taraf (entegrasyon) bu secimi kullaniciya SORMADAN varsayilan
    olarak True gecmemeli (bkz. entegrasyon/app.py "kur uyarisi" akisi).

    alt_kirilim=True (varsayilan, 2026-07-24 eklendi): ana model 3 haneli
    kodu urettikten SONRA, her benzersiz kod icin core/mizan.py::
    get_alt_kirilimlar() ile SIRKETE OZEL mizan'daki (own_vkn'in tenant
    semasindaki mizan_alt_kirilim tablosu, 2026-08-05'ten itibaren PostgreSQL'de
    - eskiden model_eval/exceller/mizan.xlsx) alt kirilim secenekleri
    cikarilir, TEK bir ek LLM cagrisiyla
    (ayni model spec, ana cagriyla AYNI) hangi alt kirilimin uygun oldugu
    sectirilir - kullanici karari (2026-07-24): "alt kirilimlar her
    muhasebeci icin farkli olabilir, model butun alt kirilimlari bilebilmeli".
    Bir kod icin uygun alt kirilim bulunamazsa (LLM'in ciktisinda o kod
    yoksa) account_code DEGISTIRILMEZ, 3 haneli halinde kalir - alt kirilim
    uydurmaktansa ana kodda kalmak tercih edildi (bkz. core/prompting.py::
    ALT_KIRILIM_SYSTEM_PROMPT). Bu adim hata verirse (LLM cagrisi basarisiz/
    parse edilemez) SESSIZCE 3 haneli koda geri doner - alt kirilim
    basarisizligi ANA tahminin basarisiz sayilmasina yol acmaz."""
    # core/cli.py --ollama-host argumaninin varsayilani hep DEFAULT_OLLAMA_HOST'tur,
    # hicbir zaman None degil - parse_model_spec() ollama_host=None aldiginda
    # base_url=None ureterek call_ollama_messages()'ta host.rstrip("/") ile
    # AttributeError'a yol aciyordu (entegrasyon/ ile uctan uca testte bulundu,
    # bkz. model_eval/project.md SS4.1). ollama_host verilmezse ayni varsayilana dus.
    effective_ollama_host = ollama_host or DEFAULT_OLLAMA_HOST
    spec = model if isinstance(model, dict) else parse_model_spec(model, effective_ollama_host)
    system_prompt = build_glossary_system_prompt() if with_glossary else SYSTEM_PROMPT

    invoice = parsed_invoice if parsed_invoice is not None else parse_invoice_xml_string(
        invoice_xml, own_vkn=own_vkn
    )
    if convert_to_try:
        invoice = convert_invoice_to_try(invoice)

    rag_similar = None
    rag_block = ""
    if rag:
        # rag_common sadece --rag/RAG kullanan cagrilarda import edilir -
        # chromadb/ollama bagimliligini RAG kullanmayan cagiranlara tasimaz
        # (core/runner.py'daki ayni deseni izler).
        import rag_common
        collection = rag_collection
        if collection is None:
            collection = rag_common.get_collection(
                persist_dir=rag_persist_dir or rag_common.DEFAULT_PERSIST_DIR,
                embed_model=rag_embed_model or rag_common.DEFAULT_EMBED_MODEL,
                ollama_host=rag_ollama_host,
            )
        rag_similar = rag_common.retrieve_similar(collection, invoice, k=rag_k)
        block = rag_common.format_few_shot_block(rag_similar)
        rag_block = f"\n{block}\n" if block else ""

    user_prompt = build_user_prompt(
        invoice, sector, tevkifat_hint=tevkifat_hint, rag_block=rag_block, iade_hint=iade_hint,
        ihrac_kayitli_hint=ihrac_kayitli_hint,
    )

    raw, latency, err = call_model(spec, system_prompt, user_prompt, temperature, timeout)
    if err:
        return {
            "invoice_id": invoice["invoice_id"],
            "direction": invoice["direction"],
            "currency": invoice["header"].get("currency"),
            "entries": [],
            "balanced": False,
            "borc_toplam": 0.0,
            "alacak_toplam": 0.0,
            "self_corrected": False,
            "self_correct_reason": None,
            "raw_response": None,
            "error": err,
        }

    entries, parse_err = parse_model_output(raw)
    if parse_err:
        return {
            "invoice_id": invoice["invoice_id"],
            "direction": invoice["direction"],
            "currency": invoice["header"].get("currency"),
            "entries": [],
            "balanced": False,
            "borc_toplam": 0.0,
            "alacak_toplam": 0.0,
            "self_corrected": False,
            "self_correct_reason": None,
            "raw_response": raw[:2000],
            "error": parse_err,
        }

    entry_dicts, totals = _normalize_entries(entries)

    self_corrected = False
    self_correct_reason = None
    if self_correct and spec["provider"] == "ollama":
        correction_request = None
        if not totals["balanced"]:
            correction_request = build_balance_correction_request(
                {"borc_total": totals["borc_toplam"], "alacak_total": totals["alacak_toplam"]}
            )
            self_correct_reason = "balance"
        elif rag_similar is not None:
            # RAG'a guclu bir emsal dustuyse ve model ona uymadiysa (RESULTS.md
            # 6.1/6.2), tek seferlik bir gozden gecirme sansi ver - run_model()
            # icindeki ayni tetikleyiciyle birebir ayni mantik.
            strong = rag_common.strongest_precedent(rag_similar)
            if strong is not None:
                pred_pairs = [(e["account_code"], e["dc"]) for e in entry_dicts]
                correction_request = rag_common.build_precedent_correction_request(strong, pred_pairs)
                self_correct_reason = "precedent_mismatch"

        if correction_request:
            corr_raw, corr_latency, corr_err = self_correct_ollama(
                spec["base_url"], spec["model"], system_prompt, user_prompt, raw, correction_request,
                temperature, timeout,
            )
            if not corr_err:
                corr_entries, corr_parse_err = parse_model_output(corr_raw)
                if not corr_parse_err:
                    entry_dicts, totals = _normalize_entries(corr_entries)
                    self_corrected = True
                    raw = corr_raw
        if not self_corrected:
            self_correct_reason = None

    if alt_kirilim and entry_dicts:
        entry_dicts = _alt_kirilim_uygula(
            invoice, entry_dicts, spec, system_prompt, temperature, timeout, own_vkn,
        )

    return {
        "invoice_id": invoice["invoice_id"],
        "direction": invoice["direction"],
        "currency": invoice["header"].get("currency"),
        "entries": entry_dicts,
        "balanced": totals["balanced"],
        "borc_toplam": totals["borc_toplam"],
        "alacak_toplam": totals["alacak_toplam"],
        "self_corrected": self_corrected,
        "self_correct_reason": self_correct_reason,
        "raw_response": raw[:2000],
        "error": None,
    }


def _alt_kirilim_uygula(invoice, entry_dicts, spec, system_prompt, temperature, timeout, own_vkn):
    """entry_dicts'teki her benzersiz 3 haneli account_code icin, mizan'daki
    alt kirilim secenekleri varsa (kod mizanda hic yoksa o kod atlanir) TEK
    bir ek LLM cagrisiyla dogru alt kirilimi sectirir ve entry_dicts'i GUNCEL
    (yeni sozluk) olarak doner - girdiyi mutate etmez.

    Herhangi bir hata (LLM cagrisi basarisiz, JSON parse edilemez) durumunda
    entry_dicts'i OLDUGU GIBI (3 haneli kodlarla) doner - bu adimin
    basarisizligi ana tahminin error alanini etkilemez, sessizce 3 haneli
    koda geri doner (bkz. predict_single_invoice docstring'i).

    1 KEZ OTOMATIK YENIDEN DENEME (2026-07-24 eklendi, kullanici karari):
    50 gercek faturayla yapilan bir testte (bkz. model_eval/CLAUDE.md) ayni
    fatura/prompt ile tekrar cagrildiginda basarili olan cagrilarin ilk
    denemede GECICI bir nedenle (ag/API hatasi, bos/gecersiz secimler)
    basarisiz oldugu gozlemlendi - LLM'in kendisi tutarli (ayni girdiyle 4/4
    ayni dogru cevap), sorun cagrinin kendisindeydi. Ilk deneme basarisiz
    olursa (err VEYA hic gecerli secim yoksa) TEK bir kez daha ayni prompt
    ile denenir; o da basarisiz olursa (kalici bir sorun oldugu varsayilir)
    sessizce 3 haneli koda donulur - sonsuz retry YAPILMAZ, kullaniciyi
    gereksiz beklemez."""
    alt_kirilimlar_tumu = get_alt_kirilimlar(own_vkn)
    benzersiz_kodlar = {e["account_code"] for e in entry_dicts}
    ilgili_alt_kirilimlar = {
        kod: alt_kirilimlar_tumu[kod] for kod in benzersiz_kodlar if kod in alt_kirilimlar_tumu
    }
    if not ilgili_alt_kirilimlar:
        return entry_dicts

    ana_koddan_alt_koda = {}
    # Her cozulen kodun NEREDEN cozuldugunun izi (2026-07-27) - disa aktarim
    # katmani (core/disa_aktarim.py) bunu insan-okur gerekceye cevirir.
    # {ana_kod: {"kaynak": "fuzzy"|"llm", "benzerlik": float|None,
    #            "oran_duzeltildi": bool}}
    kod_kaynagi = {}

    # 1) DETERMINISTIK FUZZY ESLEME (LLM'den ONCE, sadece CARI hesaplar icin,
    # 2026-07-27 kullanici karari - bkz. memory alt-kirilim-fuzzy-esleme):
    # Cari kodlarda (120/320 gibi) karsi taraf unvanini mizandaki isimlerle
    # isim benzerligine gore esle. Benzerlik CARI_FUZZY_ESIK (%85) uzerindeyse
    # o alt kodu SEC ve LLM'e o kodu HIC SORMA - boylece mizandaki yazim/
    # kisaltma farklari (LLM'in tam-metin arayinca kacirdigi) yakalanir.
    # Esik altinda kalan cari kodlar ile cari OLMAYAN kodlar (191/391/gider vb.)
    # asagidaki normal LLM adimina birakilir.
    karsi_taraf_unvani = invoice["header"].get("account_title")
    for kod in list(ilgili_alt_kirilimlar):
        if kod in CARI_HESAP_KODLARI:
            secilen, oran = _cari_fuzzy_esles(karsi_taraf_unvani, ilgili_alt_kirilimlar[kod])
            if secilen:
                ana_koddan_alt_koda[kod] = secilen
                kod_kaynagi[kod] = {"kaynak": "fuzzy", "benzerlik": oran, "oran_duzeltildi": False}

    # LLM'e sadece fuzzy'nin cozemedigi kodlar sorulur (cozulmus cari kodlari cikar).
    llm_kodlari = {
        kod: sec for kod, sec in ilgili_alt_kirilimlar.items() if kod not in ana_koddan_alt_koda
    }

    # 2) LLM ALT KIRILIM ADIMI (kalan kodlar icin - mevcut davranis, degismedi).
    if not llm_kodlari:
        return _entry_dicts_uygula(
            entry_dicts, ana_koddan_alt_koda, alt_kirilimlar_tumu, kod_kaynagi,
        )

    # Faturadaki KDV oranlari - LLM'in sectigi KDV alt kodunun oranini
    # dogrulamak/duzeltmek icin (asagida _kdv_oranini_duzelt).
    fatura_kdv_oranlari = _fatura_kdv_oranlari(invoice)

    user_prompt = build_alt_kirilim_user_prompt(invoice, entry_dicts, llm_kodlari)
    for _deneme in range(2):
        # LLM turunda yeni cozulen kodlar (retry karari fuzzy'nin cozdukleriyle
        # karismasin diye ayri sozlukte tutulur - fuzzy zaten kod cozmusse
        # "ana_koddan_alt_koda dolu" olmasi LLM'in bos donusunu maskelemesin).
        llm_secimleri = {}
        raw, latency, err = call_model(spec, ALT_KIRILIM_SYSTEM_PROMPT, user_prompt, temperature, timeout)
        if err:
            continue

        parsed = extract_json_block(raw)
        secimler = parsed.get("secimler") if isinstance(parsed, dict) else None
        if not isinstance(secimler, list):
            continue

        for secim in secimler:
            if not isinstance(secim, dict):
                continue
            ana_kod = secim.get("ana_kod")
            alt_kod = secim.get("alt_kod")
            if not ana_kod or not alt_kod:
                continue
            # Secilen alt_kod, o ana kodun GERCEKTEN mizanda listelenen bir
            # secenegi mi kontrol edilir - LLM listede olmayan bir kod uydurmus
            # olabilir, bu durumda o secim yok sayilir (3 haneli kodda kalinir).
            secenekler = llm_kodlari.get(ana_kod, [])
            gecerli_alt_kodlar = {kod for kod, _ad in secenekler}
            if alt_kod in gecerli_alt_kodlar:
                # KDV oran duzeltmesi (2026-07-27): LLM'in sectigi KDV alt kodunun
                # ORANI faturadaki KDV oraniyla celisiyorsa, ayni tur icinde dogru
                # orana cevir (turu koru). KDV disi kodlarda hicbir sey degismez.
                duzeltilmis = _kdv_oranini_duzelt(alt_kod, secenekler, fatura_kdv_oranlari)
                llm_secimleri[ana_kod] = duzeltilmis
                kod_kaynagi[ana_kod] = {
                    "kaynak": "llm",
                    "benzerlik": None,
                    "oran_duzeltildi": duzeltilmis != alt_kod,
                }

        if llm_secimleri:
            ana_koddan_alt_koda.update(llm_secimleri)
            break

    return _entry_dicts_uygula(
        entry_dicts, ana_koddan_alt_koda, alt_kirilimlar_tumu, kod_kaynagi,
    )


def _entry_dicts_uygula(entry_dicts, ana_koddan_alt_koda, alt_kirilimlar_tumu=None, kod_kaynagi=None):
    """Cozulen alt kirilimleri entry_dicts'e uygular ve cozulemeyen CARI
    hesaplara "yeni karsi taraf" uyarisi ekler - girdiyi mutate etmez, yeni
    liste doner. Hem fuzzy-only hem LLM sonrasi yoldan cagrilir.

    2026-07-27: Ayrica her entry'ye `account_description` (mizandaki HESAP ADI)
    ve `secim_kaynagi` (kodun nereden cozuldugu izi) eklenir - ikisi de
    core/disa_aktarim.py'nin diger ekibe gonderilen `records[]` semasini
    (account_description / account_code_reason) uretebilmesi icin. Mizan
    lookup'i icin ters indeks (alt_kod -> ad) kurulur; `alt_kirilimlar_tumu`
    verilmezse aciklama alani atlanir (geriye donuk uyum)."""
    # alt_kod -> ad ters indeksi (mizandaki HESAP ADI sutunu).
    kod_adlari = {}
    if alt_kirilimlar_tumu:
        for _ana, secenekler in alt_kirilimlar_tumu.items():
            for alt_kod, ad in secenekler:
                kod_adlari[alt_kod] = ad
    kod_kaynagi = kod_kaynagi or {}

    sonuc = []
    for e in entry_dicts:
        kod = e["account_code"]
        yeni_kod = ana_koddan_alt_koda.get(kod, kod)
        yeni_e = {**e, "account_code": yeni_kod}
        ad = kod_adlari.get(yeni_kod)
        if ad:
            yeni_e["account_description"] = ad
        iz = kod_kaynagi.get(kod)
        if iz:
            yeni_e["secim_kaynagi"] = iz
        # 3 haneli KALDI mi (nokta yok) VE bu bir cari hesap mi?
        if "." not in yeni_kod and yeni_kod in CARI_HESAP_KODLARI:
            yeni_e["uyari"] = (
                f"Karşı taraf mizanda bulunamadı — {yeni_kod} için alt kırılım "
                "(cari kart) açılmamış olabilir, muhasebeci kontrol etmeli (yeni "
                "müşteri/tedarikçi)."
            )
        sonuc.append(yeni_e)
    return sonuc


def _normalize_entries(entries):
    """core/scoring.py::score_entries()'in AKSINE, `amount` alanini ATMAZ -
    entegrasyon katmani "hangi hesaba ne kadar yazilacagini" gormek
    istiyor. normalize_code3/normalize_dc yine de uygulanir (model
    ciktisindaki serbest formatli kod/yon metnini standartlastirmak icin,
    score_entries ile ayni normalizasyon)."""
    entry_dicts = []
    borc_toplam = 0.0
    alacak_toplam = 0.0
    for e in entries or []:
        if not isinstance(e, dict):
            continue
        code3 = normalize_code3(e.get("account_code"))
        dc = normalize_dc(e.get("dc"))
        if not code3 or not dc:
            continue
        amount = to_float(e.get("amount"))
        entry_dicts.append({"account_code": code3, "dc": dc, "amount": amount})
        if dc == "Borc":
            borc_toplam += amount
        else:
            alacak_toplam += amount

    balanced = abs(borc_toplam - alacak_toplam) < 0.01 and len(entry_dicts) > 0
    return entry_dicts, {
        "balanced": balanced,
        "borc_toplam": round(borc_toplam, 2),
        "alacak_toplam": round(alacak_toplam, 2),
    }
