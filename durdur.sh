#!/usr/bin/env bash
# baslat.sh ile açılan Mcp_mimarisi API + entegrasyon servisini durdurur.
# PostgreSQL container'ını ise BİLEREK durdurmaz (veri kaybı riski yok ama
# başka bir işlem hâlâ kullanıyor olabilir) — istersen elle:
#   docker stop efatura-kdv-postgres

set -uo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

STATE_DIR=".calistirma"

durdur_pid_dosyasi() {
  local ad="$1"
  local pid_dosyasi="$STATE_DIR/$ad.pid"
  if [ -f "$pid_dosyasi" ]; then
    local pid
    pid=$(cat "$pid_dosyasi")
    if kill "$pid" 2>/dev/null; then
      echo "$ad durduruldu (pid $pid)."
    else
      echo "$ad zaten çalışmıyordu (pid $pid)."
    fi
    rm -f "$pid_dosyasi"
  else
    echo "$ad için pid dosyası yok, muhtemelen bu scriptle başlatılmadı."
  fi
}

durdur_pid_dosyasi "entegrasyon"
durdur_pid_dosyasi "mcp_mimarisi_api"

echo ""
echo "Not: Ollama ve PostgreSQL container'ı BİLEREK durdurulmadı"
echo "(başka süreçler de kullanıyor olabilir). Gerekirse elle:"
echo "  docker stop efatura-kdv-postgres"
echo "  kill \$(cat $STATE_DIR/ollama.pid) 2>/dev/null   # sadece bu scriptle başlattıysan"
