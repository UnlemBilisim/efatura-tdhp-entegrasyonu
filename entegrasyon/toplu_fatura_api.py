"""Toplu fatura işleme: birden fazla faturayı tek zip ile gönder, arka planda işlensin, sonucu sorgula.

    POST /fatura/toplu-isle?satici_vkn=...&onay=...&kur_secimi=...   gövde: ham zip → 202 + is_id
    GET  /fatura/toplu/{is_id}                  özet + yüzde + fatura bazında kısa durum (sayfalı)
    GET  /fatura/toplu/{is_id}/sonuclar         fatura bazında TAM sonuç (records[] dahil, sayfalı)

Zip yapısı: (a) `satici_vkn` verilirse içindeki TÜM `.xml` dosyaları o şirketin faturasıdır (klasör düzeni önemsiz);
(b) verilmezse kökte `<10 haneli vkn>/` klasörleri beklenir (çok şirketli; tek sarmalayıcı klasör tolere edilir).

Her fatura, tek-fatura uç noktasıyla (`POST /fatura/isle`) AYNI iç fonksiyondan geçer (`app._fatura_isle_ic`) — iş mantığı
burada çoğaltılmaz; yalnızca zip açma, kuyruk, kalıcı durum ve yetki eklenir. Aynı eşzamanlılık sınırını
(`fatura_isle_sirasi`) kullanır, yani toplu iş ile tek istekler birbirini ezmez. Toplu işçi sayısı varsayılan olarak
`MAX_ESZAMANLI_ISLEM - 1`'dir (en az 1): bir yuva anlık tek istekler için boş kalır.

Güvenlik/davranış kararları (2026-10-16):
  * Yetki, istek kuyruğa girmeden doğrulanır: zip'teki HER VKN anahtarın kapsamında olmalı (değilse tüm yükleme `403`),
    ve her VKN kayıtlı olmalı (değilse `404`) — tek-fatura uç noktasıyla aynı kurallar.
  * Ön filtre/kur soruları toplu işte etkileşimli sorulamaz: `onay` ve `kur_secimi` TÜM faturalara uygulanır; verilmezse
    ilgili faturalar `on_filtre_insan_incelemesi_bekliyor` / `kur_onayi_bekliyor` sonucuyla biter (hata değildir) ve
    istenirse yalnızca onlar yeni seçeneklerle yeniden gönderilir.
  * Onaylama (kalıcı kayıt + RAG) OTOMATİK YAPILMAZ — onay insan kararıdır; toplu işte üretilen tahminler `/fatura/onayla`
    için uzun süre (varsayılan 24 saat, `TOPLU_TAHMIN_TTL_DAKIKA`) saklanır ki erken biten faturaların süresi dolmasın.
  * Uygulama iş sürerken yeniden başlarsa iş KALDIĞI YERDEN devam eder (ham XML'ler iş bitene kadar diskte durur;
    işlenmiş faturalar yeniden işlenmez). İş bitince ham XML'ler silinir, sonuçlar `TOPLU_SAKLAMA_GUN` gün saklanır."""

from __future__ import annotations

import json
import logging
import os
import queue
import re
import shutil
import tempfile
import threading
import uuid
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from starlette.concurrency import run_in_threadpool

import istek_arsivi
from api_anahtarlari import IstemciKimligi
from auth import require_api_key
from log_ortak import mevcut_request_id
from musteri_onboard_api import (  # güvenli zip açmanın ortak parçaları (tek kaynak)
    MAX_ACILMIS_BAYT, MAX_DOSYA_SAYISI, MAX_SIKISTIRMA_ORANI, VKN_DESENI, ZIP_IMZASI, ZipHatasi, _uye_parcalari,
)
from security import MAX_REQUEST_BYTES, TOPLU_MAX_ZIP_BYTES, TOPLU_YOLU

_logger = logging.getLogger("entegrasyon.toplu")
_audit = logging.getLogger("entegrasyon.audit")

