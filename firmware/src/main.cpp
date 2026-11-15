// ============================================================================
//  Hibou — affichage d'occupation des salles — firmware reTerminal E1001 (ESP32-S3)
//
//  Cycle de vie (tout se passe dans setup(), loop() n'est jamais atteinte) :
//    1. réveil (timer, bouton, ou mise sous tension)
//    2. mesure batterie, connexion Wi-Fi (IP statique + canal/BSSID mémorisés)
//    3. GET /api/v1/display avec la télémétrie dans les en-têtes
//       - 200 : bitmap 800x480 1 bpp (48 000 o) -> rafraîchissement de l'écran
//       - 304 : l'écran affiche déjà la bonne image -> rien à faire
//    4. éventuelle mise à jour OTA (en-tête X-FW-URL)
//    5. deep sleep pendant X-Sleep-Seconds
// ============================================================================
#include <Arduino.h>
#include <WiFi.h>
#include <HTTPClient.h>
#include <HTTPUpdate.h>
#include <Preferences.h>
#include <SPI.h>
#include <esp_sleep.h>
#include <esp_wifi.h>
#include <driver/rtc_io.h>

#include <GxEPD2_BW.h>
#include <Fonts/FreeSansBold18pt7b.h>
#include <Fonts/FreeSans12pt7b.h>
#include <Fonts/FreeSans9pt7b.h>

#include "config.h"

#define LOG Serial1

// ---------------------------------------------------------------- écran
static const int EPD_W = 800, EPD_H = 480;
static const size_t FRAME_BYTES = EPD_W * EPD_H / 8;  // 48 000

SPIClass hspi(HSPI);
GxEPD2_BW<GxEPD2_750_GDEY075T7, GxEPD2_750_GDEY075T7::HEIGHT> display(
    GxEPD2_750_GDEY075T7(PIN_EPD_CS, PIN_EPD_DC, PIN_EPD_RST, PIN_EPD_BUSY));

// ---------------------------------------------------------------- état conservé en deep sleep
// (perdu en cas de coupure d'alimentation : on repart alors d'un état vierge, sans conséquence)
RTC_DATA_ATTR uint32_t rtcBootCount = 0;
RTC_DATA_ATTR uint32_t rtcFailCount = 0;
RTC_DATA_ATTR char     rtcEtag[24] = "";
RTC_DATA_ATTR uint8_t  rtcBssid[6] = {0};
RTC_DATA_ATTR int32_t  rtcChannel = 0;
RTC_DATA_ATTR bool     rtcHasBssid = false;

// ---------------------------------------------------------------- configuration (NVS)
struct Config {
  String ssid, pass, server, ip, gw, mask, dns;
} cfg;

Preferences prefs;

static void loadConfig() {
  prefs.begin("cfg", true);
  cfg.ssid   = prefs.getString("ssid",   DEFAULT_WIFI_SSID);
  cfg.pass   = prefs.getString("pass",   DEFAULT_WIFI_PASS);
  cfg.server = prefs.getString("server", DEFAULT_SERVER_URL);
  cfg.ip     = prefs.getString("ip",     "");               // vide = DHCP
  cfg.gw     = prefs.getString("gw",     DEFAULT_NET_GW);
  cfg.mask   = prefs.getString("mask",   DEFAULT_NET_MASK);
  cfg.dns    = prefs.getString("dns",    DEFAULT_NET_DNS);
  prefs.end();
  while (cfg.server.endsWith("/")) cfg.server.remove(cfg.server.length() - 1);
}

static String macString() {
  uint8_t m[6];
  WiFi.macAddress(m);
  char buf[18];
  snprintf(buf, sizeof(buf), "%02X:%02X:%02X:%02X:%02X:%02X", m[0], m[1], m[2], m[3], m[4], m[5]);
  return String(buf);
}

