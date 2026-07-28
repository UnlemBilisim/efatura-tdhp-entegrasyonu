"""Ön filtreleme + TDHP tahmini orkestrasyon servisi (test arayüzü ile).

Akış — YÖNE (inbox/outbox) göre ikiye ayrılır (kullanıcı kararı, 2026-07-22):

    outbox (BİZİM KESTİĞİMİZ fatura — kendi VKN'miz SATICI tarafında):
        [Ham UBL-TR XML]
              |
              v
        Mcp_mimarisi POST /fatura/kontrol-et  (KDV oranı mevzuat ön kontrolü)
              |
              +-- "uygun" ------------------------> model_eval TDHP tahmini
              |
              +-- "insan_incelemesi_gerekli" -----> kullanıcıya UYARI gösterilir
                                                     kullanıcı onaylarsa ------> model_eval TDHP tahmini
                                                     onaylamazsa --------------> durur, insan incelemesi kuyruğu

    inbox (DIŞARIDAN GELEN fatura — kendi VKN'miz ALICI tarafında):
        [Ham UBL-TR XML] ---------------------------------------------------> model_eval TDHP tahmini
        (Mcp_mimarisi HİÇ ÇAĞRILMAZ — ön filtreleme sadece bizim kestiğimiz
        faturalar için tasarlandı, bkz. Mcp_mimarisi/project.md §3.9 "sadece
        outbox" kapsam kararı. İnbox faturalarda doğrudan TDHP tahminine gidilir.)

Yön, faturanın kendi XML'inden tespit edilir (AccountingSupplierParty VKN'si
kullanıcının girdiği own_vkn'e eşitse outbox, AccountingCustomerParty VKN'si
eşitse inbox — bkz. model_eval/core/parsing.py::parse_invoice_xml_string).
Kullanıcı ayrıca bir "bu fatura bize mi ait" seçimi yapmaz, sistem XML'e bakar.

Bu servis Mcp_mimarisi'nin ve model_eval'ın koduna dokunmaz — ikisine de
dışarıdan (HTTP / import) bağlanan bağımsız üçüncü bir bileşendir (bkz.
PROJECT.md §1.1).

Çalıştırma: `uvicorn app:app --reload --port 8100` (bu dizinden).
"""

from __future__ import annotations

import json
import logging
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from mcp_mimarisi_istemcisi import McpMimarisiErisilemezHatasi, fatura_kontrol_et
from model_eval_koprusu import (
    fatura_kur_bilgisi,
    faturayi_onayla,
    model_eval_hazir_mi,
    tdhp_tahmini_yap,
)
from yon_tespiti import FaturaYonuBelirsizHatasi, fatura_yonunu_tespit_et

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
_logger = logging.getLogger("entegrasyon")

app = FastAPI(
    title="Ön Filtreleme + TDHP Tahmini Entegrasyonu",
    description=(
        "Mcp_mimarisi (KDV mevzuat ön filtresi) ile model_eval (TDHP hesap "
        "kodu tahmini) arasındaki orkestrasyon katmanı — test arayüzü dahil."
    ),
)

app.mount("/static", StaticFiles(directory="static"), name="static")

# v2 API (2026-07-27) — dış ekibe teslim edilen sözleşme. v1 endpoint'leri
# (/fatura/isle, /fatura/onayla) BOZULMADAN kalır; kendi test arayüzümüz ve
# 205 test onları kullanıyor. Tasarım gerekçesi:
# docs/explanation/v2-api-tasarim-karari.md
from v2_api import router as v2_router  # noqa: E402

app.include_router(v2_router)


