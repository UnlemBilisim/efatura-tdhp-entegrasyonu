"""Faz 1, alt-adım 3: kalem (satır) bazında KDV oranı kontrolü.

Satıcının NACE kod(ları) fatura ile birlikte DIŞARIDAN gelir (bkz.
`SaticiNaceBilgisi`) — VKN→NACE excel lookup yazılmadı, çünkü sistem sadece
fatura sahibinin (satıcının) kestiği faturalarda çalışabiliyor ve bu bilgi
üst sistemden zaten geliyor (kullanıcı kararı, bkz. PROJECT.md §0.2).

MİMARİ KARAR (2026-07-20, kullanıcı kararıyla basitleştirildi): kalem
İÇERİĞİNE (kalem metnine) hiç bakılmaz — hangi NACE'ye ait olduğu tespit
EDİLMEZ. Bunun yerine satıcının TÜM NACE kodlarının izin verdiği oranlar
tek bir "izin verilen oranlar havuzu"nda birleştirilir; kalemin beyan
edilen oranı bu havuzda varsa (herhangi bir NACE'nin izin verdiği bir oran
ise) `uygun`, değilse `insan_incelemesi_gerekli` denir. LLM kullanılmaz,
kalem metni okunmaz — sadece sayısal oran karşılaştırması yapılır.

Bu, `nace_kural_kontrolu.kontrol_et()`'in TEK NACE için yaptığı kontrolün
ÇOKLU NACE'ye genelleştirilmiş hali. Kontrol mantığının kendisi
`nace_kural_kontrolu.py`'de kalıyor, değişmedi.

Şema detayları: docs/reference/nace-kdv-excel-yapisi.md.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum

from .ubl_parser import Fatura, FaturaKalemi
from .nace_kural_kontrolu import NaceOranTablosu

# NACE'den BAĞIMSIZ, işlemin türüne bağlı genel istisna/özel-durum kodları.
# Kaynak: Istisna_Kodlari_GIB.xlsx (GİB e-Belge Uygulamaları - UBL-TR (Kod
# Listeleri) Kılavuzu, Versiyon 1.42, Mart 2026, ebelge.gib.gov.tr) —
# kullanıcı tarafından repoya eklendi, 2026-07-20'de programatik olarak
# okunup doğrulandı. Kılavuzdaki 7 kategorinin TAMAMI (Kısmi İstisna 201-250,
# Tam İstisna 301-351, İhraç Kayıtlı Satışlar 701-704, Özel Matrah 801-812,
# ÖTV İstisna 101-151, Konaklama Vergisi İstisna 001, Diğer İşlem Türü 555)
# — HARİÇ gerçek bir istisna/özel-durum maddesi OLMAYAN, sadece "özel kodu
# yok ama 0 oranlı fatura gerekiyor" durumları için kullanılan dolgu kodlar:
# 151 (ÖTV-İstisna Olmayan Diğer), 250 (Kısmi İstisna-Diğerleri),
# 350 (Tam İstisna-Diğerleri), 351 (Tam İstisna-İstisna Olmayan Diğer).
# Bu dolgu kodlarda hâlâ sadece bilgi notu verilir (_fatura_istisna_notu()),
# karar `insan_incelemesi_gerekli` kalır — kesin bir mevzuat maddesine
# dayanmadıkları için "uygun" denilemez (kullanıcı onayı, 2026-07-20).
GENEL_ISTISNA_KODLARI = {
    # Konaklama Vergisi İstisna (001)
    "001",
    # ÖTV İstisna (101-151) — 151 hariç (dolgu kod)
    "101", "102", "103", "104", "105", "106", "107", "108",
    # Kısmi İstisna (201-250) — 250 hariç (dolgu kod)
    "201", "202", "204", "205", "206", "207", "208", "209", "211", "212",
    "213", "214", "215", "216", "217", "218", "219", "220", "221", "223",
    "225", "226", "227", "228", "229", "230", "231", "232", "234", "235",
    "236", "237", "238", "239", "240", "241", "242",
    # Tam İstisna (301-351) — 350/351 hariç (dolgu kodlar)
    "301", "302", "303", "304", "305", "306", "307", "308", "309", "310",
    "311", "312", "313", "314", "315", "316", "317", "318", "319", "320",
    "321", "322", "323", "324", "325", "326", "327", "328", "329", "330",
    "331", "332", "333", "334", "335", "336", "337", "338", "339", "340",
    "341", "342", "343", "344",
    # Diğer İşlem Türü (555)
    "555",
    # İhraç Kayıtlı Satışlar (701-704)
    "701", "702", "703", "704",
    # Özel Matrah (801-812)
    "801", "802", "803", "804", "805", "806", "807", "808", "809", "810",
    "811", "812",
}

logger = logging.getLogger("efatura_kdv.kalem_nace_esleme")


class SaticiVknUyusmazligiHatasi(ValueError):
    """satir_bazli_kontrol_et()'e verilen satici_nace.vkn, faturanın gerçek
    satıcı VKN'siyle uyuşmadığında fırlatılır — "bu fatura bize ait değil"
    anlamına gelir (bkz. PROJECT.md §3.9, kullanıcı bu faturaların ayrı bir
    grup/sekmede toplanmasını istedi, 2026-07-21).

    ValueError'dan türetildi — mevcut `except ValueError` blokları (api.py,
    web_arayuz.py) hâlâ yakalar, ama artık isteyen taraf bu spesifik hatayı
    diğer ValueError'lardan (varsa) ayırt edebilir."""


