"""Geçmiş fatura kalemleriyle çapraz kontrol — ayrı bir bilgi/uyarı katmanı.

ÖNEMLİ: Bu modül KARAR ÜRETMEZ. NACE kural kontrolü (`nace_kural_kontrolu.py`,
`kalem_nace_esleme.py`) kararı (uygun/insan incelemesi gerekli) her zaman
olduğu gibi üretmeye devam eder — bu modül sadece geçmişte aynı kalemin
hangi oran(lar)la kesildiğini gösteren ek bir sinyal döner. Karar bu
sinyale göre DEĞİŞTİRİLMEZ (kullanıcı kararı, 2026-07-21).

Bu, PROJECT.md §3.7'nin "geçmiş fatura verisi sınıflandırmada girdi olarak
kullanılmaz" kararını İHLAL ETMEZ — o karar geçmiş veriden kategori/oran
ÖĞRENİP karar ÜRETMEYİ yasaklıyor (golden rule 1 ihlali riski); burada
geçmiş veri sadece insana gösterilen bir çapraz kontrol notudur.

Kapsam: sadece OUTBOX faturalar (bizim kestiğimiz) — bkz.
docs/reference/gecmis-fatura-semasi.md, scripts/gecmis_faturalari_yukle.py.

`faturayi_gecmise_kaydet()` (2026-07-21 eklendi) bu tabloya YAZAR — çoklu
fatura kontrolü (api.py'deki /fatura/coklu-kontrol) sonrasında, sadece
kullanıcının kendi şirketinin kestiği doğrulanmış faturalar otomatik olarak
buraya kaydedilir. Aynı fatura_no'nun yinelenen yüklemede tekrar
eklenmediğine dikkat edilir (istatistik şişmesin diye).

Şema detayları: docs/reference/gecmis-fatura-semasi.md.
"""

from __future__ import annotations

import os
import re
from contextlib import contextmanager
from dataclasses import dataclass, field

import psycopg2
from psycopg2 import sql
from psycopg2.pool import ThreadedConnectionPool

from .kalem_nace_esleme import kalem_istisna_kodlari
from .ubl_parser import Fatura


def _tenant_semasi(satici_vkn: str) -> str:
    """satici_vkn'den tenant şema adını türetir (2026-07-30, çoklu şirket
    geçişi). Şema adı SQL identifier'dır, %s ile parametrize EDİLEMEZ —
    burada sıkı doğrulanır (sadece rakam, VKN 10 hanelidir) ki SQL injection
    riski (şema adı üzerinden) oluşmasın."""
    if not satici_vkn or not satici_vkn.isdigit():
        raise ValueError(f"Geçersiz VKN formatı, şema adı türetilemez: {satici_vkn!r}")
    return f"tenant_{satici_vkn}"


def normalize_kalem_adi(kalem_adi: str) -> str:
    """Eşleşme için kalem adını küçük harfe çevirir, fazla boşlukları temizler.

    Tek gerçek kaynak burasıdır — scripts/gecmis_faturalari_yukle.py bu
    fonksiyonu import eder (2026-08-05, önceden birebir aynı mantığın ikinci
    bir kopyası vardı; biri değişip diğeri unutulursa normalize edilmiş
    anahtarların sessizce eşleşmeme riski taşıdığı için import'a çevrildi)."""
    return re.sub(r"\s+", " ", kalem_adi.strip().lower())


@dataclass
class GecmisOranOzeti:
    """Bir (satıcı, kalem adı) çifti için geçmişte görülen bir oranın özeti.

    istisna_kodu (2026-07-22 eklendi): oran %0 ve bir istisna koduyla
    kaydedilmişse (ör. ihracat, kod 301) bu alan doludur — "bu kalem %0
    kesilmiş" ile "bu kalem istisna nedeniyle %0 kesilmiş" farklı bilgiler,
    ikincisi inceleyen insana daha fazla bağlam verir (bkz. PROJECT.md §3.9)."""

    oran: float
    kac_kez: int
    son_gorulme_tarihi: str | None
    istisna_kodu: str | None = None


