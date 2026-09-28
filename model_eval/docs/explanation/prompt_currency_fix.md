# Prompt'ta Para Birimi Sabitleme Talimati

## Sorun

Yeni gelen (ground-truth'suz) XML faturalar `--data-format xml` ile tahmin
edilirken, EUR bazli faturalarin bir kisminda model muhasebe kaydina faturanin
gercek EUR tutari yerine, o tutari faturadaki EUR/TL kuruyla carpip elde
ettigi bir TL degeri yaziyordu - ama tutari hala parasal birim belirtmeden,
sanki EUR'muş gibi kaydediyordu.

Somut ornek: `AKK2026000000192` faturasinin gercek tutari 1.100 EUR iken,
model 120 hesabina 57.989,47 borc yazmisti (1.100 x 52.7177 TL kuru =
57.989,47). Kayit kendi icinde dengeliydi (Borc = Alacak), bu yuzden
`score_entries()`/`balanced` kontrolu bu hatayi yakalamiyordu - hata sadece
faturanin gercek "Odenecek/Alinacak Tutar" alaniyla model ciktisi manuel
karsilastirilinca ortaya cikti. 25 faturanin 8'inde (%32) bu hata vardi,
hepsi EUR bazliydi.

## Kok neden

Modele gonderilen prompt'ta (`build_user_prompt`, `evaluate_models.py`)
faturanin para birimi acikca veriliyordu ("Para Birimi: EUR") ama modele
tutarlari **hangi birimde** yazmasi gerektigi konusunda hicbir kisit
verilmiyordu. Model bazen (ozellikle buyuk toplamli faturalarda) kendiliginden
TL karsiligina cevirip yaziyordu.

## Cozum

`build_user_prompt` sonundaki TALIMAT bolumune, tutarlarin faturanin kendi
para biriminde ve verilen sayisal degerle birebir ayni yazilmasi gerektigini,
kur cevirimi yapilmamasi gerektigini belirten acik bir cumle eklendi:

> "onemli: tutarlari kesinlikle faturanin 'Para Birimi' alaninda belirtilen
> para biriminde, yukarida verilen sayisal degerleriyle BIREBIR AYNI yaz.
> Kur cevirimi yapma, TL karsiligini hesaplama..."

Bu talimat eklendikten sonra 25 faturanin tamami (`gemma4:31b-cloud --rag
--self-correct --iade-hint --tevkifat-hint`) yeniden calistirildi: 25/25
faturada model artik kendi para biriminde, faturayla birebir uyusan tutarlar
uretti (bkz. `YENI_FATURALAR_MUHASEBE_KAYITLARI.md`).

Not: Ayni calistirmada `AKL2026000002117` (IHRACKAYITLI tip) faturasinda
toplam Borc, "Odenecek/Alinacak Tutar" alanindan farkli cikti - bu bir hata
DEGIL: ihrac kayitli satislarda 192 (Ihrac Kayitli KDV) hesabina ayrica KDV
tutari borc yazilir, bu yuzden toplam borc dogal olarak odenecek tutardan
buyuk olur. Karsilastirma yaparken bu fatura tipini goz onunde bulundurun.

## Uygulanan yer

`evaluate_models.py` - `build_user_prompt()` fonksiyonu, TALIMAT
bolumu.

> ✅ **Uygulandı** (2026-07-13): `build_user_prompt()` içindeki TALIMAT
> bloğuna para birimi/kur çevrimi kısıtı eklendi; 25 faturalık gerçek
> XML batch'inde doğrulandı (0/25 kur-çarpımı hatası, önceki turda 8/25 idi).
