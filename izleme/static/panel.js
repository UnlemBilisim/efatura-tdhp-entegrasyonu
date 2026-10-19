"use strict";
// Sunucudan gelen her metin (hata mesajı, şirket adı, yol) GÜVENİLMEYEN veridir: yalnızca textContent ile basılır.
const $ = (id) => document.getElementById(id);
let veri = null, sekme = "istekler", acik = new Set(), zamanlayici = null;
let arsivVeri = null, arsivHatasi = null, detayId = null, detayVeri = null, detayHatasi = null;

function el(etiket, metin, sinif) {
  const e = document.createElement(etiket);
  if (metin !== undefined && metin !== null) e.textContent = String(metin);
  if (sinif) e.className = sinif;
  return e;
}
const saat = (iso) => (iso ? new Date(iso).toLocaleTimeString("tr-TR") : "—");
const tarihSaat = (iso) => (iso ? new Date(iso).toLocaleString("tr-TR") : "—");
const durumSinifi = (d) => (d >= 500 ? "d5" : d >= 400 ? "d4" : "d2");

function kartlar(o) {
  const k = $("kartlar"); k.replaceChildren();
  const ekle = (baslik, deger, sinif) => { const c = el("div", undefined, "kart " + (sinif || "")); c.appendChild(el("b", deger)); c.appendChild(el("span", baslik, "soluk")); k.appendChild(c); };
  ekle("İstek", o.istek);
  ekle("Hatalı istek (4xx/5xx)", o.hata_istek, o.hata_istek ? "uyari" : "ok");
  ekle("Sunucu hatası (5xx)", o.sunucu_hatasi, o.sunucu_hatasi ? "hata" : "ok");
  ekle("Hata/uyarı logu", o.hata_logu, o.hata_logu ? "uyari" : "ok");
  ekle("Çalışan onboarding işi", o.calisan_is);
}

function tablo(basliklar, satirlar, ayrinti) {
  if (!satirlar.length) return el("div", "Gösterilecek kayıt yok.", "bos");
  const t = el("table"), h = el("thead"), hr = el("tr");
  basliklar.forEach((b) => hr.appendChild(el("th", b)));
  h.appendChild(hr); t.appendChild(h);
  const tb = el("tbody");
  satirlar.forEach((s, i) => {
    const tr = el("tr", undefined, "satir");
    s.hucreler.forEach((hc) => { const td = el("td"); if (hc instanceof Node) td.appendChild(hc); else td.textContent = hc; tr.appendChild(td); });
    tb.appendChild(tr);
    const kimlik = s.anahtar;
    if (kimlik !== undefined) {
      const d = el("tr", undefined, "detay"); const td = el("td"); td.colSpan = basliklar.length;
      const pre = el("pre", ayrinti(s.kayit)); td.appendChild(pre); d.appendChild(td);
      d.classList.toggle("gizli", !acik.has(kimlik)); tb.appendChild(d);
      tr.addEventListener("click", () => { acik.has(kimlik) ? acik.delete(kimlik) : acik.add(kimlik); d.classList.toggle("gizli"); });
    }
  });
  t.appendChild(tb); return t;
}

function istekler() {
  const yalniz = $("yalnizHata").checked;
  const liste = veri.istekler.filter((i) => !yalniz || (i.durum || 0) >= 400);
  const satirlar = liste.map((i, n) => ({
    anahtar: "i" + n + i.zaman + i.yol, kayit: i,
    hucreler: [
      saat(i.zaman), (i.yontem || "") + " " + (i.yol || ""),
      (() => { const s = el("span", i.durum, "durum " + durumSinifi(i.durum)); return s; })(),
      i.sure_ms != null ? i.sure_ms + " ms" : "—", i.istemci || (i.ip || "—"),
      (() => { const m = el("span", i.hata || (i.kaynak === "erisim" && i.durum >= 400 ? "(mesaj yok — sunucu eski sürüm; yalnızca durum kodu)" : ""), i.hata ? "hata-metni" : "soluk"); return m; })(),
    ],
  }));
  return tablo(["Zaman", "İstek", "Durum", "Süre", "İstemci / IP", "Hata mesajı"], satirlar,
    (i) => JSON.stringify(i, null, 2));
}

function isler() {
  const kap = el("div");
  if (veri.is_hatasi) kap.appendChild(el("div", "İş kayıtları okunamadı: " + veri.is_hatasi, "bos"));
  if (!veri.isler.length && !veri.is_hatasi) return el("div", "Henüz onboarding işi yok.", "bos");
  veri.isler.forEach((j) => kap.appendChild(isKarti(j)));
  return kap;
}