// ---------------------------------------------------------------- provisioning série
// Protocole texte ligne par ligne (115200 bauds, port USB-C) :
//   INFO            -> "INFO mac=.. fw=.."
//   GET             -> "CFG ssid=.. server=.. ip=.. gw=.. mask=.. dns=.." (mot de passe masqué)
//   SET cle=valeur  -> "OK cle"  (clés : ssid pass server ip gw mask dns ; valeur vide = défaut)
//   CLEAR           -> efface toute la config NVS
//   DONE            -> quitte le mode provisioning et démarre normalement
static void printConfig() {
  LOG.printf("CFG ssid=%s server=%s ip=%s gw=%s mask=%s dns=%s pass=%s\n", cfg.ssid.c_str(),
             cfg.server.c_str(), cfg.ip.length() ? cfg.ip.c_str() : "dhcp", cfg.gw.c_str(),
             cfg.mask.c_str(), cfg.dns.c_str(), cfg.pass.length() ? "***" : "(vide)");
}

static void provisioningWindow() {
  LOG.printf("\nPROVISION READY mac=%s fw=%s\n", macString().c_str(), FW_VERSION);
  uint32_t deadline = millis() + PROVISION_WINDOW_MS;
  String line;
  bool active = false;
  while ((int32_t)(deadline - millis()) > 0) {
    while (LOG.available()) {
      char c = LOG.read();
      if (c == '\r') continue;
      if (c != '\n') { if (line.length() < 200) line += c; continue; }
      line.trim();
      if (line.isEmpty()) continue;
      if (!active) { active = true; digitalWrite(PIN_LED, LOW); }
      deadline = millis() + 60000;  // une session est ouverte : on prolonge

      if (line == "INFO") {
        LOG.printf("INFO mac=%s fw=%s\n", macString().c_str(), FW_VERSION);
      } else if (line == "GET") {
        printConfig();
      } else if (line == "CLEAR") {
        prefs.begin("cfg", false); prefs.clear(); prefs.end();
        loadConfig();
        LOG.println("OK CLEAR");
      } else if (line == "DONE") {
        LOG.println("OK DONE");
        digitalWrite(PIN_LED, HIGH);
        return;
      } else if (line.startsWith("SET ")) {
        int eq = line.indexOf('=');
        String key = line.substring(4, eq > 0 ? eq : line.length());
        String val = eq > 0 ? line.substring(eq + 1) : "";
        key.trim();
        const char* allowed[] = {"ssid", "pass", "server", "ip", "gw", "mask", "dns"};
        bool ok = false;
        for (auto k : allowed) ok |= key == k;
        if (!ok) { LOG.printf("ERR cle inconnue: %s\n", key.c_str()); }
        else {
          if (val.length() && key != "ssid" && key != "pass" && key != "server") {
            IPAddress tmp;
            if (!tmp.fromString(val)) { LOG.printf("ERR adresse invalide: %s\n", val.c_str()); line = ""; continue; }
          }
          prefs.begin("cfg", false);
          if (val.length()) prefs.putString(key.c_str(), val); else prefs.remove(key.c_str());
          prefs.end();
          loadConfig();
          rtcHasBssid = false;  // le réseau a pu changer
          LOG.printf("OK %s\n", key.c_str());
        }
      } else {
        LOG.printf("ERR commande inconnue: %s\n", line.c_str());
      }
      line = "";
    }
    delay(5);
  }
  if (active) digitalWrite(PIN_LED, HIGH);
}

// ---------------------------------------------------------------- batterie
static int readBatteryMv() {
  pinMode(PIN_BAT_EN, OUTPUT);
  digitalWrite(PIN_BAT_EN, HIGH);
  delay(10);
  analogSetPinAttenuation(PIN_BAT_ADC, ADC_11db);
  uint32_t sum = 0;
  for (int i = 0; i < 8; i++) sum += analogReadMilliVolts(PIN_BAT_ADC);
  digitalWrite(PIN_BAT_EN, LOW);
  return (int)(sum / 8) * 2;  // pont diviseur /2
}

