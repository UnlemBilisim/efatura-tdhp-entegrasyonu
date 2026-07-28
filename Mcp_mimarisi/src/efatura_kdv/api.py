"""Faz 1 doğrulama katmanı için HTTP API (çok kullanıcılı erişim).

Önceden bu proje sadece Python import ile (test/web_arayuz.py, test
script'leri) kullanılabiliyordu — tek seferde tek kullanıcı. Bu modül,
üst sistemin (TDHP eşleme modülü öncesi) faturayı bağımsız isteklerle
gönderebileceği bir REST API sağlar (bkz. PROJECT.md §3.8).

Mimari karar (2026-07-21, kullanıcı onayı): `NaceOranTablosu` uygulama
başlarken (startup) BİR KEZ PostgreSQL'den yüklenir ve tüm istekler arasında
bellek-içi olarak paylaşılır — her istekte yeniden DB sorgusu atılmaz,
çünkü referans verisi (NACE→oran) nadiren değişir (değiştiğinde
`scripts/excel_to_postgres.py` migrasyonu tekrar çalıştırılıp API yeniden
başlatılır).

Çalıştırma (proje kökünden):

    DATABASE_URL=postgresql://... uvicorn efatura_kdv.api:app \\
        --app-dir src --host 0.0.0.0 --port 8000

Kurulum ve endpoint şeması: docs/how-to/api-calistirma.md,
docs/reference/api-semasi.md.
"""

from __future__ import annotations

import logging
import xml.etree.ElementTree as ET
from contextlib import asynccontextmanager
from typing import Optional

import psycopg2
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from psycopg2.pool import PoolError
from pydantic import BaseModel

from .gecmis_kontrol import (
    GecmisFaturaDeposu,
    GecmisKontrolSonucu,
    fatura_kalemlerini_kayit_icin_hazirla,
    faturayi_gecmise_kaydet,
    gecmis_kontrol_et,
)
from .kalem_nace_esleme import (
    FaturaSatirBazliSonuc,
    SaticiNaceBilgisi,
    SatirKontrolSonucu,
    satir_bazli_kontrol_et,
)
from .nace_kural_kontrolu import NaceOranTablosu
from .ubl_parser import parse_ubl_invoice_from_string

# Uvicorn kendi log handler'larını (uvicorn.error/uvicorn.access) kurar ama
# bu projenin kendi logger'ına ("efatura_kdv.api") bir handler eklemez —
# basicConfig olmadan _logger.info(...) çağrıları hiçbir yere yazdırılmadan
# sessizce yutulurdu (root logger'ın handler'ı yoksa varsayılan davranış).
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)

_state: dict = {}
_logger = logging.getLogger("efatura_kdv.api")


@asynccontextmanager
async def _lifespan(app: FastAPI):
    """Uygulama başlarken NaceOranTablosu'nu bir kez yükleyip paylaşılan
    state'e koyar — her isteğin ayrı DB bağlantısı açmasını önler.
    GecmisFaturaDeposu ise her sorguda hâlâ ayrı bir DB round-trip yapar
    (geçmiş veri büyüyebileceği için tümü belleğe yüklenmez, bkz.
    gecmis_kontrol.py) ama artık her seferinde yeni TCP bağlantısı açmak
    yerine kendi içindeki ThreadedConnectionPool'dan ödünç alıyor (2026-07-22,
    bkz. GOREV_MIMARI_DUZELTME.md #3) — süreç kapanırken `depo.kapat()` ile
    havuzdaki bağlantılar serbest bırakılır."""
    _state["oran_tablosu"] = NaceOranTablosu()
    _state["gecmis_depo"] = GecmisFaturaDeposu()
    yield
    _state["gecmis_depo"].kapat()
    _state.clear()


app = FastAPI(
    title="E-Fatura KDV Doğrulama API'si (Faz 1)",
    description=(
        "UBL-TR e-faturayı NACE+KDV oran kuralına göre doğrular. "
        "Çıktı: uygun / insan_incelemesi_gerekli (bkz. PROJECT.md §0.1)."
    ),
    lifespan=_lifespan,
)


@app.exception_handler(psycopg2.OperationalError)
async def _db_down_handler(request: Request, exc: psycopg2.OperationalError):
    """DB'ye bağlanılamıyor (sunucu kapalı, ağ hatası vb.) — ham `exc` bağlantı
    dizesi/host bilgisi içerebileceği için client'a asla gitmez, sadece
    sunucu logunda tutulur (2026-07-22, bkz. GOREV_MIMARI_DUZELTME.md #4)."""
    _logger.exception("Veritabanına bağlanılamadı")
    return JSONResponse(
        status_code=503,
        content={"detail": "Veritabanına şu an ulaşılamıyor, lütfen daha sonra tekrar deneyin."},
    )


