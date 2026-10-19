"""Gelen istek/dosya arşivi — operatörün (izleme paneli, SSH üzerinden) gelen dosyaları indirip incelemesi ve bizim verdiğimiz cevabı görmesi için.

Neden: Zip'ler ve faturalar iş bitince silindiği için (dış ekibe verilen söz) bir sorun çıktığında (örn. eksik mizan) orijinal dosyaya bakmak mümkün
olmuyordu. Bu modül, gelen dosyayı ve cevabı **sınırlı süre** (varsayılan 7 gün) ayrı bir dizinde tutar, süre dolunca ve boyut tavanı aşılınca otomatik siler.

Dosyalar: `gelen.zip` (zip uçları), `istek.xml` + `cevap.json` (tek fatura), `iz.json` (KARAR İZİ, yalnızca tek fatura: işlem adım adım — kim karar verdi, hangi istem/kural, neden;
bkz. model_eval/core/iz.py), `meta.json`. İstemler fatura içeriği taşıdığı için `iz.json` de XML ile aynı süre/erişimle saklanır, dış API cevabına GİRMEZ.

Güvenlik/gizlilik kararları (2026-10-19, kullanıcı isteğiyle):
  * Arşive yalnızca izleme paneli SSH üzerinden erişir; API'ye yeni bir uç nokta EKLENMEDİ (dışarıdan erişilemez).
  * Saklama süresi `GELEN_ARSIV_GUN` (0 = kapalı), toplam boyut tavanı `GELEN_ARSIV_MAX_MB` (varsayılan 2048): aşılınca en eskiler silinir.
  * Arşiv hatası ASLA isteği bozmaz (her şey try/except içinde, yalnızca uyarı loglanır).
  * Dizin adı `request_id` (12-32 hex); yalnızca izinli dosya adları yazılır/okunur (`IZINLI_DOSYALAR`) — yol gezinmesi mümkün değil.
    Kimliği istemci `X-Request-ID` ile de verebildiğinden, var olan bir kaydın üzerine yazılmaz (ikinci istek arşivlenmez, uyarı loglanır).
  * Yalnızca KİMLİĞİ DOĞRULANMIŞ istekler arşivlenir (çağrılar yetki kontrolünden sonradır) — anonim istek diske yazdıramaz.
  * Arşiv, müşteri verisi (fatura içeriği, karşı taraf adları) içerir; dış ekibe verilen "iş bitince silinir" sözü bu yüzden belgelerde GÜNCELLENMİŞTİR."""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import tempfile
import threading
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

_logger = logging.getLogger("entegrasyon.arsiv")

IZINLI_DOSYALAR = ("gelen.zip", "istek.xml", "cevap.json", "iz.json", "meta.json")
ID_DESENI = re.compile(r"[0-9a-f]{12,32}")  # fullmatch ile kullanılır (`$` sondaki "\n"i de kabul ederdi)
TEMIZLIK_ARALIGI_SN = 300
ZIP_ICERIK_MAX = 300  # meta.json'a yazılacak en fazla dosya adı (panelde "zip'in içinde ne var" görünümü için)

_kilit = threading.Lock()
_son_temizlik = 0.0


def gun() -> int:
    try:
        return int(os.environ.get("GELEN_ARSIV_GUN", "7"))
    except ValueError:
        return 7


def max_bayt() -> int:
    try:
        return int(os.environ.get("GELEN_ARSIV_MAX_MB", "2048")) * 1024 * 1024
    except ValueError:
        return 2048 * 1024 * 1024


def aktif() -> bool:
    return gun() > 0


def kok() -> Path:
    taban = os.environ.get("ONBOARD_DATA_DIR") or Path(tempfile.gettempdir()) / "efatura-onboarding"
    return Path(taban) / "arsiv"