class FaturaIsleIstegi(BaseModel):
    fatura_xml: str
    satici_vkn: str
    """Kullanıcının KENDİ şirketinin VKN'si (fatura üzerindeki gerçek satıcı
    VKN'si değil — fatura outbox ise ikisi aynı olur, inbox ise farklıdır).
    İsim tarihsel nedenlerle 'satici_vkn' kalmıştır (Mcp_mimarisi'nin
    şemasıyla aynı alan adı) ama artık 'own_vkn' anlamında kullanılır."""
    satici_nace_kodlari: list[str] = []
    """Sadece outbox faturalarda (Mcp_mimarisi çağrılırken) kullanılır.
    İnbox faturalarda Mcp_mimarisi hiç çağrılmadığı için gerekmez, boş
    liste bırakılabilir."""
    onay: Optional[bool] = None
    """Kullanıcı 'insan_incelemesi_gerekli' uyarısını görüp yine de devam
    etmek isterse True gönderir. İlk çağrıda (henüz uyarı gösterilmeden)
    None/False olmalı. Sadece outbox akışında anlamlıdır."""
    kur_secimi: Optional[str] = None
    """Fatura TL dışında bir para biriminde ve kur bilgisi taşıyorsa
    kullanıcının 'kur_onayi_bekliyor' uyarısına verdiği cevap:
    'orijinal' (fatura kendi para biriminde işlenir) ya da 'tl' (XML'deki
    kur oranıyla TL'ye çevrilip TDHP tahmini TL üzerinden üretilir). İlk
    çağrıda (henüz uyarı gösterilmeden) None olmalı — bkz. 2026-07-23
    kullanıcı kararı (kur çevirisi sessizce yapılmaz, önce sorulur)."""


class KalemTahmini(BaseModel):
    account_code: str
    dc: str
    amount: float
    uyari: Optional[str] = None
    """Bir cari hesap (120/320 gibi) alt kırılıma çözülemediğinde dolu —
    "karşı taraf mizanda yok, yeni müşteri/tedarikçi olabilir" uyarısı
    (bkz. model_eval/core/single.py::CARI_HESAP_KODLARI). Diğer durumlarda None."""
    account_description: Optional[str] = None
    """Mizandaki HESAP ADI (örn. "%20 İndirilecek KDV") — alt kırılım
    çözüldüyse dolu (bkz. core/single.py::_entry_dicts_uygula)."""


class KayitDisa(BaseModel):
    """Dış ekibin beklediği `records[]` şeması (2026-07-27 sözleşmesi).

    İç `KalemTahmini`'den TÜRETİLİR (core/disa_aktarim.py) — iki şema bilinçli
    olarak ayrı tutulur: iç tarafta `dc`="Borc"/"Alacak" kalır (178 test +
    model_eval_sonuclar tablosu buna bağlı), dışa aktarımda "BORÇ"/"ALACAK"a
    çevrilir."""

    account_code: str
    account_code_type: str
    """'C' = cari hesap (120/320/340/440/159/420), 'G' = diğer."""
    account_description: str
    account_code_reason: str
    """Kodun neden seçildiği — DETERMİNİSTİK üretilir, LLM'e sorulmaz
    (bkz. core/disa_aktarim.py modül docstring'i)."""
    amount: float
    debit_credit: str
    """"BORÇ" / "ALACAK" (iç şemadaki "Borc"/"Alacak"ın dış karşılığı)."""


class TdhpTahminiCevabi(BaseModel):
    invoice_id: Optional[str] = None
    direction: Optional[str] = None
    currency: Optional[str] = None
    """Kayıtların üretildiği para birimi — kur_secimi='tl' seçildiyse TRY,
    aksi halde faturanın kendi para birimi (bkz. core/single.py)."""
    entries: list[KalemTahmini] = []
    records: list[KayitDisa] = []
    """Dış ekip sözleşmesi (2026-07-27) — `entries` ile AYNI kayıtların,
    onların beklediği alan adlarıyla (account_description / account_code_type /
    account_code_reason / debit_credit=BORÇ|ALACAK) yazılmış hâli. İki liste
    aynı çekirdekten üretilir, çelişemezler (bkz. core/disa_aktarim.py)."""
    dis_sema: Optional[dict] = None
    """Dış ekibin beklediği TAM zarf: records + fatura üst bilgileri
    (currency/customer/supplier/invoice_id/issue_date/payable_amount/
    file_path/success). Doğrudan bu alan karşı tarafa gönderilebilir.
    Üretimi başarısız olursa None kalır — `records` yine dolu olur
    (bkz. model_eval_koprusu.py::tdhp_tahmini_yap)."""
    balanced: Optional[bool] = None
    borc_toplam: Optional[float] = None
    alacak_toplam: Optional[float] = None
    self_corrected: Optional[bool] = None
    self_correct_reason: Optional[str] = None
    error: Optional[str] = None


