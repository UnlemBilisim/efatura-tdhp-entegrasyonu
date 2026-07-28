#!/usr/bin/env bash
# v2 API'yi elle test etmek icin. Tum akisi yurutur: gonder -> yokla ->
# gerekirse onayla -> sonucu bas.
#
# Kullanim:
#   ./v2-test.sh                                  # ubls/ icinden ilk outbox faturasi (Akyuzlu VKN/NACE)
#   ./v2-test.sh <fatura.xml>                     # belirli bir fatura
#   ./v2-test.sh <fatura.xml> --nace              # Akyuzlu'nun sabit NACE kodlariyla
#   ./v2-test.sh <fatura.xml> --nace=254004,282210   # KENDI NACE kodlarinizla
#   ./v2-test.sh <fatura.xml> --nace=... --vkn=1234567890  # KENDI VKN'nizle
#   ./v2-test.sh <fatura.xml> --tl                # TL'ye cevir
#   ./v2-test.sh --health                         # sadece saglik kontrolu
#
# own_vkn = fatura uzerindeki saticinin VKN'si DEGIL, isteği yapan sirketin
# VKN'sidir (yon tespiti buna gore yapilir). Varsayilan Akyuzlu (0460351893) -
# baska bir faturayi test ediyorsaniz --vkn=... ile kendi VKN'nizi verin.
#
# Sozlesme: teslim/API-ENTEGRASYON-KILAVUZU-v2.md
# Ornekler: teslim/ORNEK-SENARYOLAR.md

set -uo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

BASE="${API_BASE:-http://localhost:8100/api/v1}"
OWN_VKN="${OWN_VKN:-0460351893}"
# Akyuzlu'nun NACE kodlari (bkz. calistirma.txt)
NACE_KODLARI='["254004","282210","254005","282290"]'

PY=/usr/bin/python3

# ---------- saglik kontrolu ----------
saglik() {
  local cevap
  cevap=$(curl -s --max-time 10 "$BASE/health" 2>/dev/null) || {
    echo "HATA: $BASE erisilemiyor. Servis calisiyor mu? (./baslat.sh)"; return 1; }
  echo "$cevap" | $PY -c "
import json,sys
d=json.load(sys.stdin)
print('saglik :', d['status'], '-', d['detail'])
sys.exit(0 if d['status']=='healthy' else 1)
"
}

if [ "${1:-}" = "--health" ]; then saglik; exit $?; fi

saglik || { echo "Sistem hazir degil, test durduruldu."; exit 1; }

# ---------- fatura secimi ----------
FATURA=""
NACE_GONDER=0
NACE_OZEL=""
KUR_MODU="as_is"
for arg in "$@"; do
  case "$arg" in
    --nace)        NACE_GONDER=1 ;;                      # Akyuzlu'nun sabit kodlari (varsayilan)
    --nace=*)       NACE_GONDER=1; NACE_OZEL="${arg#--nace=}" ;;  # kendi kodunuz: --nace=254004,282210
    --vkn=*)       OWN_VKN="${arg#--vkn=}" ;;             # kendi VKN'niz (varsayilan Akyuzlu)
    --tl)          KUR_MODU="try" ;;
    -*)            echo "Bilinmeyen secenek: $arg"; exit 1 ;;
    *)             FATURA="$arg" ;;
  esac
done

if [ -n "$NACE_OZEL" ]; then
  # "254004,282210" -> ["254004","282210"]
  NACE_KODLARI=$($PY -c "import json,sys; print(json.dumps(sys.argv[1].split(',')))" "$NACE_OZEL")
fi

