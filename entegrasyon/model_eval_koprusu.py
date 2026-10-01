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
import hashlib
import uuid
from datetime import datetime, timedelta, timezone

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

# ✅ Uygulandı (2026-09-11, kullanıcı kararı — proje bitene kadar yerelde
# çalıştırma, Ollama'ya SADECE SSH tüneli üzerinden erişilsin): embedding
# (RAG, embeddinggemma) de artık varsayılan olarak tünele yönlendiriliyor.
# ⚠️ Bunun DAHA ÖNCE gerçek testte "Connection reset by peer" hatasına yol
# açtığı biliniyor (bkz. git geçmişi/hafıza notu) — kullanıcı riski bilerek
# kabul edip tekrar denemeyi istedi. Sorun tekrar çıkarsa
# MODEL_EVAL_RAG_OLLAMA_HOST=http://localhost:11434 (yerel) ile geri alınabilir,
# ya da bu sabit tekrar None'a çevrilip rag_common'un kendi yerel
# varsayılanına düşülebilir.
DEFAULT_MODEL_EVAL_RAG_OLLAMA_HOST = os.environ.get(
    "MODEL_EVAL_RAG_OLLAMA_HOST", DEFAULT_MODEL_EVAL_OLLAMA_HOST
)


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


def _tenant_kaynaklarini_coz(own_vkn: str) -> dict:
    """own_vkn'den (2026-07-30, coklu sirket gecisi) sirkete ozel rag_collection'i
    turetir. model_eval'in kendi rag_common modulunu cagirir - isim string'i
    burada UYDURULMAZ, tek dogru kaynak onda kalir. own_vkn DEFAULT_OWN_VKN
    ise (mevcut sirket) eski sabit isme duser, davranis DEGISMEZ.

    2026-08-05: mizan_path artik burada YOK - core/mizan.py Excel'den
    PostgreSQL'e tasindiktan sonra predict_single_invoice() mizan'ini own_vkn'i
    kendisi kullanarak (get_conn(tenant_vkn=own_vkn) ile) DB'den okuyor,
    bu koprunun ayrica bir dosya yolu turetmesine gerek kalmadi."""
    import rag_common

    return {
        "rag_collection": rag_common.get_collection(collection_name=rag_common.koleksiyon_adi_coz(own_vkn)),
    }


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

    # own_vkn'e ozel mizan/RAG kaynaklari (2026-07-30, coklu sirket gecisi) -
    # bkz. _tenant_kaynaklarini_coz docstring'i.
    tenant_kaynaklari = _tenant_kaynaklarini_coz(own_vkn)

    # ollama_host (LLM tahmini icin, gemma4:31b-cloud gibi bulut modeller)
    # tunele gider - bu modeller yerelde yok. rag_ollama_host (embedding,
    # embeddinggemma) da 2026-09-11'den itibaren AYNI tunele yonlendiriliyor
    # (kullanici karari, proje bitene kadar yerel calistirmada Ollama'ya
    # sadece SSH tuneli uzerinden erisim) - DAHA ONCE bu "Connection reset
    # by peer" hatasina yol acmisti (bkz. DEFAULT_MODEL_EVAL_RAG_OLLAMA_HOST
    # yorumu), sorun tekrar cikarsa MODEL_EVAL_RAG_OLLAMA_HOST env var'iyla
    # yerele (http://localhost:11434) geri alinabilir.
    sonuc = predict_single_invoice(
        fatura_xml,
        own_vkn=own_vkn,
        ollama_host=DEFAULT_MODEL_EVAL_OLLAMA_HOST,
        rag_ollama_host=DEFAULT_MODEL_EVAL_RAG_OLLAMA_HOST,
        convert_to_try=convert_to_try,
        parsed_invoice=parsed_invoice,
        rag_collection=tenant_kaynaklari["rag_collection"],
    )

    # Dis ekip semasi (2026-07-27 sozlesmesi): ayni kayitlarin onlarin
    # bekledigi alan adlariyla yazilmis hali. IC sema (`entries`) aynen
    # kalir - `records` ve `dis_sema` ondan TURETILIR, celisemezler.
    from core.disa_aktarim import faturayi_disa_aktar, kayitlari_disa_aktar
    from core.parsing import convert_invoice_to_try, parse_invoice_xml_string

    sonuc["records"] = kayitlari_disa_aktar(sonuc)
    # LLM ciktisinda ayni isimde bir alan bulunsa bile ona guvenilmez.
    # Dogrulama tamamlanana kadar ve yardimci adimlardan biri hata verirse
    # tahmin kesinlikle onaylanamaz durumda kalir.
    sonuc["approvable"] = False
    sonuc["validation_errors"] = []
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
        from core.validation import validate_prediction

        validation = validate_prediction(sonuc, invoice, own_vkn)
        sonuc["validation_errors"] = validation["errors"]
        sonuc["approvable"] = validation["valid"] and not sonuc.get("error")
    except Exception as exc:  # noqa: BLE001
        # Zarf uretimi ANA tahmini etkilemez - records[] zaten hazir, sadece
        # ust bilgiler eksik kalir (alt kirilim adiminin fallback deseniyle
        # ayni: yardimci bir adimin hatasi ana sonucu dusurmez).
        _logger.warning("dis_sema zarfi uretilemedi (records[] etkilenmedi): %s", exc)
        sonuc["approvable"] = False
        sonuc["validation_errors"] = [{
            "code": "VALIDATION_UNAVAILABLE",
            "message": "Deterministik dogrulama tamamlanamadi.",
        }]
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
    reporting.append_result("entegrasyon_onaylandi", kayit, tenant_vkn=own_vkn)

    collection = rag_common.get_collection(collection_name=rag_common.koleksiyon_adi_coz(own_vkn))
    rag_common.upsert_approved_invoice(collection, invoice, tdhp_tahmini.get("entries", []))


