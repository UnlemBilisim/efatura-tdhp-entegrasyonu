#!/usr/bin/env bash
# Tüm sistemi (PostgreSQL + Mcp_mimarisi API + entegrasyon servisi) tek
# komutla, arka planda başlatır. Adım adım manuel açıklama için
# proje-calistirma.md'ye bakın — bu script sadece o adımları otomatikleştirir.
#
# Kullanım: ./baslat.sh
# Durdurmak için: ./durdur.sh

set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

STATE_DIR=".calistirma"
mkdir -p "$STATE_DIR"

: "${POSTGRES_PASSWORD:?POSTGRES_PASSWORD env var tanımlı olmalı — örn. POSTGRES_PASSWORD=<güçlü-parola> ./baslat.sh}"
DATABASE_URL="postgresql://efatura:${POSTGRES_PASSWORD}@localhost:5434/efatura_kdv"
export DATABASE_URL

# Servislerin bağlanacağı ağ arayüzü — varsayılan 0.0.0.0 (tüm arayüzler,
# yerel geliştirme için). Sunucuda dış ekibin bilinen IP aralığına
# kısıtlamak isteyen bir iç ağ adresine ayarlayın (bkz.
# docs/explanation/guvenlik-durumu-2026-07-27.md, auth eklenene kadarki
# geçici azaltma önlemi).
BIND_HOST="${BIND_HOST:-0.0.0.0}"

echo "== 1/3: PostgreSQL =="
if docker ps --filter "name=efatura-kdv-postgres" --format '{{.Names}}' | grep -q efatura-kdv-postgres; then
  echo "  zaten çalışıyor."
elif docker ps -a --filter "name=efatura-kdv-postgres" --format '{{.Names}}' | grep -q efatura-kdv-postgres; then
  echo "  container var ama durmuş, başlatılıyor..."
  docker start efatura-kdv-postgres >/dev/null
else
  echo "  container hiç yok, oluşturuluyor..."
  docker run --name efatura-kdv-postgres \
    -e POSTGRES_USER=efatura \
    -e POSTGRES_PASSWORD="$POSTGRES_PASSWORD" \
    -e POSTGRES_DB=efatura_kdv \
    -p 5434:5432 \
    -d postgres:16 >/dev/null
  echo "  container ilk kez oluşturuldu, veri yüklenmesi gerekiyor:"
  echo "    cd Mcp_mimarisi && python3 scripts/excel_to_postgres.py"
  echo "  (bu script bunu SENİN YERİNE OTOMATİK ÇALIŞTIRMAZ — ilk kurulumda bir kereliğine elle çalıştır.)"
fi

# Postgres'in bağlantı kabul etmeye başlamasını bekle (yeni oluşturulduysa gecikebilir).
echo "  bağlantı bekleniyor..."
for i in $(seq 1 20); do
  if docker exec efatura-kdv-postgres pg_isready -U efatura >/dev/null 2>&1; then
    break
  fi
  sleep 1
done

echo "== 2/3: Mcp_mimarisi API (port 8000) =="
# Not: sistem "python3" bazı makinelerde başka bir projenin (örn.
# preprocessing/.venv) aktif venv'ine gidebiliyor (PATH'e bağlı) — Mcp_mimarisi'nin
# kendi bağımlılıklarına (fastapi/uvicorn/psycopg2) her zaman ulaşabilmek için
# bu script kendi izole venv'ini (.calistirma/mcp_venv) kullanır, Mcp_mimarisi
# klasörüne dokunmaz.
MCP_VENV="$STATE_DIR/mcp_venv"
if [ ! -d "$MCP_VENV" ]; then
  echo "  Mcp_mimarisi için izole venv ilk kez kuruluyor..."
  /usr/bin/python3 -m venv "$MCP_VENV"
  "$MCP_VENV/bin/pip" install -q -r Mcp_mimarisi/requirements.txt
fi
if lsof -i :8000 | grep -q LISTEN 2>/dev/null; then
  echo "  zaten çalışıyor (port 8000 dolu), atlanıyor."
else
  (
    cd Mcp_mimarisi
    echo "--- $(date '+%Y-%m-%d %H:%M:%S') yeni oturum başladı ---" >> "../$STATE_DIR/mcp_mimarisi_api.log"
    DATABASE_URL="$DATABASE_URL" nohup "../$MCP_VENV/bin/python3" -m uvicorn efatura_kdv.api:app \
      --app-dir src --host "$BIND_HOST" --port 8000 \
      >> "../$STATE_DIR/mcp_mimarisi_api.log" 2>&1 &
    echo $! > "../$STATE_DIR/mcp_mimarisi_api.pid"
  )
  echo "  başlatıldı (log: $STATE_DIR/mcp_mimarisi_api.log)"
fi

echo "== 2.5/3: Ollama (RAG için gerekli) =="
if lsof -i :11434 | grep -q LISTEN 2>/dev/null; then
  echo "  zaten çalışıyor, atlanıyor."
else
  echo "--- $(date '+%Y-%m-%d %H:%M:%S') yeni oturum başladı ---" >> "$STATE_DIR/ollama.log"
  nohup ollama serve >> "$STATE_DIR/ollama.log" 2>&1 &
  echo $! > "$STATE_DIR/ollama.pid"
  echo "  başlatıldı (log: $STATE_DIR/ollama.log)"
fi

echo "== 3/3: entegrasyon servisi (port 8100) =="
if [ ! -d entegrasyon/.venv ]; then
  echo "  entegrasyon/.venv yok, ilk kurulum yapılıyor (biraz sürebilir)..."
  python3 -m venv entegrasyon/.venv
  entegrasyon/.venv/bin/pip install -q -r entegrasyon/requirements.txt
fi
if lsof -i :8100 | grep -q LISTEN 2>/dev/null; then
  echo "  zaten çalışıyor (port 8100 dolu), atlanıyor."
else
  (
    cd entegrasyon
    echo "--- $(date '+%Y-%m-%d %H:%M:%S') yeni oturum başladı ---" >> "../$STATE_DIR/entegrasyon.log"
    DATABASE_URL="$DATABASE_URL" nohup ./.venv/bin/uvicorn app:app --host "$BIND_HOST" --port 8100 \
      >> "../$STATE_DIR/entegrasyon.log" 2>&1 &
    echo $! > "../$STATE_DIR/entegrasyon.pid"
  )
  echo "  başlatıldı (log: $STATE_DIR/entegrasyon.log)"
fi

echo ""
echo "Servislerin gerçekten ayağa kalkması birkaç saniye sürebilir."
sleep 3

echo "== Sağlık kontrolü =="
curl -s http://localhost:8000/saglik && echo "  <- Mcp_mimarisi API" || echo "  Mcp_mimarisi API henüz cevap vermiyor, log'a bak: $STATE_DIR/mcp_mimarisi_api.log"
curl -s http://localhost:8100/durum && echo "  <- entegrasyon servisi" || echo "  entegrasyon servisi henüz cevap vermiyor, log'a bak: $STATE_DIR/entegrasyon.log"

echo ""
echo "Hazır olduğunda tarayıcıda aç: http://localhost:8100"
echo "Durdurmak için: ./durdur.sh"