@dataclass
class GecmisKontrolSonucu:
    """Tek bir kalem için geçmiş çapraz kontrolünün sonucu — KARAR İÇERMEZ,
    sadece bilgi notu üretir."""

    kalem_adi: str | None
    beyan_edilen_oranlar: list[float]
    gecmis_oranlar: list[GecmisOranOzeti] = field(default_factory=list)

    @property
    def gecmiste_hic_gorulmus_mu(self) -> bool:
        return len(self.gecmis_oranlar) > 0

    @property
    def gecmisle_uyusuyor_mu(self) -> bool | None:
        """Beyan edilen oran(lar), geçmişte görülen oranlardan biriyle
        eşleşiyor mu? Geçmiş veri hiç yoksa None (bilinmiyor, ne uyumlu ne
        uyumsuz denemez)."""
        if not self.gecmis_oranlar:
            return None
        gecmis_oran_degerleri = {g.oran for g in self.gecmis_oranlar}
        return any(oran in gecmis_oran_degerleri for oran in self.beyan_edilen_oranlar)

    @property
    def bilgi_notu(self) -> str:
        """İnsana gösterilecek, karar İÇERMEYEN bilgi notu."""
        if not self.gecmis_oranlar:
            return "Bu kalem adı geçmiş faturalarımızda bulunamadı."

        parcalar = []
        for g in sorted(self.gecmis_oranlar, key=lambda g: -g.kac_kez):
            istisna_notu = f", istisna kodu {g.istisna_kodu}" if g.istisna_kodu else ""
            parcalar.append(f"%{g.oran:g}{istisna_notu} ({g.kac_kez} kez, son: {g.son_gorulme_tarihi})")
        gecmis_ozet = ", ".join(parcalar)

        if self.gecmisle_uyusuyor_mu:
            return f"Bu kalem geçmişte şu oran(lar)la kesilmiş: {gecmis_ozet}. Beyan edilen oranla uyumlu."
        return (
            f"UYARI: Bu kalem geçmişte şu oran(lar)la kesilmiş: {gecmis_ozet}. "
            f"Ancak şimdi beyan edilen oran ({self.beyan_edilen_oranlar}) bunlardan farklı — "
            "mevzuat değişmiş olabilir, kontrol edilmesi önerilir."
        )


