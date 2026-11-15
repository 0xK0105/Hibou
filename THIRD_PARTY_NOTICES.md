# Composants tiers embarqués

| Composant | Emplacement | Licence |
|---|---|---|
| ESP Web Tools 10.5.2 (ESPHome) | `server/app/static/vendor/esp-web-tools/` | Apache-2.0 (`LICENSE` dans le dossier) |
| Polices DejaVu Sans | `server/app/fonts/` | Bitstream Vera / DejaVu (`LICENSE-DejaVu.txt`) |

Dépendances installées à la construction (non embarquées dans le dépôt) : FastAPI, Uvicorn, Pillow,
icalendar, recurring-ical-events (serveur) ; PlatformIO, framework Arduino-ESP32, GxEPD2,
Adafruit GFX (firmware). Voir leurs licences respectives.
