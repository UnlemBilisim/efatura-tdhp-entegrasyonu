#!/usr/bin/env python3
"""İzleme paneli — Mac'te çalışır, sunucuya SSH ile bağlanıp istekleri/hataları/onboarding işlerini gösterir.

    python3 izleme/panel.py                 # sunucudaki kurulumu izler  → http://127.0.0.1:8300
    python3 izleme/panel.py --yerel         # bu Mac'teki Docker'ı izler
Ayarlar (env): IZLEME_SSH (varsayılan unlem-gx10-01@10.34.10.112), IZLEME_CONTAINER, IZLEME_PORT.

Salt OKUMA: yalnızca `docker logs` ve iş dosyalarını okur; sunucuda yeni port açmaz, hiçbir şeyi değiştirmez.
Yalnızca 127.0.0.1'e bağlanır. Uzak komutlar sabit şablonlardır; tek değişken (zaman penceresi) tamsayıya
çevrilip sınırlanır — kullanıcı girdisi kabuğa hiç ulaşmaz."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ayristir  # noqa: E402

STATIC = Path(__file__).resolve().parent / "static"
IS_DIZINI = "/app/data/onboarding/isler"
_CSP = "default-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'self'; connect-src 'self'; frame-ancestors 'none'"


class Kaynak:
    def __init__(self, yerel: bool, ssh: str, kapsayici: str):
        self.yerel, self.ssh, self.kapsayici = yerel, ssh, kapsayici

    def calistir(self, komut: list, zaman_asimi: int = 30) -> str:
        tam = komut if self.yerel else ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8", self.ssh, " ".join(komut)]
        s = subprocess.run(tam, capture_output=True, text=True, timeout=zaman_asimi)
        if s.returncode != 0 and not s.stdout:
            raise RuntimeError((s.stderr or "komut başarısız").strip()[:300])
        return s.stdout + (s.stderr if "logs" in komut else "")

    def loglar(self, dakika: int) -> str:
        baslangic = ayristir.pencere_baslangici(dakika)
        return self.calistir(["docker", "logs", "--timestamps", "--since", baslangic, self.kapsayici])

    def isler(self) -> str:
        sh = f"for f in {IS_DIZINI}/*.json; do [ -f \"$f\" ] && cat \"$f\" && echo; done"
        return self.calistir(["docker", "exec", self.kapsayici, "sh", "-c", f"'{sh}'" if not self.yerel else sh])


class Onbellek:
    """Aynı anda gelen yenilemeler SSH'i yormasın: sonuç kısa süre saklanır."""

    def __init__(self, sure: float = 3.0):
        self.sure, self.kilit, self.veri = sure, threading.Lock(), {}

    def al(self, anahtar, uret):
        with self.kilit:
            kayit = self.veri.get(anahtar)
            if kayit and time.monotonic() - kayit[0] < self.sure:
                return kayit[1]
            deger = uret()
            self.veri[anahtar] = (time.monotonic(), deger)
            return deger


def olaylari_getir(kaynak: Kaynak, dakika: int, saglik: bool) -> dict:
    ham = kaynak.loglar(dakika)
    sonuc = ayristir.log_ayristir(ham, saglik_goster=saglik)
    try:
        isler = ayristir.isleri_ayristir(kaynak.isler())[:30]
        is_hatasi = None
    except Exception as exc:  # noqa: BLE001 — iş dosyaları okunamazsa panel yine de çalışsın
        isler, is_hatasi = [], str(exc)[:200]
    ozet = {
        "istek": len(sonuc["istekler"]),
        "hata_istek": sum(1 for i in sonuc["istekler"] if (i.get("durum") or 0) >= 400),
        "sunucu_hatasi": sum(1 for i in sonuc["istekler"] if (i.get("durum") or 0) >= 500),
        "hata_logu": len(sonuc["hatalar"]),
        "calisan_is": sum(1 for j in isler if j.get("durum") in ("kuyrukta", "calisiyor")),
    }
    sonuc["ham"] = sonuc["ham"][:400]
    return {"ozet": ozet, "istekler": sonuc["istekler"][:500], "hatalar": sonuc["hatalar"][:200],
            "isler": isler, "ham": sonuc["ham"], "is_hatasi": is_hatasi,
            "kaynak": "Bu Mac (Docker)" if kaynak.yerel else kaynak.ssh,
            "alindi": time.strftime("%H:%M:%S")}


def sunucu_olustur(kaynak: Kaynak, port: int) -> ThreadingHTTPServer:
    onbellek = Onbellek()

    class Isleyici(BaseHTTPRequestHandler):
        def log_message(self, *a):  # panelin kendi erişim logları terminali doldurmasın
            pass

        def _gonder(self, kod, icerik: bytes, tur: str):
            self.send_response(kod)
            self.send_header("Content-Type", tur)
            self.send_header("Content-Length", str(len(icerik)))
            self.send_header("Content-Security-Policy", _CSP)
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(icerik)

        def do_GET(self):  # noqa: N802
            u = urlparse(self.path)
            if u.path == "/api/olaylar":
                q = parse_qs(u.query)
                try:
                    dakika = max(1, min(int(q.get("dakika", ["60"])[0]), 1440))
                except ValueError:
                    dakika = 60
                saglik = q.get("saglik", ["0"])[0] == "1"
                try:
                    veri = onbellek.al((dakika, saglik), lambda: olaylari_getir(kaynak, dakika, saglik))
                    self._gonder(200, json.dumps(veri, ensure_ascii=False).encode(), "application/json; charset=utf-8")
                except Exception as exc:  # noqa: BLE001
                    hata = {"baglanti_hatasi": f"{type(exc).__name__}: {exc}"[:400], "kaynak": kaynak.ssh}
                    self._gonder(502, json.dumps(hata, ensure_ascii=False).encode(), "application/json; charset=utf-8")
                return
            dosya = {"/": "index.html", "/index.html": "index.html", "/panel.js": "panel.js"}.get(u.path)
            if dosya:
                tur = "text/html; charset=utf-8" if dosya.endswith(".html") else "application/javascript; charset=utf-8"
                self._gonder(200, (STATIC / dosya).read_bytes(), tur)
            else:
                self._gonder(404, b"yok", "text/plain")

    return ThreadingHTTPServer(("127.0.0.1", port), Isleyici)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--yerel", action="store_true", help="Sunucu yerine bu Mac'teki Docker'ı izle")
    ap.add_argument("--port", type=int, default=int(os.environ.get("IZLEME_PORT", "8300")))
    a = ap.parse_args()
    kaynak = Kaynak(
        a.yerel, os.environ.get("IZLEME_SSH", "unlem-gx10-01@10.34.10.112"),
        os.environ.get("IZLEME_CONTAINER", "docker-app-1" if a.yerel else "efatura-sistemi-app-1"),
    )
    srv = sunucu_olustur(kaynak, a.port)
    print(f"İzleme paneli: http://127.0.0.1:{a.port}  (kaynak: {'yerel Docker' if a.yerel else kaynak.ssh}) — durdurmak için Ctrl+C")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