// Mizan okuma raporu (scripts/musteri_onboard_toplu.py → ozet.mizan_okuma / ozet.mizan.okuma): dosyada kaç satır vardı, kaçı neden alınmadı.
function mizanRaporu(r) {
  if (!r || typeof r !== "object") return null;
  const atlanan = Object.entries(r.atlanan || {}).filter(([, n]) => n > 0).map(([k, n]) => k.replace("_", " ") + ": " + n).join(", ");
  const kap = el("div", undefined, "mizan-rapor");
  kap.appendChild(el("span", "Mizan dosyası: " + (r.okunan_satir ?? "?") + " kodlu satır → " + (r.kabul_edilen ?? "?") + " hesap alındı" +
    (atlanan ? " (atlanan — " + atlanan + ")" : "") +
    (r.derinlik && Object.keys(r.derinlik).length ? "; kod derinliği: " + Object.entries(r.derinlik).map(([d, n]) => d + " parçalı × " + n).join(", ") : ""), "soluk"));
  (r.uyari || []).forEach((u) => kap.appendChild(el("div", "⚠ " + u, "hata-metni")));
  return kap;
}

function isKarti(j) {
  const k = el("div", undefined, "is");
  const b = el("div"); b.appendChild(el("b", "İş " + j.is_id.slice(0, 8)));
  b.appendChild(el("span", "  " + tarihSaat(j.olusturulma) + "  ·  " + j.durum + "  ·  %" + (j.yuzde ?? 0), "soluk"));
  k.appendChild(b);
  const c = el("div", undefined, "cubuk"), i = el("i"); i.style.width = (j.yuzde ?? 0) + "%"; c.appendChild(i); k.appendChild(c);
  Object.entries(j.sirketler || {}).forEach(([vkn, s]) => {
    const r = el("div", undefined, "sirket");
    r.appendChild(el("span", vkn, "mono"));
    const d = el("span", s.durum, "durum " + (s.durum === "hata" ? "d5" : (s.durum === "atlandi" || s.durum === "degismedi") ? "d4" : "d2")); r.appendChild(d);
    r.appendChild(el("span", "%" + (s.yuzde ?? 0) + (s.adim ? " " + s.adim : ""), "soluk"));
    r.appendChild(el("span", s.ayrinti || (s.ozet ? (s.ozet.mod === "guncelleme" ? "güncelleme: " + (s.ozet.degisiklik_var ? "değişiklik uygulandı" : "fark yok") : "mizan " + s.ozet.mizan_satir_sayisi + " satır, fatura eşleşme " + s.ozet.fatura_eslesme) : ""), s.durum === "hata" ? "hata-metni" : "soluk"));
    k.appendChild(r);
    const mr = mizanRaporu(s.ozet && (s.ozet.mizan_okuma || (s.ozet.mizan && s.ozet.mizan.okuma)));
    if (mr) k.appendChild(mr);
  });
  if ((j.gecersiz_klasorler || []).length) k.appendChild(el("div", "Geçersiz klasörler: " + j.gecersiz_klasorler.join(", "), "soluk"));
  return k;
}

// ---------------------------------------------------------------------------
// Gelen dosyalar (sunucudaki istek arşivi): liste + istek detayı (indir / bizim cevabımız / log)
// ---------------------------------------------------------------------------
const TIP_ADI = { musteri_onboard: "Şirket kurulumu (zip)", fatura_toplu: "Toplu fatura (zip)", fatura_isle: "Tek fatura" };
const bayt = (n) => (n == null ? "—" : n < 1024 ? n + " B" : n < 1048576 ? (n / 1024).toFixed(1) + " KB" : (n / 1048576).toFixed(1) + " MB");
const indirUrl = (id, ad) => "/api/arsiv/indir?id=" + encodeURIComponent(id) + "&ad=" + encodeURIComponent(ad);

function indirDugmesi(id, ad, metin) {
  const a = el("a", metin || ad, "dugme");
  a.href = indirUrl(id, ad);
  a.addEventListener("click", (e) => e.stopPropagation());
  return a;
}

function kv(satirlar) {
  const g = el("div", undefined, "kv");
  satirlar.forEach(([k, v]) => { if (v === undefined || v === null || v === "") return; g.appendChild(el("span", k)); g.appendChild(el("span", v)); });
  return g;
}

function panelKutusu(baslik, ...icerik) {
  const p = el("div", undefined, "panel"); p.appendChild(el("h3", baslik));
  icerik.forEach((c) => p.appendChild(c)); return p;
}