// ---------------------------------------------------------------- Wi-Fi
static bool waitWifi(uint32_t timeoutMs) {
  uint32_t t0 = millis();
  while (WiFi.status() != WL_CONNECTED) {
    if (millis() - t0 > timeoutMs) return false;
    delay(20);
  }
  return true;
}

// Résultat du scan de diagnostic (rempli seulement en cas d'échec de connexion)
static const int DIAG_MAX = 5;
static String diagSummary;
static String diagLines[DIAG_MAX];
static int diagCount = 0;

static const char* authName(wifi_auth_mode_t a) {
  switch (a) {
    case WIFI_AUTH_OPEN: return "ouvert";
    case WIFI_AUTH_WEP: return "WEP";
    case WIFI_AUTH_WPA_PSK: return "WPA";
    case WIFI_AUTH_WPA2_PSK: return "WPA2";
    case WIFI_AUTH_WPA_WPA2_PSK: return "WPA/WPA2";
    case WIFI_AUTH_WPA2_ENTERPRISE: return "WPA2-Entreprise";
    case WIFI_AUTH_WPA3_PSK: return "WPA3";
    case WIFI_AUTH_WPA2_WPA3_PSK: return "WPA2/WPA3";
    default: return "?";
  }
}

static const char* statusName(int st) {
  switch (st) {
    case WL_NO_SSID_AVAIL: return "reseau introuvable";
    case WL_CONNECT_FAILED: return "connexion refusee (mot de passe ?)";
    case WL_CONNECTION_LOST: return "connexion perdue";
    case WL_DISCONNECTED: return "deconnecte (authentification ?)";
    case WL_IDLE_STATUS: return "inactif";
    default: return "inconnu";
  }
}

// Scanne les réseaux visibles : indique si le SSID cherché est vu, sur quel canal et avec quelle sécurité
static void wifiScanReport() {
  WiFi.disconnect();
  delay(100);
  int n = WiFi.scanNetworks(false, true);  // synchrone, réseaux cachés inclus
  diagCount = 0;
  diagSummary = "";
  if (n <= 0) {
    diagSummary = "Aucun reseau Wi-Fi capte (antenne / radio ?)";
    LOG.println("scan: aucun reseau");
    return;
  }
  LOG.printf("scan: %d reseau(x)\n", n);
  int found = -1;
  for (int i = 0; i < n; i++) {
    LOG.printf("  %-32s ch=%2d rssi=%4d %s\n", WiFi.SSID(i).c_str(), WiFi.channel(i), WiFi.RSSI(i),
               authName(WiFi.encryptionType(i)));
    if (found < 0 && WiFi.SSID(i) == cfg.ssid) found = i;
  }
  if (found >= 0) {
    diagSummary = "\"" + cfg.ssid + "\" VU : canal " + WiFi.channel(found) + ", " + WiFi.RSSI(found) +
                  " dBm, " + authName(WiFi.encryptionType(found));
  } else {
    diagSummary = "\"" + cfg.ssid + "\" INTROUVABLE parmi " + n + " reseau(x) :";
  }
  // Les plus forts d'abord (scanNetworks trie déjà par RSSI décroissant)
  for (int i = 0; i < n && diagCount < DIAG_MAX; i++) {
    String name = WiFi.SSID(i).length() ? WiFi.SSID(i) : String("(cache)");
    if (name.length() > 24) name = name.substring(0, 23) + "~";
    diagLines[diagCount++] = name + "   canal " + WiFi.channel(i) + "   " + WiFi.RSSI(i) + " dBm   " +
                             authName(WiFi.encryptionType(i));
  }
  WiFi.scanDelete();
}

