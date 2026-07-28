"""kalem_nace_esleme.py için ad-hoc doğrulama script'i (pytest değil).

Repo'da otomatik test altyapısı yok — bu script, gerçek ubls/ faturaları ve
sentetik örneklerle 6 senaryoyu (tek-NACE, tek-NACE-ama-oran-uyuşmuyor,
çoklu-NACE-havuz-uygun, çoklu-NACE-havuz-uyuşmuyor, genel-toplam-tek-oran,
genel-toplam-karışık) çalıştırıp çıktıyı elle gözlemlemek için yazıldı
(CLAUDE.md: "gerçekten çalıştırıp gözlemleme" disiplini). Proje kökünden
çalıştır:

    python3 test/test_kalem_nace.py

NOT (2026-07-20): Mimari basitleştirildi — kalem İÇERİĞİNE artık bakılmıyor,
LLM kaldırıldı. Satıcının TÜM NACE kodlarının izin verdiği oranlar tek bir
havuzda birleştirilir; kalemin oranı bu havuzda mı diye bakılır.
"""

import os
import sys

PROJE_KOKU = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(PROJE_KOKU, "src"))
os.chdir(PROJE_KOKU)

from efatura_kdv.ubl_parser import parse_ubl_invoice, Fatura, FaturaKalemi, Party, VergiKirilimi
from efatura_kdv.nace_kural_kontrolu import NaceOranTablosu
from efatura_kdv.kalem_nace_esleme import SaticiNaceBilgisi, satir_bazli_kontrol_et

oran_tablosu = NaceOranTablosu()

print("=" * 70)
print("SENARYO A — tek NACE, oran havuzda (Yurtiçi Kargo)")
print("=" * 70)
f = parse_ubl_invoice("ubls/YKB2025000012995-2b495f8e-a43d-7707-e063-2907010aed44-inbox.xml")
satici = SaticiNaceBilgisi(vkn=f.satici.vkn, nace_kodlari=["532009"])
sonuc = satir_bazli_kontrol_et(f, satici, oran_tablosu)
print("Genel karar:", sonuc.genel_karar)
for s in sonuc.satir_sonuclari:
    print("-", s.kalem_adi, "| beyan:", s.beyan_edilen_oranlar, "| havuz:", s.izin_verilen_oranlar_havuzu, "| karar:", s.karar)
    print("  gerekce:", s.gerekce)

print()
print("=" * 70)
print("SENARYO A2 — tek NACE ama beyan edilen oran havuzda yok")
print("=" * 70)
# Fatura %20 diyor ama 463304 (Dondurma toptan ticaret) sadece %1/%10 destekliyor.
print("463304 izin verilen oranlar:", oran_tablosu.izin_verilen_oranlar("463304"))
satici_a2 = SaticiNaceBilgisi(vkn=f.satici.vkn, nace_kodlari=["463304"])
sonuc_a2 = satir_bazli_kontrol_et(f, satici_a2, oran_tablosu)
print("Genel karar:", sonuc_a2.genel_karar)
for s in sonuc_a2.satir_sonuclari:
    print("-", s.kalem_adi, "| beyan:", s.beyan_edilen_oranlar, "| havuz:", s.izin_verilen_oranlar_havuzu, "| karar:", s.karar)
    print("  gerekce:", s.gerekce)

print()
print("=" * 70)
print("SENARYO B — çoklu NACE, havuz birleşiyor ve oran havuzda buluyor")
print("=" * 70)
# 532009 (sadece %20) + 463304 (%1 veya %10) -> havuz = {1, 10, 20}.
# Kargo faturasının oranı %20 olduğu için havuzda VAR, kalem içeriğine hiç bakılmadan uygun.
satici_b = SaticiNaceBilgisi(vkn=f.satici.vkn, nace_kodlari=["532009", "463304"])
sonuc_b = satir_bazli_kontrol_et(f, satici_b, oran_tablosu)
print("Genel karar:", sonuc_b.genel_karar)
for s in sonuc_b.satir_sonuclari:
    print("-", s.kalem_adi, "| beyan:", s.beyan_edilen_oranlar, "| havuz:", s.izin_verilen_oranlar_havuzu, "| karar:", s.karar)
    print("  gerekce:", s.gerekce)

