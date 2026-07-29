#!/usr/bin/env node
// npm install sonrası çalışır (package.json → scripts.postinstall).
//
// Bu script YALNIZCA Python bağımlılıklarını kurar (venv + pip install).
// Servisleri BAŞLATMAZ — Docker/PostgreSQL, SSH tüneli (11435) ve
// POSTGRES_PASSWORD gibi sırlar burada otomatikleştirilemez (bkz.
// proje-calistirma.md, docs/reference/servisler-ve-portlar.md). Gerçek
// başlatma için kullanıcı `POSTGRES_PASSWORD=... ./baslat.sh` çalıştırmalı.

const { spawnSync } = require("node:child_process");
const { existsSync } = require("node:fs");
const path = require("node:path");

const KOK = __dirname ? path.join(__dirname, "..") : process.cwd();

const BILESENLER = [
  { ad: "Mcp_mimarisi", venv: ".venv" },
  { ad: "model_eval", venv: ".venv" },
  { ad: "entegrasyon", venv: ".venv" },
];

function calistir(komut, argumanlar, secenekler) {
  const sonuc = spawnSync(komut, argumanlar, {
    stdio: "inherit",
    ...secenekler,
  });
  if (sonuc.error || sonuc.status !== 0) {
    return false;
  }
  return true;
}

function python3VarMi() {
  const kontrol = spawnSync("python3", ["--version"], { stdio: "ignore" });
  return !kontrol.error && kontrol.status === 0;
}

function main() {
  if (!python3VarMi()) {
    console.warn(
      "[kur-python-bagimliliklari] UYARI: python3 bulunamadı — Python " +
        "bağımlılıkları kurulamadı. Bu makinede Python 3 kurulu olmalı. " +
        "npm install yine de başarıyla tamamlanacak, ama sistemi " +
        "çalıştırmadan önce python3 kurup bu script'i elle çalıştırın:\n" +
        "  node scripts/kur-python-bagimliliklari.js",
    );
    return;
  }

  let hepsiBasarili = true;

  for (const { ad, venv } of BILESENLER) {
    const bilesenYolu = path.join(KOK, ad);
    const requirementsYolu = path.join(bilesenYolu, "requirements.txt");
    const venvYolu = path.join(bilesenYolu, venv);

    if (!existsSync(requirementsYolu)) {
      console.warn(`[kur-python-bagimliliklari] ${ad}/requirements.txt yok, atlanıyor.`);
      continue;
    }

    console.log(`\n[kur-python-bagimliliklari] ${ad}: sanal ortam hazırlanıyor...`);

    if (!existsSync(venvYolu)) {
      const olustu = calistir("python3", ["-m", "venv", venv], { cwd: bilesenYolu });
      if (!olustu) {
        console.error(`[kur-python-bagimliliklari] ${ad}: venv oluşturulamadı.`);
        hepsiBasarili = false;
        continue;
      }
    } else {
      console.log(`[kur-python-bagimliliklari] ${ad}: venv zaten var, atlanıyor.`);
    }

    const pipYolu = path.join(
      venvYolu,
      process.platform === "win32" ? "Scripts" : "bin",
      process.platform === "win32" ? "pip.exe" : "pip",
    );

    const kuruldu = calistir(pipYolu, ["install", "-q", "-r", "requirements.txt"], {
      cwd: bilesenYolu,
    });
    if (!kuruldu) {
      console.error(`[kur-python-bagimliliklari] ${ad}: pip install başarısız.`);
      hepsiBasarili = false;
      continue;
    }

    console.log(`[kur-python-bagimliliklari] ${ad}: tamamlandı.`);
  }

  console.log(
    "\n[kur-python-bagimliliklari] Python bağımlılıkları kuruldu.\n" +
      "Sistemi çalıştırmak için (Docker + PostgreSQL + SSH tüneli elle hazır olmalı):\n" +
      "  POSTGRES_PASSWORD=<parola> ./baslat.sh\n" +
      "Detay: proje-calistirma.md, docs/reference/servisler-ve-portlar.md\n",
  );

  if (!hepsiBasarili) {
    console.warn(
      "[kur-python-bagimliliklari] Bazı bileşenlerde kurulum başarısız oldu " +
        "(yukarıya bakın). npm install yine de tamamlanacak.",
    );
  }
}

main();
