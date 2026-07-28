"""Manuel test için basit yerel web arayüzü (harici bağımlılık yok).

Fatura XML dosyası (veya BİRDEN FAZLA fatura XML'i, 2026-07-21'de eklendi)
yükleyip satıcının NACE kod(lar)ını girerek `satir_bazli_kontrol_et()`'in
gerçek çıktısını tarayıcıda görmek için. Sadece Python'un yerleşik
`http.server`/`email` kütüphanelerini kullanır — Flask vb. kurulum
gerektirmez.

Çalıştırma (proje kökünden):

    python3 test/web_arayuz.py

Sonra tarayıcıda: http://localhost:8765

Çoklu dosya desteği (2026-07-21, kullanıcı kararı): muhasebeci her oturumda
TEK bir şirketin tüm faturalarını (aynı satıcı VKN + aynı NACE kod kümesi)
toplu yükleyebilir — dosya seçici penceresinde birden fazla XML seçilir
(tarayıcının native `<input multiple>` özelliği, zip/klasör YOK, kullanıcı
kararı: "çoklu dosya seçimi... zip'lemeye gerek yok"). Her fatura BAŞARIYLA
kontrol edildiyse (VKN uyuşmazlığı/parse hatası yoksa) kalem-oran satırları
otomatik olarak gecmis_fatura_kalemleri tablosuna kaydedilir — bu davranış
`src/efatura_kdv/api.py`'deki `/fatura/coklu-kontrol` endpoint'iyle
BİREBİR aynı mantığı kullanır (bu dosya doğrudan aynı fonksiyonları çağırır,
kod tekrarı yok).
"""

import email
import html
import logging
import os
import sys
import tempfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PROJE_KOKU = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(PROJE_KOKU, "src"))
os.chdir(PROJE_KOKU)

from efatura_kdv.ubl_parser import parse_ubl_invoice
from efatura_kdv.nace_kural_kontrolu import NaceOranTablosu
from efatura_kdv.kalem_nace_esleme import (
    SaticiNaceBilgisi,
    SaticiVknUyusmazligiHatasi,
    satir_bazli_kontrol_et,
)
from efatura_kdv.gecmis_kontrol import (
    GecmisFaturaDeposu,
    fatura_kalemlerini_kayit_icin_hazirla,
    faturayi_gecmise_kaydet,
    gecmis_kontrol_et,
)

PORT = 8765

# Terminale de bassın diye kök logger'ı ayarla (kalem_nace_esleme.py'nin
# logger.info(...) çağrıları buradan akar).
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
    stream=sys.stdout,
)


class _IstekLogYakalayici(logging.Handler):
    """Bir HTTP isteği sırasında üretilen logları bellekte tutar, tarayıcıda
    "İşlem Adımları" paneli olarak göstermek için."""

    def __init__(self):
        super().__init__()
        self.setFormatter(logging.Formatter("%(asctime)s  %(message)s", datefmt="%H:%M:%S"))
        self.kayitlar = []

    def emit(self, record):
        self.kayitlar.append(self.format(record))


# Excel dosyasını tek seferde belleğe yükle (her istek için yeniden okuma).
ORAN_TABLOSU = NaceOranTablosu()
# Geçmiş fatura çapraz kontrolü için depo — her sorguda kendi DB bağlantısını
# açar (gecmis_kontrol.py), burada sadece DATABASE_URL doğrulaması yapılır.
GECMIS_DEPO = GecmisFaturaDeposu()