@app.exception_handler(PoolError)
async def _pool_exhausted_handler(request: Request, exc: PoolError):
    """Connection pool tükendiğinde (eşzamanlı istek sayısı `maxconn`'u
    aştığında) client'a 503 döner — pool boyutunu artırmak/istek hızını
    düşürmek gerektiğine işaret eder, 500 gibi beklenmedik bir sunucu
    hatasıyla karıştırılmamalı."""
    _logger.exception("DB connection pool tükendi")
    return JSONResponse(
        status_code=503,
        content={"detail": "Sunucu şu an yoğun, lütfen kısa bir süre sonra tekrar deneyin."},
    )


@app.exception_handler(Exception)
async def _beklenmeyen_hata_handler(request: Request, exc: Exception):
    """Genel yakalayıcı — Starlette, `HTTPException` fırlatıldığında bu
    handler'ı DEĞİL kendi dahili HTTPException handler'ını çağırır (spesifik
    tip her zaman genel `Exception` handler'ından önceliklidir), yani buraya
    sadece gerçekten beklenmeyen (ne DB hatası ne HTTPException olan) durumlar
    düşer. Ham exception metnini client'a SIZDIRMADAN 500 + generic mesaja
    çevirir (önceden api.py'deki `except Exception` ham `exc` metnini
    doğrudan `detail`e koyuyordu — DB şeması, dosya yolu gibi iç detaylar
    client'a sızabiliyordu)."""
    _logger.exception("Beklenmeyen hata")
    return JSONResponse(
        status_code=500,
        content={"detail": "Beklenmeyen bir sunucu hatası oluştu."},
    )


class FaturaKontrolIstegi(BaseModel):
    fatura_xml: str
    satici_vkn: str
    satici_nace_kodlari: list[str]


class SatirSonucCevabi(BaseModel):
    kalem_sira_no: Optional[str]
    kalem_adi: Optional[str]
    beyan_edilen_oranlar: list[float]
    nace_kodlari_kontrol_edildi: list[str]
    izin_verilen_oranlar_havuzu: list[float]
    karar: str
    gerekce: str

    @classmethod
    def from_dataclass(cls, s: SatirKontrolSonucu) -> "SatirSonucCevabi":
        return cls(
            kalem_sira_no=s.kalem_sira_no,
            kalem_adi=s.kalem_adi,
            beyan_edilen_oranlar=s.beyan_edilen_oranlar,
            nace_kodlari_kontrol_edildi=s.nace_kodlari_kontrol_edildi,
            izin_verilen_oranlar_havuzu=s.izin_verilen_oranlar_havuzu,
            karar=s.karar.value,
            gerekce=s.gerekce,
        )


class FaturaKontrolCevabi(BaseModel):
    fatura_no: Optional[str]
    uuid: Optional[str]
    satici_vkn: Optional[str]
    genel_karar: str
    satir_sonuclari: list[SatirSonucCevabi]

    @classmethod
    def from_dataclass(cls, sonuc: FaturaSatirBazliSonuc) -> "FaturaKontrolCevabi":
        return cls(
            fatura_no=sonuc.fatura_no,
            uuid=sonuc.uuid,
            satici_vkn=sonuc.satici_vkn,
            genel_karar=sonuc.genel_karar.value,
            satir_sonuclari=[
                SatirSonucCevabi.from_dataclass(s) for s in sonuc.satir_sonuclari
            ],
        )


class GecmisKontrolIstegiKalemi(BaseModel):
    kalem_adi: str
    beyan_edilen_oranlar: list[float]


class GecmisKontrolIstegi(BaseModel):
    satici_vkn: str
    kalemler: list[GecmisKontrolIstegiKalemi]


class CokluKontrolIstegi(BaseModel):
    fatura_xml_listesi: list[str]
    satici_vkn: str
    satici_nace_kodlari: list[str]


class GecmisOranOzeticevabi(BaseModel):
    oran: float
    kac_kez: int
    son_gorulme_tarihi: Optional[str]


class GecmisKontrolSonucCevabi(BaseModel):
    kalem_adi: Optional[str]
    beyan_edilen_oranlar: list[float]
    gecmis_oranlar: list[GecmisOranOzeticevabi]
    gecmiste_hic_gorulmus_mu: bool
    gecmisle_uyusuyor_mu: Optional[bool]
    bilgi_notu: str

    @classmethod
    def from_dataclass(cls, s: GecmisKontrolSonucu) -> "GecmisKontrolSonucCevabi":
        return cls(
            kalem_adi=s.kalem_adi,
            beyan_edilen_oranlar=s.beyan_edilen_oranlar,
            gecmis_oranlar=[
                GecmisOranOzeticevabi(
                    oran=g.oran, kac_kez=g.kac_kez, son_gorulme_tarihi=g.son_gorulme_tarihi
                )
                for g in s.gecmis_oranlar
            ],
            gecmiste_hic_gorulmus_mu=s.gecmiste_hic_gorulmus_mu,
            gecmisle_uyusuyor_mu=s.gecmisle_uyusuyor_mu,
            bilgi_notu=s.bilgi_notu,
        )


