#!/usr/bin/env bash
# PostgreSQL (nace_oranlari, gecmis_fatura_kalemleri, model_eval_sonuclar,
# tenant_* semalari) ve ChromaDB (RAG vektor veritabani) icin zamanlanmis
# yedek alir. Canliya cikis hazirligi (2026-09-11, kullanici karari) -
# onceden sadece elle alinmis TEK bir dump vardi (db-yedek/), otomatik/
# tekrarlanan bir yedekleme yoktu.
#
# Kullanim (elle bir kere test etmek icin):
#   ./scripts/otomatik-yedekleme.sh
#
# Zamanlanmis calistirma icin (crontab -e ile, her gun 03:00'te):
#   0 3 * * * cd /path/to/System && ./scripts/otomatik-yedekleme.sh >> db-yedek/yedekleme.log 2>&1
#
# POSTGRES_PASSWORD .env'den okunur. Yedekler db-yedek/ altina TARIH damgali
# dosya adiyla yazilir (ustune yazmaz, her calisma ayri bir dosya birakir) -
# YEDEK_SAKLAMA_GUN'den eski yedekler script sonunda otomatik silinir
# (sinirsiz birikmesin diye).
#
# 2026-09-28 duzeltmesi (kullanici karari - baslat.sh kaldirildi, sistem
# artik SADECE Docker ile calisiyor): ChromaDB yedegi artik host'taki
# model_eval/vector_db/ dizininden DEGIL, `app` container'inin icindeki
# named volume'den (`docker cp` ile) alinir - host dizini artik guncel
# veriyi TASIMIYOR (eski, baslat.sh doneminden kalma bir kopya olabilir,
# gercek/guncel veri docker-compose.yml'deki efatura-vector-db volume'unde).

set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

if [ -f .env ]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

: "${POSTGRES_PASSWORD:?POSTGRES_PASSWORD env var tanımlı olmalı — .env dosyasına yazın ya da elle verin}"

YEDEK_DIR="db-yedek"
YEDEK_SAKLAMA_GUN="${YEDEK_SAKLAMA_GUN:-14}"
TARIH_DAMGASI="$(date '+%Y%m%d_%H%M%S')"
mkdir -p "$YEDEK_DIR"

echo "== $(date '+%Y-%m-%d %H:%M:%S') Yedekleme başlıyor =="

echo "-- PostgreSQL (efatura-kdv-postgres) --"
if ! docker ps --filter "name=efatura-kdv-postgres" --format '{{.Names}}' | grep -q efatura-kdv-postgres; then
  echo "  HATA: efatura-kdv-postgres container'ı çalışmıyor, PostgreSQL yedeği atlanıyor." >&2
else
  PG_YEDEK_DOSYASI="efatura_kdv_${TARIH_DAMGASI}.dump"
  docker exec -e PGPASSWORD="$POSTGRES_PASSWORD" efatura-kdv-postgres \
    pg_dump -U efatura -d efatura_kdv -F c -f "/tmp/${PG_YEDEK_DOSYASI}"
  docker cp "efatura-kdv-postgres:/tmp/${PG_YEDEK_DOSYASI}" "${YEDEK_DIR}/${PG_YEDEK_DOSYASI}"
  docker exec efatura-kdv-postgres rm -f "/tmp/${PG_YEDEK_DOSYASI}"
  echo "  Yazıldı: ${YEDEK_DIR}/${PG_YEDEK_DOSYASI} ($(du -h "${YEDEK_DIR}/${PG_YEDEK_DOSYASI}" | cut -f1))"
fi

echo "-- ChromaDB (RAG vektör veritabanı, app container'ının efatura-vector-db volume'u) --"
# İsim yerine compose servis etiketiyle bulunur (docker-compose.yml'in
# bulunduğu dizin adı değişirse container adı da değişir, etiket değişmez).
APP_CONTAINER="$(docker ps --filter "label=com.docker.compose.service=app" --format '{{.Names}}' | head -1)"
if [ -z "$APP_CONTAINER" ]; then
  echo "  HATA: app container'ı (docker compose) çalışmıyor, ChromaDB yedeği atlanıyor." >&2
else
  VECTOR_GECICI_DIZIN="$(mktemp -d)"
  docker cp "${APP_CONTAINER}:/app/model_eval/vector_db" "${VECTOR_GECICI_DIZIN}/vector_db"
  VECTOR_YEDEK_DOSYASI="vector_db_${TARIH_DAMGASI}.tar.gz"
  tar -czf "${YEDEK_DIR}/${VECTOR_YEDEK_DOSYASI}" -C "$VECTOR_GECICI_DIZIN" vector_db
  rm -rf "$VECTOR_GECICI_DIZIN"
  echo "  Yazıldı: ${YEDEK_DIR}/${VECTOR_YEDEK_DOSYASI} ($(du -h "${YEDEK_DIR}/${VECTOR_YEDEK_DOSYASI}" | cut -f1))"
fi

echo "-- Eski yedekleri temizleme (${YEDEK_SAKLAMA_GUN} günden eski) --"
find "$YEDEK_DIR" -maxdepth 1 -type f \( -name "efatura_kdv_*.dump" -o -name "vector_db_*.tar.gz" \) \
  -mtime "+${YEDEK_SAKLAMA_GUN}" -print -delete

echo "== $(date '+%Y-%m-%d %H:%M:%S') Yedekleme tamamlandı =="