static bool connectWifi(uint32_t& elapsedMs) {
  uint32_t t0 = millis();
  WiFi.persistent(false);   // pas d'écriture flash à chaque connexion
  WiFi.mode(WIFI_STA);
  WiFi.setSleep(false);
  // Canaux 1 à 13 (Europe) en scan actif ; tous les canaux scannés ; WPA et plus acceptés
  wifi_country_t country = {"FR", 1, 13, 20, WIFI_COUNTRY_POLICY_MANUAL};
  esp_wifi_set_country(&country);
  WiFi.setScanMethod(WIFI_ALL_CHANNEL_SCAN);
  WiFi.setSortMethod(WIFI_CONNECT_AP_BY_SIGNAL);
  WiFi.setMinSecurity(WIFI_AUTH_WPA_PSK);

  if (cfg.ip.length()) {
    IPAddress ip, gw, mask, dns;
    ip.fromString(cfg.ip); gw.fromString(cfg.gw); mask.fromString(cfg.mask); dns.fromString(cfg.dns);
    WiFi.config(ip, gw, mask, dns);
  }

  bool ok = false;
  if (rtcHasBssid) {
    // Connexion rapide : pas de scan, on vise directement le point d'accès de la dernière fois
    WiFi.begin(cfg.ssid.c_str(), cfg.pass.c_str(), rtcChannel, rtcBssid, true);
    ok = waitWifi(WIFI_FAST_TIMEOUT_MS);
    if (!ok) {
      LOG.println("wifi: connexion rapide echouee, scan complet");
      WiFi.disconnect(true);
      delay(50);
      rtcHasBssid = false;
    }
  }
  if (!ok) {
    WiFi.begin(cfg.ssid.c_str(), cfg.pass.c_str());
    ok = waitWifi(WIFI_FULL_TIMEOUT_MS);
  }
  elapsedMs = millis() - t0;
  if (ok) {
    memcpy(rtcBssid, WiFi.BSSID(), 6);
    rtcChannel = WiFi.channel();
    rtcHasBssid = true;
    LOG.printf("wifi: ok en %lu ms, ip=%s rssi=%d ch=%d\n", (unsigned long)elapsedMs,
               WiFi.localIP().toString().c_str(), WiFi.RSSI(), rtcChannel);
  } else {
    int st = WiFi.status();
    LOG.printf("wifi: echec apres %lu ms (status=%d : %s)\n", (unsigned long)elapsedMs, st, statusName(st));
    wifiScanReport();
    LOG.println(diagSummary);
  }
  return ok;
}

// ---------------------------------------------------------------- affichage
static void displayInit() {
  hspi.begin(PIN_EPD_SCK, -1, PIN_EPD_MOSI, -1);
  display.epd2.selectSPI(hspi, SPISettings(10000000, MSBFIRST, SPI_MODE0));
  display.init(0, true, 2, false);
  display.setRotation(0);
}

static void showFrame(const uint8_t* frame) {
  displayInit();
  display.setFullWindow();
  display.firstPage();
  do {
    display.fillScreen(GxEPD_WHITE);
    display.drawBitmap(0, 0, frame, EPD_W, EPD_H, GxEPD_BLACK);  // bit 1 = noir
  } while (display.nextPage());
  display.hibernate();
}