SAYFA_ISKELETI = """<!doctype html>
<html lang="tr">
<head>
<meta charset="utf-8">
<title>NACE-KDV Kontrol — Manuel Test</title>
<style>
  body {{ font-family: -apple-system, sans-serif; max-width: 1100px; margin: 2rem auto; padding: 0 1rem; }}
  h1 {{ font-size: 1.3rem; }}
  h2 {{ font-size: 1.1rem; margin-top: 2rem; }}
  form {{ border: 1px solid #ccc; border-radius: 8px; padding: 1.2rem; margin-bottom: 1.5rem; }}
  label {{ display: block; margin-top: 0.8rem; font-weight: 600; }}
  input[type=text], input[type=file] {{ width: 100%; padding: 0.4rem; margin-top: 0.3rem; box-sizing: border-box; }}
  button {{ margin-top: 1rem; padding: 0.5rem 1.2rem; font-size: 1rem; cursor: pointer; }}
  .hata {{ color: #b00020; background: #fdecea; padding: 0.8rem; border-radius: 6px; }}
  table {{ border-collapse: collapse; width: 100%; margin-top: 1rem; }}
  th, td {{ border: 1px solid #ddd; padding: 0.5rem; text-align: left; vertical-align: top; font-size: 0.9rem; }}
  th {{ background: #f5f5f5; }}
  .uygun {{ color: #1a7f37; font-weight: 600; }}
  .incele {{ color: #b00020; font-weight: 600; }}
  .genel {{ font-size: 1.1rem; margin: 1rem 0; }}
  small {{ color: #666; }}
  .kayit-etiketi {{ display: inline-block; font-size: 0.78rem; padding: 0.1rem 0.5rem;
                     border-radius: 4px; margin-left: 0.5rem; }}
  .kayit-yeni {{ background: #d1f0d8; color: #1a7f37; }}
  .kayit-atlandi {{ background: #eee; color: #666; }}
  .fatura-bolumu {{ border: 1px solid #ddd; border-radius: 8px; padding: 1rem; margin-top: 1.2rem; }}
  .loglar {{ background: #0d1117; color: #c9d1d9; padding: 1rem; border-radius: 8px;
             font-family: ui-monospace, monospace; font-size: 0.82rem; white-space: pre-wrap;
             max-height: 400px; overflow-y: auto; margin-top: 1rem; }}
  .sekme-cubugu {{ display: flex; gap: 0.3rem; border-bottom: 2px solid #ddd; margin-top: 1.5rem; }}
  .sekme-butonu {{ padding: 0.6rem 1.1rem; border: none; background: none; cursor: pointer;
                   font-size: 0.95rem; font-weight: 600; color: #666; border-bottom: 3px solid transparent; }}
  .sekme-butonu.aktif {{ color: #0d1117; border-bottom-color: #0d1117; }}
  .sekme-sayaci {{ display: inline-block; min-width: 1.4rem; padding: 0.05rem 0.35rem; margin-left: 0.3rem;
                   border-radius: 10px; background: #eee; color: #333; font-size: 0.78rem; }}
  .sekme-butonu[data-sekme="vkn-uyusmazligi"] .sekme-sayaci {{ background: #fdecea; color: #b00020; }}
  .sekme-butonu[data-sekme="diger-hatalar"] .sekme-sayaci {{ background: #fdecea; color: #b00020; }}
  .sekme-icerigi {{ display: none; padding-top: 1rem; }}
  .sekme-icerigi.aktif {{ display: block; }}
  .bos-durum {{ color: #666; padding: 1rem 0; }}
</style>
<script>
function sekmeSec(sekmeAdi) {{
  document.querySelectorAll('.sekme-icerigi').forEach(function(el) {{
    el.classList.toggle('aktif', el.dataset.sekme === sekmeAdi);
  }});
  document.querySelectorAll('.sekme-butonu').forEach(function(el) {{
    el.classList.toggle('aktif', el.dataset.sekme === sekmeAdi);
  }});
}}
</script>
</head>
<body>
<h1>NACE-KDV Satır Bazlı Kontrol — Manuel Test</h1>
<form method="post" enctype="multipart/form-data">
  <label>Sizin şirketinizin VKN'si:</label>
  <input type="text" name="kendi_vkn" placeholder="örn. 0460351893" required>
  <small>Bu, faturanın GERÇEK satıcı VKN'siyle karşılaştırılır — sadece
    SİZİN kestiğiniz faturalar geçmiş veritabanına kaydedilir (bkz.
    PROJECT.md §3.9). Size kesilmiş (alıcı olduğunuz) faturalar da kontrol
    edilir ama kaydedilmez.</small>

  <label>Fatura XML dosyası/dosyaları (birden fazla seçilebilir):</label>
  <input type="file" name="fatura_xml" accept=".xml" multiple required>

  <label>Satıcının NACE kod(ları) — virgülle ayırın:</label>
  <input type="text" name="nace_kodlari" placeholder="örn. 532009  veya  532009, 463304" required>

  <button type="submit">Kontrol Et</button>
</form>
{icerik}
</body>
</html>
"""


