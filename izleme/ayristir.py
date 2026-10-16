"""Docker log satırlarını ve onboarding iş dosyalarını panel için olaylara çevirir (saf fonksiyonlar, ağ yok).

Girdi: `docker logs --timestamps` çıktısı. Üç tür satır tanır:
  1. `entegrasyon.istek` JSON satırı  → tam istek kaydı (yöntem, yol, durum, süre, ip, istemci, hata mesajı).
  2. Diğer JSON log satırları (uyarı/hata)  → "hatalar" akışı (yetki reddi, beklenmeyen hata vb.).
  3. uvicorn erişim satırı (`INFO: IP:PORT - "POST /yol HTTP/1.1" 400`)  → yalnızca durum kodu bilinir;
     eski sürümlerde (istek günlüğü eklenmeden önce) ya da günlük satırı yoksa YEDEK kaynak olarak kullanılır.
Çok satırlı Python hata izleri (Traceback) bir önceki ERROR olayına eklenir."""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone

GURULTU_YOLLARI = ("/durum", "/saglik", "/static/", "/favicon.ico", "/openapi.json")
_ZAMAN = re.compile(r"^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})(?:\.(\d+))?Z?\s?(.*)$")
_ERISIM = re.compile(r'^INFO:\s+(\S+?):(\d+) - "([A-Z]+) (\S+) HTTP/[\d.]+" (\d{3})')


def zaman_coz(metin: str) -> datetime | None:
    m = _ZAMAN.match(metin)
    if not m:
        return None
    try:
        return datetime.strptime(m.group(1), "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _gurultu_mu(yol: str) -> bool:
    yol = yol.split("?")[0]
    return yol == "/" or yol.startswith(GURULTU_YOLLARI)


def log_ayristir(ham: str, saglik_goster: bool = False) -> dict:
    """{"istekler": [...], "hatalar": [...], "ham": [...]} — hepsi zamana göre YENİDEN ESKİYE sıralı."""
    istekler, erisimler, hatalar, ham_satirlar = [], [], [], []
    son_hata = None
    for satir in ham.splitlines():
        m = _ZAMAN.match(satir)
        if not m:
            continue
        zaman = zaman_coz(satir)
        icerik = m.group(3)
        ham_satirlar.append({"zaman": zaman.isoformat() if zaman else None, "satir": icerik[:600]})

        if icerik.startswith("{"):
            try:
                j = json.loads(icerik)
            except ValueError:
                continue
            if j.get("logger") == "entegrasyon.istek":
                try:
                    k = json.loads(j.get("mesaj", "{}"))
                except ValueError:
                    continue
                k["zaman"] = zaman.isoformat() if zaman else j.get("zaman")
                k["kaynak"] = "istek"
                if saglik_goster or not _gurultu_mu(k.get("yol", "")):
                    istekler.append(k)
            elif j.get("seviye") in ("WARNING", "ERROR", "CRITICAL"):
                son_hata = {
                    "zaman": zaman.isoformat() if zaman else j.get("zaman"), "seviye": j["seviye"],
                    "logger": j.get("logger"), "mesaj": (j.get("mesaj") or "")[:800],
                    "request_id": j.get("request_id"), "iz": [],
                }
                hatalar.append(son_hata)
            continue

        e = _ERISIM.match(icerik)
        if e:
            ip, _port, yontem, yol, durum = e.groups()
            if saglik_goster or not _gurultu_mu(yol):
                erisimler.append({
                    "zaman": zaman.isoformat() if zaman else None, "yontem": yontem, "yol": yol,
                    "durum": int(durum), "ip": ip, "istemci": None, "hata": None, "sure_ms": None,
                    "request_id": None, "kaynak": "erisim",
                })
            continue
        # Çok satırlı hata izi: Traceback ve girintili satırlar son ERROR olayına eklenir.
        if son_hata is not None and (icerik.startswith(("Traceback", "  File", "    ")) or re.match(r"^\w+(\.\w+)*(Error|Exception)\b", icerik)):
            if len(son_hata["iz"]) < 40:
                son_hata["iz"].append(icerik[:300])

    # Erişim satırlarını, aynı olayı zaten kapsayan istek günlüğü varsa at (yol+yöntem+durum ±3 sn).
    def kapsandi(a):
        za = zaman_coz(a["zaman"] or "")
        for k in istekler:
            zk = zaman_coz(k["zaman"] or "")
            if za and zk and k.get("yol") == a["yol"] and k.get("yontem") == a["yontem"] and k.get("durum") == a["durum"] \
                    and abs((za - zk).total_seconds()) <= 3:
                return True
        return False

    tumu = istekler + [a for a in erisimler if not kapsandi(a)]
    tumu.sort(key=lambda x: x.get("zaman") or "", reverse=True)
    hatalar.sort(key=lambda x: x.get("zaman") or "", reverse=True)
    ham_satirlar.reverse()
    return {"istekler": tumu, "hatalar": hatalar, "ham": ham_satirlar}


def genel_yuzde(is_kaydi: dict) -> int:
    """Sunucudaki entegrasyon/musteri_onboard_api.py::IsDeposu._genel_yuzde ile AYNI kural (iş dosyasında
    saklanmaz, okunurken hesaplanır): bitmiş iş %100; değilse şirket yüzdelerinin ortalaması, bitmiş şirketler 100."""
    if is_kaydi.get("durum") == "bitti":
        return 100
    sirketler = list((is_kaydi.get("sirketler") or {}).values())
    if not sirketler:
        return 0
    bitti = ("kuruldu", "atlandi", "hata")
    return round(sum(100 if s.get("durum") in bitti else s.get("yuzde", 0) for s in sirketler) / len(sirketler))


def isleri_ayristir(ham: str) -> list:
    """Ardışık JSON nesnelerinden oluşan metinden iş kayıtlarını çıkarır (yeni → eski)."""
    kod, pos, isler = json.JSONDecoder(), 0, []
    while pos < len(ham):
        while pos < len(ham) and ham[pos].isspace():
            pos += 1
        if pos >= len(ham):
            break
        try:
            nesne, pos = kod.raw_decode(ham, pos)
        except ValueError:
            break
        if isinstance(nesne, dict) and "is_id" in nesne:
            nesne["yuzde"] = nesne.get("yuzde", genel_yuzde(nesne))
            isler.append(nesne)
    isler.sort(key=lambda j: j.get("olusturulma", ""), reverse=True)
    return isler


def pencere_baslangici(dakika: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(minutes=dakika)).strftime("%Y-%m-%dT%H:%M:%SZ")
