"""Karar izi (2026-10-19, kullanıcı isteği): bir faturanın nasıl işlendiğinin adım adım kaydı — gelen veri nasıl işlendi, KİM karar verdi (kural / model / emsal /
doğrulama), NEDEN, modele hangi istem (prompt) gitti, hangi kural hangi sonucu seçti. İzleme panelinde "Karar izi" olarak gösterilir (izleme/static/panel.js).

Tasarım kuralları:
  * Toplayıcı İSTEĞE BAĞLIDIR: `predict_single_invoice(..., iz=None)` varsayılanında hiçbir şey kaydedilmez, davranış ve performans AYNI kalır.
  * İz kaydı işlemi ASLA bozmaz: `ekle` içindeki her hata yutulur (iz yardımcı bir kayıttır, kararın parçası değildir).
  * Dış API cevabına GİRMEZ (istemler ve mizan listeleri iç bilgidir); yalnızca sunucudaki gelen-istek arşivine `iz.json` olarak yazılır (aynı saklama süresi).
  * Yalnızca model_eval'in bilmesi gereken şeyi bilir; entegrasyon katmanı aynı sınıfı `entegrasyon/model_eval_koprusu.py` üzerinden kullanır.

`karar_veren` değerleri: "sistem" (girdi/özet, karar değil), "kural" (deterministik kural), "llm" (dil modeli), "rag" (geçmiş emsal araması),
"dogrulama" (deterministik doğrulama), "kullanici" (insan)."""

from __future__ import annotations

import time

KARAR_VERENLER = ("sistem", "kural", "llm", "rag", "dogrulama", "kullanici")
# Tek bir metin alanı bundan uzunsa kesilir (iz dosyası şişmesin); kesildiği belirtilir.
MAX_METIN = 120_000


def _guvenli(deger, derinlik=0):
    """İz'e yazılacak değeri JSON'a güvenle çevirir: bilinmeyen tipler str'e, uzun metinler kesilir, çok derin yapılar budanır."""
    if derinlik > 8:
        return str(deger)[:200]
    if deger is None or isinstance(deger, (bool, int, float)):
        return deger
    if isinstance(deger, str):
        return deger if len(deger) <= MAX_METIN else deger[:MAX_METIN] + f"\n…[kesildi: toplam {len(deger)} karakter]"
    if isinstance(deger, dict):
        return {str(k): _guvenli(v, derinlik + 1) for k, v in deger.items()}
    if isinstance(deger, (list, tuple, set, frozenset)):
        liste = list(deger)
        try:
            liste = sorted(liste) if isinstance(deger, (set, frozenset)) else liste
        except TypeError:
            pass
        return [_guvenli(v, derinlik + 1) for v in liste]
    return str(deger)


class KararIzi:
    def __init__(self):
        self.adimlar: list = []
        self._baslangic = time.monotonic()

    def ekle(self, tur, baslik, karar_veren, sonuc=None, neden=None, **detay):
        """Bir karar/işlem adımı ekler. `sonuc`: kısa sonuç metni; `neden`: kararın gerekçesi (insan okur); `detay`: serbest yapılandırılmış alanlar
        (istemler, aday listeleri, ham cevaplar…). Hata verirse sessizce atlanır."""
        try:
            self.adimlar.append({
                "sira": len(self.adimlar) + 1,
                "sn": round(time.monotonic() - self._baslangic, 2),
                "tur": tur,
                "baslik": baslik,
                "karar_veren": karar_veren if karar_veren in KARAR_VERENLER else "sistem",
                "sonuc": _guvenli(sonuc),
                "neden": _guvenli(neden),
                "detay": _guvenli(detay),
            })
        except Exception:  # noqa: BLE001 — iz, işlemi asla bozmamalı
            pass

    def to_dict(self) -> dict:
        return {"surum": 1, "adimlar": list(self.adimlar)}