def _kacir(metin):
    return html.escape(str(metin)) if metin is not None else ""


def _log_paneli_html(kayitlar):
    if not kayitlar:
        return ""
    return f"""
    <h2>İşlem Adımları (log)</h2>
    <div class="loglar">{_kacir(chr(10).join(kayitlar))}</div>
    """


def _gecmis_sinif(gecmis_sonuc):
    """Geçmiş kontrol sonucuna göre bir CSS sınıfı döner — sadece görsel,
    karar DEĞİLDİR (bkz. gecmis_kontrol.py modül docstring'i)."""
    if not gecmis_sonuc.gecmiste_hic_gorulmus_mu:
        return ""
    return "uygun" if gecmis_sonuc.gecmisle_uyusuyor_mu else "incele"


def _kayit_etiketi_html(gecmise_kaydedildi):
    if gecmise_kaydedildi:
        return '<span class="kayit-etiketi kayit-yeni">geçmişe kaydedildi</span>'
    return '<span class="kayit-etiketi kayit-atlandi">zaten kayıtlıydı</span>'


def _fatura_sonuc_html(dosya_adi, fatura, satici_nace, sonuc, gecmis_sonuclari, gecmise_kaydedildi):
    genel_sinif = "uygun" if sonuc.genel_karar.value == "uygun" else "incele"
    satirlar = []
    for s, gecmis_sonuc in zip(sonuc.satir_sonuclari, gecmis_sonuclari):
        karar_sinif = "uygun" if s.karar.value == "uygun" else "incele"
        satirlar.append(
            f"""<tr>
              <td>{_kacir(s.kalem_sira_no)}</td>
              <td>{_kacir(s.kalem_adi)}</td>
              <td>{_kacir(s.beyan_edilen_oranlar)}</td>
              <td>{_kacir(s.nace_kodlari_kontrol_edildi)}</td>
              <td>{_kacir(s.izin_verilen_oranlar_havuzu)}</td>
              <td class="{karar_sinif}">{_kacir(s.karar.value)}</td>
              <td><small>{_kacir(s.gerekce)}</small></td>
              <td class="{_gecmis_sinif(gecmis_sonuc)}"><small>{_kacir(gecmis_sonuc.bilgi_notu)}</small></td>
            </tr>"""
        )

    return f"""
    <div class="fatura-bolumu">
    <h2>{_kacir(dosya_adi)} {_kayit_etiketi_html(gecmise_kaydedildi)}</h2>
    <p><b>Fatura no:</b> {_kacir(fatura.fatura_no)} &nbsp; <b>Satıcı VKN:</b> {_kacir(fatura.satici.vkn)}
       ({_kacir(fatura.satici.unvan)})</p>
    <p><b>Girilen NACE kod(ları):</b> {_kacir(satici_nace.nace_kodlari)}</p>
    <p class="genel">Genel karar:
       <span class="{genel_sinif}">{_kacir(sonuc.genel_karar.value)}</span>
    </p>
    <table>
      <tr>
        <th>Sıra</th><th>Kalem adı</th><th>Beyan edilen oran(lar)</th>
        <th>Kontrol edilen NACE'ler</th><th>İzin verilen oranlar havuzu</th>
        <th>Karar</th><th>Gerekçe</th>
        <th>Geçmiş fatura çapraz kontrolü<br><small>(veritabanı sorgusu — karar üretmez)</small></th>
      </tr>
      {''.join(satirlar)}
    </table>
    </div>
    """