def bekleyen_tahmin_kaydet(fatura_xml: str, own_vkn: str, tdhp_tahmini: dict) -> str:
    """Sunucunun urettigi tahmini 30 dakika sureyle onay bekleyen depoya yazar."""
    model_eval_yolunu_ekle()
    from psycopg2.extras import Json
    from core.db import get_conn

    prediction_id = str(uuid.uuid4())
    invoice_id = str(tdhp_tahmini.get("invoice_id") or "?")
    invoice_hash = hashlib.sha256(fatura_xml.encode("utf-8")).hexdigest()
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=30)
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """DELETE FROM model_eval_bekleyen_tahminler
                   WHERE expires_at < now() - interval '1 day'
                     AND status <> 'approved'"""
            )
            cur.execute(
                """INSERT INTO model_eval_bekleyen_tahminler
                   (prediction_id, tenant_vkn, invoice_id, invoice_hash, invoice_xml,
                    prediction, approvable, expires_at)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
                (
                    prediction_id, own_vkn, invoice_id, invoice_hash, fatura_xml,
                    Json(tdhp_tahmini), bool(tdhp_tahmini.get("approvable")), expires_at,
                ),
            )
        conn.commit()
    return prediction_id


class BekleyenTahminHatasi(Exception):
    def __init__(self, message: str, status_code: int):
        super().__init__(message)
        self.status_code = status_code


def bekleyen_tahmini_onayla(prediction_id: str, kimlik) -> str:
    """Tahmini atomik olarak sahiplenir; yalniz dogrulanmis sunucu kaydini onaylar.

    `kimlik` (api_anahtarlari.IstemciKimligi): yalnızca yetkili olduğu
    şirketlerin tahminlerini görebilir; diğerleri "bulunamadı" sayılır."""
    model_eval_yolunu_ekle()
    from core.db import get_conn

    tenant_filtresi = (kimlik.tum_sirketler, list(kimlik.izinli_vknler))
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """UPDATE model_eval_bekleyen_tahminler
                   SET status = 'approving'
                   WHERE prediction_id = %s AND status = 'pending'
                     AND approvable = TRUE AND expires_at > now()
                     AND (%s OR tenant_vkn = ANY(%s))
                   RETURNING invoice_xml, tenant_vkn, prediction, invoice_id""",
                (prediction_id, *tenant_filtresi),
            )
            row = cur.fetchone()
            if row is None:
                cur.execute(
                    """SELECT status, approvable, expires_at <= now()
                       FROM model_eval_bekleyen_tahminler
                       WHERE prediction_id = %s AND (%s OR tenant_vkn = ANY(%s))""",
                    (prediction_id, *tenant_filtresi),
                )
                state = cur.fetchone()
                conn.rollback()
                if state is None:
                    raise BekleyenTahminHatasi("Tahmin bulunamadi.", 404)
                if state[0] == "approved":
                    raise BekleyenTahminHatasi("Tahmin daha once onaylanmis.", 409)
                if state[2]:
                    raise BekleyenTahminHatasi("Tahminin onay suresi dolmus.", 409)
                if not state[1]:
                    raise BekleyenTahminHatasi("Dogrulamadan gecmeyen tahmin onaylanamaz.", 422)
                raise BekleyenTahminHatasi("Tahmin baska bir islem tarafindan onaylaniyor.", 409)
        conn.commit()

    fatura_xml, own_vkn, prediction, invoice_id = row
    try:
        faturayi_onayla(
            fatura_xml,
            own_vkn=own_vkn,
            tdhp_tahmini=prediction,
            onaylandi_zamani=datetime.now(timezone.utc).isoformat(),
        )
    except Exception:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE model_eval_bekleyen_tahminler SET status='pending' WHERE prediction_id=%s AND status='approving'",
                    (prediction_id,),
                )
            conn.commit()
        raise

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """UPDATE model_eval_bekleyen_tahminler
                   SET status='approved', approved_at=now(), invoice_xml=''
                   WHERE prediction_id=%s AND status='approving'""",
                (prediction_id,),
            )
        conn.commit()
    return invoice_id


def kayitli_vknleri_getir() -> list[str]:
    """Arayüzdeki own_vkn input'una öneri göstermek için (2026-07-30, çoklu
    şirket geçişi) — onboard edilmiş tüm şirketlerin VKN'lerini döner.

    DEFAULT_OWN_VKN (mevcut şirket, henüz tenant_<vkn> şemasına göç etmediyse
    public'te duruyor) listeye HER ZAMAN dahil edilir — aksi halde göç
    tamamlanana kadar arayüzde hiç görünmez, ki bu mevcut kullanıcı için
    bir gerileme olurdu. `core.db.kayitli_tenant_vknleri()` sadece
    tenant_<vkn> şemalarını okur, public'i bilmez."""
    model_eval_yolunu_ekle()

    from core.constants import DEFAULT_OWN_VKN
    from core.db import kayitli_tenant_vknleri

    vknler = kayitli_tenant_vknleri()
    if DEFAULT_OWN_VKN not in vknler:
        vknler = [DEFAULT_OWN_VKN] + vknler
    return vknler


def sirket_kayitli_mi(own_vkn: str) -> bool:
    """Şirket onboard edilmiş mi — tek kaynak core.db.tenant_kayitli_mi
    (kayitli_vknleri_getir ile aynı kural: tenant şeması + DEFAULT_OWN_VKN)."""
    model_eval_yolunu_ekle()

    from core.db import tenant_kayitli_mi

    return tenant_kayitli_mi(own_vkn)


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