class CokluKontrolFaturaSonucu(BaseModel):
    dosya_index: int
    basarili: bool
    hata: Optional[str] = None
    fatura_kontrol: Optional[FaturaKontrolCevabi] = None
    gecmis_kontrolleri: list[GecmisKontrolSonucCevabi] = []
    gecmise_kaydedildi: bool = False


@app.get("/saglik")
def saglik():
    """Servisin ayakta olup olmadığını ve NaceOranTablosu'nun yüklü olup
    olmadığını bildirir — yük dengeleyici/orkestrasyon sağlık kontrolü için."""
    return {"durum": "ayakta", "nace_tablosu_yuklu": "oran_tablosu" in _state}


def _tek_fatura_kontrol_et(fatura_xml: str, satici_vkn: str, satici_nace_kodlari: list[str]):
    """`/fatura/kontrol-et` ve `/fatura/coklu-kontrol` ortak mantığı — XML'i
    ayrıştırır, NACE kural kontrolünü çalıştırır. Hata durumunda
    (ET.ParseError, genel parse hatası, VKN uyuşmazlığı) HTTPException
    fırlatır; çağıran taraf (coklu-kontrol) bunu yakalayıp fatura başına
    ayrı bir hata kaydına çevirir, tüm isteği düşürmez."""
    _logger.info(
        "[MCP 1/3] İSTEK — satici_vkn=%s, nace_kodlari=%s, xml_boyutu=%d byte",
        satici_vkn, satici_nace_kodlari, len(fatura_xml),
    )
    try:
        fatura = parse_ubl_invoice_from_string(fatura_xml)
    except ET.ParseError as exc:
        _logger.warning("[MCP 1/3] XML PARSE HATASI — %s", exc)
        raise HTTPException(status_code=400, detail=f"Geçersiz XML: {exc}") from exc
    except Exception as exc:
        # xml.etree.ElementTree.fromstring bazı malformed XML'lerde
        # ParseError yerine başka exception tipleri de fırlatabiliyor —
        # istemciye 500 yerine anlamlı bir 400 dönmek için genel yakalama.
        _logger.warning("[MCP 1/3] FATURA AYRIŞTIRMA HATASI — %s", exc)
        raise HTTPException(status_code=400, detail=f"Fatura ayrıştırılamadı: {exc}") from exc

    _logger.info(
        "[MCP 1/3] AYRIŞTIRILDI — fatura_no=%s, satici_vkn(fatura)=%s, kalem_sayisi=%d",
        fatura.fatura_no, fatura.satici.vkn if fatura.satici else None, len(fatura.kalemler),
    )

    satici_nace = SaticiNaceBilgisi(vkn=satici_vkn, nace_kodlari=satici_nace_kodlari)

    _logger.info("[MCP 2/3] NACE KURAL KONTROLÜ ÇALIŞTIRILIYOR — satir_bazli_kontrol_et()")
    try:
        sonuc = satir_bazli_kontrol_et(fatura, satici_nace, _state["oran_tablosu"])
    except ValueError as exc:
        # satir_bazli_kontrol_et VKN uyuşmazlığında ValueError fırlatıyor
        # (bkz. kalem_nace_esleme.py) — bu bir istemci hatasıdır (400).
        _logger.warning("[MCP 2/3] VKN UYUŞMAZLIĞI — %s", exc)
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    _logger.info(
        "[MCP 3/3] SONUÇ — genel_karar=%s, satir_sayisi=%d",
        sonuc.genel_karar.value, len(sonuc.satir_sonuclari),
    )
    for s in sonuc.satir_sonuclari:
        _logger.info(
            "[MCP 3/3]   kalem=%r beyan=%s izin_verilen_havuz=%s → karar=%s",
            s.kalem_adi, s.beyan_edilen_oranlar, s.izin_verilen_oranlar_havuzu, s.karar.value,
        )

    return fatura, sonuc