class FaturaOnaylaIstegi(BaseModel):
    fatura_xml: str
    satici_vkn: str
    """own_vkn — yön tespiti ve fatura parse'ı için (bkz. FaturaIsleIstegi)."""
    tdhp_tahmini: "TdhpTahminiCevabi"
    """Kullanıcının 'doğru' dediği TDHP tahmini — /fatura/isle cevabından
    aynen geri gönderilir, sunucu tekrar LLM'e gitmez, sadece kaydeder."""


class FaturaOnaylaCevabi(BaseModel):
    kaydedildi: bool
    mesaj: str


class KurBilgisiCevabi(BaseModel):
    currency: Optional[str] = None
    exchange_rate: Optional[float] = None
    exchange_target_currency: Optional[str] = None


class FaturaIsleCevabi(BaseModel):
    asama: str
    """'on_filtre_insan_incelemesi_bekliyor' | 'kur_onayi_bekliyor' |
    'tdhp_tahmini_tamamlandi' | 'model_eval_hazir_degil'
    (inbox faturalarda ön filtre hiç çalışmaz ama ayrı bir asama değeri
    üretilmez — doğrudan 'tdhp_tahmini_tamamlandi' döner, 'mesaj' alanı
    "ön filtreleme atlandı" diye açıklar; bkz. fatura_isle() satır ~306)"""
    yon: Optional[str] = None
    """'inbox' | 'outbox' — faturanın XML'inden tespit edilen yön."""
    on_filtre_sonucu: Optional[dict] = None
    """Sadece outbox faturalarda dolu — inbox'ta Mcp_mimarisi hiç
    çağrılmadığı için None."""
    kur_bilgisi: Optional[KurBilgisiCevabi] = None
    """Fatura TL dışında bir para biriminde ve kur bilgisi taşıyorsa dolu —
    'kur_onayi_bekliyor' aşamasında kullanıcıya gösterilir."""
    tdhp_tahmini: Optional[TdhpTahminiCevabi] = None
    mesaj: str


@app.get("/")
def index():
    return FileResponse("static/index.html")


@app.get("/durum")
def durum():
    """Test arayüzünün başlangıçta göstereceği hazırlık bilgisi — model_eval
    tarafı henüz eklenmediyse kullanıcı bunu net görsün (sessizce mock
    veri dönülmez)."""
    hazir, mesaj = model_eval_hazir_mi()
    return {"model_eval_hazir": hazir, "model_eval_mesaj": mesaj}


@app.post("/fatura/onayla", response_model=FaturaOnaylaCevabi)
def fatura_onayla(istek: FaturaOnaylaIstegi) -> FaturaOnaylaCevabi:
    """Kullanıcı arayüzde TDHP tahminini görüp 'bu doğru, kaydet' butonuna
    bastığında çağrılır (2026-07-23, kullanıcı kararı). Sunucu tekrar LLM'e
    gitmez — istek zaten önceki /fatura/isle cevabındaki tdhp_tahmini'ni
    taşıyor, burada sadece PostgreSQL + RAG vektör DB'sine yazılır (bkz.
    model_eval_koprusu.py::faturayi_onayla)."""
    onaylandi_zamani = datetime.now(timezone.utc).isoformat()
    _logger.info(
        "[ONAY] İSTEK — invoice_id=%s, kaydedilecek zaman=%s",
        istek.tdhp_tahmini.invoice_id, onaylandi_zamani,
    )
    try:
        faturayi_onayla(
            istek.fatura_xml,
            own_vkn=istek.satici_vkn,
            tdhp_tahmini=istek.tdhp_tahmini.model_dump(),
            onaylandi_zamani=onaylandi_zamani,
        )
    except NotImplementedError as exc:
        _logger.warning("[ONAY] MODEL_EVAL HAZIR DEĞİL — %s", exc)
        raise HTTPException(status_code=501, detail=str(exc)) from exc

    _logger.info("[ONAY] KAYDEDİLDİ — invoice_id=%s", istek.tdhp_tahmini.invoice_id)
    return FaturaOnaylaCevabi(
        kaydedildi=True,
        mesaj="Fatura onaylandı — PostgreSQL'e kaydedildi ve RAG vektör veritabanına eklendi.",
    )


