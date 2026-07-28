# e-Fatura KDV Doğrulama + TDHP Tahmini — tek image içinde tüm Python
# bileşenleri (Mcp_mimarisi + entegrasyon + model_eval).
#
# Neden tek image: entegrasyon/model_eval_yolu.py, model_eval'i "../model_eval"
# kardeş dizini olarak sys.path'e ekliyor (bkz. o dosyanın docstring'i) — bu
# yüzden iki servis ayrı image'lara bölünmez, aynı dosya sistemi köküne
# birlikte kopyalanır ve kardeş dizin ilişkisi korunur.
#
# Bu image İÇERMEZ: PostgreSQL (docker-compose.yml'de ayrı servis),
# Ollama (docker-compose.yml'de ayrı servis), SSH tüneli (host/sunucu
# seviyesinde systemd servisi olarak kalır — bkz. mimari.md, uzak GPU'ya
# gittiği için container içine alınamaz).

FROM python:3.9-slim

WORKDIR /app

# Sistem bağımlılıkları: psycopg2-binary derleme ihtiyacı + healthcheck için curl
RUN apt-get update && apt-get install -y --no-install-recommends \
        curl \
        supervisor \
    && rm -rf /var/lib/apt/lists/*

# --- Bağımlılıkları kur (kod kopyalanmadan önce, layer cache için) ---
COPY Mcp_mimarisi/requirements.txt /app/Mcp_mimarisi/requirements.txt
COPY entegrasyon/requirements.txt /app/entegrasyon/requirements.txt
COPY model_eval/requirements.txt /app/model_eval/requirements.txt

RUN pip install --no-cache-dir \
        -r /app/Mcp_mimarisi/requirements.txt \
        -r /app/entegrasyon/requirements.txt \
        -r /app/model_eval/requirements.txt

# --- Kaynak kodu kopyala (kardeş dizin yapısı korunur) ---
COPY Mcp_mimarisi/ /app/Mcp_mimarisi/
COPY entegrasyon/ /app/entegrasyon/
COPY model_eval/ /app/model_eval/

# --- Process yönetimi ---
COPY docker/supervisord.conf /etc/supervisor/conf.d/supervisord.conf

EXPOSE 8000 8100

# Her iki servisin de /saglik ve /durum endpoint'i sağlıklı mı diye kontrol eder
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -sf http://localhost:8000/saglik && curl -sf http://localhost:8100/durum || exit 1

CMD ["/usr/bin/supervisord", "-c", "/etc/supervisor/conf.d/supervisord.conf"]
