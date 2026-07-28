"""v2 API — asenkron fatura isleme (202 + job_id deseni).

Tasarim gerekcesi: docs/explanation/v2-api-tasarim-karari.md

v1 (`/fatura/isle`) BOZULMADAN kalir; bu modul ayri bir router olarak
`app.py`'ye baglanir. Muhasebe kaydini ureten kod AYNIDIR
(model_eval_koprusu.tdhp_tahmini_yap) - v2 yalnizca sunum ve akis
katmanini degistirir.

Akis:
    POST /api/v1/invoices              -> 202 { job_id }        (arka planda isle)
    GET  /api/v1/invoices/{job_id}     -> 200 durum + sonuc
    POST /api/v1/invoices/{job_id}/approve -> 202               (XML tekrar gonderilmez)
    GET  /api/v1/health                -> 200
"""

from __future__ import annotations

import logging
import xml.etree.ElementTree as ET
from typing import Literal, Optional

from fastapi import APIRouter, BackgroundTasks, HTTPException, Response
from pydantic import BaseModel, Field

import is_deposu
from model_eval_koprusu import model_eval_hazir_mi, tdhp_tahmini_yap
from v2_semalar import sonucu_v2ye_cevir
from yon_tespiti import FaturaYonuBelirsizHatasi, fatura_yonunu_tespit_et

_logger = logging.getLogger("entegrasyon.v2")

router = APIRouter(prefix="/api/v1", tags=["v2"])


# ---------------------------------------------------------------- semalar


class InvoiceRequest(BaseModel):
    invoice_xml: str = Field(min_length=1, description="UBL-TR fatura XML'i (ham metin)")
    own_vkn: str = Field(
        min_length=10, max_length=11, pattern=r"^\d{10,11}$",
        description="Istegi yapan sirketin VKN'si (10 hane) / TCKN (11 hane)",
    )
    seller_nace_codes: list[str] = Field(
        default_factory=list, description="Saticinin NACE kodlari (yalnizca outbound)"
    )
    currency_mode: Literal["as_is", "try"] = Field(
        default="as_is",
        description="TL disi faturada: 'as_is' kendi para biriminde, 'try' TL'ye cevir",
    )


class JobAccepted(BaseModel):
    job_id: str
    status: str
    message: str


class ApprovalRequest(BaseModel):
    approved: bool = Field(description="KDV uyarisina ragmen devam edilsin mi")


# ------------------------------------------------------------- endpointler


@router.get("/health")
def health():
    """Servisin fatura isleyebilir durumda olup olmadigini bildirir."""
    hazir, mesaj = model_eval_hazir_mi()
    return {"status": "healthy" if hazir else "degraded", "detail": mesaj}


@router.post("/invoices", status_code=202, response_model=JobAccepted)
def fatura_kuyruga_al(istek: InvoiceRequest, arka_plan: BackgroundTasks, response: Response):
    """Faturayi kuyruga alir ve hemen 202 + job_id doner.

    Isleme arka planda yapilir (5-90 sn surebilir) - istemci HTTP baglantisini
    acik tutmak zorunda kalmaz. Durum icin GET /invoices/{job_id}.

    XML burada AYRISTIRILIR (hizli, LLM yok) — bozuk XML'i kuyruga almak
    yerine hemen 400 dondurmek icin. Boylece istemci hatayi aninda ogrenir,
    is olusturulup 'failed' olmasini beklemez."""
    try:
        fatura_yonunu_tespit_et(istek.invoice_xml, istek.own_vkn)
    except ET.ParseError as exc:
        raise HTTPException(status_code=400, detail=f"Gecersiz XML: {exc}") from exc
    except FaturaYonuBelirsizHatasi as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    job_id = is_deposu.is_olustur(istek.model_dump())
    arka_plan.add_task(_isi_calistir, job_id)
    response.headers["Location"] = f"/api/v1/invoices/{job_id}"
    _logger.info("[v2] IS KUYRUGA ALINDI — job_id=%s", job_id)
    return JobAccepted(
        job_id=job_id,
        status="queued",
        message="Fatura kuyruga alindi. Durum icin GET /api/v1/invoices/{job_id}",
    )


