# Boîte à outils firmware : compilation PlatformIO, publication OTA, flash USB, provisioning.
# Contexte de build = racine du dépôt (voir docker-compose.yml).
FROM python:3.12-slim

LABEL org.opencontainers.image.title="hibou-firmware" \
      org.opencontainers.image.description="Chaîne de compilation du firmware reTerminal E1001"

ENV PLATFORMIO_CORE_DIR=/opt/platformio \
    PLATFORMIO_NO_ANSI=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update \
 && apt-get install -y --no-install-recommends git curl ca-certificates \
 && rm -rf /var/lib/apt/lists/* \
 && pip install --no-cache-dir "platformio>=6.1,<7" pyserial pillow

# Pré-installation de la plateforme ESP32, des toolchains et des bibliothèques dans l'image :
# les compilations suivantes fonctionnent sans accès Internet.
WORKDIR /build
COPY firmware/platformio.ini /build/platformio.ini
RUN pio pkg install -e reterminal_e1001 \
 && mkdir -p src include && printf '#include <Arduino.h>\nvoid setup(){}\nvoid loop(){}\n' > src/main.cpp \
 && pio run -e reterminal_e1001 \
 && rm -rf src include .pio/build

COPY tools/provision.py tools/simulate_device.py /opt/tools/
COPY firmware/toolbox.sh /usr/local/bin/toolbox
RUN chmod +x /usr/local/bin/toolbox

ENTRYPOINT ["toolbox"]
CMD ["build"]