def _fatura_hata_html(dosya_adi, hata_metni):
    return f"""
    <div class="fatura-bolumu">
    <h2>{_kacir(dosya_adi)}</h2>
    <p class="hata">Hata: {_kacir(hata_metni)}</p>
    </div>
    """


def _sekmeli_sonuc_html(basarili_bolumler, vkn_uyusmazligi_bolumler, diger_hata_bolumler):
    """Fatura sonuçlarını 3 sekmeye ayırır (kullanıcı kararı, 2026-07-21):
    Başarılı (NACE kontrolü tamamlananlar), VKN Uyuşmazlığı ("bu fatura bize
    ait değil" — SaticiVknUyusmazligiHatasi), Diğer Hatalar (bozuk XML vb.
    teknik parse hataları). VKN uyuşmazlığı özellikle ayrı tutuluyor çünkü
    anlamı diğerlerinden farklı: "faturayı siz kesmediniz, size gelsin"."""

    def _bos_veya(bolumler, bos_metni):
        if not bolumler:
            return f'<p class="bos-durum">{_kacir(bos_metni)}</p>'
        return "".join(bolumler)

    return f"""
    <div class="sekme-cubugu">
      <button type="button" class="sekme-butonu aktif" data-sekme="basarili"
              onclick="sekmeSec('basarili')">
        Başarılı <span class="sekme-sayaci">{len(basarili_bolumler)}</span>
      </button>
      <button type="button" class="sekme-butonu" data-sekme="vkn-uyusmazligi"
              onclick="sekmeSec('vkn-uyusmazligi')">
        VKN Uyuşmazlığı <span class="sekme-sayaci">{len(vkn_uyusmazligi_bolumler)}</span>
      </button>
      <button type="button" class="sekme-butonu" data-sekme="diger-hatalar"
              onclick="sekmeSec('diger-hatalar')">
        Diğer Hatalar <span class="sekme-sayaci">{len(diger_hata_bolumler)}</span>
      </button>
    </div>
    <div class="sekme-icerigi aktif" data-sekme="basarili">
      {_bos_veya(basarili_bolumler, "Başarıyla kontrol edilen fatura yok.")}
    </div>
    <div class="sekme-icerigi" data-sekme="vkn-uyusmazligi">
      <p><small>Bu faturalar girilen şirket VKN'si ile kesilmemiş — muhtemelen
      size ait değil, size gelmesi gereken bir fatura yanlışlıkla buraya
      yüklenmiş olabilir.</small></p>
      {_bos_veya(vkn_uyusmazligi_bolumler, "VKN uyuşmazlığı olan fatura yok.")}
    </div>
    <div class="sekme-icerigi" data-sekme="diger-hatalar">
      {_bos_veya(diger_hata_bolumler, "Başka hata veren fatura yok.")}
    </div>
    """


def _multipart_dosyalarini_ayikla(body_bytes, content_type):
    """Ham multipart/form-data gövdesini email.parser ile ayrıştırır —
    stdlib'in `cgi` modülü aynı isimli BİRDEN FAZLA dosya alanını
    (name="fatura_xml", multiple) düzgün desteklemediği için (Python 3.9'da
    kaldırılmaya hazırlanan, çoklu-değerli alanlarda güvenilmez bir modül)
    bunun yerine e-posta MIME ayrıştırıcısı kullanılıyor — multipart/
    form-data, MIME'ın bir alt kümesidir, bu yüzden email.parser güvenle
    ayrıştırabiliyor.

    Döner: (fatura_xml_dosyalari: [(dosya_adi, icerik_bytes), ...], form_alanlari: {isim: deger})
    """
    header_bytes = f"Content-Type: {content_type}\r\nMIME-Version: 1.0\r\n\r\n".encode("utf-8")
    mesaj = email.message_from_bytes(header_bytes + body_bytes)

    fatura_dosyalari = []
    form_alanlari = {}
    for parca in mesaj.get_payload():
        disposition = parca.get("Content-Disposition", "")
        if "name=\"fatura_xml\"" in disposition and "filename=" in disposition:
            dosya_adi = parca.get_filename() or "isimsiz.xml"
            icerik = parca.get_payload(decode=True)
            if icerik:  # boş dosya seçimi (input multiple'da olabilir) atlanır
                fatura_dosyalari.append((dosya_adi, icerik))
        elif "name=\"nace_kodlari\"" in disposition:
            form_alanlari["nace_kodlari"] = (parca.get_payload(decode=True) or b"").decode("utf-8")
        elif "name=\"kendi_vkn\"" in disposition:
            form_alanlari["kendi_vkn"] = (parca.get_payload(decode=True) or b"").decode("utf-8")

    return fatura_dosyalari, form_alanlari


class Handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass  # sessiz — terminal çıktısını kirletmesin

    def do_GET(self):
        self._yaz(200, SAYFA_ISKELETI.format(icerik=""))

    def do_POST(self):
        log_yakalayici = _IstekLogYakalayici()
        efatura_logger = logging.getLogger("efatura_kdv")
        efatura_logger.addHandler(log_yakalayici)
        try:
            content_type = self.headers.get("Content-Type", "")
            if not content_type.startswith("multipart/form-data"):
                self._yaz(400, SAYFA_ISKELETI.format(
                    icerik='<p class="hata">Beklenmeyen form türü.</p>'
                ))
                return

            content_length = int(self.headers.get("Content-Length", 0))
            body_bytes = self.rfile.read(content_length)

            fatura_dosyalari, form_alanlari = _multipart_dosyalarini_ayikla(body_bytes, content_type)
            nace_metni = form_alanlari.get("nace_kodlari", "")
            kendi_vkn = form_alanlari.get("kendi_vkn", "").strip()

            if not fatura_dosyalari or not nace_metni.strip() or not kendi_vkn:
                self._yaz(400, SAYFA_ISKELETI.format(
                    icerik='<p class="hata">Şirket VKN\'si, en az bir fatura dosyası ve NACE kodu(ları) zorunlu.</p>'
                ))
                return

            nace_kodlari = [k.strip() for k in nace_metni.split(",") if k.strip()]

            # Sonuçlar 3 gruba ayrılır (kullanıcı kararı, 2026-07-21):
            # başarılı, VKN uyuşmazlığı ("bu fatura bize ait değil"), diğer
            # teknik hatalar (bozuk XML vb.) — bkz. _sekmeli_sonuc_html().
            basarili_bolumler = []
            vkn_uyusmazligi_bolumler = []
            diger_hata_bolumler = []
            for dosya_adi, icerik_bytes in fatura_dosyalari:
                try:
                    with tempfile.NamedTemporaryFile(suffix=".xml", delete=False) as tmp:
                        tmp.write(icerik_bytes)
                        tmp_yolu = tmp.name

                    try:
                        fatura = parse_ubl_invoice(tmp_yolu)
                    finally:
                        os.unlink(tmp_yolu)

                    # Kullanıcının girdiği VKN kullanılıyor (faturanın kendi
                    # satıcı VKN'si DEĞİL) — satir_bazli_kontrol_et() bunu
                    # faturanın gerçek satıcı VKN'siyle karşılaştırıp
                    # uyuşmazsa ValueError fırlatır (kalem_nace_esleme.py
                    # güvenlik kontrolü). Bu, kullanıcının BAŞKASINA kesilmiş
                    # (inbox) bir faturayı yanlışlıkla "ben kestim" gibi
                    # işaretlemesini engeller — 2026-07-21'de bir Turkcell
                    # (inbox) faturasının yanlışlıkla geçmiş veritabanına
                    # kaydedildiği tespit edilip düzeltildi.
                    satici_nace = SaticiNaceBilgisi(vkn=kendi_vkn, nace_kodlari=nace_kodlari)
                    sonuc = satir_bazli_kontrol_et(fatura, satici_nace, ORAN_TABLOSU)

                    # Her kalem için geçmiş fatura veritabanında ARAMA
                    # yapılıyor — bu arama sonucu KARAR ÜRETMEZ, sadece
                    # tabloda ayrı bir sütun olarak gösterilir.
                    gecmis_sonuclari = [
                        gecmis_kontrol_et(
                            kendi_vkn, s.kalem_adi or "", s.beyan_edilen_oranlar, GECMIS_DEPO
                        )
                        for s in sonuc.satir_sonuclari
                    ]

                    # Fatura başarıyla kontrol edildi demek, satir_bazli_
                    # kontrol_et() yukarıda VKN eşleşmesini zaten doğruladı
                    # (kendi_vkn == fatura.satici.vkn) — yani bu SADECE
                    # kullanıcının kendi kestiği (outbox) fatura olabilir.
                    # Kalem-oran satırlarını otomatik olarak geçmiş
                    # veritabanına kaydet (aynı fatura_no zaten kayıtlıysa
                    # tekrar eklenmez, bkz. gecmis_kontrol.py).
                    kalemler_kayit_icin = fatura_kalemlerini_kayit_icin_hazirla(fatura)
                    gecmise_kaydedildi = False
                    if kalemler_kayit_icin and fatura.fatura_no:
                        gecmise_kaydedildi = faturayi_gecmise_kaydet(
                            GECMIS_DEPO,
                            kendi_vkn,
                            fatura.fatura_no,
                            fatura.duzenleme_tarihi,
                            kalemler_kayit_icin,
                            kaynak="web-arayuz-coklu",
                        )

                    basarili_bolumler.append(
                        _fatura_sonuc_html(
                            dosya_adi, fatura, satici_nace, sonuc, gecmis_sonuclari, gecmise_kaydedildi
                        )
                    )
                except SaticiVknUyusmazligiHatasi as e:
                    # "Bu fatura bize ait değil" — ayrı bir sekmede toplanır
                    # ki muhasebeci bu faturaları tek bakışta görüp gerçek
                    # sahibine yönlendirebilsin (kullanıcı kararı, 2026-07-21).
                    vkn_uyusmazligi_bolumler.append(_fatura_hata_html(dosya_adi, str(e)))
                except Exception as e:
                    # Bozuk XML, parse hatası vb. — VKN uyuşmazlığından farklı
                    # bir anlam taşır ("bu faturayı hiç işleyemedik", "bu
                    # faturayı işleyemedik ama size ait olabilir de olmayabilir
                    # de" değil, teknik bir sorun), bu yüzden ayrı sekme.
                    diger_hata_bolumler.append(_fatura_hata_html(dosya_adi, f"{type(e).__name__}: {e}"))

            icerik = (
                _sekmeli_sonuc_html(basarili_bolumler, vkn_uyusmazligi_bolumler, diger_hata_bolumler)
                + _log_paneli_html(log_yakalayici.kayitlar)
            )
            self._yaz(200, SAYFA_ISKELETI.format(icerik=icerik))

        except Exception as e:
            hata_metni = _kacir(f"{type(e).__name__}: {e}")
            icerik = (
                f'<p class="hata">Hata oluştu:<br>{hata_metni}</p>'
                + _log_paneli_html(log_yakalayici.kayitlar)
            )
            self._yaz(500, SAYFA_ISKELETI.format(icerik=icerik))
        finally:
            efatura_logger.removeHandler(log_yakalayici)

    def _yaz(self, kod, icerik_html):
        self.send_response(kod)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(icerik_html.encode("utf-8"))


if __name__ == "__main__":
    print(f"Sunucu başladı: http://localhost:{PORT}  (durdurmak için Ctrl+C)")
    ThreadingHTTPServer(("localhost", PORT), Handler).serve_forever()