if [ -z "$FATURA" ]; then
  FATURA=$(ls Mcp_mimarisi/ubls/*outbox.xml 2>/dev/null | head -1)
  [ -z "$FATURA" ] && { echo "HATA: ubls/ icinde fatura bulunamadi."; exit 1; }
  echo "fatura : $(basename "$FATURA")  (ornek, kendi dosyanizi verebilirsiniz)"
else
  [ -f "$FATURA" ] || { echo "HATA: dosya yok: $FATURA"; exit 1; }
  echo "fatura : $(basename "$FATURA")"
fi

if [ $NACE_GONDER -eq 1 ]; then
  NACE_GOSTER="$NACE_KODLARI"
else
  NACE_GOSTER="YOK (onay gerekebilir)"
fi
echo "own_vkn: $OWN_VKN | nace: $NACE_GOSTER | kur: $KUR_MODU"
echo ""

# ---------- istek govdesini kur ----------
ISTEK=$(FATURA="$FATURA" OWN_VKN="$OWN_VKN" NACE="$([ $NACE_GONDER -eq 1 ] && echo "$NACE_KODLARI" || echo '[]')" KUR="$KUR_MODU" $PY -c '
import json, os
print(json.dumps({
    "invoice_xml": open(os.environ["FATURA"], encoding="utf-8").read(),
    "own_vkn": os.environ["OWN_VKN"],
    "seller_nace_codes": json.loads(os.environ["NACE"]),
    "currency_mode": os.environ["KUR"],
}, ensure_ascii=False))
')

# ---------- 1) gonder ----------
echo "── 1) POST /invoices"
GONDER=$(curl -s -w "\n%{http_code}" --max-time 60 -X POST "$BASE/invoices" \
  -H "Content-Type: application/json" -d "$ISTEK")
KOD=$(echo "$GONDER" | tail -1)
GOVDE=$(echo "$GONDER" | sed '$d')

if [ "$KOD" != "202" ]; then
  echo "   HTTP $KOD — istek kabul edilmedi:"
  echo "$GOVDE" | $PY -m json.tool 2>/dev/null || echo "$GOVDE"
  exit 1
fi

JOB=$(echo "$GOVDE" | $PY -c "import json,sys; print(json.load(sys.stdin)['job_id'])")
echo "   HTTP 202 — job_id: $JOB"

# ---------- 2) yokla ----------
echo "── 2) GET /invoices/$JOB (yoklama)"
BASLA=$(date +%s)
DURUM=""
for i in $(seq 1 60); do
  sleep 3
  DURUM=$(curl -s --max-time 15 "$BASE/invoices/$JOB" \
    | $PY -c "import json,sys; print(json.load(sys.stdin).get('status','?'))" 2>/dev/null || echo "?")
  GECEN=$(( $(date +%s) - BASLA ))
  printf "\r   %3ds  -> %s          " "$GECEN" "$DURUM"
  case "$DURUM" in
    completed|failed|awaiting_approval) break ;;
  esac
done
echo ""

# ---------- 3) onay gerekiyorsa ----------
if [ "$DURUM" = "awaiting_approval" ]; then
  echo "── 3) ONAY GEREKLI — KDV on kontrolu"
  curl -s --max-time 15 "$BASE/invoices/$JOB" | $PY -c "
import json,sys
d = json.load(sys.stdin)
vc = d.get('vat_check') or {}
print('   genel karar:', vc.get('verdict'))
for s in (vc.get('lines') or [])[:3]:
    print(f\"     kalem {s['line_no']}: {(s['line_name'] or '')[:40]}\")
    print(f\"       beyan={s['declared_rates']} izin={s['allowed_rates']}\")
    print(f\"       {s['explanation']}\")
n = len(vc.get('lines') or [])
if n > 3: print(f'     ... ve {n-3} kalem daha')
"
  echo ""
  read -r -p "   Onaylayip devam edilsin mi? [e/H] " YANIT
  if [ "$YANIT" != "e" ] && [ "$YANIT" != "E" ]; then
    curl -s -X POST "$BASE/invoices/$JOB/approve" -H "Content-Type: application/json" \
      -d '{"approved":false}' >/dev/null
    echo "   Iptal edildi (is 'failed' durumuna gecti)."
    exit 0
  fi

  curl -s --max-time 30 -X POST "$BASE/invoices/$JOB/approve" \
    -H "Content-Type: application/json" -d '{"approved":true}' \
    | $PY -c "import json,sys; print('   onay:', json.load(sys.stdin)['message'])"

  for i in $(seq 1 60); do
    sleep 3
    DURUM=$(curl -s --max-time 15 "$BASE/invoices/$JOB" \
      | $PY -c "import json,sys; print(json.load(sys.stdin).get('status','?'))" 2>/dev/null || echo "?")
    GECEN=$(( $(date +%s) - BASLA ))
    printf "\r   %3ds  -> %s          " "$GECEN" "$DURUM"
    case "$DURUM" in completed|failed) break ;; esac
  done
  echo ""
fi

# ---------- 4) sonuc ----------
echo "── 4) SONUC"
curl -s --max-time 15 "$BASE/invoices/$JOB" | $PY -c "
import json, sys
d = json.load(sys.stdin)

if d['status'] == 'failed':
    print('   BASARISIZ:', d.get('error'))
    sys.exit(1)
if d['status'] != 'completed':
    print('   Zaman asimi — is hala:', d['status'])
    print('   Daha sonra sorgulayabilirsiniz: GET $BASE/invoices/' + d['job_id'])
    sys.exit(1)

inv, tot = d['invoice'], d['totals']
print(f\"   fatura : {inv['id']}  ({inv['issue_date']}, {inv['direction']})\")
print(f\"   tutar  : {inv['payable_amount']} {inv['currency']}\")
print(f\"   taraf  : {(inv['customer']['name'] or inv['customer']['vkn'])[:45]}\")
vc = d.get('vat_check')
print(f\"   KDV    : {vc['verdict'] if vc else 'kontrol edilmedi (inbound)'}\")
if d.get('auto_approved'):
    print('   *** OTOMATIK ONAYLANDI (gecici davranis) — vat_check uyarisini incele ***')
print(f\"   denge  : borc {tot['debit']} = alacak {tot['credit']} -> {'TAMAM' if tot['balanced'] else 'DENGESIZ!'}\")
print()
print('   MUHASEBE KAYITLARI')
for e in d['entries']:
    isaret = ' <-- KONTROL GEREKLI' if e['needs_review'] else ''
    print(f\"     {e['side']:6} {e['account_code']:16} {e['amount']:>13} {(e['account_name'] or '')[:32]}{isaret}\")
for u in d.get('warnings') or []:
    print(f'   UYARI: {u}')
print()
print('   Tam JSON:')
print('     curl -s $BASE/invoices/' + d['job_id'] + ' | python3 -m json.tool')
"