@router.get("/invoices/{job_id}")
def is_durumu(job_id: str):
    """Isin durumunu ve (hazirsa) sonucunu doner."""
    kayit = is_deposu.is_getir(job_id)
    if kayit is None:
        raise HTTPException(status_code=404, detail=f"Is bulunamadi: {job_id}")

    cevap = {"job_id": kayit["job_id"], "status": kayit["status"]}
    if kayit["status"] == "failed":
        cevap["error"] = kayit["error"]
    elif kayit["result"] is not None:
        cevap.update(kayit["result"])
    return cevap


@router.post("/invoices/{job_id}/approve", status_code=202, response_model=JobAccepted)
def isi_onayla(job_id: str, istek: ApprovalRequest, arka_plan: BackgroundTasks):
    """KDV uyarisi/kur secimi bekleyen bir isi onaylar ve islemeyi surdurur.

    v1'den en onemli fark: istemci fatura XML'ini TEKRAR GONDERMEZ - saklanan
    istek govdesi kullanilir (500 KB XML ikinci kez agdan gecmez)."""
    kayit = is_deposu.is_getir(job_id)
    if kayit is None:
        raise HTTPException(status_code=404, detail=f"Is bulunamadi: {job_id}")

    # NOT (2026-07-28): v1'de ayri bir "kur onayi bekliyor" asamasi vardi;
    # v2'de YOK cunku `currency_mode` zaten istekte tasiniyor (varsayilan
    # "as_is") - istemciye sormaya gerek kalmiyor, bir tur daha HTTP gidip
    # gelmiyor. Bu yuzden onaylanabilir tek durum "awaiting_approval".
    onaylanabilir = {"awaiting_approval"}
    if kayit["status"] not in onaylanabilir:
        # 409: is bu asamada onay kabul etmiyor (zaten tamamlanmis ya da
        # henuz islenmemis). HTTP semantigi kullanilir, govdede gizlenmez.
        raise HTTPException(
            status_code=409,
            detail=f"Is '{kayit['status']}' durumunda; onay yalnizca "
                   f"{sorted(onaylanabilir)} durumlarinda kabul edilir.",
        )

    if not istek.approved:
        is_deposu.durum_guncelle(
            job_id, "failed", error="Kullanici onaylamadi, islem iptal edildi."
        )
        return JobAccepted(job_id=job_id, status="failed", message="Islem iptal edildi.")

    guncel = dict(kayit["request"])
    guncel["_onaylandi"] = True
    is_deposu.istek_guncelle(job_id, guncel)
    arka_plan.add_task(_isi_calistir, job_id)
    _logger.info("[v2] IS ONAYLANDI — job_id=%s", job_id)
    return JobAccepted(job_id=job_id, status="queued", message="Onay alindi, isleme devam ediyor.")


# ------------------------------------------------------------ arka plan isi


