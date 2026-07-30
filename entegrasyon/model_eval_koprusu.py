"""model_eval'a bağlanan ince köprü modülü.

Bu modül model_eval'ın kod tabanını İMPORT EDER (ayrı süreç değil, ayrı
proje ama aynı Python içinden çağrılır — model_eval/entegrasyon.md'deki
"iki proje kod olarak birleştirilmez" kuralı Mcp_mimarisi ↔ model_eval
arasındaki HTTP ayrımı için geçerli; bu köprü ise zaten model_eval'ın
kendi çalışma alanının bir parçası, entegrasyon/ sadece iki tarafı bir
araya getiren üçüncü bir bileşen).

Durum: model_eval içinde tek-fatura senkron tahmin fonksiyonu
(`core/single.py::predict_single_invoice`) eklendi (2026-07-22). Bu köprü
onu import edip çağırır; model_eval'ın kendi test suite'i (166 test,
`tests/test_single.py` dahil) bağımsız olarak geçmiş durumda.

`model_eval_hazir_mi()` kontrolü, ileride model_eval tarafında bir
regresyon (fonksiyon silinir/yeniden adlandırılırsa) olursa entegrasyon
katmanının sessizce mock veri üretmek yerine yine açık bir hata göstermesi
için korunuyor — normal koşulda hep `True` dönmeli.
"""

from __future__ import annotations

import logging
import os

from model_eval_yolu import MODEL_EVAL_DIR, model_eval_yolunu_ekle

_logger = logging.getLogger("entegrasyon.model_eval_koprusu")

# gemma4:31b-cloud gibi Ollama "bulut" modelleri (ollama.com hesabına bağlı)
# yerel makinede DEĞİL, kullanıcının SSH tüneliyle bağlandığı uzak sunucuda
# (unlem-gx10-01, bkz. sunucu-yönlendirme.md/çalıştırma.txt) çalışıyor.
# Yerel Ollama'da (11434) bu modeller yok, tünel varsayılan olarak 11435'e
# açılıyor (`ssh -N -L 11435:localhost:11434 ...`) — bu yüzden varsayılan
# host burada 11434 değil 11435. Farklı bir tünel/port kullanılıyorsa
# MODEL_EVAL_OLLAMA_HOST env var'ı ile override edilebilir.
DEFAULT_MODEL_EVAL_OLLAMA_HOST = os.environ.get("MODEL_EVAL_OLLAMA_HOST", "http://localhost:11435")


def model_eval_hazir_mi() -> tuple[bool, str]:
    """core/single.py::predict_single_invoice fonksiyonunun eklenip
    eklenmediğini kontrol eder. Import hatasını yutmaz — gerçek durumu
    (hangi dosya/fonksiyon eksik) döner ki arayüzde "muhtemelen çalışır"
    değil, gerçek hata gösterilsin."""
    single_py = MODEL_EVAL_DIR / "core" / "single.py"
    if not single_py.exists():
        return False, f"{single_py} henüz yok — model_eval tarafı henüz eklenmedi."
    model_eval_yolunu_ekle()
    try:
        from core.single import predict_single_invoice  # noqa: F401
    except ImportError as exc:
        return False, f"core/single.py var ama predict_single_invoice import edilemedi: {exc}"
    return True, "hazır"


