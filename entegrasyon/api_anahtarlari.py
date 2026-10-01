"""Şirkete bağlı API anahtarları — hangi istemcinin hangi şirket(ler) adına
işlem yapabileceğini belirler.

Anahtarın kendisi saklanmaz, sadece sha256 özeti tutulur: anahtarlar
yüksek entropili rastgele değerler olduğu için tuzsuz sha256 yeterlidir ve
veritabanı sızsa bile anahtarlar sızmaz. Anahtarlar `api_anahtari_yonet.py`
ile üretilir/iptal edilir."""

from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass

from model_eval_yolu import model_eval_yolunu_ekle

ANAHTAR_ON_EKI = "efk_"

_TABLO_SQL = """
CREATE TABLE IF NOT EXISTS public.api_anahtarlari (
    id             BIGSERIAL PRIMARY KEY,
    etiket         TEXT NOT NULL UNIQUE,
    anahtar_hash   TEXT NOT NULL UNIQUE,
    tum_sirketler  BOOLEAN NOT NULL DEFAULT FALSE,
    izinli_vknler  TEXT[] NOT NULL DEFAULT '{}',
    aktif          BOOLEAN NOT NULL DEFAULT TRUE,
    olusturulma    TIMESTAMPTZ NOT NULL DEFAULT now(),
    son_kullanim   TIMESTAMPTZ
);
"""

_tablo_hazir = False


@dataclass(frozen=True)
class IstemciKimligi:
    etiket: str
    tum_sirketler: bool
    izinli_vknler: frozenset

    def vkn_izinli_mi(self, vkn: str | None) -> bool:
        return self.tum_sirketler or (vkn in self.izinli_vknler)


def anahtar_ozeti(anahtar: str) -> str:
    return hashlib.sha256(anahtar.encode("utf-8")).hexdigest()


def _get_conn():
    model_eval_yolunu_ekle()
    from core.db import get_conn

    return get_conn()


def tabloyu_hazirla() -> None:
    global _tablo_hazir
    if _tablo_hazir:
        return
    with _get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(_TABLO_SQL)
        conn.commit()
    _tablo_hazir = True


def anahtari_dogrula(anahtar: str) -> IstemciKimligi | None:
    """Aktif bir anahtarsa istemci kimliğini döner, değilse None."""
    tabloyu_hazirla()
    with _get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """UPDATE public.api_anahtarlari SET son_kullanim = now()
                   WHERE anahtar_hash = %s AND aktif
                   RETURNING etiket, tum_sirketler, izinli_vknler""",
                (anahtar_ozeti(anahtar),),
            )
            satir = cur.fetchone()
        conn.commit()
    if satir is None:
        return None
    etiket, tum_sirketler, izinli_vknler = satir
    return IstemciKimligi(etiket, tum_sirketler, frozenset(izinli_vknler))


def anahtar_olustur(etiket: str, izinli_vknler: list[str], tum_sirketler: bool = False) -> str:
    """Yeni anahtar üretip kaydeder; düz metin anahtarı SADECE burada döner."""
    if not tum_sirketler and not izinli_vknler:
        raise ValueError("En az bir VKN verilmeli ya da tum_sirketler=True olmalı")
    for vkn in izinli_vknler:
        if not (vkn.isdigit() and len(vkn) == 10):
            raise ValueError(f"Geçersiz VKN: {vkn!r} — 10 haneli sayısal olmalı")
    anahtar = ANAHTAR_ON_EKI + secrets.token_urlsafe(32)
    tabloyu_hazirla()
    with _get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO public.api_anahtarlari
                   (etiket, anahtar_hash, tum_sirketler, izinli_vknler)
                   VALUES (%s, %s, %s, %s)""",
                (etiket, anahtar_ozeti(anahtar), tum_sirketler, list(izinli_vknler)),
            )
        conn.commit()
    return anahtar


def anahtar_vkn_ekle(etiket: str, vkn: str) -> bool:
    """Var olan aktif bir anahtarın izinli VKN listesine yeni bir VKN ekler;
    anahtarın kendi değeri DEĞİŞMEZ, yalnızca kapsamı genişler. Aynı mali
    müşavirin yeni bir müşterisi (şirketi) onboard edildiğinde kullanılır —
    her müşavire bir anahtar ilkesi (2026-10-01 kullanıcı kararı) bunu
    gerektirir, aksi halde her yeni müşteride anahtar iptal edilip yeniden
    üretilir ve dış ekibin elindeki değer bayatlardı.

    Zaten o VKN'ye yetkiliyse (veya anahtar tüm şirketlere yetkiliyse)
    listeye tekrar eklenmez, yine de True döner. Aktif anahtar yoksa False
    döner."""
    if not (vkn.isdigit() and len(vkn) == 10):
        raise ValueError(f"Geçersiz VKN: {vkn!r} — 10 haneli sayısal olmalı")
    tabloyu_hazirla()
    with _get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """UPDATE public.api_anahtarlari
                   SET izinli_vknler = ARRAY(
                       SELECT DISTINCT unnest(izinli_vknler || %s::text[])
                   )
                   WHERE etiket = %s AND aktif
                   RETURNING etiket""",
                ([vkn], etiket),
            )
            guncellendi = cur.fetchone() is not None
        conn.commit()
    return guncellendi


def anahtari_iptal_et(etiket: str) -> bool:
    tabloyu_hazirla()
    with _get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE public.api_anahtarlari SET aktif = FALSE WHERE etiket = %s AND aktif",
                (etiket,),
            )
            iptal_edildi = cur.rowcount == 1
        conn.commit()
    return iptal_edildi


def anahtarlari_listele() -> list[dict]:
    tabloyu_hazirla()
    with _get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT etiket, tum_sirketler, izinli_vknler, aktif, olusturulma, son_kullanim
                   FROM public.api_anahtarlari ORDER BY olusturulma"""
            )
            sutunlar = [d[0] for d in cur.description]
            return [dict(zip(sutunlar, satir)) for satir in cur.fetchall()]