def _isi_calistir(job_id: str) -> None:
    """Arka planda faturayi isler ve is kaydini gunceller.

    Hicbir istisna disari sizmaz - FastAPI BackgroundTasks icinde firlatilan
    bir hata sessizce yutulur ve is sonsuza dek 'processing' kalirdi. Her
    hata 'failed' durumuna yazilir."""
    kayit = is_deposu.is_getir(job_id)
    if kayit is None:
        _logger.error("[v2] is kaybolmus: %s", job_id)
        return

    istek = kayit["request"]
    try:
        is_deposu.durum_guncelle(job_id, "processing")

        yon = fatura_yonunu_tespit_et(istek["invoice_xml"], istek["own_vkn"])
        onaylandi = bool(istek.get("_onaylandi"))

        # --- KDV on kontrolu (yalnizca outbound) ---
        on_filtre = None
        if yon == "outbox":
            from mcp_mimarisi_istemcisi import McpMimarisiErisilemezHatasi, fatura_kontrol_et

            try:
                on_filtre = fatura_kontrol_et(
                    istek["invoice_xml"], istek["own_vkn"], istek.get("seller_nace_codes") or []
                )
            except McpMimarisiErisilemezHatasi as exc:
                is_deposu.durum_guncelle(
                    job_id, "failed", error=f"KDV on kontrol servisi erisilemiyor: {exc}"
                )
                return

            # ------------------------------------------------------------------
            # GECICI: OTOMATIK ONAY (2026-07-28, kullanici karari)
            # ------------------------------------------------------------------
            # Normalde KDV on kontrolu "uygun" donmezse is `awaiting_approval`
            # durumunda DURUR ve insan onayi beklenir. Karsi sistemle onay
            # haberlesmesinin formati henuz kararlastirilmadigi icin bu adim
            # GECICI olarak devre disi: uyari ciksa bile akis kesilmeden devam
            # eder ve sonuca `auto_approved: true` isareti + bir uyari yazilir.
            #
            # ONEMLI: Bu, mevzuat kontrolunun CAYDIRICILIGINI kaldirir - uyari
            # veren faturalar da muhasebe kaydina donusur. Uyari bilgisi
            # `vat_check` alaninda AYNEN korunur (kaybolmaz), cagiran taraf
            # gormeyi tercih ederse oradan okuyabilir.
            #
            # GERI ALMA: Asagidaki `OTOMATIK_ONAY = True` satirini False yapmak
            # yeterli - eski davranis (awaiting_approval) geri doner. Onay
            # endpoint'i (`POST .../approve`) ve is deposu durumu KALDIRILMADI,
            # calisir durumda bekliyor.
            OTOMATIK_ONAY = True

            if on_filtre.get("genel_karar") != "uygun" and not onaylandi:
                if OTOMATIK_ONAY:
                    _logger.warning(
                        "[v2] KDV UYARISI OTOMATIK ONAYLANDI — job_id=%s, karar=%s "
                        "(gecici davranis, bkz. v2_api.py::OTOMATIK_ONAY)",
                        job_id, on_filtre.get("genel_karar"),
                    )
                    onaylandi = True  # akis kesilmeden devam eder
                else:
                    from v2_semalar import _vat_check_v2

                    is_deposu.durum_guncelle(
                        job_id,
                        "awaiting_approval",
                        result={
                            "vat_check": _vat_check_v2(on_filtre),
                            "message": "KDV on kontrolu insan incelemesi gerektiriyor. "
                                       "POST /api/v1/invoices/{job_id}/approve ile onaylayin.",
                        },
                    )
                    return

        # --- Muhasebe kaydi uretimi ---
        tahmin = tdhp_tahmini_yap(
            istek["invoice_xml"],
            own_vkn=istek["own_vkn"],
            convert_to_try=(istek.get("currency_mode") == "try"),
        )

        if tahmin.get("error"):
            is_deposu.durum_guncelle(job_id, "failed", error=tahmin["error"])
            return

        sonuc = sonucu_v2ye_cevir(tahmin, on_filtre, yon)

        # Otomatik onaylanan isleri sonucta ISARETLE (gecici davranis, yukari
        # bakin). Istemcinin bu kayitlarin insan onayindan GECMEDIGINI bilmesi
        # gerekiyor - sessizce "onaylanmis" gibi gostermek yaniltici olurdu.
        if on_filtre and on_filtre.get("genel_karar") != "uygun":
            sonuc["auto_approved"] = True
            sonuc.setdefault("warnings", []).append(
                "KDV on kontrolu uyari verdi ancak islem OTOMATIK ONAYLANDI "
                "(gecici davranis) — kayitlari muhasebeye aktarmadan once "
                "vat_check alanindaki uyarilari inceleyin."
            )
        else:
            sonuc["auto_approved"] = False

        is_deposu.durum_guncelle(job_id, "completed", result=sonuc)
        _logger.info(
            "[v2] IS TAMAMLANDI — job_id=%s, auto_approved=%s",
            job_id, sonuc["auto_approved"],
        )

    except Exception as exc:  # noqa: BLE001
        _logger.exception("[v2] IS BASARISIZ — job_id=%s", job_id)
        is_deposu.durum_guncelle(job_id, "failed", error=f"{type(exc).__name__}: {exc}")
