"""Çok şirketli zip ile müşteri (şirket) onboarding uç noktası.

    POST /musteri/onboard        zip yüklenir → 202 + is_id (hemen döner)
    GET  /musteri/isler/{is_id}  ilerleme + şirket bazında sonuç

Zip yapısı (kökte `<vkn>/` klasörleri; tek bir sarmalayıcı klasör tolere edilir):

    <vkn>/mizan.xlsx
    <vkn>/faturalar/*.xml
    <vkn>/yevmiye.xlsx  (ya da yevmiye.csv)
    <vkn>/nace.txt      (opsiyonel)

Asıl onboarding mantığı DEĞİŞMEDİ: `scripts/musteri_onboard_toplu.py`
(şema + mizan + yevmiye eşleştirme + RAG) şirket başına aynen çağrılır — burada
yeniden yazılmaz. Bu modül yalnızca güvenli zip açma, kuyruklama, kalıcı iş
durumu ve yetkiyi ekler.

Güvenlik kararları (2026-10-06, kullanıcı onayıyla; 2026-10-16'da güncelleme eklendi):
  * KAYITLI şirket (2026-10-16, kullanıcı kararı): zip tekrar gelirse artık işlenir — gelen veri mevcutla KARŞILAŞTIRILIR, yalnızca
    fark uygulanır (fark yoksa hiçbir şey yazılmaz), eski değer + güncellenme zamanı veritabanında loglanır
    (`model_eval/core/onboarding_guncelleme.py`). Önceki karar ("kayıtlı şirket atlanır, üzerine yazılmaz") şu GÜVENCEYLE
    gevşetildi: güncelleme yalnızca anahtarın o VKN adına yetkili olduğu durumda yapılır (`vkn_izinli_mi`); aksi halde şirket
    `atlandi` olur, hiçbir şey değiştirilmez. Yani onboard yetkisi olan BAŞKA bir müşavir, kapsamında olmayan bir şirketin
    mizanını/emsallerini değiştiremez.
  * AYNI anahtarın daha önce başlatıp yarım bıraktığı kurulum yeniden denenir (kurulum idempotent).
  * Yalnızca `onboard_yetkisi` verilmiş anahtarlar kullanabilir
    (`auth.py::require_onboard_yetkisi`); başarılı KURULUMDA yeni VKN o anahtarın kapsamına eklenir.
  * Zip güvenli açılır: zip-slip, zip bomb, dosya sayısı/boyut sınırı, yalnızca
    izinli dosya adları; dosyalar `extractall` ile değil tek tek, gerçek bayt
    sayısı sayılarak yazılır (başlıktaki boyut güvenilmez)."""

from __future__ import annotations

import importlib.util
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
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from starlette.concurrency import run_in_threadpool

from api_anahtarlari import IstemciKimligi
from auth import require_onboard_yetkisi
from security import ONBOARD_MAX_ZIP_BYTES, ONBOARD_YOLU

_logger = logging.getLogger("entegrasyon.onboard")
_audit = logging.getLogger("entegrasyon.audit")

MAX_DOSYA_SAYISI = 20000
MAX_ACILMIS_BAYT = int(os.environ.get("ONBOARD_MAX_ACILMIS_BYTES", str(1024 * 1024 * 1024)))
MAX_TEK_DOSYA_BAYT = 100 * 1024 * 1024
MAX_SIKISTIRMA_ORANI = 300  # yalnızca >1 MB açılmış dosyalarda uygulanır
MAX_BEKLEYEN_IS = 5

VKN_DESENI = re.compile(r"^\d{10}$")  # anahtar deposu da yalnızca 10 haneli VKN kabul eder
KOK_DOSYALARI = {"mizan.xlsx", "yevmiye.xlsx", "yevmiye.csv", "nace.txt"}
ZIP_IMZASI = b"PK\x03\x04"