def tdhp_tahmini_yap(
    fatura_xml: str,
    own_vkn: str,
    convert_to_try: bool = False,
    file_path: str | None = None,
    parsed_invoice: dict | None = None,
) -> dict:
    """Tek bir faturayı model_eval'a TDHP tahmini için gönderir.

    Girdi: ham UBL-TR XML string'i (Mcp_mimarisi'nden aynen aktarılır) +
    şirketin kendi VKN'si (inbox/outbox yönü tespiti için).

    convert_to_try=False (varsayılan): fatura kendi para biriminde
    (EUR/USD vb. olsa bile) işlenir, hiçbir çevirme yapılmaz — mevcut
    davranış. True verilirse (kullanıcı arayüzdeki "TL'ye çevir" uyarısını
    onayladıysa — bkz. app.py), core/single.py kur oranıyla TL'ye çevirip
    tahmini TL üzerinden üretir. Faturada kur bilgisi yoksa ValueError
    fırlatır (bkz. core/parsing.py::convert_invoice_to_try).

    parsed_invoice (opsiyonel, 2026-07-29 eklendi): çağıran taraf (app.py)
    aynı XML'i zaten yön tespiti için parse_invoice_xml_string() ile parse
    ettiyse, sonucu buraya vererek hem predict_single_invoice'ın hem dış
    şema (dis_sema) üretiminin XML'i TEKRAR parse etmesini önler — aynı
    fatura_xml/own_vkn ile üç kez (yon_tespiti, core/single.py, burada)
    parse ediliyordu. Verilmezse (varsayılan) davranış DEĞİŞMEZ: bu
    fonksiyon kendi parse eder. own_vkn'in parsed_invoice üretilirken
    kullanılanla aynı olması çağıran tarafın sorumluluğundadır.

    Çıktı: core/single.py::predict_single_invoice'in döndürdüğü sözlük
    (kod+yön+tutar+para birimi üçlüsü, bkz. entegrasyon/README.md).

    predict_single_invoice henüz yoksa NotImplementedError fırlatır —
    çağıran taraf (app.py) bunu HTTP 501'e çevirir kullanıcıya gösterir."""
    hazir, mesaj = model_eval_hazir_mi()
    if not hazir:
        raise NotImplementedError(
            f"model_eval tarafı henüz hazır değil: {mesaj} "
            "(bkz. entegrasyon/README.md — model_eval agent'ına iletilecek görev)"
        )

    from core.single import predict_single_invoice

    # ollama_host (LLM tahmini icin, gemma4:31b-cloud gibi bulut modeller)
    # tunele gitmeli - bu modeller yerelde yok. rag_ollama_host (embedding,
    # embeddinggemma) ise BILEREK tunele YONLENDIRILMEZ - embeddinggemma
    # yerelde zaten kurulu (bkz. mimari.md SS4, "veri gizliligi gerekcesiyle
    # yerelde calisir"), tunel uzerinden gondermek gereksiz network riski
    # (baglanti kopmasi/gecikme) ekliyordu, gercek testte "Connection reset
    # by peer" hatasina yol acti - rag_ollama_host=None birakilarak
    # rag_common'un kendi varsayilanina (yerel 11434) dusmesi saglaniyor.
    sonuc = predict_single_invoice(
        fatura_xml,
        own_vkn=own_vkn,
        ollama_host=DEFAULT_MODEL_EVAL_OLLAMA_HOST,
        convert_to_try=convert_to_try,
        parsed_invoice=parsed_invoice,
    )

    # Dis ekip semasi (2026-07-27 sozlesmesi): ayni kayitlarin onlarin
    # bekledigi alan adlariyla yazilmis hali. IC sema (`entries`) aynen
    # kalir - `records` ve `dis_sema` ondan TURETILIR, celisemezler.
    from core.disa_aktarim import faturayi_disa_aktar, kayitlari_disa_aktar
    from core.parsing import convert_invoice_to_try, parse_invoice_xml_string

    sonuc["records"] = kayitlari_disa_aktar(sonuc)
    try:
        # Fatura ust bilgileri (customer/supplier/issue_date/payable_amount)
        # icin: parsed_invoice verildiyse TEKRAR parse ETMEDEN onu kullan,
        # verilmediyse (eski davranis) burada parse et - ayrica bir XML
        # parser YAZILMAZ, tek dogru kaynak core/parsing.py'dir.
        invoice = parsed_invoice if parsed_invoice is not None else parse_invoice_xml_string(
            fatura_xml, own_vkn=own_vkn
        )
        # convert_to_try=True ise ZARFI DA cevir (2026-07-27 duzeltmesi):
        # predict_single_invoice tutarlari TL'ye cevirip `entries`i TL uretiyor,
        # ama burada fatura SIFIRDAN ayristirildigi icin header hala orijinal
        # para biriminde kaliyordu - sonuc: records[] TL, zarftaki
        # currency/payable_amount EUR (11.594 EUR faturaya 618.978 TL kayit
        # gorunuyordu, 53 kat tutarsizlik). Ayni cevrimi burada da uygula.
        if convert_to_try:
            invoice = convert_invoice_to_try(invoice)
        sonuc["dis_sema"] = faturayi_disa_aktar(sonuc, invoice, own_vkn, file_path=file_path)
    except Exception as exc:  # noqa: BLE001
        # Zarf uretimi ANA tahmini etkilemez - records[] zaten hazir, sadece
        # ust bilgiler eksik kalir (alt kirilim adiminin fallback deseniyle
        # ayni: yardimci bir adimin hatasi ana sonucu dusurmez).
        _logger.warning("dis_sema zarfi uretilemedi (records[] etkilenmedi): %s", exc)
    return sonuc