@dataclass
class SaticiNaceBilgisi:
    """Fatura ile birlikte dışarıdan gelen girdi — VKN→NACE lookup yok."""

    vkn: str
    nace_kodlari: list[str] = field(default_factory=list)  # ana + tali faaliyet(ler)


class SatirKararTuru(Enum):
    """Nihai, kullanıcıya/muhasebe akışına giden karar. Bilerek sadece 2
    değer var — Faz 1'de kesin "uyumsuz" hiç üretilmiyor (bkz. PROJECT.md
    §0.1): oran uyuşmasa bile temkinli davranılıp insana devrediliyor,
    çünkü kalem içeriği/istisna/tevkifat nüansı henüz tam çözülmüyor."""

    UYGUN = "uygun"
    INSAN_INCELEMESI_GEREKLI = "insan_incelemesi_gerekli"


@dataclass
class SatirKontrolSonucu:
    """satir_bazli_kontrol_et()'in her bir kalem için ürettiği nihai sonuç."""

    kalem_sira_no: str | None
    kalem_adi: str | None
    beyan_edilen_oranlar: list[float]
    nace_kodlari_kontrol_edildi: list[str]
    izin_verilen_oranlar_havuzu: list[float]
    karar: SatirKararTuru
    gerekce: str


@dataclass
class FaturaSatirBazliSonuc:
    fatura_no: str | None
    uuid: str | None
    satici_vkn: str | None
    satir_sonuclari: list[SatirKontrolSonucu]

    @property
    def genel_karar(self) -> SatirKararTuru:
        """Herhangi bir satır insan incelemesi gerektiriyorsa fatura geneli
        de öyledir — en temkinli satır kazanır (golden rule 3)."""
        if any(
            s.karar == SatirKararTuru.INSAN_INCELEMESI_GEREKLI
            for s in self.satir_sonuclari
        ):
            return SatirKararTuru.INSAN_INCELEMESI_GEREKLI
        return SatirKararTuru.UYGUN