class ZipHatasi(ValueError):
    """Zip geçersiz ya da güvensiz — istek 400 ile reddedilir, hiçbir şey yazılmaz."""


# --------------------------------------------------------------------------
# Güvenli zip açma
# --------------------------------------------------------------------------

def _uye_parcalari(ad: str) -> list:
    if "\\" in ad or ad.startswith("/") or re.match(r"^[A-Za-z]:", ad) or "\x00" in ad:
        raise ZipHatasi(f"Güvensiz dosya yolu: {ad[:80]!r}")
    parcalar = [p for p in ad.split("/") if p not in ("", ".")]
    if ".." in parcalar:
        raise ZipHatasi(f"Güvensiz dosya yolu (..): {ad[:80]!r}")
    return parcalar


def zip_guvenli_ac(zip_yolu: Path, hedef: Path) -> dict:
    """Zip'i `hedef/<vkn>/...` altına açar. Dönen: {"vknler": [...], "atlanan_dosya": N,
    "gecersiz_klasorler": [...]}. Geçersiz/güvensiz zip için ZipHatasi."""
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

        uyeler = []  # (info, parcalar)
        atlanan = 0
        for info in bilgiler:
            parcalar = _uye_parcalari(info.filename)  # güvensizse tüm zip reddedilir
            if info.is_dir() or not parcalar:
                continue
            if parcalar[0] == "__MACOSX" or parcalar[-1].startswith("._") or parcalar[-1] == ".DS_Store":
                atlanan += 1
                continue
            uyeler.append((info, parcalar))

        # Tek bir VKN-olmayan sarmalayıcı klasörü (macOS "Sıkıştır" gibi) tolere et.
        ust_klasorler = {p[0] for _, p in uyeler if len(p) > 1}
        if len(ust_klasorler) == 1 and not VKN_DESENI.match(next(iter(ust_klasorler))):
            uyeler = [(i, p[1:]) for i, p in uyeler if len(p) > 1]

        hedef.mkdir(parents=True, exist_ok=True)
        toplam = 0
        vknler: set = set()
        gecersiz_klasorler: set = set()
        fatura_sayac: dict = {}
        for info, parcalar in uyeler:
            if len(parcalar) < 2:
                atlanan += 1  # kökteki dosyalar (VKN klasörü dışı)
                continue
            vkn, ic = parcalar[0], parcalar[1:]
            if not VKN_DESENI.match(vkn):
                gecersiz_klasorler.add(vkn)
                atlanan += 1
                continue
            ic_ad = [p.lower() for p in ic]
            if len(ic) == 1 and ic_ad[0] in KOK_DOSYALARI:
                hedef_dosya = hedef / vkn / ic_ad[0]
            elif len(ic) == 2 and ic_ad[0] == "faturalar" and ic_ad[1].endswith(".xml"):
                # Dosya adı önemsiz (fatura no XML içinden okunur) — sıra numarasıyla yaz:
                # özel karakter/çakışma riskini baştan ortadan kaldırır.
                n = fatura_sayac[vkn] = fatura_sayac.get(vkn, 0) + 1
                hedef_dosya = hedef / vkn / "faturalar" / f"{n:06d}.xml"
            else:
                atlanan += 1
                continue

            if info.file_size > MAX_TEK_DOSYA_BAYT:
                raise ZipHatasi(f"Dosya çok büyük: {'/'.join(parcalar)[:80]}")
            if info.file_size > 1024 * 1024 and info.file_size / max(info.compress_size, 1) > MAX_SIKISTIRMA_ORANI:
                raise ZipHatasi(f"Şüpheli sıkıştırma oranı (zip bomb olabilir): {'/'.join(parcalar)[:80]}")

            hedef_dosya.parent.mkdir(parents=True, exist_ok=True)
            yazilan = 0
            with zf.open(info) as kaynak, open(hedef_dosya, "wb") as cikti:
                while True:
                    parca = kaynak.read(1024 * 1024)
                    if not parca:
                        break
                    yazilan += len(parca)
                    toplam += len(parca)
                    # Başlıktaki boyuta güvenme — gerçekte yazılan bayt sayılır.
                    if yazilan > MAX_TEK_DOSYA_BAYT or toplam > MAX_ACILMIS_BAYT:
                        raise ZipHatasi("Açılmış içerik izin verilen boyutu aşıyor (zip bomb olabilir).")
                    cikti.write(parca)
            vknler.add(vkn)

    return {"vknler": sorted(vknler), "atlanan_dosya": atlanan, "gecersiz_klasorler": sorted(gecersiz_klasorler)}