MAX_FATURA = int(os.environ.get("TOPLU_MAX_FATURA", "2000"))
MAX_BEKLEYEN_IS = 5
TAHMIN_TTL_DAKIKA = int(os.environ.get("TOPLU_TAHMIN_TTL_DAKIKA", str(24 * 60)))
SAKLAMA_GUN = int(os.environ.get("TOPLU_SAKLAMA_GUN", "14"))

# FaturaIsleCevabi.asama → toplu sonuç kategorisi (özet sayaçları ve süzme için)
SONUC_KATEGORILERI = {
    "tdhp_tahmini_tamamlandi": "hazir",
    "tdhp_dogrulama_basarisiz": "onaysiz",
    "on_filtre_insan_incelemesi_bekliyor": "onay_bekliyor",
    "kur_onayi_bekliyor": "kur_bekliyor",
    "model_eval_hazir_degil": "hata",
}
TUM_KATEGORILER = ("hazir", "onaysiz", "onay_bekliyor", "kur_bekliyor", "hata")


def veri_dizini() -> Path:
    taban = os.environ.get("ONBOARD_DATA_DIR") or Path(tempfile.gettempdir()) / "efatura-onboarding"
    return Path(taban) / "toplu"


def _simdi() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# --------------------------------------------------------------------------
# Güvenli zip açma (yalnızca .xml)
# --------------------------------------------------------------------------

def _goruntu_adi(parcalar: list) -> str:
    return "/".join(parcalar)[:150]


def faturalari_cikar(zip_yolu: Path, hedef: Path, satici_vkn: Optional[str]) -> dict:
    """Zip'teki `.xml` dosyalarını `hedef/NNNNNN.xml` olarak açar; dosya adı özel karakter/çakışma riski taşımasın diye
    sıra numarasıyla yazılır, özgün ad yalnızca gösterim için saklanır. Dönen:
    {"faturalar": [{"sira", "vkn", "dosya", "yol"}], "atlanan_dosya": N}. Güvensiz/geçersiz zip için ZipHatasi."""
    try:
        zf = zipfile.ZipFile(zip_yolu)
    except zipfile.BadZipFile as exc:
        raise ZipHatasi("Geçerli bir zip dosyası değil.") from exc
    with zf:
        bilgiler = zf.infolist()
        if len(bilgiler) > MAX_DOSYA_SAYISI:
            raise ZipHatasi(f"Zip çok fazla girdi içeriyor (>{MAX_DOSYA_SAYISI}).")
        if any(i.flag_bits & 0x1 for i in bilgiler):
            raise ZipHatasi("Parola korumalı zip desteklenmiyor.")

        uyeler, atlanan = [], 0
        for info in bilgiler:
            parcalar = _uye_parcalari(info.filename)  # güvensizse TÜM zip reddedilir
            if info.is_dir() or not parcalar:
                continue
            if parcalar[0] == "__MACOSX" or parcalar[-1].startswith("._") or parcalar[-1] == ".DS_Store" \
                    or not parcalar[-1].lower().endswith(".xml"):
                atlanan += 1
                continue
            uyeler.append((info, parcalar))

        if satici_vkn is None:
            ust = {p[0] for _, p in uyeler if len(p) > 1}
            if len(ust) == 1 and not VKN_DESENI.match(next(iter(ust))):  # tek sarmalayıcı klasörü tolere et
                uyeler = [(i, p[1:]) for i, p in uyeler if len(p) > 1]

        hedef.mkdir(parents=True, exist_ok=True)
        faturalar, toplam = [], 0
        for info, parcalar in uyeler:
            if satici_vkn is not None:
                vkn, gosterim = satici_vkn, parcalar
            else:
                if len(parcalar) < 2 or not VKN_DESENI.match(parcalar[0]):
                    atlanan += 1  # VKN klasörü dışındaki dosyalar
                    continue
                vkn, gosterim = parcalar[0], parcalar[1:]
            if len(faturalar) >= MAX_FATURA:
                raise ZipHatasi(f"Zip en fazla {MAX_FATURA} fatura içerebilir; birkaç zip'e bölün.")
            if info.file_size > MAX_REQUEST_BYTES:
                raise ZipHatasi(f"Fatura çok büyük (>{MAX_REQUEST_BYTES // (1024 * 1024)} MB): {_goruntu_adi(gosterim)}")
            if info.file_size > 1024 * 1024 and info.file_size / max(info.compress_size, 1) > MAX_SIKISTIRMA_ORANI:
                raise ZipHatasi(f"Şüpheli sıkıştırma oranı (zip bomb olabilir): {_goruntu_adi(gosterim)}")

            sira = len(faturalar) + 1
            yol = hedef / f"{sira:06d}.xml"
            yazilan = 0
            with zf.open(info) as kaynak, open(yol, "wb") as cikti:
                while True:
                    parca = kaynak.read(1024 * 1024)
                    if not parca:
                        break
                    yazilan += len(parca)
                    toplam += len(parca)
                    if yazilan > MAX_REQUEST_BYTES or toplam > MAX_ACILMIS_BAYT:  # başlıktaki boyuta güvenme
                        raise ZipHatasi("Açılmış içerik izin verilen boyutu aşıyor (zip bomb olabilir).")
                    cikti.write(parca)
            faturalar.append({"sira": sira, "vkn": vkn, "dosya": _goruntu_adi(gosterim), "yol": yol.name})
    return {"faturalar": faturalar, "atlanan_dosya": atlanan}