// Écran de diagnostic, affiché seulement à la mise sous tension (installation)
static void showDiagnostic(const char* title, const String& detail) {
  displayInit();
  display.setFullWindow();
  display.firstPage();
  do {
    display.fillScreen(GxEPD_WHITE);
    display.fillRect(0, 0, EPD_W, 80, GxEPD_BLACK);
    display.setTextColor(GxEPD_WHITE);
    display.setFont(&FreeSansBold18pt7b);
    display.setCursor(24, 52);
    display.print(title);
    display.setTextColor(GxEPD_BLACK);
    display.setFont(&FreeSans12pt7b);
    int y = 118;
    auto line = [&](const String& k, const String& v) {
      display.setCursor(32, y); display.print(k);
      display.setCursor(250, y); display.print(v);
      y += 32;
    };
    line("MAC", macString());
    line("Wi-Fi (SSID)", cfg.ssid);
    line("IP", cfg.ip.length() ? cfg.ip : String("DHCP"));
    line("Serveur", cfg.server);
    line("Firmware", FW_VERSION);
    y += 4;
    display.setFont(&FreeSansBold18pt7b);
    display.setCursor(32, y + 6);
    display.print(detail);
    y += 34;
    if (diagSummary.length()) {
      display.setFont(&FreeSans12pt7b);
      display.setCursor(32, y);
      display.print(diagSummary);
      y += 26;
      display.setFont(&FreeSans9pt7b);
      for (int i = 0; i < diagCount && y < EPD_H - 6; i++) {
        display.setCursor(48, y);
        display.print(diagLines[i]);
        y += 21;
      }
    }
  } while (display.nextPage());
  display.hibernate();
}

// ---------------------------------------------------------------- deep sleep
[[noreturn]] static void sleepFor(uint32_t seconds) {
  if (seconds < MIN_SLEEP_S) seconds = MIN_SLEEP_S;
  if (seconds > MAX_SLEEP_S) seconds = MAX_SLEEP_S;
  LOG.printf("sommeil %lu s\n", (unsigned long)seconds);
  LOG.flush();
  WiFi.disconnect(true);
  WiFi.mode(WIFI_OFF);
  digitalWrite(PIN_LED, HIGH);
  esp_sleep_enable_timer_wakeup((uint64_t)seconds * 1000000ULL);
  rtc_gpio_pullup_en((gpio_num_t)PIN_BTN_WAKE);
  rtc_gpio_pulldown_dis((gpio_num_t)PIN_BTN_WAKE);
  esp_sleep_enable_ext0_wakeup((gpio_num_t)PIN_BTN_WAKE, 0);  // bouton actif à l'état bas
  esp_deep_sleep_start();
}

static uint32_t backoffSeconds(uint32_t fails) {
  // 2 min, 5 min, 10 min, 30 min, puis 1 h
  static const uint32_t steps[] = {120, 300, 600, 1800, 3600};
  uint32_t i = fails ? fails - 1 : 0;
  return steps[i > 4 ? 4 : i];
}

[[noreturn]] static void fail(const char* why, bool coldBoot) {
  rtcFailCount++;
  LOG.printf("ECHEC: %s (echecs consecutifs: %lu)\n", why, (unsigned long)rtcFailCount);
  if (coldBoot) showDiagnostic("Connexion impossible", why);
  sleepFor(backoffSeconds(rtcFailCount));
}

// ---------------------------------------------------------------- OTA
static void maybeOta(const String& path, int batteryMv) {
  if (!path.length()) return;
  if (batteryMv > 0 && batteryMv < 3600) {
    LOG.println("ota: batterie trop faible, reporte");
    return;
  }
  String url = path.startsWith("http") ? path : cfg.server + path;
  LOG.printf("ota: telechargement %s\n", url.c_str());
  WiFiClient client;
  httpUpdate.rebootOnUpdate(true);
  httpUpdate.setLedPin(PIN_LED, LOW);
  t_httpUpdate_return r = httpUpdate.update(client, url);
  if (r == HTTP_UPDATE_FAILED)
    LOG.printf("ota: echec (%d) %s\n", httpUpdate.getLastError(), httpUpdate.getLastErrorString().c_str());
}