function metinOnizleme(m) {
  const k = el("div");
  if (m.hata || m.metin == null) { k.appendChild(el("div", "Okunamadı: " + (m.hata || "içerik yok"), "hata-metni")); return k; }
  let metin = m.metin;
  try { metin = JSON.stringify(JSON.parse(m.metin), null, 2); } catch (e) { /* JSON değil (XML) ya da kesilmiş: olduğu gibi göster */ }
  const o = el("div", undefined, "onizleme"); o.appendChild(el("pre", metin)); k.appendChild(o);
  if (m.kesildi) k.appendChild(el("div", "Önizleme " + bayt(m.bayt) + " dosyanın ilk kısmıdır — tamamı için indirin.", "soluk"));
  return k;
}

function dosyalar() {
  if (detayId) return detaySayfasi();
  if (arsivHatasi) return el("div", "Arşiv okunamadı: " + arsivHatasi, "bos");
  if (!arsivVeri) return el("div", "Yükleniyor…", "bos");
  const kap = el("div");
  kap.appendChild(el("div", "Sunucunun son " + arsivVeri.toplam + " gelen isteği (zip ve tek fatura). Satıra tıklayınca dosya içeriği, bizim cevabımız ve log açılır. " +
    "Arşiv sınırlı süre saklanır (GELEN_ARSIV_GUN, varsayılan 7 gün).", "soluk"));
  const yalniz = $("yalnizHata").checked;
  const liste = arsivVeri.kayitlar.filter((k) => !yalniz || (k.durum || 0) >= 400);
  const satirlar = liste.map((k) => ({
    hucreler: [
      tarihSaat(k.zaman), TIP_ADI[k.tip] || k.tip || "—", k.istemci || k.ip || "—",
      (k.vknler && k.vknler.length ? k.vknler.join(", ") : k.vkn || "—") + (k.dosya_adi ? "  " + k.dosya_adi : ""),
      el("span", k.durum ?? "—", "durum " + durumSinifi(k.durum || 0)),
      (() => { const h = el("span"); Object.keys(k.dosyalar || {}).forEach((ad) => h.appendChild(indirDugmesi(k.request_id, ad, ad + " (" + bayt(k.dosyalar[ad]) + ")"))); return h; })(),
    ],
    tikla: () => { detayAc(k.request_id); },
  }));
  if (!satirlar.length) { kap.appendChild(el("div", "Gösterilecek kayıt yok.", "bos")); return kap; }
  const t = el("table"), h = el("thead"), hr = el("tr");
  ["Zaman", "Tür", "İstemci / IP", "VKN / dosya", "Durum", "Dosyalar"].forEach((b) => hr.appendChild(el("th", b)));
  h.appendChild(hr); t.appendChild(h);
  const tb = el("tbody");
  satirlar.forEach((s) => {
    const tr = el("tr", undefined, "satir");
    s.hucreler.forEach((hc) => { const td = el("td"); if (hc instanceof Node) td.appendChild(hc); else td.textContent = hc; tr.appendChild(td); });
    tr.addEventListener("click", s.tikla); tb.appendChild(tr);
  });
  t.appendChild(tb); kap.appendChild(t); return kap;
}

