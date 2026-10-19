#!/usr/bin/env python3
"""İzleme paneli — Mac'te çalışır, sunucuya SSH ile bağlanıp istekleri/hataları/onboarding işlerini gösterir.

    python3 izleme/panel.py                 # sunucudaki kurulumu izler  → http://127.0.0.1:8300
    python3 izleme/panel.py --yerel         # bu Mac'teki Docker'ı izler
Ayarlar (env): IZLEME_SSH (varsayılan unlem-gx10-01@10.34.10.112), IZLEME_CONTAINER, IZLEME_PORT.

Salt OKUMA: yalnızca `docker logs`, iş dosyalarını ve gelen-istek arşivini (`docker exec ... cat/head`) okur; sunucuda yeni port açmaz, hiçbir şeyi değiştirmez.
Yalnızca 127.0.0.1'e bağlanır. Uzak komutlar sabit şablonlardır; değişkenler yalnızca doğrulanmış değerlerdir
(zaman penceresi tamsayı; arşiv kimliği hex deseni; dosya adı sabit beyaz liste — bkz. arsiv.py) — ham kullanıcı girdisi kabuğa hiç ulaşmaz."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import threading
import time
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent))
import arsiv  # noqa: E402
import ayristir  # noqa: E402

STATIC = Path(__file__).resolve().parent / "static"
IS_DIZINI = "/app/data/onboarding/isler"
_CSP = "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; script-src 'self'; connect-src 'self'; frame-ancestors 'none'"


class Kaynak:
    def __init__(self, yerel: bool, ssh: str, kapsayici: str):
        self.yerel, self.ssh, self.kapsayici = yerel, ssh, kapsayici

    def calistir(self, komut: list, zaman_asimi: int = 30) -> str:
        tam = komut if self.yerel else ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8", self.ssh, " ".join(komut)]
        s = subprocess.run(tam, capture_output=True, text=True, errors="replace", timeout=zaman_asimi)  # head -c çok baytlı karakteri kesebilir
        if s.returncode != 0 and not s.stdout:
            raise RuntimeError((s.stderr or "komut başarısız").strip()[:300])
        return s.stdout + (s.stderr if "logs" in komut else "")

    def loglar(self, dakika: int) -> str:
        baslangic = ayristir.pencere_baslangici(dakika)
        return self.calistir(["docker", "logs", "--timestamps", "--since", baslangic, self.kapsayici])

    def isler(self) -> str:
        sh = f"for f in {IS_DIZINI}/*.json; do [ -f \"$f\" ] && cat \"$f\" && echo; done"
        return self.calistir(["docker", "exec", self.kapsayici, "sh", "-c", f"'{sh}'" if not self.yerel else sh])


    # ---- gelen-istek arşivi (entegrasyon/istek_arsivi.py) ----

    def arsiv_metalari(self, adet: int = 500) -> str:
        sh = (f"for d in $(ls -1t {arsiv.ARSIV_DIZINI} 2>/dev/null | head -{int(adet)}); do "
              f"cat {arsiv.ARSIV_DIZINI}/$d/meta.json 2>/dev/null && echo; done")
        return self.calistir(["docker", "exec", self.kapsayici, "sh", "-c", f"'{sh}'" if not self.yerel else sh])

    def metin_oku(self, yol: str, bayt: int) -> str:
        """Doğrulanmış (arsiv.dosya_yolu / sabit dizin + hex kimlik) bir dosyanın ilk `bayt` baytı."""
        return self.calistir(["docker", "exec", self.kapsayici, "head", "-c", str(int(bayt)), yol])

    def dosya_ac(self, yol: str) -> subprocess.Popen:
        komut = ["docker", "exec", self.kapsayici, "cat", yol]
        tam = komut if self.yerel else ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8", self.ssh, " ".join(komut)]
        return subprocess.Popen(tam, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    def istek_loglari(self, baslangic: str, bitis: str) -> str:
        return self.calistir(["docker", "logs", "--timestamps", "--since", baslangic, "--until", bitis, self.kapsayici])


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


def _json_ya_da_yok(metin: str):
    try:
        return json.loads(metin)
    except ValueError:
        return None


def arsiv_listesi(kaynak: Kaynak) -> dict:
    kayitlar = arsiv.meta_ayristir(kaynak.arsiv_metalari())
    return {"kayitlar": [arsiv.ozet(k) for k in kayitlar[:300]], "toplam": len(kayitlar),
            "kaynak": "Bu Mac (Docker)" if kaynak.yerel else kaynak.ssh, "alindi": time.strftime("%H:%M:%S")}


def _is_ve_sonuclar(kaynak: Kaynak, meta: dict) -> dict:
    """İsteğin başlattığı iş (onboarding ya da toplu fatura) ve — toplu fatura ise — bizim fatura bazında verdiğimiz sonuçlar."""
    is_id = meta.get("is_id")
    cikti = {"is": None, "sonuclar": None, "sonuclar_kesildi": False, "is_hatasi": None}
    if not arsiv.gecerli_is_id(is_id):
        return cikti
    try:
        if meta.get("tip") == "musteri_onboard":
            cikti["is"] = _json_ya_da_yok(kaynak.metin_oku(f"{arsiv.ISLER_DIZINI}/{is_id}.json", arsiv.ONIZLEME_BAYT))
            if isinstance(cikti["is"], dict):  # yüzde iş dosyasında saklanmaz, okunurken hesaplanır (isleri_ayristir ile aynı kural)
                cikti["is"].setdefault("yuzde", ayristir.genel_yuzde(cikti["is"]))
        elif meta.get("tip") == "fatura_toplu":
            cikti["is"] = _json_ya_da_yok(kaynak.metin_oku(f"{arsiv.TOPLU_DIZINI}/{is_id}/is.json", arsiv.ONIZLEME_BAYT))
            if isinstance(cikti["is"], dict):  # toplu_fatura_api.TopluDeposu.getir ile aynı kural
                t = cikti["is"]
                t.setdefault("yuzde", 100 if t.get("durum") == "bitti" else (round(t.get("tamamlanan", 0) * 100 / t["toplam"]) if t.get("toplam") else 0))
            ham = kaynak.metin_oku(f"{arsiv.TOPLU_DIZINI}/{is_id}/sonuclar.jsonl", arsiv.ONIZLEME_SONUC_BAYT)
            satirlar = [_json_ya_da_yok(s) for s in ham.splitlines()]
            cikti["sonuclar"] = [s for s in satirlar if isinstance(s, dict)]
            cikti["sonuclar_kesildi"] = len(ham.encode("utf-8", "replace")) >= arsiv.ONIZLEME_SONUC_BAYT
    except Exception as exc:  # noqa: BLE001 — iş dosyası silinmiş/okunamıyorsa detay yine de gösterilsin
        cikti["is_hatasi"] = str(exc)[:200]
    return cikti


def _istek_loglari(kaynak: Kaynak, meta: dict, request_id: str) -> dict:
    try:
        t0 = datetime.fromisoformat(meta["zaman"]).astimezone(timezone.utc)
        bas = (t0 - timedelta(minutes=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
        bit = (t0 + timedelta(minutes=20)).strftime("%Y-%m-%dT%H:%M:%SZ")
        ham = kaynak.istek_loglari(bas, bit)
        satirlar = [s for s in ham.splitlines() if request_id in s]
        ayr = ayristir.log_ayristir("\n".join(satirlar), saglik_goster=True)
        return {"istekler": ayr["istekler"][:20], "hatalar": ayr["hatalar"][:50], "ham": ayr["ham"][:100], "log_hatasi": None}
    except Exception as exc:  # noqa: BLE001
        return {"istekler": [], "hatalar": [], "ham": [], "log_hatasi": str(exc)[:200]}


def arsiv_detayi(kaynak: Kaynak, request_id: str) -> dict:
    """Bir istek için: meta, gelen metin dosyalarının (XML) ve bizim cevabımızın önizlemesi, bağlı iş ve o isteğe ait log satırları."""
    meta = _json_ya_da_yok(kaynak.metin_oku(arsiv.dosya_yolu(request_id, "meta.json"), 262144))
    if not isinstance(meta, dict):
        raise FileNotFoundError("arşiv kaydı okunamadı")
    onizleme = {}
    for ad in ("cevap.json", "istek.xml"):
        boyut = (meta.get("dosyalar") or {}).get(ad)
        if boyut is None:
            continue
        try:
            onizleme[ad] = {"metin": kaynak.metin_oku(arsiv.dosya_yolu(request_id, ad), arsiv.ONIZLEME_BAYT),
                            "kesildi": boyut > arsiv.ONIZLEME_BAYT, "bayt": boyut}
        except Exception as exc:  # noqa: BLE001
            onizleme[ad] = {"metin": None, "hata": str(exc)[:200], "bayt": boyut}
    return {"meta": meta, "onizleme": onizleme, "is": _is_ve_sonuclar(kaynak, meta), "log": _istek_loglari(kaynak, meta, request_id)}


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

        def _json(self, kod: int, veri: dict):
            self._gonder(kod, json.dumps(veri, ensure_ascii=False).encode(), "application/json; charset=utf-8")

        def _indir(self, request_id: str, ad: str):
            """Arşivlenmiş dosyayı sunucudan akıtarak tarayıcıya indirtir (belleğe alınmaz; zip 200 MB'a kadar olabilir)."""
            try:
                meta_yolu = arsiv.dosya_yolu(request_id, "meta.json")  # geçersiz kimlik → ValueError, komut kurulmaz
                yol = arsiv.dosya_yolu(request_id, ad) if ad != arsiv.TOPLU_SONUC_DOSYASI else None
            except ValueError:
                return self._json(400, {"hata": "geçersiz arşiv kimliği ya da dosya adı"})
            try:
                meta = _json_ya_da_yok(kaynak.metin_oku(meta_yolu, 262144))
                if yol is None:  # bizim fatura başına verdiğimiz cevaplar (toplu işin dizininde)
                    yol = arsiv.toplu_sonuc_yolu(meta)
                boyut = ((meta or {}).get("dosyalar") or {}).get(ad)
                proc = kaynak.dosya_ac(yol)
            except ValueError as exc:
                return self._json(400, {"hata": str(exc)})
            except Exception as exc:  # noqa: BLE001
                return self._json(502, {"hata": f"{type(exc).__name__}: {exc}"[:300]})
            ilk = proc.stdout.read(65536)
            if not ilk:
                hata = proc.stderr.read(300).decode("utf-8", "replace").strip()
                proc.wait()
                return self._json(404, {"hata": "dosya bulunamadı (süresi dolmuş/silinmiş olabilir)" + (": " + hata if hata else "")})
            self.send_response(200)
            self.send_header("Content-Type", "application/octet-stream")
            if isinstance(boyut, int):
                self.send_header("Content-Length", str(boyut))
            self.send_header("Content-Disposition", f'attachment; filename="{arsiv.indirme_adi(meta, request_id, ad)}"')
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", "sandbox")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            try:
                self.wfile.write(ilk)
                while True:
                    parca = proc.stdout.read(65536)
                    if not parca:
                        break
                    self.wfile.write(parca)
            except (BrokenPipeError, ConnectionResetError):
                pass  # tarayıcı indirmeyi iptal etti
            finally:
                proc.stdout.close()
                proc.stderr.close()
                if proc.poll() is None:
                    proc.kill()
                proc.wait()

        def do_GET(self):  # noqa: N802
            u = urlparse(self.path)
            if u.path.startswith("/api/arsiv"):
                q = parse_qs(u.query)
                kimlik, ad = q.get("id", [""])[0], q.get("ad", [""])[0]
                try:
                    if u.path == "/api/arsiv":
                        return self._json(200, onbellek.al(("arsiv",), lambda: arsiv_listesi(kaynak)))
                    if u.path == "/api/arsiv/detay":
                        if not arsiv.gecerli_id(kimlik):
                            return self._json(400, {"hata": "geçersiz arşiv kimliği"})
                        return self._json(200, arsiv_detayi(kaynak, kimlik))
                    if u.path == "/api/arsiv/indir":
                        return self._indir(kimlik, ad)
                except FileNotFoundError as exc:
                    return self._json(404, {"hata": str(exc)})
                except Exception as exc:  # noqa: BLE001
                    return self._json(502, {"baglanti_hatasi": f"{type(exc).__name__}: {exc}"[:400], "kaynak": kaynak.ssh})
                return self._gonder(404, b"yok", "text/plain")
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
