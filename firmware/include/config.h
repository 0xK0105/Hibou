#pragma once
// ---------------------------------------------------------------------------
// Valeurs par défaut communes à tous les écrans.
// Elles sont compilées dans le firmware ; chaque écran peut ensuite les
// surcharger via le provisioning série (tools/provision.py), stocké en NVS.
// Typiquement : SSID / mot de passe / serveur ici, IP statique par écran via provision.py.
//
// Pour ne pas committer les secrets : créez include/config_local.h (ignoré par git)
// avec les mêmes #define, il est pris en priorité.
// ---------------------------------------------------------------------------
#if __has_include("config_local.h")
#include "config_local.h"
#endif

#ifndef DEFAULT_WIFI_SSID
#define DEFAULT_WIFI_SSID   "ECRANS-IOT"
#endif
#ifndef DEFAULT_WIFI_PASS
#define DEFAULT_WIFI_PASS   "changez-moi"
#endif
#ifndef DEFAULT_SERVER_URL
#define DEFAULT_SERVER_URL  "http://10.20.0.10:8000"   // sans slash final
#endif
// Réseau par défaut (l'IP de l'écran elle-même est propre à chaque terminal : provision.py --ip)
#ifndef DEFAULT_NET_GW
#define DEFAULT_NET_GW      "10.20.0.1"
#endif
#ifndef DEFAULT_NET_MASK
#define DEFAULT_NET_MASK    "255.255.255.0"
#endif
#ifndef DEFAULT_NET_DNS
#define DEFAULT_NET_DNS     "10.20.0.1"
#endif

#ifndef FW_VERSION
#define FW_VERSION "dev"
#endif

// --- Délais ---------------------------------------------------------------
#define WIFI_FAST_TIMEOUT_MS    4000   // connexion avec canal/BSSID mémorisés
#define WIFI_FULL_TIMEOUT_MS   12000   // connexion avec scan complet
#define HTTP_TIMEOUT_MS        15000
#define PROVISION_WINDOW_MS     3000   // fenêtre d'écoute série au démarrage à froid
#define MIN_SLEEP_S               30
#define MAX_SLEEP_S     (72UL * 3600)

// --- Brochage reTerminal E1001 (wiki Seeed) ------------------------------
#define PIN_EPD_SCK    7
#define PIN_EPD_MOSI   9
#define PIN_EPD_CS    10
#define PIN_EPD_DC    11
#define PIN_EPD_RST   12
#define PIN_EPD_BUSY  13
#define PIN_BAT_ADC    1
#define PIN_BAT_EN    21
#define PIN_LED        6    // active à l'état bas
#define PIN_BTN_WAKE   4    // bouton blanc de droite : réveil + rafraîchissement forcé
#define PIN_LOG_RX    44    // UART relié au pont USB-série du port USB-C
#define PIN_LOG_TX    43
