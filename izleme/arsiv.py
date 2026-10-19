"""Sunucudaki gelen-istek arşivi (entegrasyon/istek_arsivi.py) için panel tarafı yardımcıları — saf fonksiyonlar, ağ yok.

Güvenlik: kullanıcıdan (tarayıcıdan) gelen iki değer uzak komuta ulaşır — `request_id` ve dosya adı. İkisi de burada
KATI beyaz liste ile doğrulanır (hex kimlik deseni + sabit dosya adı kümesi); doğrulamadan geçmeyen değer kabuğa hiç gitmez.
`IZINLI_DOSYALAR` ve `ID_DESENI`, sunucudaki `entegrasyon/istek_arsivi.py` ile AYNI kalmalıdır (testte denetlenir)."""

from __future__ import annotations

import json
import re

ARSIV_DIZINI = "/app/data/onboarding/arsiv"
ISLER_DIZINI = "/app/data/onboarding/isler"
TOPLU_DIZINI = "/app/data/onboarding/toplu"

IZINLI_DOSYALAR = ("gelen.zip", "istek.xml", "cevap.json", "iz.json", "meta.json")
# DİKKAT: `$` sondaki "\n"den önce de eşleşir (re.match("^x$", "x\n") başarılı!) — kabuğa satır sonu sızmasın diye fullmatch.
ID_DESENI = re.compile(r"[0-9a-f]{12,32}")
IS_ID_DESENI = re.compile(r"[0-9a-f]{32}")
# Tarayıcıda önizlenecek metin dosyalarında üst sınır (bayt): büyük cevap panelin/SSH'in boğulmasına yol açmasın.
ONIZLEME_BAYT = 262144
ONIZLEME_SONUC_BAYT = 2097152
# Karar izi (iz.json): istemler (prompt) ve ham model cevapları yüzünden birkaç yüz KB olabilir; panel bunu ayrıştırıp yapılandırılmış gösterir.
IZ_BAYT = 4194304
TOPLU_SONUC_DOSYASI = "sonuclar.jsonl"  # arşivde değil, toplu işin dizininde (bizim fatura başına verdiğimiz cevaplar)


def gecerli_id(deger) -> bool:
    return isinstance(deger, str) and bool(ID_DESENI.fullmatch(deger))


def gecerli_is_id(deger) -> bool:
    return isinstance(deger, str) and bool(IS_ID_DESENI.fullmatch(deger))


def gecerli_dosya(deger) -> bool:
    return isinstance(deger, str) and deger in IZINLI_DOSYALAR


def toplu_sonuc_yolu(meta: dict | None) -> str:
    """Toplu fatura isteğinin işine ait sonuçlar.jsonl yolu (is_id arşiv meta'sından gelir ve yeniden doğrulanır)."""
    is_id = (meta or {}).get("is_id")
    if (meta or {}).get("tip") != "fatura_toplu" or not gecerli_is_id(is_id):
        raise ValueError("bu istek bir toplu fatura işi başlatmadı")
    return f"{TOPLU_DIZINI}/{is_id}/{TOPLU_SONUC_DOSYASI}"


def dosya_yolu(request_id: str, dosya: str) -> str:
    """Doğrulanmış kimlik+dosya için sunucudaki mutlak yol. Geçersizse ValueError (komut ASLA kurulmaz)."""
    if not gecerli_id(request_id) or not gecerli_dosya(dosya):
        raise ValueError("geçersiz arşiv kimliği ya da dosya adı")
    return f"{ARSIV_DIZINI}/{request_id}/{dosya}"


def indirme_adi(meta: dict | None, request_id: str, dosya: str) -> str:
    """Tarayıcıya önerilen dosya adı: <tip>_<tarih>_<kimlik8>_<dosya> (yalnızca güvenli karakterler)."""
    tip = re.sub(r"[^a-z_]", "", str((meta or {}).get("tip") or "istek"))[:20] or "istek"
    zaman = re.sub(r"[^0-9]", "", str((meta or {}).get("zaman") or ""))[:12]
    return f"{tip}_{zaman}_{request_id[:8]}_{dosya}".replace("__", "_")


def meta_ayristir(ham: str) -> list:
    """Ardışık meta.json nesnelerinden (her biri `indent=1` çok satırlı olabilir) kayıt listesi — yeni → eski."""
    kod, pos, kayitlar = json.JSONDecoder(), 0, []
    while pos < len(ham):
        while pos < len(ham) and ham[pos].isspace():
            pos += 1
        if pos >= len(ham):
            break
        try:
            nesne, pos = kod.raw_decode(ham, pos)
        except ValueError:
            # Bozuk/yarım bir kayıt tüm listeyi öldürmesin: bir sonraki '{' satırına atla
            sonraki = ham.find("\n{", pos)
            if sonraki < 0:
                break
            pos = sonraki + 1
            continue
        if isinstance(nesne, dict) and gecerli_id(nesne.get("request_id")):
            kayitlar.append(nesne)
    kayitlar.sort(key=lambda k: k.get("zaman") or "", reverse=True)
    return kayitlar


def ozet(kayit: dict) -> dict:
    """Liste satırı için alanlar (panel yalnızca bunları gösterir)."""
    d = kayit.get("dosyalar") or {}
    return {
        "request_id": kayit["request_id"], "zaman": kayit.get("zaman"), "tip": kayit.get("tip"), "yol": kayit.get("yol"),
        "durum": kayit.get("durum"), "hata": kayit.get("hata"), "istemci": kayit.get("istemci"), "ip": kayit.get("ip"),
        "vkn": kayit.get("vkn"), "vknler": kayit.get("vknler"), "dosya_adi": kayit.get("dosya_adi"),
        "is_id": kayit.get("is_id"), "fatura_no": kayit.get("fatura_no"), "sonuc": kayit.get("sonuc"),
        "approvable": kayit.get("approvable"), "toplam_fatura": kayit.get("toplam_fatura"),
        "dosyalar": {ad: d[ad] for ad in IZINLI_DOSYALAR if ad in d and ad != "meta.json"},
    }