function detaySayfasi() {
  const kap = el("div");
  const geri = el("button", "← Listeye dön", "geri"); geri.addEventListener("click", () => { detayId = null; detayVeri = null; detayHatasi = null; arsivYukle(); ciz(); });
  const yen = el("button", "Yenile"); yen.style.marginLeft = "8px"; yen.addEventListener("click", () => detayAc(detayId));
  const ust = el("div", undefined, "geri"); ust.appendChild(geri); ust.appendChild(yen); kap.appendChild(ust);
  if (detayHatasi) { kap.appendChild(el("div", "Detay okunamadı: " + detayHatasi, "bos")); return kap; }
  if (!detayVeri) { kap.appendChild(el("div", "Yükleniyor…", "bos")); return kap; }
  const { meta, onizleme, log } = detayVeri, j = detayVeri.is;
  const id = meta.request_id;

  kap.appendChild(panelKutusu("İstek",
    kv([
      ["Zaman", tarihSaat(meta.zaman)], ["Tür", TIP_ADI[meta.tip] || meta.tip], ["Yol", meta.yol],
      ["Durum", meta.durum], ["Hata nedeni", meta.hata], ["İstemci (anahtar)", meta.istemci], ["IP", meta.ip],
      ["VKN", meta.vkn || (meta.vknler || []).join(", ")], ["Dosya adı", meta.dosya_adi], ["Fatura no", meta.fatura_no],
      ["Sonuç aşaması", meta.sonuc], ["Onaylanabilir", meta.approvable === undefined ? undefined : String(meta.approvable)],
      ["İş kimliği", meta.is_id], ["request_id", id],
    ]),
    (() => { const d = el("div"); d.style.marginTop = "10px"; Object.keys(meta.dosyalar || {}).forEach((ad) => d.appendChild(indirDugmesi(id, ad, "⬇ " + ad + " (" + bayt(meta.dosyalar[ad]) + ")")));
      if (meta.tip === "fatura_toplu" && meta.is_id) d.appendChild(indirDugmesi(id, "sonuclar.jsonl", "⬇ sonuclar.jsonl (fatura başına cevaplarımız)"));
      return d; })()));

  if ((meta.zip_icerik || []).length) {
    const t = el("table"), hr = el("tr"); ["Dosya", "Boyut"].forEach((b) => hr.appendChild(el("th", b))); const h = el("thead"); h.appendChild(hr); t.appendChild(h);
    const tb = el("tbody");
    meta.zip_icerik.forEach((d) => { const tr = el("tr"); tr.appendChild(el("td", d.ad, "mono")); tr.appendChild(el("td", bayt(d.bayt))); tb.appendChild(tr); });
    t.appendChild(tb);
    const kutu = el("div", undefined, "onizleme"); kutu.appendChild(t);
    kap.appendChild(panelKutusu("Zip'in içindekiler (" + meta.zip_dosya_sayisi + " dosya" + (meta.zip_dosya_sayisi > meta.zip_icerik.length ? ", ilk " + meta.zip_icerik.length + " gösteriliyor" : "") + ")", kutu));
  }

  if (onizleme["cevap.json"]) kap.appendChild(panelKutusu("Bizim verdiğimiz cevap", metinOnizleme(onizleme["cevap.json"])));
  else if (meta.hata) kap.appendChild(panelKutusu("Bizim verdiğimiz cevap", el("div", "HTTP " + meta.durum + " — " + meta.hata)));

  if (j && j.is_hatasi) kap.appendChild(panelKutusu("Başlatılan iş", el("div", "İş kaydı okunamadı: " + j.is_hatasi, "hata-metni")));
  if (j && j.is) {
    const k = el("div");
    if (meta.tip === "musteri_onboard") k.appendChild(isKarti(j.is));
    else {
      const s = j.is;
      k.appendChild(kv([["Durum", s.durum + "  %" + (s.yuzde ?? 0)], ["İlerleme", (s.tamamlanan ?? 0) + " / " + (s.toplam ?? 0) + " fatura"],
        ["Sayılar", Object.entries(s.sayilar || {}).map(([a, n]) => a + ": " + n).join("  ·  ")], ["VKN'ler", (s.vknler || []).join(", ")]]));
    }
    kap.appendChild(panelKutusu("Bu isteğin başlattığı iş", k));
  }
  if (j && j.sonuclar) {
    const satirlar = j.sonuclar.map((r, n) => ({
      anahtar: "r" + id + n, kayit: r,
      hucreler: [r.sira, r.dosya, r.vkn, el("span", r.sonuc, "durum " + (r.sonuc === "hata" ? "d5" : r.sonuc === "hazir" ? "d2" : "d4")),
        (r.ozet && r.ozet.fatura_no) || "", r.hata || (r.ozet && (r.ozet.mesaj || (r.ozet.red_kodlari || []).join(", "))) || ""],
    }));
    const kutu = panelKutusu("Fatura bazında verdiğimiz sonuçlar (" + j.sonuclar.length + (j.sonuclar_kesildi ? ", ilk kısım" : "") + ")",
      tablo(["#", "Dosya", "VKN", "Sonuç", "Fatura no", "Açıklama"], satirlar, (r) => JSON.stringify(r, null, 2)));
    if (j.sonuclar_kesildi) kutu.appendChild(el("div", "Sonuçların tamamı için sonuclar.jsonl dosyasını indirin.", "soluk"));
    kap.appendChild(kutu);
  }

  if (onizleme["istek.xml"]) kap.appendChild(panelKutusu("Bize gelen fatura XML'i", metinOnizleme(onizleme["istek.xml"])));

  const logK = el("div");
  if (log.log_hatasi) logK.appendChild(el("div", "Log okunamadı: " + log.log_hatasi, "hata-metni"));
  (log.istekler || []).forEach((i) => logK.appendChild(el("div", saat(i.zaman) + "  " + (i.yontem || "") + " " + (i.yol || "") + "  →  " + i.durum + (i.sure_ms != null ? "  (" + i.sure_ms + " ms)" : "") + (i.hata ? "  — " + i.hata : ""), i.hata ? "hata-metni" : "")));
  (log.hatalar || []).forEach((h) => { logK.appendChild(el("div", saat(h.zaman) + "  " + h.seviye + "  " + (h.logger || "") + ": " + (h.mesaj || ""), "hata-metni")); if ((h.iz || []).length) { const o = el("div", undefined, "onizleme"); o.appendChild(el("pre", h.iz.join("\n"))); logK.appendChild(o); } });
  if (!logK.childNodes.length) logK.appendChild(el("div", "Bu isteğe ait log satırı bulunamadı.", "soluk"));
  kap.appendChild(panelKutusu("Bu isteğe ait loglar", logK));
  return kap;
}