@app.post("/fatura/kontrol-et", response_model=FaturaKontrolCevabi)
def fatura_kontrol_et(istek: FaturaKontrolIstegi) -> FaturaKontrolCevabi:
    """Ham UBL-TR XML'ini ve satıcının NACE kod(lar)ını alıp kalem bazlı
    KDV oran kontrolü sonucunu döner."""
    _fatura, sonuc = _tek_fatura_kontrol_et(
        istek.fatura_xml, istek.satici_vkn, istek.satici_nace_kodlari
    )
    return FaturaKontrolCevabi.from_dataclass(sonuc)


@app.post("/fatura/gecmis-kontrol", response_model=list[GecmisKontrolSonucCevabi])
def fatura_gecmis_kontrol(istek: GecmisKontrolIstegi) -> list[GecmisKontrolSonucCevabi]:
    """Her kalem için, satıcının geçmişte (outbox faturalarda) bu kalemi
    hangi oran(lar)la kestiğini döner. KARAR ÜRETMEZ — sadece bilgi/uyarı
    notu içerir, /fatura/kontrol-et'in ürettiği karara dokunmaz (bkz.
    PROJECT.md §3.9, gecmis_kontrol.py modül docstring'i). Ayrı bir
    endpoint'tir, ana kontrol akışıyla otomatik tetiklenmez — istemci
    isterse ayrıca çağırır."""
    return [
        GecmisKontrolSonucCevabi.from_dataclass(
            gecmis_kontrol_et(
                istek.satici_vkn, kalem.kalem_adi, kalem.beyan_edilen_oranlar, _state["gecmis_depo"]
            )
        )
        for kalem in istek.kalemler
    ]


@app.post("/fatura/coklu-kontrol", response_model=list[CokluKontrolFaturaSonucu])
def fatura_coklu_kontrol(istek: CokluKontrolIstegi) -> list[CokluKontrolFaturaSonucu]:
    """Aynı satıcı VKN + NACE kod(lar)ıyla BİRDEN FAZLA fatura XML'ini
    kontrol eder — muhasebecinin tek oturumda tek şirketin tüm faturalarını
    toplu yüklemesi için (kullanıcı kararı, 2026-07-21: her oturumda tek
    şirket, o şirketin tüm NACE kodları verilir).

    Her fatura için: (1) NACE kural kontrolü çalışır, (2) her kalem için
    geçmiş çapraz kontrolü çalışır, (3) fatura BAŞARIYLA kontrol edildiyse
    (VKN uyuşmazlığı/parse hatası YOKSA) kalem-oran satırları otomatik
    olarak gecmis_fatura_kalemleri tablosuna kaydedilir.

    Kaydetme güvenli — satir_bazli_kontrol_et() zaten satici_vkn'nin
    faturanın GERÇEK satıcı VKN'siyle eşleştiğini garanti ediyor
    (kalem_nace_esleme.py güvenlik kontrolü, eşleşmezse ValueError→400) —
    yani buraya kadar gelen her fatura kullanıcının KENDİ kestiği
    faturadır (outbox), PROJECT.md §3.9'daki kapsam korunur.

    Bir fatura başarısız olursa (bozuk XML, VKN uyuşmazlığı) TÜM istek
    düşmez — o faturanın sonucu `basarili=false` + `hata` alanıyla
    işaretlenir, diğer faturalar işlenmeye devam eder."""
    sonuclar = []
    for index, fatura_xml in enumerate(istek.fatura_xml_listesi):
        try:
            fatura, sonuc = _tek_fatura_kontrol_et(
                fatura_xml, istek.satici_vkn, istek.satici_nace_kodlari
            )
        except HTTPException as exc:
            sonuclar.append(
                CokluKontrolFaturaSonucu(dosya_index=index, basarili=False, hata=exc.detail)
            )
            continue

        gecmis_kontrolleri = [
            gecmis_kontrol_et(
                istek.satici_vkn, s.kalem_adi or "", s.beyan_edilen_oranlar, _state["gecmis_depo"]
            )
            for s in sonuc.satir_sonuclari
        ]

        kalemler_kayit_icin = fatura_kalemlerini_kayit_icin_hazirla(fatura)
        gecmise_kaydedildi = False
        if kalemler_kayit_icin and fatura.fatura_no:
            gecmise_kaydedildi = faturayi_gecmise_kaydet(
                _state["gecmis_depo"],
                istek.satici_vkn,
                fatura.fatura_no,
                fatura.duzenleme_tarihi,
                kalemler_kayit_icin,
            )

        sonuclar.append(
            CokluKontrolFaturaSonucu(
                dosya_index=index,
                basarili=True,
                fatura_kontrol=FaturaKontrolCevabi.from_dataclass(sonuc),
                gecmis_kontrolleri=[
                    GecmisKontrolSonucCevabi.from_dataclass(g) for g in gecmis_kontrolleri
                ],
                gecmise_kaydedildi=gecmise_kaydedildi,
            )
        )

    return sonuclar