@app.post("/fatura/isle", response_model=FaturaIsleCevabi)
def fatura_isle(istek: FaturaIsleIstegi) -> FaturaIsleCevabi:
    istek_basi = time.monotonic()
    fatura_boyutu = len(istek.fatura_xml)
    _logger.info(
        "[1/5] İSTEK ALINDI — own_vkn=%s, nace_kodlari=%s, xml_boyutu=%d byte, onay=%s",
        istek.satici_vkn, istek.satici_nace_kodlari, fatura_boyutu, istek.onay,
    )

    _logger.info("[2/5] YÖN TESPİTİ — fatura kendi VKN'imizin satıcı/alıcı tarafında olduğu tespit ediliyor")
    try:
        yon = fatura_yonunu_tespit_et(istek.fatura_xml, istek.satici_vkn)
    except FaturaYonuBelirsizHatasi as exc:
        _logger.warning("[2/5] YÖN BELİRSİZ — %s", exc)
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ET.ParseError as exc:
        # Bozuk/geçersiz XML — istemci hatası, 400 döner (2026-07-27: önceki
        # sürümde yakalanmıyordu ve 500 Internal Server Error olarak dışarı
        # çıkıyordu; dış ekip entegrasyonunda yanıltıcıydı).
        _logger.warning("[2/5] XML AYRIŞTIRILAMADI — %s", exc)
        raise HTTPException(
            status_code=400,
            detail=f"Geçersiz XML — belge ayrıştırılamadı: {exc}",
        ) from exc
    _logger.info("[2/5] YÖN TESPİT EDİLDİ — %s", yon)

    if yon == "inbox":
        # Kullanıcı kararı (2026-07-22): dışarıdan gelen faturalarda
        # Mcp_mimarisi'nin KDV/NACE ön filtrelemesi HİÇ ÇALIŞMAZ — sistem
        # sadece bizim kestiğimiz (outbox) faturalar için tasarlandı (bkz.
        # Mcp_mimarisi/project.md §3.9). İnbox'ta doğrudan TDHP tahminine geçilir.
        _logger.info("[3/5] ÖN FİLTRE ATLANDI — inbox fatura, Mcp_mimarisi hiç çağrılmıyor")

        hazir, hazir_mesaji = model_eval_hazir_mi()
        if not hazir:
            _logger.warning("[4/5] MODEL_EVAL HAZIR DEĞİL — %s", hazir_mesaji)
            return FaturaIsleCevabi(
                asama="model_eval_hazir_degil", yon=yon,
                mesaj=f"model_eval tarafı henüz TDHP tahmini üretemiyor: {hazir_mesaji}",
            )

        kur_cevabi = _kur_onayi_gerekiyor_mu(istek, yon)
        if kur_cevabi is not None:
            return kur_cevabi

        _logger.info("[4/5] MODEL_EVAL'A GÖNDERİLİYOR — predict_single_invoice() çağrılıyor (RAG + LLM, uzun sürebilir)")
        t0 = time.monotonic()
        try:
            tahmin = tdhp_tahmini_yap(
                istek.fatura_xml, own_vkn=istek.satici_vkn,
                convert_to_try=(istek.kur_secimi == "tl"),
            )
        except NotImplementedError as exc:
            _logger.warning("[4/5] MODEL_EVAL HAZIR DEĞİL (%.2fs) — %s", time.monotonic() - t0, exc)
            return FaturaIsleCevabi(asama="model_eval_hazir_degil", yon=yon, mesaj=str(exc))

        _log_model_eval_cevabi(tahmin, time.monotonic() - t0, adim="[5/5]")
        _logger.info("TAMAMLANDI (inbox) — toplam süre %.2fs", time.monotonic() - istek_basi)
        return FaturaIsleCevabi(
            asama="tdhp_tahmini_tamamlandi", yon=yon,
            tdhp_tahmini=TdhpTahminiCevabi(**tahmin),
            mesaj="İnbox fatura — ön filtreleme atlandı, doğrudan TDHP tahmini üretildi.",
        )

    # yon == "outbox" — mevcut akış: önce Mcp_mimarisi, sonra (uygunsa) model_eval.
    _logger.info("[3/5] MCP_MIMARISI'NE GÖNDERİLİYOR — POST /fatura/kontrol-et")
    t0 = time.monotonic()
    try:
        on_filtre = fatura_kontrol_et(
            istek.fatura_xml, istek.satici_vkn, istek.satici_nace_kodlari
        )
    except McpMimarisiErisilemezHatasi as exc:
        _logger.error("[3/5] MCP_MIMARISI HATASI (%.2fs) — %s", time.monotonic() - t0, exc)
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except ValueError as exc:
        # Mcp_mimarisi'nin kendi 400 hatası (bozuk XML / VKN uyuşmazlığı).
        _logger.warning("[3/5] MCP_MIMARISI 400 (%.2fs) — %s", time.monotonic() - t0, exc)
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    genel_karar = on_filtre.get("genel_karar")
    satir_sayisi = len(on_filtre.get("satir_sonuclari", []))
    _logger.info(
        "[3/5] MCP_MIMARISI CEVABI (%.2fs) — fatura_no=%s, genel_karar=%s, satir_sayisi=%d",
        time.monotonic() - t0, on_filtre.get("fatura_no"), genel_karar, satir_sayisi,
    )

    devam_etsin = genel_karar == "uygun" or (
        genel_karar == "insan_incelemesi_gerekli" and istek.onay is True
    )

    if not devam_etsin:
        _logger.info(
            "[4/5] KARAR: DURDURULDU — genel_karar=%s, onay=%s → kullanıcıdan onay bekleniyor (toplam %.2fs)",
            genel_karar, istek.onay, time.monotonic() - istek_basi,
        )
        return FaturaIsleCevabi(
            asama="on_filtre_insan_incelemesi_bekliyor", yon=yon,
            on_filtre_sonucu=on_filtre,
            mesaj=(
                "Ön filtreleme sonucu: İNSAN İNCELEMESİ GEREKLİ. "
                "Aşağıdaki kalem(ler)de beyan edilen KDV oranı, satıcının "
                "NACE kod(lar)ının izin verdiği oranlarla uyuşmuyor. "
                "Devam etmek için onay vererek tekrar gönderin."
            ),
        )

    _logger.info(
        "[4/5] KARAR: DEVAM — genel_karar=%s%s → model_eval'a geçiliyor",
        genel_karar, " (kullanıcı onayıyla)" if genel_karar != "uygun" else "",
    )

    hazir, hazir_mesaji = model_eval_hazir_mi()
    if not hazir:
        _logger.warning("[5/5] MODEL_EVAL HAZIR DEĞİL — %s", hazir_mesaji)
        return FaturaIsleCevabi(
            asama="model_eval_hazir_degil", yon=yon,
            on_filtre_sonucu=on_filtre,
            mesaj=(
                "Ön filtreleme tamamlandı ama model_eval tarafı henüz TDHP "
                f"tahmini üretemiyor: {hazir_mesaji}"
            ),
        )

    kur_cevabi = _kur_onayi_gerekiyor_mu(istek, yon, on_filtre_sonucu=on_filtre)
    if kur_cevabi is not None:
        return kur_cevabi

    _logger.info("[5/5] MODEL_EVAL'A GÖNDERİLİYOR — predict_single_invoice() çağrılıyor (RAG + LLM, uzun sürebilir)")
    t0 = time.monotonic()
    try:
        tahmin = tdhp_tahmini_yap(
            istek.fatura_xml, own_vkn=istek.satici_vkn,
            convert_to_try=(istek.kur_secimi == "tl"),
        )
    except NotImplementedError as exc:
        _logger.warning("[5/5] MODEL_EVAL HAZIR DEĞİL (%.2fs) — %s", time.monotonic() - t0, exc)
        return FaturaIsleCevabi(
            asama="model_eval_hazir_degil", yon=yon,
            on_filtre_sonucu=on_filtre,
            mesaj=str(exc),
        )

    _log_model_eval_cevabi(tahmin, time.monotonic() - t0, adim="[5/5]")
    _logger.info("TAMAMLANDI (outbox) — toplam süre %.2fs", time.monotonic() - istek_basi)

    return FaturaIsleCevabi(
        asama="tdhp_tahmini_tamamlandi", yon=yon,
        on_filtre_sonucu=on_filtre,
        tdhp_tahmini=TdhpTahminiCevabi(**tahmin),
        mesaj="Ön filtreden geçti, TDHP tahmini üretildi.",
    )