def _izin_verilen_oranlar_havuzu(
    nace_kodlari: list[str], oran_tablosu: NaceOranTablosu
) -> tuple[list[float], list[str], dict[str, list[float]]]:
    """Satıcının TÜM NACE kodlarının izin verdiği oranları TEK bir havuzda
    birleştirir. Örnek: NACE-A sadece %20, NACE-B %1/%10/%20 destekliyorsa,
    havuz = {1.0, 10.0, 20.0} olur — kalem hangisine ait olursa olsun, bu
    üç orandan biriyse `uygun` sayılır (kalem içeriği hiç incelenmez).

    Dönen değerler: (1) birleşik havuz, (2) excel'de gerçekten bulunan NACE
    kodlarının listesi, (3) her NACE kodunun KENDİ izin verdiği oranlar
    sözlüğü (`{nace_kodu: oranlar}`) — bu üçüncü değer, bir kalemin oranı
    uygun bulunduğunda "TAM OLARAK HANGİ NACE sayesinde uygun" diye
    gerekçede belirtebilmek için tutuluyor (_nace_gerekce_metni)."""
    havuz: set[float] = set()
    bulunan_kodlar: list[str] = []
    nace_oranlari: dict[str, list[float]] = {}
    for kod in nace_kodlari:
        izin_verilenler = oran_tablosu.izin_verilen_oranlar(kod)
        if izin_verilenler is None:
            continue  # NACE excelde yok — bu kod havuza katkı yapmaz
        bulunan_kodlar.append(kod)
        nace_oranlari[kod] = izin_verilenler
        havuz.update(izin_verilenler)
    return sorted(havuz), bulunan_kodlar, nace_oranlari


def _nace_gerekce_metni(
    beyan_edilen_oranlar: list[float], nace_oranlari: dict[str, list[float]]
) -> str:
    """Beyan edilen HER oran için, o oranı hangi NACE kod(lar)ının
    desteklediğini "%20 -> NACE '532009'" formatında listeler. Birden fazla
    NACE aynı oranı destekliyorsa hepsi gösterilir (hangisinin "doğru" NACE
    olduğu bu modülde aranmaz — kalem içeriği incelenmediği için bilinmiyor,
    sadece HANGİ NACE'lerin bu oranı meşru kıldığı gösterilir)."""
    parcalar = []
    for oran in beyan_edilen_oranlar:
        destekleyen_kodlar = [
            kod for kod, oranlar in nace_oranlari.items() if oran in oranlar
        ]
        if destekleyen_kodlar:
            parcalar.append(f"%{oran:g} -> NACE {destekleyen_kodlar}")
    return "; ".join(parcalar)


def kalem_istisna_kodlari(kalem: FaturaKalemi, fatura: Fatura) -> list[tuple[str, str | None]]:
    """Kalemde veya (kalemde yoksa) faturanın genel toplamında bulunan
    (istisna_kodu, istisna_aciklama) çiftlerini döner. İstisna kodu genelde
    ihracat faturalarında kalemde değil faturanın genelinde bulunur (bkz.
    docs/reference/ubl-fatura-yapisi.md).

    Public (2026-07-22'de _-prefiksi kaldırıldı) — scripts/gecmis_faturalari_yukle.py
    da bu fonksiyonu kullanıyor, kod tekrarı yerine tek kaynak (bkz.
    PROJECT.md §3.9, "oran yok ama istisna kodu var" kalemlerin geçmiş
    tabloya kaydedilmesi kararı)."""
    kalem_kirilimlari = [
        (k.istisna_kodu, k.istisna_aciklama)
        for k in kalem.kdv_kirilimlari
        if k.istisna_kodu
    ]
    if kalem_kirilimlari:
        return kalem_kirilimlari
    return [
        (k.istisna_kodu, k.istisna_aciklama)
        for k in fatura.genel_vergi_kirilimlari
        if k.istisna_kodu
    ]


def _genel_istisna_dogrulamasi(kalem: FaturaKalemi, fatura: Fatura) -> str | None:
    """Kalemde/faturada NACE'den bağımsız, bilinen bir GENEL istisna kodu
    (`GENEL_ISTISNA_KODLARI`, GİB Kod Listeleri Kılavuzu kaynaklı) varsa
    kısa bir gerekçe döner (bu durumda çağıran taraf `uygun` kararı verir)
    — yoksa None.

    SADECE resmi kılavuzda AÇIKÇA tanımlanmış, gerçek bir mevzuat maddesine
    dayanan istisna/özel-durum kodları burada doğrulanır. "151"/"250"/"350"/
    "351" gibi "Diğerleri"/"İstisna Olmayan Diğer" anlamına gelen dolgu
    kodlar BİLİNÇLİ olarak dışarıda bırakıldı — bunlar gerçek bir istisna
    maddesi değil (kullanıcı onayı, 2026-07-20)."""
    for kod, aciklama in kalem_istisna_kodlari(kalem, fatura):
        if kod in GENEL_ISTISNA_KODLARI:
            aciklama_metni = f" ({aciklama})" if aciklama else ""
            return (
                f"Beyan edilen oran, NACE'lerin izin verdiği havuzda olmasa da "
                f"faturada bilinen bir istisna kodu var: {kod}{aciklama_metni} — "
                "NACE'den bağımsız, geçerli bir istisna türü olduğu için uygun "
                "kabul edildi."
            )
    return None