def faturayi_onayla(fatura_xml: str, own_vkn: str, tdhp_tahmini: dict, onaylandi_zamani: str) -> None:
    """Kullanıcı arayüzde 'bu doğru' butonuna bastığında çağrılır (2026-07-23,
    kullanıcı kararı). İki ayrı yere yazar:

    1. PostgreSQL (`core/reporting.py::append_result`, `model_eval_sonuclar`
       tablosu, `file_label="entegrasyon_onaylandi"`) — denetim/kayıt amaçlı.
       Kullanıcı kararı: aynı fatura birden fazla kez onaylanırsa tekrar
       kontrolü YAPILMAZ, her onay ayrı bir satır olarak birikir — sadece
       `onaylandi_zamani` alanı kaydedilir ki ileride geçmiş/yinelenen
       kayıtlar istenirse tarihe göre temizlenebilsin.
    2. ChromaDB RAG koleksiyonu (`rag_common.upsert_approved_invoice`) —
       onaylanan tahmin, gelecekteki benzer faturalar için few-shot örneği
       olarak kullanılabilsin diye. Bu YAZMA, `build_vector_db.py`'nin
       "sadece Archive2/jsons ground-truth'u indeksle" kuralını GENİŞLETİYOR
       — kullanıcı onayı da bir tür ground-truth sayılıyor. invoice_id ile
       upsert edilir (aynı fatura tekrar onaylanırsa ChromaDB kaydı
       GÜNCELLENİR, PostgreSQL'deki gibi çoğalmaz — ikisi kasıtlı olarak
       farklı davranıyor, bkz. rag_common.py::upsert_approved_invoice
       docstring'i).

    model_eval hazır değilse (predict_single_invoice yoksa) NotImplementedError
    fırlatır — app.py bunu yakalayıp kullanıcıya gösterir, sessizce
    yutmaz."""
    hazir, mesaj = model_eval_hazir_mi()
    if not hazir:
        raise NotImplementedError(
            f"model_eval tarafı henüz hazır değil: {mesaj}"
        )

    model_eval_yolunu_ekle()

    from core import reporting
    from core.parsing import parse_invoice_xml_string
    import rag_common

    invoice = parse_invoice_xml_string(fatura_xml, own_vkn=own_vkn)

    kayit = {
        "invoice_id": tdhp_tahmini.get("invoice_id") or invoice["invoice_id"],
        "direction": tdhp_tahmini.get("direction") or invoice["direction"],
        "currency": tdhp_tahmini.get("currency"),
        "entries": tdhp_tahmini.get("entries", []),
        "balanced": tdhp_tahmini.get("balanced"),
        "borc_toplam": tdhp_tahmini.get("borc_toplam"),
        "alacak_toplam": tdhp_tahmini.get("alacak_toplam"),
        "onaylandi_zamani": onaylandi_zamani,
        "error": None,
    }
    reporting.append_result("entegrasyon_onaylandi", kayit)

    collection = rag_common.get_collection()
    rag_common.upsert_approved_invoice(collection, invoice, tdhp_tahmini.get("entries", []))


def fatura_kur_bilgisi(fatura_xml: str, own_vkn: str) -> dict:
    """Faturanın para birimi/kur oranını, TDHP tahminine geçmeden ÖNCE
    kontrol etmek için (bkz. app.py — TL olmayan faturada kullanıcıya
    uyarı gösterip "TL'ye çevir" seçeneği sunulur). model_eval'ın kendi
    parse_invoice_xml_string'ini kullanır, ayrı bir XML ayrıştırma
    mantığı yazmaz (bkz. yon_tespiti.py'deki aynı desen)."""
    model_eval_yolunu_ekle()

    from core.parsing import parse_invoice_xml_string

    invoice = parse_invoice_xml_string(fatura_xml, own_vkn=own_vkn)
    h = invoice["header"]
    return {
        "currency": h.get("currency"),
        "exchange_rate": h.get("exchange_rate"),
        "exchange_target_currency": h.get("exchange_target_currency"),
    }
