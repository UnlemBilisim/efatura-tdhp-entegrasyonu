"""Ayni anda islenen pahali istek sayisini sinirlar (2026-09-11, kullanici
karari — 'islemleri siraya alalim, hepsini ayni anda islemeyelim').

Neden threading.Semaphore (asyncio.Semaphore DEGIL): /fatura/isle ve
/fatura/kontrol-et endpoint'leri SYNC fonksiyonlar (`def`, `async def`
degil) — FastAPI bunlari kendi ic thread pool'unda calistirir. asyncio
primitifleri farkli thread'ler arasinda guvenli degildir (her thread'in
kendi event loop'u olabilir/olmayabilir), threading.Semaphore ise GIL
altinda thread-safe ve tam da bu senaryo icin tasarlanmis.

Limit ASILMAZ/reddedilmez — asan istekler semaphore serbest kalana kadar
BEKLER (kuyruga alinir), kullanicinin istedigi "hepsini ayni anda
islemeyelim" davranisi budur; rate limiting (istegi 429 ile reddetme)
DEGILDIR, o ayri/kapsam disi birakildi (kullanici karari, 2026-09-11).

UYARI - SEMAFOR SURECE OZELDIR, UVICORN WORKER SAYISIYLA CARPILIR
(2026-10-01, TODO.md maddesi): Bu modul-seviyesi Semaphore her Python
sureci icin AYRI olusur. Su an hem Mcp_mimarisi hem entegrasyon
`docker/supervisord.conf`'ta `--workers` BELIRTILMEDEN (tek worker)
calistirildigi icin limit gercekten MAX_ESZAMANLI_ISLEM'dir. Ama ileride
performans icin `uvicorn ... --workers N` eklenirse, her worker kendi
semaforunu tutar - gercek es zamanli limit MAX_ESZAMANLI_ISLEM * N olur,
sessizce ve fark edilmeden. Worker sayisi artirilacaksa: (a) MAX_ESZAMANLI_
ISLEM'i N'e bolup dusur, YA DA (b) paylasilan bir sinirlayiciya (orn.
Postgres advisory lock, Redis) gecilmeli - ikinci yol process sayisindan
BAGIMSIZ calisir ama ek bir bagimlilik gerektirir, simdilik (a) yeterli."""

from __future__ import annotations

import os
import threading
from contextlib import contextmanager


def _limit_olustur(env_var_adi: str, varsayilan: int) -> threading.Semaphore:
    limit = int(os.environ.get(env_var_adi, str(varsayilan)))
    if limit < 1:
        limit = 1
    return threading.Semaphore(limit)


# Varsayilan 2 - kullanici "2-3 paralellik" dedi, ortadan bir deger secildi;
# MAX_ESZAMANLI_ISLEM env var'i ile degistirilebilir.
_fatura_isle_semafor = _limit_olustur("MAX_ESZAMANLI_ISLEM", 2)


@contextmanager
def fatura_isle_sirasi():
    """`with fatura_isle_sirasi():` blogu icindeki kod, ayni anda en fazla
    MAX_ESZAMANLI_ISLEM kadar calisir - fazlasi burada bekler."""
    _fatura_isle_semafor.acquire()
    try:
        yield
    finally:
        _fatura_isle_semafor.release()
