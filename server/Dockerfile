# Serveur d'affichage des salles : API des écrans + interface d'administration
FROM python:3.12-slim

LABEL org.opencontainers.image.title="hibou-server" \
      org.opencontainers.image.description="Hibou — serveur des écrans e-paper reTerminal E1001 (occupation des salles)"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    EPAPER_DATA_DIR=/data \
    TZ=Europe/Paris

RUN apt-get update \
 && apt-get install -y --no-install-recommends tzdata \
 && rm -rf /var/lib/apt/lists/* \
 && useradd --system --uid 10001 --home-dir /srv --shell /usr/sbin/nologin epaper \
 && mkdir -p /data && chown epaper:epaper /data

WORKDIR /srv
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app

USER epaper
VOLUME /data
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=4).status == 200 else 1)"

# Un seul worker : SQLite + verrou applicatif. Largement suffisant pour quelques centaines d'écrans.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
