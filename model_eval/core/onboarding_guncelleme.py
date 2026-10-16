"""Kayıtlı bir şirketin onboarding verisini GÜNCELLEME: gelen veriyi mevcutla karşılaştır, yalnızca FARKI uygula,
eski değeri ve güncellenme zamanını veritabanında logla.

Neden ayrı bir modül: ilk kurulum (`scripts/musteri_onboard_toplu.py::_musteriyi_onboard_et`) mizanı TRUNCATE + INSERT ile
yeniden yazar ve tüm faturaları yeniden indeksler — kayıtlı bir şirket için bu, değişmeyen veriyi gereksiz yere silip
yazmak (ve embedding'i baştan hesaplamak) olurdu. Burada her parça (NACE / mizan / RAG emsalleri) mevcut durumla
karşılaştırılır; fark yoksa HİÇBİR ŞEY yazılmaz.

Değişiklik geçmişi: `onboarding_guncelleme_gecmisi` tablosu (şirketin KENDİ şemasında; varsayılan şirkette public).
Her değişen kayıt için eski değer + yeni değer + zaman + hangi iş/anahtar. İlk kurulumdaki toplu yazma LOGLANMAZ
(geçmiş yalnızca güncellemeleri izler).

Parçalar ve kurallar:
  * NACE: dosya yoksa dokunulmaz (yokluk silme değildir). Karşılaştırma nokta/boşluktan bağımsız (`10.71.01` == `107101`).
  * Mizan: dosya TAM hesap planı (anlık görüntü) kabul edilir — yeni olan eklenir, adı değişen güncellenir (`updated_at`),
    dosyada artık olmayan SİLİNİR (eski değeri geçmişte kalır). Veri kaybına karşı koruma: dosyada hiç 3 seviyeli hesap yoksa
    ya da mevcut hesapların yarıdan fazlası silinecekse (eksik/yanlış dosya şüphesi) mizan DEĞİŞTİRİLMEZ, uyarı döner.
  * RAG emsalleri: yeni fatura eklenir, içeriği (hesap kayıtları/karşı taraf) değişen güncellenir; aynı olana dokunulmaz
    (embedding yeniden hesaplanmaz). Dosyada olmayan emsal ASLA silinmez (`/fatura/onayla` ile eklenmiş olabilir)."""

from __future__ import annotations

import json
import re
from pathlib import Path

from psycopg2.extras import Json

GECMIS_SQL = """
CREATE TABLE IF NOT EXISTS onboarding_guncelleme_gecmisi (
    id                BIGSERIAL PRIMARY KEY,
    vkn               TEXT NOT NULL,
    alan              TEXT NOT NULL CHECK (alan IN ('nace', 'mizan', 'rag')),
    islem             TEXT NOT NULL CHECK (islem IN ('eklendi', 'guncellendi', 'silindi')),
    anahtar           TEXT,
    eski_deger        JSONB,
    yeni_deger        JSONB,
    guncelleme_zamani TIMESTAMPTZ NOT NULL DEFAULT now(),
    is_id             TEXT,
    istemci           TEXT
);
CREATE INDEX IF NOT EXISTS idx_onboarding_guncelleme_gecmisi_zaman
    ON onboarding_guncelleme_gecmisi (guncelleme_zamani DESC);
"""

MIZAN_SILME_ORANI_SINIRI = 0.5
MIZAN_SILME_KORUMASI_MIN_SATIR = 10  # çok küçük planlarda oran anlamsız
RAG_SORGU_PARCASI = 500


class GuncellemeHatasi(ValueError):
    """Güncelleme verisi kullanılamaz (örn. mizan dosyasında hesap yok)."""


def gecmisi_hazirla(cur) -> None:
    cur.execute(GECMIS_SQL)