def _fatura_istisna_notu(kalem: FaturaKalemi, fatura: Fatura) -> str | None:
    """Kalemde veya faturanın genel toplamında BİLİNMEYEN/genel-olmayan bir
    istisna kodu varsa kısa bir bilgi notu döner, yoksa None.

    `_genel_istisna_dogrulamasi()`'nden FARKLI: burası kesin bir istisna
    doğrulaması yapmaz, sadece "belki bir sebep var, insan kontrol etsin"
    diye ipucu verir — SADECE `GENEL_ISTISNA_KODLARI`'nda OLMAYAN kodlar
    için (ör. 151/250/350/351 gibi "Diğerleri"/"İstisna Olmayan Diğer"
    dolgu kodları, ya da GİB listesinde hiç bulunamayan bilinmeyen kodlar)."""
    for kod, aciklama in kalem_istisna_kodlari(kalem, fatura):
        if kod in GENEL_ISTISNA_KODLARI:
            continue  # bunlar _genel_istisna_dogrulamasi() tarafından ele alınır
        aciklama_metni = f" ({aciklama})" if aciklama else ""
        return (
            f"Not: faturada istisna kodu {kod}{aciklama_metni} mevcut — "
            "bu oran farkının sebebi olabilir, ancak bu modül bu tür istisna "
            "kodunu doğrulamaz (Faz 2 kapsamı), sadece bilgi amaçlıdır."
        )
    return None


def _kalem_beyan_edilen_oranlari(
    kalem: FaturaKalemi, fatura: Fatura
) -> tuple[list[float], str | None]:
    """Kalemin beyan edilen oranlarını döner. Satır seviyesinde oran yoksa
    faturanın genel toplamındaki BENZERSİZ oran sayısına göre:
    - tam 1 farklı oran varsa -> o oran bu kalem için de kullanılır.
    - 0 ya da 2+ farklı oran varsa -> boş liste + insan-incele gerekçesi.

    Bu fallback gerçekten gerekli: bazı gerçek faturalarda (özellikle
    TEMELFATURA/telekom tipi, ör. Turkcell) satır seviyesinde HİÇ
    cac:TaxTotal yok — KDV sadece fatura genelinde tek bir yerde yazıyor
    (bkz. docs/reference/ubl-fatura-yapisi.md). Bu durumda "kalemin kendi
    oranı yok diye atla" demek yerine, TEK bir genel oran varsa güvenle o
    oranı kullanmak (kullanıcı kararı, 2026-07-20) daha faydalı; ama BİRDEN
    FAZLA farklı oran karışıksa hangi kaleme ait olduğu belirlenemediği için
    tahmin edilmiyor (döndürülen tuple'ın 2. elemanı doluysa çağıran taraf
    bunu direkt insan_incelemesi_gerekli yapar).
    """
    if kalem.kdv_oranlari:
        return kalem.kdv_oranlari, None

    # set() ile benzersizleştirip sorted() ile listeye çeviriyoruz — asıl
    # önemli olan len(genel_oranlar): 1 ise güvenli, 0 ya da 2+ ise değil.
    genel_oranlar = sorted({
        k.oran for k in fatura.genel_kdv_kirilimlari if k.oran is not None
    })

    if len(genel_oranlar) == 1:
        return genel_oranlar, None
    if not genel_oranlar:
        return [], "Kalemde ve fatura genelinde KDV oranı bulunamadı."
    return [], (
        "Satır bazında KDV oranı yok, fatura genelinde birden fazla farklı "
        f"oran karışık ({genel_oranlar}) — hangi kaleme ait olduğu "
        "belirlenemiyor."
    )