def _kur_onayi_gerekiyor_mu(
    istek: "FaturaIsleIstegi", yon: str, on_filtre_sonucu: Optional[dict] = None
) -> Optional[FaturaIsleCevabi]:
    """Fatura TL dışında bir para biriminde ve kur bilgisi taşıyorsa,
    kullanıcı henüz bir seçim (kur_secimi) yapmadıysa model_eval'a
    geçmeden ÖNCE durur ve kullanıcıya sorar (kullanıcı kararı,
    2026-07-23): kur çevirisi asla sessizce yapılmaz. Kullanıcı zaten bir
    seçim yaptıysa (kur_secimi='orijinal' ya da 'tl') None döner, akış
    normal şekilde devam eder."""
    if istek.kur_secimi is not None:
        return None

    kur = fatura_kur_bilgisi(istek.fatura_xml, own_vkn=istek.satici_vkn)
    if kur["exchange_rate"] is None:
        # Kur bilgisi yok (TL faturası ya da XML'de PricingExchangeRate hiç
        # yok) — sormaya gerek yok, doğrudan devam.
        return None

    _logger.info(
        "[KUR] Fatura %s cinsinden, kur oranı mevcut (1 %s = %.4f %s) — kullanıcıya soruluyor",
        kur["currency"], kur["currency"], kur["exchange_rate"], kur["exchange_target_currency"],
    )
    return FaturaIsleCevabi(
        asama="kur_onayi_bekliyor", yon=yon,
        on_filtre_sonucu=on_filtre_sonucu,
        kur_bilgisi=KurBilgisiCevabi(**kur),
        mesaj=(
            f"Bu fatura {kur['currency']} cinsinden düzenlenmiş (1 {kur['currency']} = "
            f"{kur['exchange_rate']:.4f} {kur['exchange_target_currency']}). "
            "TDHP tahminini faturanın kendi para biriminde mi (kur_secimi='orijinal') "
            "yoksa TL karşılığı üzerinden mi (kur_secimi='tl') üretmek istediğinizi "
            "seçip tekrar gönderin."
        ),
    )


