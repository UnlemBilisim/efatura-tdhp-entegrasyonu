"use strict";
// Sunucudan gelen her metin (hata mesajı, şirket adı, yol) GÜVENİLMEYEN veridir: yalnızca textContent ile basılır.
const $ = (id) => document.getElementById(id);
let veri = null, sekme = "istekler", acik = new Set(), zamanlayici = null;

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
  veri.isler.forEach((j) => {
    const k = el("div", undefined, "is");
    const b = el("div"); b.appendChild(el("b", "İş " + j.is_id.slice(0, 8)));
    b.appendChild(el("span", "  " + tarihSaat(j.olusturulma) + "  ·  " + j.durum + "  ·  %" + (j.yuzde ?? 0), "soluk"));
    k.appendChild(b);
    const c = el("div", undefined, "cubuk"), i = el("i"); i.style.width = (j.yuzde ?? 0) + "%"; c.appendChild(i); k.appendChild(c);
    Object.entries(j.sirketler || {}).forEach(([vkn, s]) => {
      const r = el("div", undefined, "sirket");
      r.appendChild(el("span", vkn, "mono"));
      const d = el("span", s.durum, "durum " + (s.durum === "hata" ? "d5" : s.durum === "atlandi" ? "d4" : "d2")); r.appendChild(d);
      r.appendChild(el("span", "%" + (s.yuzde ?? 0) + (s.adim ? " " + s.adim : ""), "soluk"));
      r.appendChild(el("span", s.ayrinti || (s.ozet ? "mizan " + s.ozet.mizan_satir_sayisi + " satır, fatura eşleşme " + s.ozet.fatura_eslesme : ""), s.durum === "hata" ? "hata-metni" : "soluk"));
      k.appendChild(r);
    });
    if ((j.gecersiz_klasorler || []).length) k.appendChild(el("div", "Geçersiz klasörler: " + j.gecersiz_klasorler.join(", "), "soluk"));
    kap.appendChild(k);
  });
  return kap;
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
  const gorunum = { istekler, isler, hatalar, ham };
  ["istekler", "isler", "hatalar", "ham"].forEach((s) => { const b = $(s); b.classList.toggle("gizli", s !== sekme); if (s === sekme) b.replaceChildren(gorunum[s]()); });
}

async function yukle() {
  const q = "dakika=" + $("pencere").value + "&saglik=" + ($("saglik").checked ? 1 : 0);
  try {
    const r = await fetch("/api/olaylar?" + q);
    const j = await r.json();
    if (!r.ok) throw new Error(j.baglanti_hatasi || "Hata " + r.status);
    veri = j; $("baglanti").style.display = "none"; ciz();
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
  ciz();
});
["pencere", "saglik"].forEach((i) => $(i).addEventListener("change", yukle));
$("yalnizHata").addEventListener("change", ciz);
$("otomatik").addEventListener("change", otomatikAyarla);
$("yenile").addEventListener("click", yukle);
yukle(); otomatikAyarla();