# --------------------------------------------------------------------------
# Kalıcı iş durumu
# --------------------------------------------------------------------------

def veri_dizini() -> Path:
    return Path(os.environ.get("ONBOARD_DATA_DIR") or Path(tempfile.gettempdir()) / "efatura-onboarding")


def _simdi() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class IsDeposu:
    """İş durumunu diske (JSON) yazar — uygulama yeniden başlasa da sonuç kaybolmaz."""

    def __init__(self, kok: Path):
        self.kok = kok
        self._kilit = threading.Lock()
        (kok / "isler").mkdir(parents=True, exist_ok=True)
        (kok / "kurulumlar").mkdir(parents=True, exist_ok=True)

    def _is_yolu(self, is_id: str) -> Path:
        if not re.fullmatch(r"[0-9a-f]{32}", is_id):
            raise KeyError(is_id)
        return self.kok / "isler" / f"{is_id}.json"

    def _yaz(self, yol: Path, veri: dict) -> None:
        gecici = yol.with_suffix(".tmp")
        gecici.write_text(json.dumps(veri, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(gecici, yol)

    def olustur(self, etiket: str, vknler: list, atlanan_dosya: int, gecersiz_klasorler: list, guncelleme_yetkisiz: Optional[list] = None) -> dict:
        is_id = uuid.uuid4().hex
        veri = {
            "is_id": is_id, "etiket": etiket, "olusturulma": _simdi(), "durum": "kuyrukta",
            "atlanan_dosya": atlanan_dosya, "gecersiz_klasorler": gecersiz_klasorler,
            "guncelleme_yetkisiz": sorted(guncelleme_yetkisiz or []),
            "sirketler": {v: {"durum": "bekliyor", "yuzde": 0, "adim": None, "ayrinti": None, "ozet": None} for v in vknler},
        }
        with self._kilit:
            self._yaz(self._is_yolu(is_id), veri)
        return veri

    def getir(self, is_id: str) -> Optional[dict]:
        try:
            yol = self._is_yolu(is_id)
        except KeyError:
            return None
        with self._kilit:
            veri = json.loads(yol.read_text(encoding="utf-8")) if yol.exists() else None
        if veri is not None:
            veri["yuzde"] = self._genel_yuzde(veri)
        return veri

    @staticmethod
    def _genel_yuzde(veri: dict) -> int:
        """İşin genel yüzdesi = şirket yüzdelerinin ortalaması. Şirket yüzdesi adım adım artar
        (şema 25 → mizan 50 → eşleştirme 75 → RAG 100); `kuruldu`/`guncellendi`/`degismedi`/`atlandi`/`hata` şirketler genel hesapta 100 sayılır
        (iş o şirket için bitti; `hata` şirketin kendi `yuzde`/`adim` değeri hatanın hangi adımda olduğunu gösterir). Adım içi (örn. RAG'ın uzun sürmesi) ilerleme gösterilmez: yüzde basamaklıdır."""
        if veri.get("durum") == "bitti":
            return 100
        sirketler = veri["sirketler"].values()
        if not sirketler:
            return 0
        bitti = ("kuruldu", "guncellendi", "degismedi", "atlandi", "hata")  # hata veren şirket de "işlenmesi bitti" sayılır (yüzdesi hatanın yerini gösterir)
        return round(sum(100 if s["durum"] in bitti else s.get("yuzde", 0) for s in sirketler) / len(sirketler))

    def guncelle(self, is_id: str, is_durumu: Optional[str] = None, vkn: Optional[str] = None, **sirket_alanlari) -> None:
        """`is_durumu` işin kendi durumunu, `vkn` + diğer alanlar (durum, ayrinti, ozet) o şirketin kaydını günceller."""
        with self._kilit:
            yol = self._is_yolu(is_id)
            veri = json.loads(yol.read_text(encoding="utf-8"))
            if is_durumu:
                veri["durum"] = is_durumu
            if vkn:
                veri["sirketler"][vkn].update(sirket_alanlari)
            self._yaz(yol, veri)

    def bekleyen_sayisi(self) -> int:
        n = 0
        for yol in (self.kok / "isler").glob("*.json"):
            try:
                if json.loads(yol.read_text(encoding="utf-8"))["durum"] in ("kuyrukta", "calisiyor"):
                    n += 1
            except (ValueError, KeyError):
                continue
        return n

    def yarim_kalanlari_isaretle(self) -> list:
        """Uygulama yeniden başladığında 'çalışıyor/kuyrukta' kalmış işleri hataya çevirir
        (bellekteki kuyruk kayboldu; yeniden yüklenirse yarım kurulumlar tekrar denenebilir)."""
        isaretlenen = []
        for yol in (self.kok / "isler").glob("*.json"):
            try:
                veri = json.loads(yol.read_text(encoding="utf-8"))
            except ValueError:
                continue
            if veri.get("durum") not in ("kuyrukta", "calisiyor"):
                continue
            for s in veri["sirketler"].values():
                if s["durum"] in ("bekliyor", "calisiyor"):
                    s["durum"], s["ayrinti"] = "hata", "Uygulama yeniden başladığı için iş yarıda kaldı; zip'i yeniden yükleyin."
            veri["durum"] = "bitti"
            self._yaz(yol, veri)
            isaretlenen.append(veri["is_id"])
        return isaretlenen

    # --- şirket kurulum kaydı: "tamam" / "yarim" (yalnızca BİZİM başlattığımız kurulumlar) ---
    def kurulum_kaydi(self, vkn: str) -> Optional[dict]:
        yol = self.kok / "kurulumlar" / f"{vkn}.json"
        with self._kilit:
            return json.loads(yol.read_text(encoding="utf-8")) if yol.exists() else None

    def kurulum_kaydet(self, vkn: str, durum: str, etiket: str) -> None:
        with self._kilit:
            self._yaz(self.kok / "kurulumlar" / f"{vkn}.json", {"durum": durum, "etiket": etiket, "zaman": _simdi()})


# --------------------------------------------------------------------------
# Çalışan (arka plan, tek tek)
# --------------------------------------------------------------------------

class Calisan:
    """İşleri kuyruktan alır, şirketleri sırayla kurar. Bağımlılıklar enjekte edilir
    (testler veritabanı/Ollama olmadan çalışır; üretim bağlantısı `varsayilan_calisan`)."""

    def __init__(
        self,
        depo: IsDeposu,
        kurulu_mu: Callable[[str], bool],
        kur: Callable[..., dict],
        kapsam_ekle: Callable[[str, str], bool],
        is_dizini: Callable[[str], Path],
        guncelle: Optional[Callable[..., dict]] = None,
    ):
        self.depo, self.kurulu_mu, self.kur, self.kapsam_ekle, self.is_dizini = depo, kurulu_mu, kur, kapsam_ekle, is_dizini
        # guncelle(vkn, musteri_dizini, ilerleme, is_id, istemci) -> özet sözlüğü; verilmezse kayıtlı şirket eskisi gibi atlanır.
        self.guncelle = guncelle
        self.kuyruk: "queue.Queue[str]" = queue.Queue()
        self._thread: Optional[threading.Thread] = None

    def baslat(self) -> None:
        self.depo.yarim_kalanlari_isaretle()
        if self._thread is None:
            self._thread = threading.Thread(target=self._dongu, name="onboard-calisan", daemon=True)
            self._thread.start()

    def ekle(self, is_id: str) -> None:
        self.kuyruk.put(is_id)

    def _dongu(self) -> None:
        while True:
            is_id = self.kuyruk.get()
            try:
                self.isle(is_id)
            except Exception:  # noqa: BLE001
                _logger.error("onboard isi beklenmedik sekilde coktu is_id=%s", is_id, exc_info=True)

    def isle(self, is_id: str) -> None:
        veri = self.depo.getir(is_id)
        if veri is None:
            return
        etiket = veri["etiket"]
        dizin = self.is_dizini(is_id)
        self.depo.guncelle(is_id, is_durumu="calisiyor")
        try:
            for vkn in veri["sirketler"]:
                self._sirketi_isle(is_id, etiket, vkn, dizin, yetkisiz=vkn in (veri.get("guncelleme_yetkisiz") or []))
        finally:
            shutil.rmtree(dizin, ignore_errors=True)  # gelen ham müşteri verisi iş bitince silinir
            self.depo.guncelle(is_id, is_durumu="bitti")
        sonuclar = {v: s["durum"] for v, s in (self.depo.getir(is_id) or {}).get("sirketler", {}).items()}
        _audit.info(json.dumps({"olay": "musteri_onboard_bitti", "is_id": is_id, "istemci": etiket, "sonuclar": sonuclar}, ensure_ascii=False))

    def _guncelle(self, is_id: str, etiket: str, vkn: str, dizin: Path) -> None:
        """Kayıtlı şirket: gelen veriyi mevcutla karşılaştırıp yalnızca farkı uygular (`guncellendi`), fark yoksa `degismedi`."""
        self.depo.guncelle(is_id, vkn=vkn, durum="calisiyor")

        def ilerleme(adim: str, yuzde: int) -> None:
            self.depo.guncelle(is_id, vkn=vkn, adim=adim, yuzde=yuzde)

        try:
            ozet = self.guncelle(vkn, dizin / vkn, ilerleme, is_id, etiket)
        except Exception as exc:  # noqa: BLE001
            mesaj = f"{type(exc).__name__}: {str(exc)}".replace(str(dizin), "<zip>")[:400]
            _logger.error("onboard guncelleme basarisiz vkn=%s is_id=%s: %s", vkn, is_id, mesaj)
            self.depo.guncelle(is_id, vkn=vkn, durum="hata", ayrinti=mesaj)
            return
        self.depo.guncelle(is_id, vkn=vkn, durum="guncellendi" if ozet.get("degisiklik_var") else "degismedi", yuzde=100, ozet=ozet)

    def _sirketi_isle(self, is_id: str, etiket: str, vkn: str, dizin: Path, yetkisiz: bool = False) -> None:
        kayit = self.depo.kurulum_kaydi(vkn)
        yeniden_deneme = bool(kayit and kayit["durum"] == "yarim" and kayit["etiket"] == etiket)
        if self.kurulu_mu(vkn) and not yeniden_deneme:
            if yetkisiz or self.guncelle is None:
                # Güncelleme yalnızca anahtarın o VKN adına yetkili olduğu durumda yapılır (başka müşavirin verisi korunur).
                self.depo.guncelle(is_id, vkn=vkn, durum="atlandi", yuzde=100,
                                   ayrinti="Şirket zaten kurulu ve bu anahtarın bu şirket üzerinde güncelleme yetkisi yok — hiçbir şey değiştirilmedi.")
            else:
                self._guncelle(is_id, etiket, vkn, dizin)
            return
        self.depo.guncelle(is_id, vkn=vkn, durum="calisiyor")
        self.depo.kurulum_kaydet(vkn, "yarim", etiket)  # başarısız olursa yarım kalır, AYNI anahtar tekrar deneyebilir
        def ilerleme(adim: str, yuzde: int) -> None:
            self.depo.guncelle(is_id, vkn=vkn, adim=adim, yuzde=yuzde)

        try:
            ozet = self.kur(vkn, dizin / vkn, ilerleme)
        except Exception as exc:  # noqa: BLE001
            mesaj = f"{type(exc).__name__}: {str(exc)}".replace(str(dizin), "<zip>")[:400]
            _logger.error("onboard basarisiz vkn=%s is_id=%s: %s", vkn, is_id, mesaj)
            self.depo.guncelle(is_id, vkn=vkn, durum="hata", ayrinti=mesaj)  # yuzde/adim: hatanın nerede olduğu görünsün
            return
        self.depo.kurulum_kaydet(vkn, "tamam", etiket)
        try:
            self.kapsam_ekle(etiket, vkn)
        except Exception:  # noqa: BLE001
            _logger.error("yeni VKN anahtar kapsamina eklenemedi vkn=%s etiket=%s", vkn, etiket, exc_info=True)
            self.depo.guncelle(is_id, vkn=vkn, durum="kuruldu", yuzde=100, ozet=ozet,
                               ayrinti="Şirket kuruldu ama anahtar kapsamına eklenemedi — api_anahtari_yonet.py vkn-ekle ile ekleyin.")
            return
        self.depo.guncelle(is_id, vkn=vkn, durum="kuruldu", yuzde=100, ozet=ozet)


def _varsayilan_calisan() -> Calisan:
    kok = veri_dizini()
    depo = IsDeposu(kok)

    def kurulu_mu(vkn: str) -> bool:
        from model_eval_yolu import model_eval_yolunu_ekle

        model_eval_yolunu_ekle()
        from core.db import tenant_kayitli_mi

        return tenant_kayitli_mi(vkn)

    def _betik():
        betik = Path(__file__).resolve().parent.parent / "scripts" / "musteri_onboard_toplu.py"
        spec = importlib.util.spec_from_file_location("musteri_onboard_toplu", betik)
        modul = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(modul)
        return modul

    def kur(vkn: str, musteri_dizini: Path, ilerleme=None) -> dict:
        return _betik().musteriyi_onboard_et(vkn, musteri_dizini, os.environ["DATABASE_URL"], ilerleme=ilerleme)

    def guncelle(vkn: str, musteri_dizini: Path, ilerleme, is_id: str, istemci: str) -> dict:
        return _betik().musteriyi_guncelle(
            vkn, musteri_dizini, os.environ["DATABASE_URL"], ilerleme=ilerleme, is_id=is_id, istemci=istemci,
        )

    def kapsam_ekle(etiket: str, vkn: str) -> bool:
        import api_anahtarlari

        return api_anahtarlari.anahtar_vkn_ekle(etiket, vkn)

    return Calisan(depo, kurulu_mu, kur, kapsam_ekle, lambda is_id: kok / "dosyalar" / is_id, guncelle=guncelle)


_calisan: Optional[Calisan] = None
_calisan_kilidi = threading.Lock()


def calisan() -> Calisan:
    global _calisan
    with _calisan_kilidi:
        if _calisan is None:
            _calisan = _varsayilan_calisan()
        return _calisan


def calisani_baslat() -> None:
    calisan().baslat()


# --------------------------------------------------------------------------
# HTTP uçları
# --------------------------------------------------------------------------

router = APIRouter()


@router.post(ONBOARD_YOLU, status_code=202)
async def musteri_onboard(request: Request, kimlik: IstemciKimligi = Depends(require_onboard_yetkisi)) -> dict:
    """Gövde: ham zip (`Content-Type: application/zip`). Yetki, gövde okunmadan ÖNCE doğrulanır."""
    c = calisan()
    if c.depo.bekleyen_sayisi() >= MAX_BEKLEYEN_IS:
        raise HTTPException(status_code=429, detail="Bekleyen onboarding işi çok fazla; biri bitince tekrar deneyin.")

    is_dizini_kok = c.depo.kok / "yuklemeler"
    is_dizini_kok.mkdir(parents=True, exist_ok=True)
    zip_yolu = is_dizini_kok / f"{uuid.uuid4().hex}.zip"
    boyut = 0
    try:
        with open(zip_yolu, "wb") as f:
            async for parca in request.stream():
                boyut += len(parca)
                if boyut > ONBOARD_MAX_ZIP_BYTES:
                    raise HTTPException(status_code=413, detail="Zip izin verilen boyutu aşıyor.")
                f.write(parca)
        with open(zip_yolu, "rb") as f:
            if f.read(4) != ZIP_IMZASI:
                raise HTTPException(status_code=400, detail="Gövde bir zip dosyası değil.")

        is_id_oncesi = uuid.uuid4().hex  # dosya dizini için; gerçek iş kimliği depo.olustur'dan gelir
        gecici_dizin = c.depo.kok / "dosyalar" / is_id_oncesi
        try:
            sonuc = await run_in_threadpool(zip_guvenli_ac, zip_yolu, gecici_dizin)
        except ZipHatasi as exc:
            shutil.rmtree(gecici_dizin, ignore_errors=True)
            raise HTTPException(status_code=400, detail=str(exc))
        if not sonuc["vknler"]:
            shutil.rmtree(gecici_dizin, ignore_errors=True)
            raise HTTPException(
                status_code=400,
                detail="Zip içinde işlenecek şirket klasörü bulunamadı. Kökte <10 haneli VKN>/ klasörleri ve "
                       "içlerinde mizan.xlsx, faturalar/*.xml, yevmiye.xlsx|csv bekleniyor.",
            )
    finally:
        zip_yolu.unlink(missing_ok=True)

    # Kayıtlı bir şirket için güncelleme yalnızca anahtar o VKN adına yetkiliyse yapılır; yetkisizler iş kaydında işaretlenir.
    yetkisiz = [v for v in sonuc["vknler"] if c.kurulu_mu(v) and not kimlik.vkn_izinli_mi(v)]
    is_kaydi = c.depo.olustur(kimlik.etiket, sonuc["vknler"], sonuc["atlanan_dosya"], sonuc["gecersiz_klasorler"], yetkisiz)
    # Dosyalar, gerçek iş kimliğine göre adlandırılmış dizine taşınır (çalışan bunu is_id ile bulur).
    hedef = c.is_dizini(is_kaydi["is_id"])
    hedef.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(gecici_dizin), str(hedef))
    _audit.info(json.dumps({"olay": "musteri_onboard_basladi", "is_id": is_kaydi["is_id"], "istemci": kimlik.etiket,
                            "vknler": sonuc["vknler"], "zip_bayt": boyut}, ensure_ascii=False))
    c.ekle(is_kaydi["is_id"])
    return {"is_id": is_kaydi["is_id"], "durum": "kuyrukta", "sirketler": sonuc["vknler"],
            "atlanan_dosya": sonuc["atlanan_dosya"], "gecersiz_klasorler": sonuc["gecersiz_klasorler"]}


@router.get("/musteri/isler/{is_id}")
def musteri_is_durumu(is_id: str, kimlik: IstemciKimligi = Depends(require_onboard_yetkisi)) -> dict:
    veri = calisan().depo.getir(is_id)
    # Başka anahtarın işi "yok" gibi davranır — varlığı sızdırılmaz.
    if veri is None or veri["etiket"] != kimlik.etiket:
        raise HTTPException(status_code=404, detail="İş bulunamadı.")
    return {k: v for k, v in veri.items() if k != "etiket"}