def _dizin(request_id: str, olustur: bool = False) -> Optional[Path]:
    if not request_id or not ID_DESENI.fullmatch(request_id):
        return None  # "-" (istek bağlamı dışı) ya da geçersiz kimlik: arşivlenmez
    d = kok() / request_id
    if olustur:
        # Kimliği istemci `X-Request-ID` ile verebilir (log_ortak.RequestIdMiddleware): var olan bir kaydın üzerine YAZILMAZ
        # (yetkili bir istemci başkasının/önceki isteğin arşivini ezemesin); FileExistsError çağıranda uyarı olarak loglanır.
        d.parent.mkdir(parents=True, exist_ok=True)
        d.mkdir()
    return d


def _simdi() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def meta_yaz(request_id: str, **alanlar) -> None:
    """meta.json'u günceller (var olanla birleştirir). Arşiv kapalıysa ya da kayıt yoksa sessizce geçer."""
    if not aktif():
        return
    try:
        d = _dizin(request_id)
        if d is None or not d.exists():
            return
        with _kilit:
            yol = d / "meta.json"
            meta = json.loads(yol.read_text(encoding="utf-8")) if yol.exists() else {}
            meta.update({k: v for k, v in alanlar.items() if v is not None})
            meta["request_id"] = request_id
            gecici = yol.with_suffix(".tmp")
            gecici.write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
            os.replace(gecici, yol)
    except Exception:  # noqa: BLE001
        _logger.warning("arsiv meta yazilamadi request_id=%s", request_id, exc_info=True)


def _zip_icerigi(zip_yolu: Path) -> dict:
    """Zip'in dosya listesi (yalnızca merkezi dizin okunur, içerik açılmaz). Geçersiz zip'te boş döner."""
    try:
        with zipfile.ZipFile(zip_yolu) as zf:
            bilgiler = [i for i in zf.infolist() if not i.is_dir()]
        return {
            "zip_dosya_sayisi": len(bilgiler),
            "zip_icerik": [{"ad": i.filename[:200], "bayt": i.file_size} for i in bilgiler[:ZIP_ICERIK_MAX]],
        }
    except Exception:  # noqa: BLE001 — geçersiz/bozuk zip: yalnızca dosyanın kendisi saklanır
        return {}


def zip_kaydet(request_id: str, zip_yolu: Path, tip: str, istemci: Optional[str], ip: Optional[str], yol: str) -> None:
    """Gelen zip'in bir kopyasını arşive koyar (geçersiz zip'ler de — hata ayıklamak için)."""
    if not aktif():
        return
    try:
        d = _dizin(request_id, olustur=True)
        if d is None:
            return
        shutil.copyfile(zip_yolu, d / "gelen.zip")
        meta_yaz(request_id, tip=tip, zaman=_simdi(), istemci=istemci, ip=ip, yol=yol,
                 dosyalar={"gelen.zip": (d / "gelen.zip").stat().st_size}, **_zip_icerigi(d / "gelen.zip"))
        _temizlik_gerekirse()
    except Exception:  # noqa: BLE001
        _logger.warning("gelen zip arsivlenemedi request_id=%s", request_id, exc_info=True)


def cevap_yaz(request_id: str, govde: dict) -> None:
    """Zip uç noktalarında bizim verdiğimiz cevabı (başarıda 202 gövdesi, hatada {"durum","detay"}) cevap.json olarak saklar."""
    if not aktif():
        return
    try:
        d = _dizin(request_id)
        if d is None or not d.exists():
            return
        (d / "cevap.json").write_text(json.dumps(govde, ensure_ascii=False, indent=1), encoding="utf-8")
        yol = d / "meta.json"
        with _kilit:
            dosyalar = (json.loads(yol.read_text(encoding="utf-8")) if yol.exists() else {}).get("dosyalar") or {}
        dosyalar["cevap.json"] = (d / "cevap.json").stat().st_size
        meta_yaz(request_id, dosyalar=dosyalar)
    except Exception:  # noqa: BLE001
        _logger.warning("arsiv cevabi yazilamadi request_id=%s", request_id, exc_info=True)