def _log_model_eval_cevabi(tahmin: dict, sure_s: float, adim: str) -> None:
    if tahmin.get("error"):
        _logger.error("%s MODEL_EVAL HATA DÖNDÜ (%.2fs) — %s", adim, sure_s, tahmin["error"])
    else:
        _logger.info(
            "%s MODEL_EVAL CEVABI (%.2fs) — invoice_id=%s, direction=%s, kalem_sayisi=%d, "
            "balanced=%s, borc=%.2f, alacak=%.2f, self_corrected=%s",
            adim, sure_s, tahmin.get("invoice_id"), tahmin.get("direction"),
            len(tahmin.get("entries", [])), tahmin.get("balanced"),
            tahmin.get("borc_toplam", 0.0), tahmin.get("alacak_toplam", 0.0),
            tahmin.get("self_corrected"),
        )

    # Dış ekibe gidecek JSON'u log'a bas (2026-07-27, kullanıcı isteği):
    # arayüzden fatura yüklendiğinde çıktı terminalden izlenebilsin diye.
    # Hata durumunda da basılır — o zaman success=false görünür, sorunu
    # gizlemek yerine gösterir.
    dis_sema = tahmin.get("dis_sema")
    if dis_sema is not None:
        _logger.info(
            "%s DIŞ EKİP JSON'U:\n%s",
            adim, json.dumps(dis_sema, ensure_ascii=False, indent=2),
        )
    else:
        # records[] yine kullanılabilir; zarf üretimi ayrı bir adım (bkz.
        # model_eval_koprusu.py::tdhp_tahmini_yap).
        _logger.warning("%s dis_sema YOK — records[]: %s", adim, tahmin.get("records"))