# --------------------------------------------------------------------------
# Kalıcı iş durumu
# --------------------------------------------------------------------------

def ozet_cikar(cevap: dict) -> dict:
    """Tam cevaptan, listede göstermek için kısa özet (records[] hariç)."""
    t = cevap.get("tdhp_tahmini") or {}
    return {
        "asama": cevap.get("asama"), "yon": cevap.get("yon"), "fatura_no": t.get("invoice_id"),
        "approvable": t.get("approvable"), "prediction_id": cevap.get("prediction_id"),
        "red_kodlari": sorted({e.get("code") for e in (t.get("validation_errors") or []) if e.get("code")}),
        "mesaj": (cevap.get("mesaj") or "")[:300],
    }


class TopluDeposu:
    def __init__(self, kok: Path):
        self.kok = kok
        self._kilit = threading.Lock()
        kok.mkdir(parents=True, exist_ok=True)

    def dizin(self, is_id: str) -> Path:
        if not re.fullmatch(r"[0-9a-f]{32}", is_id):
            raise KeyError(is_id)
        return self.kok / is_id

    def _yaz(self, yol: Path, veri: dict) -> None:
        gecici = yol.with_suffix(".tmp")
        gecici.write_text(json.dumps(veri, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(gecici, yol)

    def olustur(self, is_id: str, etiket: str, faturalar: list, onay, kur_secimi, atlanan: int, request_id: Optional[str] = None) -> dict:
        d = self.dizin(is_id)
        veri = {
            "is_id": is_id, "etiket": etiket, "olusturulma": _simdi(), "durum": "kuyrukta",
            "toplam": len(faturalar), "tamamlanan": 0, "sayilar": {k: 0 for k in TUM_KATEGORILER},
            "vknler": sorted({f["vkn"] for f in faturalar}), "onay": onay, "kur_secimi": kur_secimi, "atlanan_dosya": atlanan,
            "request_id": request_id,
        }
        with self._kilit:
            self._yaz(d / "is.json", veri)
            self._yaz(d / "manifest.json", {"faturalar": faturalar})
        return veri

    def getir(self, is_id: str) -> Optional[dict]:
        try:
            yol = self.dizin(is_id) / "is.json"
        except KeyError:
            return None
        with self._kilit:
            veri = json.loads(yol.read_text(encoding="utf-8")) if yol.exists() else None
        if veri is not None:
            veri["yuzde"] = 100 if veri["durum"] == "bitti" else (round(veri["tamamlanan"] * 100 / veri["toplam"]) if veri["toplam"] else 0)
        return veri

    def manifest(self, is_id: str) -> list:
        return json.loads((self.dizin(is_id) / "manifest.json").read_text(encoding="utf-8"))["faturalar"]

    def durum_guncelle(self, is_id: str, durum: str) -> None:
        with self._kilit:
            yol = self.dizin(is_id) / "is.json"
            veri = json.loads(yol.read_text(encoding="utf-8"))
            veri["durum"] = durum
            self._yaz(yol, veri)

    def sonuc_ekle(self, is_id: str, kayit: dict) -> None:
        """Bir faturanın sonucunu sonuclar.jsonl'a EKLER ve sayaçları günceller (kalıcı, bellekte tutulmaz)."""
        with self._kilit:
            d = self.dizin(is_id)
            with open(d / "sonuclar.jsonl", "a", encoding="utf-8") as f:
                f.write(json.dumps(kayit, ensure_ascii=False) + "\n")
            yol = d / "is.json"
            veri = json.loads(yol.read_text(encoding="utf-8"))
            veri["tamamlanan"] += 1
            veri["sayilar"][kayit["sonuc"]] += 1
            self._yaz(yol, veri)

    def sonuclar(self, is_id: str) -> list:
        yol = self.dizin(is_id) / "sonuclar.jsonl"
        if not yol.exists():
            return []
        kayitlar = []
        for satir in yol.read_text(encoding="utf-8").splitlines():
            try:
                kayitlar.append(json.loads(satir))
            except ValueError:
                continue  # çökme anında yarım yazılmış son satır
        return kayitlar

    def bekleyen_sayisi(self) -> int:
        n = 0
        for yol in self.kok.glob("*/is.json"):
            try:
                n += json.loads(yol.read_text(encoding="utf-8"))["durum"] in ("kuyrukta", "calisiyor")
            except (ValueError, KeyError):
                continue
        return n

    def bitmemis_isler(self) -> list:
        sonuc = []
        for yol in sorted(self.kok.glob("*/is.json")):
            try:
                v = json.loads(yol.read_text(encoding="utf-8"))
            except ValueError:
                continue
            if v.get("durum") in ("kuyrukta", "calisiyor"):
                sonuc.append(v["is_id"])
        return sonuc

    def eskileri_temizle(self, gun: int) -> int:
        sinir = datetime.now(timezone.utc) - timedelta(days=gun)
        silinen = 0
        for yol in self.kok.glob("*/is.json"):
            try:
                v = json.loads(yol.read_text(encoding="utf-8"))
                if v["durum"] == "bitti" and datetime.fromisoformat(v["olusturulma"]) < sinir:
                    shutil.rmtree(yol.parent, ignore_errors=True)
                    silinen += 1
            except (ValueError, KeyError):
                continue
        return silinen


# --------------------------------------------------------------------------
# Çalışan
# --------------------------------------------------------------------------

class TopluCalisan:
    """`islem(xml, vkn, dosya_adi, onay, kur_secimi, gonderen) -> FaturaIsleCevabi sözlüğü` enjekte edilir
    (testler LLM/veritabanı olmadan çalışır; üretim bağlantısı app.py'de)."""

    def __init__(self, depo: TopluDeposu, islem: Callable[..., dict], isci_sayisi: int = 1):
        self.depo, self.islem, self.isci_sayisi = depo, islem, max(1, isci_sayisi)
        self.kuyruk: "queue.Queue[str]" = queue.Queue()
        self._threadler: list = []
        self._kilit = threading.Lock()
        self._calisan_isler: set = set()

    def bitmemisleri_kuyrukla(self) -> None:
        """Yeniden başlatma: bitmemiş işler kaldığı yerden devam eder (ham XML'ler duruyorsa); yoksa kapatılır."""
        self.depo.eskileri_temizle(SAKLAMA_GUN)
        for is_id in self.depo.bitmemis_isler():
            if (self.depo.dizin(is_id) / "xml").exists():
                self.kuyruk.put(is_id)
            else:
                self.depo.durum_guncelle(is_id, "bitti")

    def baslat(self) -> None:
        self.bitmemisleri_kuyrukla()
        while len(self._threadler) < self.isci_sayisi:
            t = threading.Thread(target=self._dongu, name=f"toplu-isci-{len(self._threadler)}", daemon=True)
            t.start()
            self._threadler.append(t)

    def ekle(self, is_id: str) -> None:
        self.kuyruk.put(is_id)

    def _dongu(self) -> None:
        while True:
            try:
                is_id = self.kuyruk.get(timeout=3600)
            except queue.Empty:
                # Saatte bir (iş yokken de) eski sonuçlar temizlenir; yalnızca açılışta temizlemek uzun süre açık kalan
                # sunucuda "14 gün saklanır" sözünü tutmazdı.
                self.depo.eskileri_temizle(SAKLAMA_GUN)
                continue
            try:
                self.isle(is_id)
            except Exception:  # noqa: BLE001
                _logger.error("toplu is beklenmedik sekilde coktu is_id=%s", is_id, exc_info=True)

    def isle(self, is_id: str) -> None:
        # Aynı iş iki işçi tarafından çift işlenmesin (yeniden kuyruklama durumlarına karşı).
        with self._kilit:
            if is_id in self._calisan_isler:
                return
            self._calisan_isler.add(is_id)
        try:
            veri = self.depo.getir(is_id)
            if veri is None or veri["durum"] == "bitti":
                return
            self.depo.durum_guncelle(is_id, "calisiyor")
            yapilanlar = {k["sira"] for k in self.depo.sonuclar(is_id)}
            xml_dizini = self.depo.dizin(is_id) / "xml"
            for f in self.depo.manifest(is_id):
                if f["sira"] in yapilanlar:
                    continue
                self._faturayi_isle(is_id, veri, f, xml_dizini)
            self.depo.durum_guncelle(is_id, "bitti")
            shutil.rmtree(xml_dizini, ignore_errors=True)  # ham müşteri faturaları iş bitince silinir
            son = self.depo.getir(is_id)
            _audit.info(json.dumps({"olay": "toplu_fatura_bitti", "is_id": is_id, "istemci": veri["etiket"],
                                    "toplam": son["toplam"], "sayilar": son["sayilar"]}, ensure_ascii=False))
        finally:
            with self._kilit:
                self._calisan_isler.discard(is_id)

    def _faturayi_isle(self, is_id: str, veri: dict, f: dict, xml_dizini: Path) -> None:
        kayit = {"sira": f["sira"], "dosya": f["dosya"], "vkn": f["vkn"]}
        try:
            xml = (xml_dizini / f["yol"]).read_text(encoding="utf-8")
            cevap = self.islem(xml, f["vkn"], f["dosya"], veri["onay"], veri["kur_secimi"], veri["etiket"])
            kayit.update(cevap=cevap, sonuc=SONUC_KATEGORILERI.get(cevap.get("asama"), "hata"), ozet=ozet_cikar(cevap))
        except HTTPException as exc:
            kayit.update(sonuc="hata", cevap=None, hata=str(exc.detail)[:400], http_durum=exc.status_code)
        except UnicodeDecodeError:
            kayit.update(sonuc="hata", cevap=None, hata="Dosya UTF-8 metin olarak okunamadı.")
        except Exception as exc:  # noqa: BLE001
            _logger.error("toplu fatura islenemedi is_id=%s sira=%s", is_id, f["sira"], exc_info=True)
            kayit.update(sonuc="hata", cevap=None, hata=f"Beklenmeyen hata: {type(exc).__name__}")
        self.depo.sonuc_ekle(is_id, kayit)
        # Ham fatura/XML ASLA loglanmaz; yalnızca kimlik ve sonuç kategorisi.
        _audit.info(json.dumps({
            "olay": "toplu_fatura_islendi", "is_id": is_id, "sira": f["sira"], "dosya": f["dosya"], "vkn": f["vkn"],
            "istemci": veri["etiket"], "sonuc": kayit["sonuc"],
            "approvable": (kayit.get("ozet") or {}).get("approvable"), "red_kodlari": (kayit.get("ozet") or {}).get("red_kodlari"),
        }, ensure_ascii=False))


# --------------------------------------------------------------------------
# Bağlantı noktaları (app.py doldurur) ve HTTP uçları
# --------------------------------------------------------------------------

_calisan: Optional[TopluCalisan] = None
_calisan_kilidi = threading.Lock()
_baglanti: dict = {"islem": None, "kayitli_mi": None}


def baglan(islem: Callable[..., dict], kayitli_mi: Callable[[str], bool]) -> None:
    """app.py: tek-fatura iç fonksiyonunu ve şirket-kayıt kontrolünü bağlar (döngüsel import olmasın diye)."""
    _baglanti["islem"], _baglanti["kayitli_mi"] = islem, kayitli_mi


def calisan() -> TopluCalisan:
    global _calisan
    with _calisan_kilidi:
        if _calisan is None:
            varsayilan = int(os.environ.get("MAX_ESZAMANLI_ISLEM", "2"))
            _calisan = TopluCalisan(
                TopluDeposu(veri_dizini()), lambda *a: _baglanti["islem"](*a),
                int(os.environ.get("TOPLU_ISCI_SAYISI", str(max(1, varsayilan - 1)))),
            )
        return _calisan


def calisani_baslat() -> None:
    calisan().baslat()


router = APIRouter()


@router.post(TOPLU_YOLU, status_code=202)
async def toplu_isle(
    request: Request,
    satici_vkn: Optional[str] = Query(default=None, pattern=r"^\d{10}$", description="Zip'teki tüm faturaların şirketi (verilmezse <vkn>/ klasörleri)"),
    onay: Optional[bool] = Query(default=None),
    kur_secimi: Optional[str] = Query(default=None, pattern=r"^(orijinal|tl)$"),
    kimlik: IstemciKimligi = Depends(require_api_key),
) -> dict:
    """Gövde: ham zip. Kimlik ve (veri bilinmeden) anahtar doğrulanır; VKN yetkisi zip açıldıktan sonra, kuyruğa girmeden doğrulanır."""
    c = calisan()
    if c.depo.bekleyen_sayisi() >= MAX_BEKLEYEN_IS:
        raise HTTPException(status_code=429, detail="Bekleyen toplu iş çok fazla; biri bitince tekrar deneyin.")
    if satici_vkn is not None and not kimlik.vkn_izinli_mi(satici_vkn):
        raise HTTPException(status_code=403, detail=f"Bu anahtarın VKN {satici_vkn} adına işlem yetkisi yok.")

    yukleme_dizini = c.depo.kok / "_yuklemeler"
    yukleme_dizini.mkdir(parents=True, exist_ok=True)
    zip_yolu = yukleme_dizini / f"{uuid.uuid4().hex}.zip"
    is_id = uuid.uuid4().hex
    xml_dizini = c.depo.dizin(is_id) / "xml"
    basarili = False
    boyut = 0
    rid = mevcut_request_id()
    try:
        with open(zip_yolu, "wb") as f:
            async for parca in request.stream():
                boyut += len(parca)
                if boyut > TOPLU_MAX_ZIP_BYTES:
                    raise HTTPException(status_code=413, detail="Zip izin verilen boyutu aşıyor.")
                f.write(parca)
        # Gelen dosyanın bir kopyası sınırlı süre arşivlenir (operatör incelemesi; geçersiz zip'ler de — bkz. istek_arsivi.py)
        istek_arsivi.zip_kaydet(rid, zip_yolu, "fatura_toplu", kimlik.etiket, request.client.host if request.client else None, TOPLU_YOLU)
        with open(zip_yolu, "rb") as f:
            if f.read(4) != ZIP_IMZASI:
                raise HTTPException(status_code=400, detail="Gövde bir zip dosyası değil.")
        try:
            sonuc = await run_in_threadpool(faturalari_cikar, zip_yolu, xml_dizini, satici_vkn)
        except ZipHatasi as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        if not sonuc["faturalar"]:
            raise HTTPException(
                status_code=400,
                detail="Zip içinde işlenecek fatura (.xml) bulunamadı. `satici_vkn` verdiyseniz XML'ler zip'te olmalı; "
                       "vermediyseniz kökte <10 haneli VKN>/ klasörleri ve içlerinde .xml dosyaları bekleniyor.",
            )

        vknler = sorted({f["vkn"] for f in sonuc["faturalar"]})
        yetkisiz = [v for v in vknler if not kimlik.vkn_izinli_mi(v)]
        if yetkisiz:  # hiçbir şey kuyruğa girmeden
            raise HTTPException(status_code=403, detail=f"Bu anahtarın şu VKN'ler adına işlem yetkisi yok: {', '.join(yetkisiz)}")
        kayitsiz = [v for v in vknler if not _baglanti["kayitli_mi"](v)]
        if kayitsiz:
            raise HTTPException(status_code=404, detail=f"Şu VKN'ler için kayıtlı şirket yok (önce onboard edilmeli): {', '.join(kayitsiz)}")

        veri = c.depo.olustur(is_id, kimlik.etiket, sonuc["faturalar"], onay, kur_secimi, sonuc["atlanan_dosya"], request_id=rid)
        istek_arsivi.meta_yaz(rid, durum=202, is_id=is_id, vknler=vknler, toplam_fatura=veri["toplam"])
        basarili = True
    except HTTPException as exc:
        istek_arsivi.hata_yaz(rid, exc.status_code, exc.detail)
        raise
    finally:
        zip_yolu.unlink(missing_ok=True)
        if not basarili:
            shutil.rmtree(c.depo.dizin(is_id), ignore_errors=True)

    _audit.info(json.dumps({"olay": "toplu_fatura_basladi", "is_id": is_id, "istemci": kimlik.etiket, "vknler": veri["vknler"],
                            "fatura_sayisi": veri["toplam"], "zip_bayt": boyut}, ensure_ascii=False))
    c.ekle(is_id)
    yanit = {"is_id": is_id, "durum": "kuyrukta", "toplam": veri["toplam"], "vknler": veri["vknler"],
             "atlanan_dosya": veri["atlanan_dosya"]}
    istek_arsivi.cevap_yaz(rid, yanit)
    return yanit


def _is_getir(is_id: str, kimlik: IstemciKimligi) -> dict:
    veri = calisan().depo.getir(is_id)
    if veri is None or veri["etiket"] != kimlik.etiket:  # başkasının işi "yok" gibi davranır
        raise HTTPException(status_code=404, detail="İş bulunamadı.")
    return veri


def _sayfala(liste: list, sayfa: int, boyut: int) -> dict:
    bas = (sayfa - 1) * boyut
    return {"sayfa": sayfa, "boyut": boyut, "toplam_kayit": len(liste), "kayitlar": liste[bas:bas + boyut]}


@router.get("/fatura/toplu/{is_id}")
def toplu_is_durumu(
    is_id: str, sayfa: int = Query(1, ge=1), boyut: int = Query(100, ge=1, le=500),
    sonuc: Optional[str] = Query(default=None, pattern=r"^(hazir|onaysiz|onay_bekliyor|kur_bekliyor|hata)$"),
    kimlik: IstemciKimligi = Depends(require_api_key),
) -> dict:
    veri = _is_getir(is_id, kimlik)
    kisa = [
        {"sira": k["sira"], "dosya": k["dosya"], "vkn": k["vkn"], "sonuc": k["sonuc"], **(k.get("ozet") or {}),
         **({"hata": k["hata"], "http_durum": k.get("http_durum")} if k.get("hata") else {})}
        for k in calisan().depo.sonuclar(is_id) if sonuc is None or k["sonuc"] == sonuc
    ]
    ozet = {k: v for k, v in veri.items() if k != "etiket"}
    return {**ozet, "faturalar": _sayfala(kisa, sayfa, boyut)}


@router.get("/fatura/toplu/{is_id}/sonuclar")
def toplu_sonuclar(
    is_id: str, sayfa: int = Query(1, ge=1), boyut: int = Query(20, ge=1, le=100),
    sonuc: Optional[str] = Query(default=None, pattern=r"^(hazir|onaysiz|onay_bekliyor|kur_bekliyor|hata)$"),
    kimlik: IstemciKimligi = Depends(require_api_key),
) -> dict:
    _is_getir(is_id, kimlik)
    tam = [k for k in calisan().depo.sonuclar(is_id) if sonuc is None or k["sonuc"] == sonuc]
    return _sayfala(tam, sayfa, boyut)