// ================================================================ setup
void setup() {
  LOG.begin(115200, SERIAL_8N1, PIN_LOG_RX, PIN_LOG_TX);
  pinMode(PIN_LED, OUTPUT);
  digitalWrite(PIN_LED, HIGH);
  rtcBootCount++;

  esp_sleep_wakeup_cause_t cause = esp_sleep_get_wakeup_cause();
  const char* reason = "power_on";
  if (cause == ESP_SLEEP_WAKEUP_TIMER) reason = "timer";
  else if (cause == ESP_SLEEP_WAKEUP_EXT0) reason = "button";
  bool coldBoot = cause == ESP_SLEEP_WAKEUP_UNDEFINED;
  if (coldBoot) { rtcEtag[0] = 0; rtcFailCount = 0; }

  loadConfig();
  if (coldBoot) {
    WiFi.mode(WIFI_STA);  // nécessaire pour lire la MAC
    provisioningWindow();
  }
  LOG.printf("\nreveil: %s, boot #%lu, fw %s\n", reason, (unsigned long)rtcBootCount, FW_VERSION);

  int batteryMv = readBatteryMv();
  LOG.printf("batterie: %d mV\n", batteryMv);

  uint32_t wifiMs = 0;
  if (!connectWifi(wifiMs)) fail("Wi-Fi injoignable", coldBoot);

  HTTPClient http;
  http.setTimeout(HTTP_TIMEOUT_MS);
  http.setConnectTimeout(5000);
  http.setReuse(false);
  if (!http.begin(cfg.server + "/api/v1/display")) fail("URL serveur invalide", coldBoot);

  http.addHeader("X-Device-MAC", macString());
  http.addHeader("X-FW-Version", FW_VERSION);
  http.addHeader("X-Battery-mV", String(batteryMv));
  http.addHeader("X-RSSI", String(WiFi.RSSI()));
  http.addHeader("X-IP", WiFi.localIP().toString());
  http.addHeader("X-Wake-Reason", reason);
  http.addHeader("X-Boot-Count", String(rtcBootCount));
  http.addHeader("X-WiFi-ms", String(wifiMs));
  http.addHeader("X-Fail-Count", String(rtcFailCount));
  if (rtcEtag[0]) http.addHeader("If-None-Match", rtcEtag);
  const char* wanted[] = {"X-Sleep-Seconds", "ETag", "X-FW-URL"};
  http.collectHeaders(wanted, 3);

  int code = http.GET();
  uint32_t sleepS = http.header("X-Sleep-Seconds").toInt();
  String etag = http.header("ETag");
  String fwUrl = http.header("X-FW-URL");
  LOG.printf("http: %d, sommeil demande %lu s\n", code, (unsigned long)sleepS);

  if (code == 200) {
    int len = http.getSize();
    if (len != (int)FRAME_BYTES) { http.end(); fail("Taille d'image inattendue", coldBoot); }
    uint8_t* frame = (uint8_t*)ps_malloc(FRAME_BYTES);
    if (!frame) frame = (uint8_t*)malloc(FRAME_BYTES);
    WiFiClient* stream = http.getStreamPtr();
    size_t got = 0;
    uint32_t t0 = millis();
    while (got < FRAME_BYTES && millis() - t0 < HTTP_TIMEOUT_MS) {
      size_t n = stream->readBytes(frame + got, FRAME_BYTES - got);
      if (n == 0 && !stream->connected()) break;
      got += n;
    }
    http.end();
    if (got != FRAME_BYTES) { free(frame); fail("Image incomplete", coldBoot); }

    // Le Wi-Fi n'est plus utile pendant les ~3 s de rafraîchissement, sauf si une OTA suit
    if (!fwUrl.length()) { WiFi.disconnect(true); WiFi.mode(WIFI_OFF); }
    showFrame(frame);
    free(frame);
    strlcpy(rtcEtag, etag.c_str(), sizeof(rtcEtag));
  } else if (code == 304) {
    http.end();
    LOG.println("image inchangee");
  } else {
    http.end();
    char msg[48];
    snprintf(msg, sizeof(msg), "Erreur serveur (HTTP %d)", code);
    fail(msg, coldBoot);
  }

  rtcFailCount = 0;
  if (fwUrl.length() && WiFi.status() == WL_CONNECTED) maybeOta(fwUrl, batteryMv);
  sleepFor(sleepS ? sleepS : 1800);
}

void loop() {}