print()
print("=" * 70)
print("SENARYO C — çoklu NACE, havuz birleşse de oran hiçbirinde yok")
print("=" * 70)
# 463304 (%1 veya %10) + varsayımsal başka bir %1/%10'lu kod -> havuz {1, 10}.
# Kargo faturasının oranı %20 olduğu için havuzda YOK -> insan incelemesi gerekli.
satici_c = SaticiNaceBilgisi(vkn=f.satici.vkn, nace_kodlari=["463304"])
sonuc_c = satir_bazli_kontrol_et(f, satici_c, oran_tablosu)
print("Genel karar:", sonuc_c.genel_karar)
for s in sonuc_c.satir_sonuclari:
    print("-", s.kalem_adi, "| beyan:", s.beyan_edilen_oranlar, "| havuz:", s.izin_verilen_oranlar_havuzu, "| karar:", s.karar)
    print("  gerekce:", s.gerekce)

print()
print("=" * 70)
print("SENARYO D — satır bazlı KDV yok, genel toplamda TEK oran")
print("=" * 70)
f2 = parse_ubl_invoice("ubls/0012025037182379-1a2ed6b9-eebf-4cc1-a9dd-7a7f7f4200fc-inbox.xml")
print("Satıcı:", f2.satici.vkn, f2.satici.unvan)
for k in f2.kalemler[:5]:
    print(" -", k.kalem_adi, "kdv_oranlari:", k.kdv_oranlari)
print("Genel KDV kırılımları:", [(k.oran, k.vergi_tipi_kodu) for k in f2.genel_kdv_kirilimlari])
satici_d = SaticiNaceBilgisi(vkn=f2.satici.vkn, nace_kodlari=["619099"])  # örnek tek NACE
sonuc_d = satir_bazli_kontrol_et(f2, satici_d, oran_tablosu)
for s in sonuc_d.satir_sonuclari:
    print("-", s.kalem_adi, "| beyan:", s.beyan_edilen_oranlar, "| karar:", s.karar)
    print("  gerekce:", s.gerekce)

print()
print("=" * 70)
print("SENARYO E — satır bazlı KDV yok, genel toplamda KARIŞIK oran (sentetik)")
print("=" * 70)
sentetik_fatura = Fatura(
    fatura_no="TEST-001",
    uuid="test-uuid",
    satici=Party(vkn="1111111111", unvan="Test A.Ş."),
    alici=Party(vkn="2222222222", unvan="Alıcı A.Ş."),
    kalemler=[
        FaturaKalemi(sira_no="1", kalem_adi="Karışık kalem 1", vergi_kirilimlari=[]),
        FaturaKalemi(sira_no="2", kalem_adi="Karışık kalem 2", vergi_kirilimlari=[]),
    ],
    genel_vergi_kirilimlari=[
        VergiKirilimi(oran=20.0, vergi_tipi_kodu="0015"),
        VergiKirilimi(oran=10.0, vergi_tipi_kodu="0015"),
    ],
)
satici_e = SaticiNaceBilgisi(vkn="1111111111", nace_kodlari=["532009"])
sonuc_e = satir_bazli_kontrol_et(sentetik_fatura, satici_e, oran_tablosu)
for s in sonuc_e.satir_sonuclari:
    print("-", s.kalem_adi, "| karar:", s.karar)
    print("  gerekce:", s.gerekce)

print()
print("=" * 70)
print("SENARYO F — genel istisna kodu (301, ihracat) ile oran uyuşmazlığı çözülüyor")
print("=" * 70)
f3 = parse_ubl_invoice("ubls/AKK2025000000071-4835c90e-4de8-461a-aca8-68d8cfab64c2-outbox.xml")
satici_f = SaticiNaceBilgisi(vkn=f3.satici.vkn, nace_kodlari=["254004", "282210", "254005", "282290"])
sonuc_f = satir_bazli_kontrol_et(f3, satici_f, oran_tablosu)
print("Genel karar:", sonuc_f.genel_karar)
for s in sonuc_f.satir_sonuclari:
    print("-", s.kalem_adi, "| beyan:", s.beyan_edilen_oranlar, "| karar:", s.karar)
    print("  gerekce:", s.gerekce)