def gecmise_yaz(cur, vkn, alan, islem, anahtar, eski, yeni, is_id, istemci) -> None:
    cur.execute(
        """INSERT INTO onboarding_guncelleme_gecmisi
           (vkn, alan, islem, anahtar, eski_deger, yeni_deger, is_id, istemci)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
        (vkn, alan, islem, anahtar, Json(eski) if eski is not None else None,
         Json(yeni) if yeni is not None else None, is_id, istemci),
    )


# ---------------------------------------------------------------- NACE

def nace_normalize(kodlar) -> list:
    """Nokta/boşluk ve boş satırları atıp sıralı, tekrarsız liste döner (karşılaştırma için)."""
    return sorted({re.sub(r"[\s.]", "", str(k)) for k in (kodlar or []) if re.sub(r"[\s.]", "", str(k))})


def nace_fark(mevcut, yeni) -> dict:
    m, y = set(nace_normalize(mevcut)), set(nace_normalize(yeni))
    return {"degisti": m != y, "eklenen": sorted(y - m), "cikan": sorted(m - y)}


def nace_guncelle(vkn, yeni_kodlar, cur, is_id, istemci, getir, kaydet) -> dict:
    """`getir(vkn) -> liste`, `kaydet(vkn, liste)` enjekte edilir (sirket_bilgileri kendi bağlantısını açar).
    Geçmiş satırı ÖNCE yazılır (commit çağıranda); kaydetme hata verirse çağıran rollback eder → yarım iz kalmaz."""
    mevcut = getir(vkn)
    fark = nace_fark(mevcut, yeni_kodlar)
    if not fark["degisti"]:
        return {"degisti": False}
    gecmisi_hazirla(cur)
    gecmise_yaz(cur, vkn, "nace", "guncellendi" if mevcut else "eklendi", "nace_kodlari",
                {"nace_kodlari": mevcut} if mevcut else None, {"nace_kodlari": list(yeni_kodlar)}, is_id, istemci)
    kaydet(vkn, list(yeni_kodlar))
    return {"degisti": True, "eklenen": fark["eklenen"], "cikan": fark["cikan"]}


# ---------------------------------------------------------------- MİZAN

def mizan_fark(mevcut: dict, yeni: dict) -> dict:
    """{kod: ad} sözlükleri. eklenen {kod: ad}, degisen {kod: (eski_ad, yeni_ad)}, silinen {kod: ad}."""
    return {
        "eklenen": {k: v for k, v in yeni.items() if k not in mevcut},
        "degisen": {k: (mevcut[k], v) for k, v in yeni.items() if k in mevcut and mevcut[k] != v},
        "silinen": {k: v for k, v in mevcut.items() if k not in yeni},
    }


def mizan_guncelle(satirlar, cur, vkn, is_id, istemci) -> dict:
    """satirlar: [(hesap_kodu, ana_kod, hesap_adi)] (yalnızca 3 seviyeli kodlar). Aynı `cur` (tenant search_path'li);
    commit çağıranda — değişiklik + geçmiş TEK işlemde."""
    yeni = {kod: ad for kod, _ana, ad in satirlar}
    ana_kodlar = {kod: ana for kod, ana, _ad in satirlar}
    if not yeni:
        raise GuncellemeHatasi(
            "Mizan dosyasında 3 seviyeli hesap (örn. 320.01.00272) bulunamadı — sütun başlıkları ya da HESAP KODU "
            "hücrelerinin metin biçimi kontrol edilmeli. Mevcut mizan DEĞİŞTİRİLMEDİ."
        )
    gecmisi_hazirla(cur)
    cur.execute("SELECT hesap_kodu, hesap_adi FROM mizan_alt_kirilim")
    mevcut = {k: a for k, a in cur.fetchall()}
    fark = mizan_fark(mevcut, yeni)
    ozet = {"eklenen": len(fark["eklenen"]), "degisen": len(fark["degisen"]), "silinen": len(fark["silinen"]),
            "uygulandi": False, "toplam": len(yeni)}
    if not (fark["eklenen"] or fark["degisen"] or fark["silinen"]):
        return ozet

    if len(mevcut) >= MIZAN_SILME_KORUMASI_MIN_SATIR and len(fark["silinen"]) > len(mevcut) * MIZAN_SILME_ORANI_SINIRI:
        ozet["uyari"] = (
            f"Mizan değişikliği UYGULANMADI: mevcut {len(mevcut)} hesabın {len(fark['silinen'])} tanesi dosyada yok "
            "(eksik/yanlış dosya şüphesi). Dosya gerçekten tam hesap planıysa bize bildirin."
        )
        return ozet

    for kod, ad in fark["eklenen"].items():
        cur.execute("INSERT INTO mizan_alt_kirilim (hesap_kodu, ana_kod, hesap_adi) VALUES (%s, %s, %s)", (kod, ana_kodlar[kod], ad))
        gecmise_yaz(cur, vkn, "mizan", "eklendi", kod, None, {"hesap_adi": ad}, is_id, istemci)
    for kod, (eski, yeni_ad) in fark["degisen"].items():
        cur.execute("UPDATE mizan_alt_kirilim SET hesap_adi = %s, updated_at = now() WHERE hesap_kodu = %s", (yeni_ad, kod))
        gecmise_yaz(cur, vkn, "mizan", "guncellendi", kod, {"hesap_adi": eski}, {"hesap_adi": yeni_ad}, is_id, istemci)
    for kod, eski in fark["silinen"].items():
        cur.execute("DELETE FROM mizan_alt_kirilim WHERE hesap_kodu = %s", (kod,))
        gecmise_yaz(cur, vkn, "mizan", "silindi", kod, {"hesap_adi": eski}, None, is_id, istemci)
    ozet["uygulandi"] = True
    return ozet


# ---------------------------------------------------------------- RAG emsalleri

def _meta_ozeti(meta: dict) -> dict:
    """Karşılaştırılacak alanlar: karşı taraf, yön, tür ve hesap kayıtları (sıradan bağımsız)."""
    try:
        girdiler = json.loads(meta.get("entries_json") or "[]")
    except ValueError:
        girdiler = []
    return {
        "vkn": meta.get("vkn") or "", "account_title": meta.get("account_title") or "",
        "direction": meta.get("direction") or "", "invoice_type": meta.get("invoice_type") or "",
        "entries": sorted(json.dumps(e, ensure_ascii=False, sort_keys=True) for e in girdiler),
    }


def rag_fark(mevcut: dict, yeni_kayitlar: list) -> dict:
    """mevcut: {id: metadata}; yeni_kayitlar: [(id, doc, meta)]. Döner: yeni / degisen / ayni (id listeleri + kayıtlar)."""
    yeni, degisen, ayni = [], [], []
    for kid, doc, meta in yeni_kayitlar:
        if kid not in mevcut:
            yeni.append((kid, doc, meta))
        elif _meta_ozeti(mevcut[kid]) != _meta_ozeti(meta):
            degisen.append((kid, doc, meta))
        else:
            ayni.append(kid)
    return {"yeni": yeni, "degisen": degisen, "ayni": ayni}


def rag_kayitlarini_hazirla(json_dizini: Path) -> list:
    """`yevmiye_fatura_esle` çıktısı JSON'lardan (`build_vector_db.index_directory` ile AYNI yöntemle) [(id, doc, meta)]."""
    from core.parsing import load_invoice_paths, normalize_code3, normalize_dc, parse_invoice
    from rag_common import build_retrieval_text, extract_named_gt_entries, invoice_metadata

    kayitlar = []
    for yol in load_invoice_paths(json_dizini):
        fatura = parse_invoice(yol)
        if not fatura["gt_pairs"]:
            continue
        with open(yol, "r", encoding="utf-8") as f:
            ham = json.load(f)
        isimli = extract_named_gt_entries(ham, normalize_code3, normalize_dc)
        if not isimli:
            continue
        kayitlar.append((fatura["invoice_id"], build_retrieval_text(fatura), invoice_metadata(fatura, isimli)))
    return kayitlar


def rag_guncelle(kayitlar, koleksiyon, cur, vkn, is_id, istemci) -> dict:
    """koleksiyon: ChromaDB koleksiyonu (get/upsert). Yalnızca yeni+değişen yazılır (embedding yalnızca onlar için hesaplanır)."""
    gecmisi_hazirla(cur)
    mevcut = {}
    idler = [k[0] for k in kayitlar]
    for i in range(0, len(idler), RAG_SORGU_PARCASI):
        parca = idler[i:i + RAG_SORGU_PARCASI]
        sonuc = koleksiyon.get(ids=parca, include=["metadatas"])
        for kid, meta in zip(sonuc.get("ids") or [], sonuc.get("metadatas") or []):
            mevcut[kid] = meta or {}
    fark = rag_fark(mevcut, kayitlar)
    yazilacak = fark["yeni"] + fark["degisen"]
    for kid, doc, meta in yazilacak:
        eski = mevcut.get(kid)
        gecmise_yaz(cur, vkn, "rag", "guncellendi" if eski is not None else "eklendi", kid,
                    {"account_title": eski.get("account_title"), "entries_json": eski.get("entries_json")} if eski is not None else None,
                    {"account_title": meta.get("account_title"), "entries_json": meta.get("entries_json")}, is_id, istemci)
    if yazilacak:
        koleksiyon.upsert(ids=[k[0] for k in yazilacak], documents=[k[1] for k in yazilacak], metadatas=[k[2] for k in yazilacak])
    return {"yeni": len(fark["yeni"]), "degisen": len(fark["degisen"]), "ayni": len(fark["ayni"]), "taranan": len(kayitlar)}