def hata_yaz(request_id: str, durum: int, detay: str) -> None:
    """Reddedilen zip isteği: durum + hata nedeni hem meta.json'a hem cevap.json'a (bizim döndüğümüz cevap) yazılır."""
    detay = str(detay)[:500]
    meta_yaz(request_id, durum=durum, hata=detay[:300])
    cevap_yaz(request_id, {"durum": durum, "detay": detay})


def fatura_kaydet(request_id: str, xml: str, cevap: Optional[dict], hata: Optional[dict], istemci: Optional[str],
                  ip: Optional[str], vkn: Optional[str], dosya_adi: Optional[str], iz: Optional[dict] = None) -> None:
    """Tek-fatura isteği: gelen XML + bizim cevabımız (ya da hata) + karar izi (`iz.json`: nasıl işlendi, kim karar verdi, hangi istem/kural, neden)."""
    if not aktif():
        return
    try:
        d = _dizin(request_id, olustur=True)
        if d is None:
            return
        (d / "istek.xml").write_text(xml, encoding="utf-8")
        dosyalar = {"istek.xml": (d / "istek.xml").stat().st_size}
        if cevap is not None:
            (d / "cevap.json").write_text(json.dumps(cevap, ensure_ascii=False, indent=1), encoding="utf-8")
            dosyalar["cevap.json"] = (d / "cevap.json").stat().st_size
        if iz:
            (d / "iz.json").write_text(json.dumps(iz, ensure_ascii=False), encoding="utf-8")
            dosyalar["iz.json"] = (d / "iz.json").stat().st_size
        t = (cevap or {}).get("tdhp_tahmini") or {}
        meta_yaz(
            request_id, tip="fatura_isle", zaman=_simdi(), istemci=istemci, ip=ip, yol="/fatura/isle",
            vkn=vkn, dosya_adi=dosya_adi, dosyalar=dosyalar,
            durum=(hata or {}).get("durum") or 200, hata=(hata or {}).get("detay"),
            sonuc=(cevap or {}).get("asama"), fatura_no=t.get("invoice_id"), approvable=t.get("approvable"),
        )
        _temizlik_gerekirse()
    except Exception:  # noqa: BLE001
        _logger.warning("fatura istegi arsivlenemedi request_id=%s", request_id, exc_info=True)


def _boyut(d: Path) -> int:
    return sum(f.stat().st_size for f in d.rglob("*") if f.is_file())


def _zaman(d: Path) -> float:
    try:
        meta = json.loads((d / "meta.json").read_text(encoding="utf-8"))
        return datetime.fromisoformat(meta["zaman"]).timestamp()
    except Exception:  # noqa: BLE001
        return d.stat().st_mtime


def temizle() -> dict:
    """Süresi dolanları, sonra boyut tavanı aşılırsa en eskileri siler. Dönen: {"silinen_sure": n, "silinen_boyut": n}."""
    sonuc = {"silinen_sure": 0, "silinen_boyut": 0}
    if not kok().exists():
        return sonuc
    sinir = time.time() - gun() * 86400
    dizinler = [d for d in kok().iterdir() if d.is_dir()]
    kalan = []
    for d in dizinler:
        if gun() > 0 and _zaman(d) < sinir:
            shutil.rmtree(d, ignore_errors=True)
            sonuc["silinen_sure"] += 1
        else:
            kalan.append(d)
    boyutlar = {d: _boyut(d) for d in kalan}
    toplam = sum(boyutlar.values())
    for d in sorted(kalan, key=_zaman):  # en eskiden başla
        if toplam <= max_bayt():
            break
        toplam -= boyutlar[d]
        shutil.rmtree(d, ignore_errors=True)
        sonuc["silinen_boyut"] += 1
    return sonuc


def _temizlik_gerekirse() -> None:
    global _son_temizlik
    simdi = time.monotonic()
    if simdi - _son_temizlik < TEMIZLIK_ARALIGI_SN:
        return
    _son_temizlik = simdi
    try:
        s = temizle()
        if s["silinen_sure"] or s["silinen_boyut"]:
            _logger.info("arsiv temizlendi: %s", s)
    except Exception:  # noqa: BLE001
        _logger.warning("arsiv temizligi basarisiz", exc_info=True)
