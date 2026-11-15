#!/usr/bin/env bash
# Boîte à outils firmware (exécutée dans le conteneur « firmware »).
#
#   build                       compile, fusionne l'image complète, publie sur le serveur
#   flash  <port> [version]     flashe l'image complète en USB (Linux : --device /dev/ttyUSB0)
#   provision <args…>           tools/provision.py (même options)
#   simulate  <args…>           tools/simulate_device.py (même options)
#   shell [args…]               bash dans le conteneur (ex : shell -c "commande")
#
# Variables (fichier .env) : FW_VERSION, WIFI_SSID, WIFI_PASSWORD, SERVER_URL, NET_GW, NET_MASK, NET_DNS,
#                            PUBLISH (1), ACTIVATE (0), FORCE (0), PUBLISH_URL (http://server:8000)
set -euo pipefail

SRC=${SRC_DIR:-/src}
BUILD=/build
OUT=${OUT_DIR:-/out}
ENV_NAME=reterminal_e1001
PUBLISH_URL=${PUBLISH_URL:-http://server:8000}
ESPTOOL="python3 ${PLATFORMIO_CORE_DIR}/packages/tool-esptoolpy/esptool.py"

die() { echo "ERREUR : $*" >&2; exit 1; }
info() { echo "==> $*"; }
cstr() { python3 -c 'import json,sys; print(json.dumps(sys.argv[1], ensure_ascii=False))' "$1"; }

cmd_build() {
  : "${FW_VERSION:?FW_VERSION non défini (ex : docker compose run --rm -e FW_VERSION=0.2.0 firmware)}"
  : "${WIFI_SSID:?WIFI_SSID non défini dans .env}"
  : "${WIFI_PASSWORD:?WIFI_PASSWORD non défini dans .env}"
  : "${SERVER_URL:?SERVER_URL non défini dans .env (URL du serveur vue par les écrans)}"
  [[ "$FW_VERSION" =~ ^[0-9A-Za-z._-]{1,31}$ ]] || die "FW_VERSION invalide : $FW_VERSION"
  [[ "$SERVER_URL" != *"://server"* ]] || die "SERVER_URL doit être l'adresse joignable par les écrans (IP du serveur), pas le nom du conteneur"

  if [[ "${PUBLISH:-1}" == 1 && "${FORCE:-0}" != 1 ]]; then
    if curl -fsS "$PUBLISH_URL/api/firmware" 2>/dev/null | python3 -c "import json,sys; sys.exit(0 if any(f['version']=='$FW_VERSION' for f in json.load(sys.stdin)) else 1)"; then
      die "la version $FW_VERSION existe déjà sur le serveur. Incrémentez FW_VERSION (ou FORCE=1)."
    fi
  fi

  info "Préparation des sources (version $FW_VERSION)"
  rm -rf "$BUILD/src" "$BUILD/include"
  cp -r "$SRC/src" "$SRC/include" "$BUILD/"
  cp "$SRC/platformio.ini" "$BUILD/platformio.ini"
  rm -f "$BUILD/include/config_local.h"
  cat > "$BUILD/include/config_local.h" <<EOF
// Généré par toolbox.sh le $(date -Iseconds) — ne pas modifier
#define FW_VERSION          $(cstr "$FW_VERSION")
#define DEFAULT_WIFI_SSID   $(cstr "$WIFI_SSID")
#define DEFAULT_WIFI_PASS   $(cstr "$WIFI_PASSWORD")
#define DEFAULT_SERVER_URL  $(cstr "${SERVER_URL%/}")
#define DEFAULT_NET_GW      $(cstr "${NET_GW:-}")
#define DEFAULT_NET_MASK    $(cstr "${NET_MASK:-255.255.255.0}")
#define DEFAULT_NET_DNS     $(cstr "${NET_DNS:-${NET_GW:-}}")
EOF

  info "Compilation"
  (cd "$BUILD" && pio run -e "$ENV_NAME")

  local B="$BUILD/.pio/build/$ENV_NAME"
  local DEST="$OUT/$FW_VERSION"
  mkdir -p "$DEST"
  info "Fusion de l'image complète (bootloader + partitions + app)"
  $ESPTOOL --chip esp32s3 merge_bin -o "$DEST/factory.bin" \
    --flash_mode keep --flash_freq keep --flash_size 8MB \
    0x0 "$B/bootloader.bin" \
    0x8000 "$B/partitions.bin" \
    0xe000 "${PLATFORMIO_CORE_DIR}/packages/framework-arduinoespressif32/tools/partitions/boot_app0.bin" \
    0x10000 "$B/firmware.bin" >/dev/null
  cp "$B/firmware.bin" "$DEST/firmware.bin"
  (cd "$DEST" && sha256sum firmware.bin factory.bin > SHA256SUMS)
  cat > "$DEST/build-info.json" <<EOF
{"version": $(cstr "$FW_VERSION"), "built_at": "$(date -Iseconds)", "ssid": $(cstr "$WIFI_SSID"),
 "server_url": $(cstr "$SERVER_URL"), "gateway": $(cstr "${NET_GW:-}")}
EOF
  info "Artefacts : $DEST"
  ls -la "$DEST"

  if [[ "${PUBLISH:-1}" == 1 ]]; then
    info "Publication sur $PUBLISH_URL"
    curl -fsS -F "version=$FW_VERSION" -F "file=@$DEST/firmware.bin" -F "factory=@$DEST/factory.bin" \
      -F "notes=build $(date -Iseconds)" "$PUBLISH_URL/api/firmware" >/dev/null \
      || die "publication impossible (le serveur tourne-t-il ? docker compose up -d)"
    if [[ "${ACTIVATE:-0}" == 1 ]]; then
      curl -fsS -X POST "$PUBLISH_URL/api/firmware/$FW_VERSION/activate" >/dev/null
      info "Version $FW_VERSION ACTIVÉE : les écrans se mettront à jour à leur prochain réveil."
    else
      info "Version publiée (non activée). Activez-la depuis l'onglet Firmware, ou relancez avec ACTIVATE=1."
    fi
  fi
}

cmd_flash() {
  local port=${1:?usage : flash <port série> [version]}
  local version=${2:-$(ls -1t "$OUT" 2>/dev/null | head -1)}
  [[ -n "$version" && -f "$OUT/$version/factory.bin" ]] || die "aucune image $OUT/$version/factory.bin (lancez d'abord build)"
  info "Flash de $version sur $port"
  $ESPTOOL --chip esp32s3 --port "$port" --baud 921600 write_flash 0x0 "$OUT/$version/factory.bin"
}

case "${1:-build}" in
  build)     shift || true; cmd_build "$@" ;;
  flash)     shift; cmd_flash "$@" ;;
  provision) shift; exec python3 /opt/tools/provision.py "$@" ;;
  simulate)  shift; exec python3 /opt/tools/simulate_device.py --server "$PUBLISH_URL" "$@" ;;
  shell)     shift; exec bash "$@" ;;
  *)         die "commande inconnue : $1 (build | flash | provision | simulate | shell)" ;;
esac
