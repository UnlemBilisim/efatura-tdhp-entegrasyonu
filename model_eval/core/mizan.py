"""Mizan (hesap plani) alt kirilim referansi - TDHP_GLOSSARY'nin (genel,
tum muhasebeciler icin ayni 3 haneli kod aciklamalari) alt kirilim versiyonu.

Muhasebecinin kendi mizanindan (PostgreSQL, tenant_<vkn> semasindaki
mizan_alt_kirilim tablosu) her 3 haneli TDHP kodunun o SIRKETE OZEL alt
kirilimlarini (orn. 191.05.00005 = "%20 5/10 Tevkifatli KDV") cikarir.
TDHP_GLOSSARY'nin aksine bu liste sirketten sirkete FARKLIDIR - 2026-07-24,
kullanici karari: "alt kirilimlar her muhasebeci icin farkli olabilir, sadece
ana basliklar (101, 102 gibi) sabit".

2026-08-05 - Excel'den (model_eval/exceller/<vkn>/mizan.xlsx) PostgreSQL'e
tasindi (kullanici karari: "her kullanicinin farkli mizan bilgisi oldugu icin
buna gore bir yapi tasarlamamiz lazim") - her sirketin mizani artik kendi
tenant semasindaki mizan_alt_kirilim tablosunda durur (bkz. core/db.py::_SCHEMA).
Excel'den DB'ye ilk yukleme icin scripts/mizan_excel_yukle.py (tek seferlik,
idempotent - TRUNCATE + INSERT).

Kullanim: core/single.py::predict_single_invoice() ana modelin urettigi
3 haneli kodu (orn. "191") aldiktan SONRA, bu kodun TUM alt kirilimlarini
(orn. 191'in altindaki 9 alt kod) ikinci bir LLM cagrisina (core/prompting.py::
build_alt_kirilim_prompt) verir - boylece alt kirilim secimi ayri, odakli
bir adimda yapilir, ana tahmin akisi (3 haneli kod bulma) etkilenmez."""

import logging
import re
import threading

from .db import get_conn

_logger = logging.getLogger(__name__)

_mizan_cache = {}
_mizan_cache_lock = threading.Lock()


def _kod_normalize(kod):
    """Hesap kodundaki ayirici tutarsizligini giderir: '191-01-00020' ya da
    '191 01 00020' -> '191.01.00020'. Sadece ayirici karakter normalize
    edilir (tire/bosluk -> nokta, ardisik nokta -> tek nokta) - rakamlar/
    uzunluk degismez, veri UYDURULMAZ (kullanici karari: guven skoru yok,
    sadece format temizligi). Excel'den DB'ye yuklerken kullanilir (bkz.
    scripts/mizan_excel_yukle.py) - DB'deki hesap_kodu zaten normalize
    halde tutulur, calisma zamaninda tekrar normalize edilmez."""
    kod = kod.strip()
    kod = re.sub(r"[\-\s]+", ".", kod)
    kod = re.sub(r"\.+", ".", kod)
    return kod.strip(".")


def _tenant_vkn_gecerli_mi(tenant_vkn):
    """get_conn()'un search_path ureten _tenant_semasi() ile ayni dogrulama
    (sadece rakam, 10 hane) - burada erken kontrol edilir ki gecersiz/bos
    own_vkn icin get_conn() ValueError firlatmasin, bu fonksiyon onun yerine
    sessizce bos sozluk donsun (mizan yok sayilir, cagiran taraf 3 haneli
    koda duser - ayni davranis mizan dosyasi yoksa da gecerliydi)."""
    return bool(tenant_vkn) and tenant_vkn.isdigit() and len(tenant_vkn) == 10


def get_alt_kirilimlar(tenant_vkn=None):
    """3 haneli TDHP koduna gore gruplanmis alt kirilim sozlugu doner:
    {"191": [("191.01.00020", "%20 Indirilecek KDV"), ...], ...}

    Sadece 3-seviyeli kodlar (XXX.YY.ZZZZZ formatinda, ana kodun DOGRUDAN
    alt kirilimlari) alinir - ust seviye ozet satirlari (orn. sadece "191"
    ya da "191.01") burada YOK, cunku onlar zaten TDHP_GLOSSARY'de ana
    kod olarak var; bu sozluk sadece "hangi alt kirilimdan birini secmen
    gerekiyor" sorusuna cevap veriyor.

    tenant_vkn gecersiz/bos ise (own_vkn belirtilmemis) YA DA bu sirketin
    mizan_alt_kirilim tablosu bossa/DB'ye baglanilamazsa exception FIRLATMAZ,
    loglayip BOS sozluk doner - cagiran taraf (core/single.py::
    _alt_kirilim_uygula) bunu "bu sirket icin alt kirilim yok" sayip 3
    haneli koda duser (2026-07-30'dan itibaren gecerli davranis, kaynak
    Excel'den DB'ye tasinsa da DEGISMEDI).

    Process-omru cache'lenir (rag_common.py::get_collection ile ayni desen,
    key=tenant_vkn) - DB her istekte yeniden sorgulanmaz."""
    key = tenant_vkn or ""
    if key in _mizan_cache:
        return _mizan_cache[key]
    with _mizan_cache_lock:
        if key not in _mizan_cache:
            if not _tenant_vkn_gecerli_mi(tenant_vkn):
                _logger.info(
                    "mizan.py: gecersiz/bos own_vkn (%r) - mizan yok sayilacak, "
                    "alt kirilim adimi bu istek icin devre disi (3 haneli koda dusulecek)",
                    tenant_vkn,
                )
                _mizan_cache[key] = {}
            else:
                try:
                    with get_conn(tenant_vkn=tenant_vkn) as conn:
                        with conn.cursor() as cur:
                            cur.execute("SELECT hesap_kodu, ana_kod, hesap_adi FROM mizan_alt_kirilim")
                            rows = cur.fetchall()
                    by_main_code = {}
                    for kod, ana_kod, ad in rows:
                        by_main_code.setdefault(ana_kod, []).append((kod, ad))
                    if not by_main_code:
                        _logger.info(
                            "mizan.py: tenant_%s.mizan_alt_kirilim bos - mizan yok sayilacak",
                            tenant_vkn,
                        )
                    _mizan_cache[key] = by_main_code
                except Exception as exc:  # noqa: BLE001
                    _logger.warning(
                        "mizan.py: tenant_%s.mizan_alt_kirilim okunamadi (%s) - mizan yok sayilacak",
                        tenant_vkn, exc,
                    )
                    _mizan_cache[key] = {}
    return _mizan_cache[key]


def reset_mizan_cache_for_tests():
    global _mizan_cache
    with _mizan_cache_lock:
        _mizan_cache = {}