class GecmisFaturaDeposu:
    """PostgreSQL'deki gecmis_fatura_kalemleri tablosunu sorgular.

    NaceOranTablosu'nun aksine tüm tabloyu belleğe yüklemez — geçmiş veri
    büyüyebileceği için (yeni outbox faturalar zamanla eklenir) her sorgu
    doğrudan DB'ye gider, indeks (satici_vkn, kalem_adi_normalize) bu
    sorguyu hızlı tutar.

    Connection pool (2026-07-22 eklendi, bkz. GOREV_MIMARI_DUZELTME.md #3):
    önceden her sorgu/yazma kendi `psycopg2.connect()`'ini açıp kapatıyordu
    — çok kullanıcılı yükte her istek yeni bir TCP+auth handshake açıyor,
    Postgres'in `max_connections` sınırını hızla tüketebiliyordu. Artık
    `ThreadedConnectionPool` süreç başlangıcında bir kez kuruluyor,
    bağlantılar `getconn()`/`putconn()` ile ödünç alınıp iade ediliyor —
    FastAPI (`api.py`) thread havuzunda eşzamanlı istekleri işlediği için
    thread-safe bir pool gerekiyor (basit tekil bağlantı yeterli değil)."""

    def __init__(self, database_url: str | None = None, minconn: int = 2, maxconn: int = 10):
        self._database_url = database_url or os.environ.get("DATABASE_URL")
        if not self._database_url:
            raise RuntimeError(
                "DATABASE_URL env var tanımlı değil — örn. "
                "postgresql://user:pass@localhost:5432/efatura_kdv "
                "(bkz. docs/how-to/postgres-kurulum.md)"
            )
        self._pool = ThreadedConnectionPool(minconn, maxconn, self._database_url)

    def kapat(self) -> None:
        """Süreç kapanırken havuzdaki tüm bağlantıları serbest bırakır
        (bkz. api.py _lifespan)."""
        self._pool.closeall()

    @contextmanager
    def _tenant_baglantisi(self, satici_vkn: str):
        """Havuzdan bir bağlantı alır, search_path'i bu şirketin tenant
        şemasına çevirir (2026-07-30, çoklu şirket geçişi). Havuz TEK ve
        bağlantılar şirketler arası yeniden kullanıldığı için search_path
        DSN'e gömülemez — her ödünç almada yeniden set edilmeli.

        Şema henüz yoksa (yeni şirket onboard edilmemiş) burada
        OLUŞTURULMAZ — bu, scripts/tenant_onboarding.py'nin sorumluluğu;
        burada sessizce şema oluşturmak, yanlış yazılmış bir VKN'nin fark
        edilmeden yeni bir boş şema açmasına yol açar."""
        conn = self._pool.getconn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    sql.SQL("SET search_path TO {}, public").format(
                        sql.Identifier(_tenant_semasi(satici_vkn))
                    )
                )
            yield conn
        finally:
            self._pool.putconn(conn)

    def gecmis_oranlari_getir(self, satici_vkn: str, kalem_adi: str) -> list[GecmisOranOzeti]:
        """Verilen satıcı+kalem adı için geçmişte görülen oranları, kaç kez
        görüldüğü ve son görülme tarihiyle birlikte döner."""
        kalem_adi_normalize = normalize_kalem_adi(kalem_adi)

        with self._tenant_baglantisi(satici_vkn) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT oran, istisna_kodu, COUNT(*) AS kac_kez, MAX(fatura_tarihi) AS son_gorulme
                    FROM gecmis_fatura_kalemleri
                    WHERE satici_vkn = %s AND kalem_adi_normalize = %s
                    GROUP BY oran, istisna_kodu
                    ORDER BY kac_kez DESC
                    """,
                    (satici_vkn, kalem_adi_normalize),
                )
                rows = cur.fetchall()

        return [
            GecmisOranOzeti(
                oran=float(oran),
                kac_kez=kac_kez,
                son_gorulme_tarihi=str(son_gorulme) if son_gorulme else None,
                istisna_kodu=istisna_kodu,
            )
            for oran, istisna_kodu, kac_kez, son_gorulme in rows
        ]


def gecmis_kontrol_et(
    satici_vkn: str,
    kalem_adi: str,
    beyan_edilen_oranlar: list[float],
    depo: GecmisFaturaDeposu,
) -> GecmisKontrolSonucu:
    """Tek bir kalem için geçmiş çapraz kontrolünü çalıştırır. KARAR ÜRETMEZ —
    sadece bilgi notu içeren bir sonuç döner (bkz. modül docstring'i)."""
    gecmis_oranlar = depo.gecmis_oranlari_getir(satici_vkn, kalem_adi)
    return GecmisKontrolSonucu(
        kalem_adi=kalem_adi,
        beyan_edilen_oranlar=beyan_edilen_oranlar,
        gecmis_oranlar=gecmis_oranlar,
    )


def faturayi_gecmise_kaydet(
    depo: GecmisFaturaDeposu,
    satici_vkn: str,
    fatura_no: str,
    fatura_tarihi: str | None,
    kalemler: list[tuple[str, float, "str | None"]],
    kaynak: str = "coklu-kontrol-api",
) -> bool:
    """Bir faturanın kalem-oran satırlarını gecmis_fatura_kalemleri tablosuna
    yazar. Çağıran taraf (api.py), SADECE bu faturayı kullanıcının kendi
    şirketinin kestiğini (satici_vkn == fatura.satici.vkn) doğruladıktan
    sonra bu fonksiyonu çağırmalıdır — burası bu doğrulamayı YAPMAZ, sadece
    yazar (kalem_nace_esleme.py'deki VKN güvenlik kontrolü bunu zaten
    garanti ediyor, bkz. api.py fatura_coklu_kontrol()).

    Aynı fatura_no zaten kayıtlıysa hiçbir şey yazmadan False döner —
    yinelenen yükleme "kaç kez kesilmiş" istatistiğini şişirmesin diye
    (kullanıcı kararı, 2026-07-21). Yeni satır(lar) yazıldıysa True döner.

    Yarış durumu düzeltmesi (2026-07-22, bkz. GOREV_MIMARI_DUZELTME.md #1):
    "SELECT var mı → yoksa INSERT" mantığı eskiden iki ayrı adımdı, aralarında
    lock/transaction yoktu — iki eşzamanlı istek aynı fatura_no'yu gönderirse
    ikisi de "yok" görüp ikisi de yazabiliyordu (istatistik çift sayılır).
    Artık tek transaction içinde `islenmis_faturalar` claim tablosuna
    `INSERT ... ON CONFLICT DO NOTHING RETURNING` ile "kazanan tek istek"
    deseni kuruluyor: satır dönerse (kazandık) asıl kalemler aynı transaction'da
    yazılıp commit edilir; satır dönmezse (PRIMARY KEY çakıştı, biri bizden
    önce commit etmiş) hiçbir şey yazmadan False dönülür. Bu, PostgreSQL'in
    constraint garantisine dayanır — uygulama seviyesinde ayrı bir lock
    gerekmez.

    kalemler: [(kalem_adi, oran, istisna_kodu), ...] — bir kalemin birden
    fazla KDV kırılımı varsa (nadir) birden fazla tuple olarak geçilir.
    istisna_kodu (2026-07-22 eklendi) — oran %0/istisna kaynaklıysa hangi
    istisna koduyla kesildiği (bkz. GecmisOranOzeti.istisna_kodu, PROJECT.md
    §3.9). Çağıran taraf bu bilgiyi bilmiyorsa None geçebilir."""
    with depo._tenant_baglantisi(satici_vkn) as conn:
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO islenmis_faturalar (fatura_no)
                    VALUES (%s)
                    ON CONFLICT (fatura_no) DO NOTHING
                    RETURNING fatura_no
                    """,
                    (fatura_no,),
                )
                if cur.fetchone() is None:
                    conn.rollback()
                    return False  # zaten işlenmiş (bu istek ya da eşzamanlı bir başkası)

                for kalem_adi, oran, istisna_kodu in kalemler:
                    cur.execute(
                        """
                        INSERT INTO gecmis_fatura_kalemleri
                            (satici_vkn, kalem_adi_normalize, kalem_adi_orijinal,
                             oran, istisna_kodu, fatura_no, fatura_tarihi, kaynak_dosya)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                        """,
                        (
                            satici_vkn,
                            normalize_kalem_adi(kalem_adi),
                            kalem_adi,
                            oran,
                            istisna_kodu,
                            fatura_no,
                            fatura_tarihi,
                            kaynak,
                        ),
                    )
            conn.commit()
            return True
        except Exception:
            conn.rollback()
            raise


def fatura_kalemlerini_kayit_icin_hazirla(fatura: Fatura) -> list[tuple[str, float, "str | None"]]:
    """Bir Fatura'nın kalemlerinden faturayi_gecmise_kaydet()'e verilecek
    (kalem_adi, oran, istisna_kodu) listesini üretir.

    İstisna düzeltmesi (2026-07-22, bkz. scripts/gecmis_faturalari_yukle.py
    aynı isimli mantık): kalemin sayısal oranı (kdv_oranlari) varsa o
    kullanılır (istisna_kodu=None); yoksa ama kalemde/fatura genelinde bir
    istisna kodu varsa (ör. ihracat, kod 301) oran %0 + istisna_kodu dolu
    olarak eklenir. Önceki sürüm bu ikinci durumu hiç yakalamıyordu — istisna
    faturaları (AKK2025000000003 gibi) geçmiş tabloya hiç girmiyordu.
    api.py ve test/web_arayuz.py bu fonksiyonu ortak kullanır (kod tekrarı
    yerine tek kaynak)."""
    kalemler: list[tuple[str, float, "str | None"]] = []
    for kalem in fatura.kalemler:
        if not kalem.kalem_adi:
            continue

        if kalem.kdv_oranlari:
            for oran in kalem.kdv_oranlari:
                kalemler.append((kalem.kalem_adi, oran, None))
            continue

        for istisna_kodu, _aciklama in kalem_istisna_kodlari(kalem, fatura):
            kalemler.append((kalem.kalem_adi, 0.0, istisna_kodu))

    return kalemler