async function detayAc(id) {
  detayId = id; detayVeri = null; detayHatasi = null; ciz();
  try {
    const r = await fetch("/api/arsiv/detay?id=" + encodeURIComponent(id));
    const j = await r.json();
    if (!r.ok) throw new Error(j.hata || j.baglanti_hatasi || "Hata " + r.status);
    if (detayId !== id) return;  // kullanıcı bu arada başka yere geçtiyse eski cevabı basma
    detayVeri = j;
  } catch (e) { if (detayId === id) detayHatasi = e.message; }
  ciz();
}

async function arsivYukle() {
  try {
    const r = await fetch("/api/arsiv");
    const j = await r.json();
    if (!r.ok) throw new Error(j.hata || j.baglanti_hatasi || "Hata " + r.status);
    arsivVeri = j; arsivHatasi = null;
  } catch (e) { arsivHatasi = e.message; }
  if (sekme === "dosyalar" && !detayId) ciz();
}

function hatalar() {
  const satirlar = veri.hatalar.map((h, n) => ({
    anahtar: "h" + n + h.zaman, kayit: h,
    hucreler: [saat(h.zaman), el("span", h.seviye, "durum " + (h.seviye === "ERROR" || h.seviye === "CRITICAL" ? "d5" : "d4")), h.logger || "", h.mesaj || "", h.request_id || ""],
  }));
  return tablo(["Zaman", "Seviye", "Kaynak", "Mesaj", "request_id"], satirlar,
    (h) => (h.mesaj || "") + (h.iz && h.iz.length ? "\n\n" + h.iz.join("\n") : ""));
}

function ham() {
  const pre = el("pre", veri.ham.map((s) => saat(s.zaman) + "  " + s.satir).join("\n"));
  const k = el("div", undefined, "is"); k.appendChild(pre); return k;
}

function ciz() {
  if (!veri) return;
  $("kaynak").textContent = "kaynak: " + veri.kaynak;
  $("guncel").textContent = "güncellendi " + veri.alindi;
  kartlar(veri.ozet);
  const gorunum = { istekler, dosyalar, isler, hatalar, ham };
  ["istekler", "dosyalar", "isler", "hatalar", "ham"].forEach((s) => { const b = $(s); b.classList.toggle("gizli", s !== sekme); if (s === sekme) b.replaceChildren(gorunum[s]()); });
}

async function yukle() {
  const q = "dakika=" + $("pencere").value + "&saglik=" + ($("saglik").checked ? 1 : 0);
  try {
    const r = await fetch("/api/olaylar?" + q);
    const j = await r.json();
    if (!r.ok) throw new Error(j.baglanti_hatasi || "Hata " + r.status);
    veri = j; $("baglanti").style.display = "none";
    if (sekme === "dosyalar") { if (!detayId) arsivYukle(); return; }  // detay açıkken yeniden çizme: okuma/kaydırma bozulmasın
    ciz();
  } catch (e) {
    const b = $("baglanti"); b.style.display = "block";
    b.textContent = "Sunucuya bağlanılamadı — " + e.message + " (SSH erişimini ve VPN/ağ bağlantısını kontrol edin)";
  }
}

function otomatikAyarla() {
  clearInterval(zamanlayici);
  if ($("otomatik").checked) zamanlayici = setInterval(yukle, 5000);
}

$("sekmeler").addEventListener("click", (e) => {
  if (!e.target.dataset.s) return;
  sekme = e.target.dataset.s;
  document.querySelectorAll("#sekmeler button").forEach((b) => b.classList.toggle("aktif", b.dataset.s === sekme));
  if (sekme === "dosyalar" && !detayId) arsivYukle();
  ciz();
});
["pencere", "saglik"].forEach((i) => $(i).addEventListener("change", yukle));
$("yalnizHata").addEventListener("change", ciz);
$("otomatik").addEventListener("change", otomatikAyarla);
$("yenile").addEventListener("click", yukle);
yukle(); otomatikAyarla();
