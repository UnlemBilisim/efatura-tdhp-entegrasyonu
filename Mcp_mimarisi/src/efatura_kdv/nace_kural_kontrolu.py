"""Faz 1: NACE koduna göre KDV oranı kural kontrolü.

Mevzuat MCP'si yok (Faz 2'de gelecek) — bu modül sadece `nace_oranlari`
PostgreSQL tablosundaki "bu NACE hangi oranları kesebilir" bilgisiyle beyan
edilen oranı karşılaştırır. Oran ÜRETMEZ, sadece eşleşme kontrolü yapar
(bkz. PROJECT.md §0.1, §3.2 — Değişmez Kural 1 istisnası).

Veri kaynağı 2026-07-21'de excel'den (`nace_kdv (1).xlsx`) PostgreSQL'e
taşındı (çoklu-kullanıcı/eşzamanlı erişim gerekçesiyle, bkz. PROJECT.md
§3.6.1). Tablo içeriği hâlâ `2026_KOD_DEGISIKLIKLERI` sayfasından türetildi
(fatura tarihinden bağımsız — kullanıcı kararı, 2026-07-17) ve
`scripts/excel_to_postgres.py` ile bir kereye mahsus taşındı.

Şema detayları: docs/reference/nace-kdv-excel-yapisi.md
("PostgreSQL Şeması" bölümü).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from enum import Enum

import psycopg2

# DB sütun adı → oran değeri. Excel'deki KDV%0/KDV %1/KDV %10/KDV %20
# sütunlarının birebir karşılığı (bkz. scripts/excel_to_postgres.py).
_KDV_SUTUNLARI = {
    "kdv_0": 0.0,
    "kdv_1": 1.0,
    "kdv_10": 10.0,
    "kdv_20": 20.0,
}


def _nace_kodu_normalize_et(nace_kodu: str) -> str:
    """NACE kodunu noktalardan arındırıp karşılaştırılabilir hale getirir.

    `nace_oranlari` tablosu Excel'deki (`YENİ KOD`) ham haliyle NOKTASIZ
    dolduruldu (ör. '254004'), ama fatura/istek tarafında kod noktalı gelebilir
    (ör. '25.40.04') — ikisi aynı NACE kodu ama string olarak eşleşmez. Bu
    2026-07-28'de gerçek bir faturada (AKL2026000000211) NACE '25.40.04'
    tabloda '254004' olarak var olduğu halde 'bulunamadı' denip faturanın
    sessizce insan incelemesine düşmesine yol açtı."""
    return str(nace_kodu).strip().replace(".", "")


class KararTuru(Enum):
    """Faz 1 kontrolünün üretebileceği iki karar — kesin 'uyumsuz' burada YOK."""

    UYGUN = "uygun"
    INSAN_INCELEMESI_GEREKLI = "insan_incelemesi_gerekli"


@dataclass
class KontrolSonucu:
    """kontrol_et()'in dönüş değeri — karar + kararın dayandığı veriler."""

    karar: KararTuru
    nace_kodu: str
    beyan_edilen_oran: float | None
    izin_verilen_oranlar: list[float]
    gerekce: str


class NaceOranTablosu:
    """PostgreSQL'deki `nace_oranlari` tablosunu belleğe yükleyip NACE→izin
    verilen oranlar sorgusu sunar. Bu tablo değişen+değişmeyen tüm kodları
    içeren tam ve güncel veridir; fatura tarihinden bağımsız olarak tek
    kaynak olarak kullanılır.

    Bağlantı `DATABASE_URL` env var'ından okunur (örn.
    `postgresql://user:pass@localhost:5432/efatura_kdv`) — bkz.
    docs/how-to/postgres-kurulum.md.
    """

    def __init__(self, database_url: str | None = None):
        database_url = database_url or os.environ.get("DATABASE_URL")
        if not database_url:
            raise RuntimeError(
                "DATABASE_URL env var tanımlı değil — örn. "
                "postgresql://user:pass@localhost:5432/efatura_kdv "
                "(bkz. docs/how-to/postgres-kurulum.md)"
            )
        self._tablo = self._tabloyu_yukle(database_url)

    @staticmethod
    def _tabloyu_yukle(database_url: str) -> dict[str, list[float]]:
        """nace_oranlari tablosunun tamamını NACE kodu → izin verilen oranlar sözlüğüne çevirir."""
        conn = psycopg2.connect(database_url)
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT nace_kodu, kdv_0, kdv_1, kdv_10, kdv_20 FROM nace_oranlari"
                )
                rows = cur.fetchall()
        finally:
            conn.close()

        tablo: dict[str, list[float]] = {}
        for nace_kodu, kdv_0, kdv_1, kdv_10, kdv_20 in rows:
            bayraklar = {"kdv_0": kdv_0, "kdv_1": kdv_1, "kdv_10": kdv_10, "kdv_20": kdv_20}
            # Bir NACE'nin BİRDEN FAZLA oran sütunu TRUE olabilir (ör. tarım
            # kodlarında hem %1 hem %20) — bu "çok oranlı NACE" durumudur,
            # bu yüzden tek bir oran değil, liste tutuluyor.
            oranlar = [
                _KDV_SUTUNLARI[sutun] for sutun, deger in bayraklar.items() if deger
            ]
            tablo[_nace_kodu_normalize_et(nace_kodu)] = oranlar
        return tablo

    def izin_verilen_oranlar(self, nace_kodu: str) -> list[float] | None:
        """Belleğe yüklenmiş tablodan bir NACE kodunu sorgular.

        Verilen NACE kodu için izin verilen oran listesini döner.
        NACE bulunamazsa None döner.

        DİKKAT: dönüş değeri `None` (NACE hiç yok) ile `[]` (NACE var ama
        hiçbir oran sütunu TRUE değil, ör. veri eksikliği) FARKLI anlamlar
        taşır — `kontrol_et()` bu ikisini ayrı ele almaz (ikisi de insan
        incelemesine düşürür) ama ileride ayrıştırmak istenirse bu ayrım
        burada zaten korunuyor."""
        return self._tablo.get(_nace_kodu_normalize_et(nace_kodu))