def satir_bazli_kontrol_et(
    fatura: Fatura,
    satici_nace: SaticiNaceBilgisi,
    oran_tablosu: NaceOranTablosu,
) -> FaturaSatirBazliSonuc:
    """Faturanın her kalemi için, satıcının TÜM NACE kodlarının izin
    verdiği oranlar havuzuna göre kontrol yapar (kalem içeriği incelenmez)."""
    logger.info(
        "=== FATURA KONTROLÜ BAŞLIYOR: fatura_no=%s satici_vkn=%s kalem_sayisi=%d ===",
        fatura.fatura_no, fatura.satici.vkn, len(fatura.kalemler),
    )
    # Güvenlik kontrolü: çağıran taraf yanlışlıkla BAŞKA bir satıcının NACE
    # bilgisini bu faturaya vermiş olabilir (ör. iki fatura karışmış). Bu
    # sessizce yanlış bir "uygun" kararına yol açacağı için (fatura X'in
    # oranı, satıcı Y'nin NACE'ine göre kontrol edilmiş olur) erken ve
    # gürültülü şekilde (exception) durduruluyor — sessiz veri hatası yerine.
    if fatura.satici.vkn and satici_nace.vkn != fatura.satici.vkn:
        raise SaticiVknUyusmazligiHatasi(
            f"satici_nace.vkn ({satici_nace.vkn!r}) faturanın satıcı VKN'siyle "
            f"({fatura.satici.vkn!r}) uyuşmuyor — yanlış satıcıya ait NACE "
            "bilgisiyle karşılaştırma yapılmasını önlemek için işlem durduruldu."
        )

    # Havuz, fatura başına BİR KEZ hesaplanır — her kalem için satıcının
    # NACE'leri aynı olduğundan tekrar tekrar hesaplamaya gerek yok.
    havuz, bulunan_nace_kodlari, nace_oranlari = _izin_verilen_oranlar_havuzu(
        satici_nace.nace_kodlari, oran_tablosu
    )
    logger.info(
        "Satıcı NACE kodları=%s | excelde bulunanlar=%s | izin verilen oranlar havuzu=%s",
        satici_nace.nace_kodlari, bulunan_nace_kodlari, havuz,
    )

    satir_sonuclari = []
    for kalem in fatura.kalemler:
        beyan_edilen_oranlar, engel_gerekcesi = _kalem_beyan_edilen_oranlari(
            kalem, fatura
        )

        if engel_gerekcesi is not None:
            logger.info(
                "KALEM #%s (%r): %s -> İNSAN İNCELEMESİ GEREKLİ",
                kalem.sira_no, kalem.kalem_adi, engel_gerekcesi,
            )
            satir_sonuclari.append(
                SatirKontrolSonucu(
                    kalem_sira_no=kalem.sira_no,
                    kalem_adi=kalem.kalem_adi,
                    beyan_edilen_oranlar=[],
                    nace_kodlari_kontrol_edildi=bulunan_nace_kodlari,
                    izin_verilen_oranlar_havuzu=havuz,
                    karar=SatirKararTuru.INSAN_INCELEMESI_GEREKLI,
                    gerekce=engel_gerekcesi,
                )
            )
            continue

        if not bulunan_nace_kodlari:
            # Satıcının NACE kod(lar)ının HİÇBİRİ excelde bulunamadı — havuz
            # boş, hiçbir oranla kıyaslama yapılamaz.
            gerekce = (
                f"Satıcının bildirilen NACE kod(lar)ı ({satici_nace.nace_kodlari}) "
                "referans tabloda bulunamadı."
            )
            logger.info("KALEM #%s (%r): %s -> İNSAN İNCELEMESİ GEREKLİ", kalem.sira_no, kalem.kalem_adi, gerekce)
            satir_sonuclari.append(
                SatirKontrolSonucu(
                    kalem_sira_no=kalem.sira_no,
                    kalem_adi=kalem.kalem_adi,
                    beyan_edilen_oranlar=beyan_edilen_oranlar,
                    nace_kodlari_kontrol_edildi=[],
                    izin_verilen_oranlar_havuzu=[],
                    karar=SatirKararTuru.INSAN_INCELEMESI_GEREKLI,
                    gerekce=gerekce,
                )
            )
            continue

        # Asıl kontrol: beyan edilen HER oran, havuzda var mı? Tek bir oran
        # bile havuzda değilse kalem "uygun" sayılmaz (en temkinli oran
        # kazanır — bir kalemde teorik olarak birden fazla kırılım olabilir).
        tumu_havuzda_mi = all(oran in havuz for oran in beyan_edilen_oranlar)
        logger.info(
            "KALEM #%s (%r): beyan edilen oran(lar)=%s | havuz=%s | tümü havuzda mı=%s",
            kalem.sira_no, kalem.kalem_adi, beyan_edilen_oranlar, havuz, tumu_havuzda_mi,
        )

        if tumu_havuzda_mi:
            karar = SatirKararTuru.UYGUN
            # Sadece "havuzda var" demek yerine TAM OLARAK hangi NACE kodunun
            # bu oranı desteklediğini de belirt — inceleyen kişi hangi
            # yetkiye dayanarak "uygun" denildiğini görebilsin.
            gerekce = (
                f"Beyan edilen oran(lar) {beyan_edilen_oranlar} uygun: "
                f"{_nace_gerekce_metni(beyan_edilen_oranlar, nace_oranlari)}."
            )
        else:
            # Oran havuzla uyuşmadı — ama bu istisna kaynaklı bir fark
            # olabilir. Önce GENEL istisna kodlarını (301/302/311/701)
            # kontrol et: bunlardan biri varsa artık kesin olarak `uygun`
            # denebilir (2026-07-20 kapsam genişletmesi — bkz. PROJECT.md).
            genel_istisna_gerekce = _genel_istisna_dogrulamasi(kalem, fatura)
            if genel_istisna_gerekce is not None:
                karar = SatirKararTuru.UYGUN
                gerekce = genel_istisna_gerekce
                logger.info(
                    "KALEM #%s (%r): oran havuzla uyuşmuyor ama genel istisna "
                    "kodu tespit edildi -> UYGUN",
                    kalem.sira_no, kalem.kalem_adi,
                )
            else:
                # Genel istisna da yoksa hâlâ temkinli kal — ama en azından
                # BİLİNMEYEN bir istisna kodu (13/ı, 13/c, ya da 350/351 gibi
                # gerçek istisna olmayan kodlar) varsa gerekçeye bilgi notu
                # ekle, inceleyen insana ipucu versin (ama karar değişmez).
                karar = SatirKararTuru.INSAN_INCELEMESI_GEREKLI
                gerekce = (
                    f"Beyan edilen oran(lar) {beyan_edilen_oranlar}, satıcının "
                    f"NACE kod(lar)ının ({bulunan_nace_kodlari}) izin verdiği "
                    f"oranlar havuzunda ({havuz}) değil."
                )
                istisna_notu = _fatura_istisna_notu(kalem, fatura)
                if istisna_notu:
                    gerekce = f"{gerekce} {istisna_notu}"

        satir_sonuclari.append(
            SatirKontrolSonucu(
                kalem_sira_no=kalem.sira_no,
                kalem_adi=kalem.kalem_adi,
                beyan_edilen_oranlar=beyan_edilen_oranlar,
                nace_kodlari_kontrol_edildi=bulunan_nace_kodlari,
                izin_verilen_oranlar_havuzu=havuz,
                karar=karar,
                gerekce=gerekce,
            )
        )

    return FaturaSatirBazliSonuc(
        fatura_no=fatura.fatura_no,
        uuid=fatura.uuid,
        satici_vkn=fatura.satici.vkn,
        satir_sonuclari=satir_sonuclari,
    )