def kontrol_et(
    nace_kodu: str,
    beyan_edilen_oran: float,
    tablo: NaceOranTablosu,
) -> KontrolSonucu:
    """Faz 1 kural kontrolü (bkz. PROJECT.md §0.1, 5 adımlı mantık).

    1. NACE tabloda bulunamazsa → insan incelemesi gerekli.
    2. Beyan edilen oran, NACE'nin izin verdiği oranlardan biriyse → uygun
       (çok-oranlı NACE'lerde bile — hangi alt-kategori olduğu Faz 1'de
       aranmaz, kullanıcı onayı 2026-07-17).
    3. Değilse → insan incelemesi gerekli (kesin "uyumsuz" Faz 1'de üretilmez).
    """
    izin_verilenler = tablo.izin_verilen_oranlar(nace_kodu)

    if izin_verilenler is None:
        # NACE kodu tabloda HİÇ YOK — ya kapsam dışı bir kod, ya da eski/
        # geçersiz bir kod (bkz. docs/reference/nace-kdv-excel-yapisi.md).
        # Kesinlikle "uyumsuz" denmez; oran hiç bilinmediği için tahmin
        # yapmak yerine insana devredilir (golden rule 3).
        return KontrolSonucu(
            karar=KararTuru.INSAN_INCELEMESI_GEREKLI,
            nace_kodu=nace_kodu,
            beyan_edilen_oran=beyan_edilen_oran,
            izin_verilen_oranlar=[],
            gerekce=f"NACE kodu '{nace_kodu}' referans tabloda bulunamadı.",
        )

    # `in` kontrolü: beyan_edilen_oran float, izin_verilenler de float
    # listesi (0.0/1.0/10.0/20.0 gibi tam sayı değerli float'lar) — ondalık
    # yuvarlama riski taşımayan sabit değerler olduğu için `in` ile eşitlik
    # kontrolü burada güvenli.
    if beyan_edilen_oran in izin_verilenler:
        return KontrolSonucu(
            karar=KararTuru.UYGUN,
            nace_kodu=nace_kodu,
            beyan_edilen_oran=beyan_edilen_oran,
            izin_verilen_oranlar=izin_verilenler,
            gerekce=(
                f"Beyan edilen oran %{beyan_edilen_oran:g}, NACE '{nace_kodu}' "
                f"için izin verilen oranlardan biri ({izin_verilenler})."
            ),
        )

    # Oran NACE'nin izin verdiği listede yok — bu kesin "uyumsuz/hatalı"
    # anlamına gelmez! Faz 1'de kalem metni hiç analiz edilmediği için
    # (bkz. PROJECT.md §0.1), bu durumun asıl sebebi bir istisna/tevkifat
    # olabilir (bkz. kalem_nace_esleme.py'deki GENEL_ISTISNA_KODLARI kontrolü,
    # bu modülün BİLMEDİĞİ, üst katmanda ele alınan bir durum). Bu yüzden
    # burada da temkinli davranılıp insana devredilir.
    return KontrolSonucu(
        karar=KararTuru.INSAN_INCELEMESI_GEREKLI,
        nace_kodu=nace_kodu,
        beyan_edilen_oran=beyan_edilen_oran,
        izin_verilen_oranlar=izin_verilenler,
        gerekce=(
            f"Beyan edilen oran %{beyan_edilen_oran:g}, NACE '{nace_kodu}' "
            f"için izin verilen oranlar arasında değil ({izin_verilenler})."
        ),
    )
