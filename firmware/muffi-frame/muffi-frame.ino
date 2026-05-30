/**
 * Muffi Photo Frame ❤️
 * Waveshare ESP32-C6 1.47inch Display-M
 * LovyanGFX + JPEGDEC
 * BOOT-Knopf (GPIO9) = nächstes Bild
 */

#include <LovyanGFX.hpp>
#include <WiFi.h>
#include <WiFiUdp.h>
#include <ArduinoOTA.h>
#include <HTTPClient.h>
#include <JPEGDEC.h>
#include <ArduinoJson.h>
#include <Preferences.h>

#if __has_include("secrets.h")
#include "secrets.h"
#endif

// ============ EINSTELLUNGEN ============
#ifndef WIFI_SSID_DEFAULT
#define WIFI_SSID_DEFAULT ""
#endif

#ifndef WIFI_PASSWORD_DEFAULT
#define WIFI_PASSWORD_DEFAULT ""
#endif

const char* SERVER_BASE_DEFAULT   = "http://frame-server.local:8765"; // Beispielwert, lokal anpassen
#define DEFAULT_REFRESH_MS   (5 * 60 * 1000UL)
#define BUTTON_PIN   9    // BOOT-Knopf
#define SIDE_BUTTON_PIN 0  // Seitentaste (bei Bedarf anpassen)
#ifdef RGB_BUILTIN
#define LED_PIN      RGB_BUILTIN
#else
#define LED_PIN      8    // Fallback
#endif
#define SERVO_PIN    3    // SG90 Signal
#define SERVO_FREQ   50   // 50Hz
#define SERVO_HOCHFORMAT_DEFAULT   1638  // 0°  (~500µs  von 20ms)
#define SERVO_QUERFORMAT_DEFAULT   4915  // 90° (~1500µs von 20ms)
#define SERVO_DELAY_MS_DEFAULT     600
#define DOUBLE_CLICK_MS 500UL
#define LONG_PRESS_MS   1000UL
#define DEBOUNCE_MS     40UL
// =======================================

class LGFX : public lgfx::LGFX_Device {
  lgfx::Panel_ST7789  _panel;
  lgfx::Bus_SPI       _bus;
  lgfx::Light_PWM     _light;
public:
  LGFX() {
    { auto cfg = _bus.config();
      cfg.spi_host  = SPI2_HOST;
      cfg.spi_mode  = 0;
      cfg.freq_write= 40000000;
      cfg.pin_sclk  = 7;
      cfg.pin_mosi  = 6;
      cfg.pin_miso  = -1;
      cfg.pin_dc    = 15;
      _bus.config(cfg); _panel.setBus(&_bus); }
    { auto cfg = _panel.config();
      cfg.pin_cs   = 14;
      cfg.pin_rst  = 21;
      cfg.pin_busy = -1;
      cfg.panel_width  = 172;
      cfg.panel_height = 320;
      cfg.offset_x     = 34;
      cfg.offset_y     = 0;
      cfg.invert       = true;
      cfg.rgb_order    = false;
      _panel.config(cfg); }
    { auto cfg = _light.config();
      cfg.pin_bl      = 22;
      cfg.invert      = false;
      cfg.freq        = 44100;
      cfg.pwm_channel = 7;
      _light.config(cfg); _panel.setLight(&_light); }
    setPanel(&_panel);
  }
};

LGFX tft;
JPEGDEC jpeg;

void showStatus(const char* msg, uint16_t color = TFT_WHITE);

// Bilderliste
struct PhotoInfo {
  String name;
  bool   landscape;
};
PhotoInfo fileList[200];
int       fileCount  = 0;
int       currentIdx = 0;

uint8_t* jpegBuf = nullptr;
size_t   jpegLen = 0;

int           currentRotation = 0; // 0=Hochformat, 1=Querformat

// Hauptbutton (BOOT): ISR-basiert für zuverlässigen Doppelklick
volatile unsigned long bootLastEdgeMs = 0;
volatile unsigned long bootLastReleaseMs = 0;
volatile uint8_t bootClickCount = 0;
volatile bool bootClickPending = false;

// Seitentaste: kurzer Klick = Farbe weiter
bool sideBtnPressed = false;
unsigned long sideBtnPressMs = 0;
unsigned long sideBtnLastEdgeMs = 0;

// Dynamischer Refresh (via Server-Config)
unsigned long refreshMs = DEFAULT_REFRESH_MS;
unsigned long lastRefresh = 0;
unsigned long lastWiFiRetryMs = 0;
unsigned long lastNoPhotoRetryMs = 0;
bool otaReady = false;
unsigned long lastUploadPollMs = 0;
bool uploadUiVisible = false;
int lastUploadProgress = -1;
String lastUploadPhase = "idle";
bool bootClickHandlingEnabled = false;

// LED + Netzwerk State
Preferences prefs;
String wifiSsid = "";
String wifiPassword = "";
String serverBase = SERVER_BASE_DEFAULT;
bool wlanFallbackEnabled = false;
String wlanFallbackBase = "";
uint16_t wlanSyncTimeoutMs = 1500;
String lastWlanSyncToken = "";
unsigned long lastWlanSyncMs = 0;
bool ledOn = true;
uint8_t ledBrightness = 180;
uint8_t ledR = 255;
uint8_t ledG = 214;
uint8_t ledB = 160;
int ledColorIndex = 0;
unsigned long lastLedPollMs = 0;
unsigned long lastLedSyncMs = 0;
String ledOrder = "GRB"; // Waveshare ESP32-C6 Display-M default
bool motorEnabled = true;
int servoHochformatPulse = SERVO_HOCHFORMAT_DEFAULT;
int servoQuerformatPulse = SERVO_QUERFORMAT_DEFAULT;
uint16_t servoMoveDelayMs = SERVO_DELAY_MS_DEFAULT;
int currentServoPulse = SERVO_HOCHFORMAT_DEFAULT;
String lastMotorCommandToken = "";
unsigned long lastMotorPollMs = 0;

const uint8_t LED_CATALOG[][3] = {
  {255,   0,   0}, // rot
  {255,  80,   0}, // orange
  {255, 255,   0}, // gelb
  {  0, 255,   0}, // grün
  {  0, 255, 255}, // cyan
  {  0,   0, 255}, // blau
  {128,   0, 255}, // violett
  {255,   0, 180}  // magenta
};
const int LED_CATALOG_COUNT = sizeof(LED_CATALOG) / sizeof(LED_CATALOG[0]);

String normalizeServerBase(const String& input) {
  String out = input;
  out.trim();
  if (!out.length()) out = String(SERVER_BASE_DEFAULT);
  while (out.endsWith("/")) out.remove(out.length() - 1);
  return out;
}

String normalizeOptionalServerBase(const String& input) {
  String out = input;
  out.trim();
  if (!out.length()) return "";
  while (out.endsWith("/")) out.remove(out.length() - 1);
  return out;
}

String serverUrl(const String& path) {
  if (!path.length()) return serverBase;
  if (path.startsWith("/")) return serverBase + path;
  return serverBase + "/" + path;
}

void loadNetworkConfigFromPrefs() {
  wifiSsid = prefs.getString("wifiSsid", "");
  wifiPassword = prefs.getString("wifiPw", "");
  serverBase = normalizeServerBase(prefs.getString("srvBase", SERVER_BASE_DEFAULT));
  wlanFallbackEnabled = prefs.getBool("srvFbOn", false);
  wlanFallbackBase = normalizeOptionalServerBase(prefs.getString("srvFb", ""));
  uint32_t t = prefs.getUInt("wlanTO", 1500);
  if (t < 600) t = 600;
  if (t > 5000) t = 5000;
  wlanSyncTimeoutMs = (uint16_t)t;
}

void saveNetworkConfigToPrefs() {
  prefs.putString("wifiSsid", wifiSsid);
  prefs.putString("wifiPw", wifiPassword);
  prefs.putString("srvBase", serverBase);
  prefs.putBool("srvFbOn", wlanFallbackEnabled);
  prefs.putString("srvFb", wlanFallbackBase);
  prefs.putUInt("wlanTO", wlanSyncTimeoutMs);
}

bool connectWiFiOnce(const String& ssid, const String& password, uint32_t timeoutMs, const char* statusLabel) {
  if (!ssid.length()) return false;
  showStatus(statusLabel, TFT_WHITE);
  WiFi.begin(ssid.c_str(), password.c_str());

  unsigned long start = millis();
  while (WiFi.status() != WL_CONNECTED && (millis() - start) < timeoutMs) {
    delay(300);
  }
  return WiFi.status() == WL_CONNECTED;
}

bool fetchWlanConfigFromServer() {
  if (WiFi.status() != WL_CONNECTED) return false;

  const int MAX_ENDPOINTS = 4;
  String endpoints[MAX_ENDPOINTS];
  int endpointCount = 0;

  endpoints[0] = serverUrl("/api/wlan?source=esp");
  endpointCount = 1;

  if (wlanFallbackEnabled && wlanFallbackBase.length()) {
    endpoints[endpointCount++] = wlanFallbackBase + "/api/wlan?source=esp";
  }

  String defaultEndpoint = String(SERVER_BASE_DEFAULT) + "/api/wlan?source=esp";
  bool hasDefault = false;
  for (int i = 0; i < endpointCount; i++) {
    if (endpoints[i] == defaultEndpoint) {
      hasDefault = true;
      break;
    }
  }
  if (!hasDefault && endpointCount < MAX_ENDPOINTS) {
    endpoints[endpointCount++] = defaultEndpoint;
  }

  String body = "";
  bool okFetch = false;

  for (int i = 0; i < endpointCount; i++) {
    String url = endpoints[i];
    if (!url.length()) continue;

    bool duplicate = false;
    for (int j = 0; j < i; j++) {
      if (endpoints[j] == url) {
        duplicate = true;
        break;
      }
    }
    if (duplicate) continue;

    HTTPClient http;
    http.begin(url);
    http.setTimeout(wlanSyncTimeoutMs);
    int code = http.GET();
    if (code == 200) {
      body = http.getString();
      http.end();
      okFetch = true;
      break;
    }
    http.end();
  }
  if (!okFetch) return false;

  JsonDocument doc;
  if (deserializeJson(doc, body)) return false;

  String nextSsid = String((const char*)(doc["ssid"] | ""));
  String nextPw = String((const char*)(doc["password"] | ""));
  String nextBase = normalizeServerBase(String((const char*)(doc["serverBase"] | SERVER_BASE_DEFAULT)));
  bool nextFallbackEnabled = bool(doc["fallbackEnabled"] | false);
  String nextFallbackBase = normalizeOptionalServerBase(String((const char*)(doc["fallbackServerBase"] | "")));
  uint32_t nextSyncTimeout = uint32_t(doc["syncTimeoutMs"] | wlanSyncTimeoutMs);
  if (nextSyncTimeout < 600) nextSyncTimeout = 600;
  if (nextSyncTimeout > 5000) nextSyncTimeout = 5000;
  String syncToken = String((const char*)(doc["syncToken"] | ""));

  bool changed = false;
  if (nextBase.length() && nextBase != serverBase) {
    serverBase = nextBase;
    changed = true;
  }

  if (nextSsid.length() && nextPw.length()) {
    if (nextSsid != wifiSsid || nextPw != wifiPassword) {
      wifiSsid = nextSsid;
      wifiPassword = nextPw;
      changed = true;
    }
  }

  if (nextFallbackEnabled != wlanFallbackEnabled || nextFallbackBase != wlanFallbackBase) {
    wlanFallbackEnabled = nextFallbackEnabled;
    wlanFallbackBase = nextFallbackBase;
    changed = true;
  }

  if ((uint16_t)nextSyncTimeout != wlanSyncTimeoutMs) {
    wlanSyncTimeoutMs = (uint16_t)nextSyncTimeout;
    changed = true;
  }

  if (changed) {
    saveNetworkConfigToPrefs();
    Serial.println("WLAN/Server Config vom Server aktualisiert");
  }

  if (syncToken.length() && syncToken != lastWlanSyncToken) {
    lastWlanSyncToken = syncToken;
    prefs.putString("wlanTok", lastWlanSyncToken);
    Serial.println("WLAN Sync Token bestaetigt: " + lastWlanSyncToken);
    showStatus("Config empfangen", TFT_GREEN);
    delay(180);
  }
  return true;
}

void setupOTA() {
  if (otaReady) return;

  ArduinoOTA.setHostname("muffi-frame");

  ArduinoOTA.onStart([]() {
    showStatus("OTA Update...", TFT_CYAN);
  });

  ArduinoOTA.onEnd([]() {
    showStatus("OTA Fertig", TFT_GREEN);
    delay(800);
  });

  ArduinoOTA.onError([](ota_error_t) {
    showStatus("OTA Fehler", TFT_RED);
  });

  ArduinoOTA.begin();
  otaReady = true;
  Serial.println("OTA bereit");
}

bool connectWiFi(uint32_t timeoutMs = 30000) {
  if (WiFi.status() == WL_CONNECTED) return true;

  WiFi.mode(WIFI_STA);

  bool ok = false;
  if (wifiSsid.length()) {
    ok = connectWiFiOnce(wifiSsid, wifiPassword, timeoutMs, "WLAN (saved)...");
  }

  if (!ok) {
    ok = connectWiFiOnce(String(WIFI_SSID_DEFAULT), String(WIFI_PASSWORD_DEFAULT), timeoutMs, "WLAN (default)...");
    if (ok) {
      wifiSsid = WIFI_SSID_DEFAULT;
      wifiPassword = WIFI_PASSWORD_DEFAULT;
      saveNetworkConfigToPrefs();
    }
  }

  if (ok) {
    showStatus("WLAN OK", TFT_GREEN);
    Serial.println("WLAN OK: " + WiFi.localIP().toString());
    setupOTA();
    delay(400);
    return true;
  }

  showStatus("WLAN Fehler!", TFT_RED);
  Serial.println("WLAN Verbindung fehlgeschlagen");
  return false;
}

bool ensureWiFiConnected() {
  if (WiFi.status() == WL_CONNECTED) return true;

  if (millis() - lastWiFiRetryMs < 5000) {
    return false;
  }
  lastWiFiRetryMs = millis();
  return connectWiFi(10000);
}

void IRAM_ATTR bootButtonISR() {
  unsigned long now = millis();
  if (now - bootLastEdgeMs < DEBOUNCE_MS) return;
  bootLastEdgeMs = now;

  // Auf Release zählen (LOW -> HIGH)
  if (digitalRead(BUTTON_PIN) == HIGH) {
    if (now - bootLastReleaseMs <= DOUBLE_CLICK_MS) {
      if (bootClickCount < 250) bootClickCount++;
    } else {
      bootClickCount = 1;
    }
    bootLastReleaseMs = now;
    bootClickPending = true;
  }
}

void handleBootClicks() {
  if (!bootClickPending) return;

  unsigned long lastRel = 0;
  uint8_t clicks = 0;
  noInterrupts();
  lastRel = bootLastReleaseMs;
  clicks = bootClickCount;
  interrupts();

  if (millis() - lastRel <= DOUBLE_CLICK_MS) return;

  noInterrupts();
  bootClickPending = false;
  bootClickCount = 0;
  interrupts();

  if (clicks >= 2) {
    Serial.println("Doppelklick: LED Farbe weiter");
    cycleLedColor();
    reportLedState("button-double");
  } else if (clicks == 1) {
    Serial.println("Nächstes Bild");
    if (ensureWiFiConnected() && refreshFileList() && fileCount > 0) {
      currentIdx = (currentIdx + 1) % fileCount;
      showImage(currentIdx);
    } else {
      showStatus("Kein WLAN/Fotos", TFT_YELLOW);
    }
  }
}

void applyLed() {
  uint8_t r = ledOn ? (uint16_t(ledR) * ledBrightness) / 255 : 0;
  uint8_t g = ledOn ? (uint16_t(ledG) * ledBrightness) / 255 : 0;
  uint8_t b = ledOn ? (uint16_t(ledB) * ledBrightness) / 255 : 0;

  uint8_t c0 = r, c1 = g, c2 = b;
  if (ledOrder == "GRB") { c0 = g; c1 = r; c2 = b; }
  else if (ledOrder == "RGB") { c0 = r; c1 = g; c2 = b; }
  else if (ledOrder == "BRG") { c0 = b; c1 = r; c2 = g; }
  else if (ledOrder == "BGR") { c0 = b; c1 = g; c2 = r; }
  else if (ledOrder == "RBG") { c0 = r; c1 = b; c2 = g; }
  else if (ledOrder == "GBR") { c0 = g; c1 = b; c2 = r; }
  else { c0 = g; c1 = r; c2 = b; } // sicherer Fallback

  neopixelWrite(LED_PIN, c0, c1, c2);
}

void saveLedState() {
  prefs.putBool("ledOn", ledOn);
  prefs.putUChar("ledBri", ledBrightness);
  prefs.putUChar("ledR", ledR);
  prefs.putUChar("ledG", ledG);
  prefs.putUChar("ledB", ledB);
  prefs.putInt("ledIdx", ledColorIndex);
  prefs.putString("ledOrd", ledOrder);
}

void setLedColor(uint8_t r, uint8_t g, uint8_t b, int idx = -1) {
  ledR = r;
  ledG = g;
  ledB = b;
  ledColorIndex = idx;
  applyLed();
  saveLedState();
}

void cycleLedColor() {
  if (LED_CATALOG_COUNT <= 0) return;
  int nextIdx = ledColorIndex;
  if (nextIdx < 0 || nextIdx >= LED_CATALOG_COUNT) {
    nextIdx = 0;
  } else {
    nextIdx = (nextIdx + 1) % LED_CATALOG_COUNT;
  }
  ledOn = true;
  setLedColor(LED_CATALOG[nextIdx][0], LED_CATALOG[nextIdx][1], LED_CATALOG[nextIdx][2], nextIdx);
}

String ledColorHex() {
  char hex[8];
  snprintf(hex, sizeof(hex), "#%02X%02X%02X", ledR, ledG, ledB);
  return String(hex);
}

bool parseHexColor(const String& s, uint8_t& r, uint8_t& g, uint8_t& b) {
  if (s.length() != 7 || s[0] != '#') return false;
  auto hex2 = [&](char c) -> int {
    if (c >= '0' && c <= '9') return c - '0';
    if (c >= 'a' && c <= 'f') return c - 'a' + 10;
    if (c >= 'A' && c <= 'F') return c - 'A' + 10;
    return -1;
  };
  int v[6];
  for (int i = 0; i < 6; i++) {
    v[i] = hex2(s[i + 1]);
    if (v[i] < 0) return false;
  }
  r = (v[0] << 4) | v[1];
  g = (v[2] << 4) | v[3];
  b = (v[4] << 4) | v[5];
  return true;
}

bool reportLedState(const char* source) {
  if (!ensureWiFiConnected()) return false;

  HTTPClient http;
  http.begin(serverUrl("/api/led"));
  http.setTimeout(2000);
  http.addHeader("Content-Type", "application/json");

  JsonDocument doc;
  doc["on"] = ledOn;
  doc["brightness"] = ledBrightness;
  doc["color"] = ledColorHex();
  doc["colorIndex"] = ledColorIndex;
  doc["ledOrder"] = ledOrder;
  doc["source"] = source ? source : "esp";

  String payload;
  serializeJson(doc, payload);

  int code = http.POST(payload);
  http.end();
  if (code >= 200 && code < 300) {
    lastLedSyncMs = millis();
    return true;
  }
  return false;
}

bool refreshLedFromServer() {
  if (!ensureWiFiConnected()) return false;

  HTTPClient http;
  http.begin(serverUrl("/api/led"));
  http.setTimeout(2500);
  int code = http.GET();
  if (code != 200) {
    http.end();
    return false;
  }

  String body = http.getString();
  http.end();

  JsonDocument doc;
  if (deserializeJson(doc, body)) return false;

  bool newOn = doc["on"] | ledOn;
  int newBrightness = doc["brightness"] | int(ledBrightness);
  if (newBrightness < 0) newBrightness = 0;
  if (newBrightness > 255) newBrightness = 255;

  String colorHex = String(doc["color"] | "");
  uint8_t nr = ledR, ng = ledG, nb = ledB;
  bool colorChanged = false;
  if (colorHex.length() == 7) {
    uint8_t tr, tg, tb;
    if (parseHexColor(colorHex, tr, tg, tb)) {
      nr = tr; ng = tg; nb = tb;
      colorChanged = true;
    }
  }

  int newIdx = doc["colorIndex"] | ledColorIndex;
  if (newIdx < -1 || newIdx >= LED_CATALOG_COUNT) newIdx = -1;

  String newOrder = String(doc["ledOrder"] | doc["led_order"] | ledOrder);
  newOrder.toUpperCase();
  if (!(newOrder == "RGB" || newOrder == "GRB" || newOrder == "BRG" || newOrder == "BGR" || newOrder == "RBG" || newOrder == "GBR")) {
    newOrder = ledOrder;
  }

  bool changed = false;
  if (newOn != ledOn) { ledOn = newOn; changed = true; }
  if (uint8_t(newBrightness) != ledBrightness) { ledBrightness = uint8_t(newBrightness); changed = true; }
  if (newIdx != ledColorIndex) { ledColorIndex = newIdx; changed = true; }
  if (newOrder != ledOrder) { ledOrder = newOrder; changed = true; }
  if (colorChanged && (nr != ledR || ng != ledG || nb != ledB)) {
    ledR = nr; ledG = ng; ledB = nb; changed = true;
  }

  if (changed) {
    applyLed();
    saveLedState();
  }
  return true;
}

void saveMotorState() {
  prefs.putBool("mEn", motorEnabled);
  prefs.putInt("mPH", servoHochformatPulse);
  prefs.putInt("mPQ", servoQuerformatPulse);
  prefs.putUInt("mDel", servoMoveDelayMs);
}

bool refreshMotorFromServer() {
  if (!ensureWiFiConnected()) return false;

  HTTPClient http;
  http.begin(serverUrl("/api/motor"));
  http.setTimeout(2500);
  int code = http.GET();
  if (code != 200) {
    http.end();
    return false;
  }

  String body = http.getString();
  http.end();

  JsonDocument doc;
  if (deserializeJson(doc, body)) return false;

  bool newEnabled = doc["enabled"] | motorEnabled;

  int newPortrait = doc["portraitPulse"] | servoHochformatPulse;
  if (newPortrait < 500) newPortrait = 500;
  if (newPortrait > 8000) newPortrait = 8000;

  int newLandscape = doc["landscapePulse"] | servoQuerformatPulse;
  if (newLandscape < 500) newLandscape = 500;
  if (newLandscape > 8000) newLandscape = 8000;

  int newDelay = doc["moveDelayMs"] | int(servoMoveDelayMs);
  if (newDelay < 120) newDelay = 120;
  if (newDelay > 5000) newDelay = 5000;

  bool changed = false;
  if (newEnabled != motorEnabled) { motorEnabled = newEnabled; changed = true; }
  if (newPortrait != servoHochformatPulse) { servoHochformatPulse = newPortrait; changed = true; }
  if (newLandscape != servoQuerformatPulse) { servoQuerformatPulse = newLandscape; changed = true; }
  if (uint16_t(newDelay) != servoMoveDelayMs) { servoMoveDelayMs = uint16_t(newDelay); changed = true; }
  if (changed) saveMotorState();

  String cmdToken = String(doc["commandToken"] | "");
  String cmdOrientation = String(doc["commandOrientation"] | "");
  cmdOrientation.toLowerCase();
  if (cmdToken.length() && cmdToken != lastMotorCommandToken) {
    lastMotorCommandToken = cmdToken;
    if (motorEnabled) {
      if (cmdOrientation == "portrait") {
        Serial.println("Motor-Test: Hochformat");
        servoMove(servoHochformatPulse);
      } else if (cmdOrientation == "landscape") {
        Serial.println("Motor-Test: Querformat");
        servoMove(servoQuerformatPulse);
      }
    }
  }

  return true;
}

// Servo auf Position fahren und dann Signal abschalten (kein Zittern)
void servoMove(int position) {
  if (!motorEnabled) return;
  int target = position;
  if (target < 500) target = 500;
  if (target > 8000) target = 8000;

  int from = currentServoPulse;
  if (from < 500 || from > 8000) from = target;

  int speedRef = int(servoMoveDelayMs);
  if (speedRef < 120) speedRef = 120;
  if (speedRef > 5000) speedRef = 5000;

  // Schrittweise fahren (sichtbarer Speed-Unterschied)
  // Wichtig: Servos reagieren in ~20ms Frames. Zu kurze Pausen => kaum Bewegung.
  // klein/schnell -> größere Puls-Sprünge + kürzere Pausen
  // groß/langsam -> kleinere Puls-Sprünge + längere Pausen
  int pulseStep = map(speedRef, 120, 5000, 320, 80);
  int stepPauseMs = map(speedRef, 120, 5000, 20, 45);
  int finalHoldMs = map(speedRef, 120, 5000, 180, 420);
  if (pulseStep < 20) pulseStep = 20;
  if (stepPauseMs < 20) stepPauseMs = 20;
  if (finalHoldMs < 120) finalHoldMs = 120;

  if (target == from) {
    ledcWrite(SERVO_PIN, target);
    delay(finalHoldMs);
    ledcWrite(SERVO_PIN, 0);
    currentServoPulse = target;
    return;
  }

  int dir = (target > from) ? 1 : -1;
  int pulse = from;

  while (true) {
    int nextPulse = pulse + dir * pulseStep;
    if ((dir > 0 && nextPulse >= target) || (dir < 0 && nextPulse <= target)) {
      nextPulse = target;
    }

    ledcWrite(SERVO_PIN, nextPulse);
    pulse = nextPulse;

    if (pulse == target) break;
    delay(stepPauseMs);
  }

  delay(finalHoldMs);
  ledcWrite(SERVO_PIN, 0); // Signal aus = kein Brummen
  currentServoPulse = target;
}

int jpegDraw(JPEGDRAW* pDraw) {
  tft.pushImage(pDraw->x, pDraw->y, pDraw->iWidth, pDraw->iHeight, pDraw->pPixels);
  return 1;
}

void showStatus(const char* msg, uint16_t color) {
  tft.fillScreen(TFT_BLACK);
  tft.setTextColor(color);
  tft.setTextSize(2);
  tft.setCursor(5, tft.height() / 2 - 10);
  tft.print(msg);
}

// Dateiliste vom Server holen
bool refreshFileList() {
  HTTPClient http;
  http.begin(serverUrl("/list"));
  http.setTimeout(8000);
  int code = http.GET();
  if (code != 200) { http.end(); return false; }
  String body = http.getString();
  http.end();

  JsonDocument doc;
  if (deserializeJson(doc, body)) return false;

  JsonArray arr = doc["files"].as<JsonArray>();
  fileCount = 0;
  for (JsonVariant v : arr) {
    if (fileCount >= 200) break;
    fileList[fileCount].name      = v["name"].as<String>();
    fileList[fileCount].landscape = String(v["orientation"].as<String>()) == "landscape";
    fileCount++;
  }
  Serial.println("Dateien: " + String(fileCount));
  return fileCount > 0;
}

bool reportFrameState(const String& filename, bool isLandscape, int idx, int count) {
  HTTPClient http;
  http.begin(serverUrl("/api/frame-state"));
  http.setTimeout(2000);
  http.addHeader("Content-Type", "application/json");

  JsonDocument doc;
  doc["filename"] = filename;
  doc["orientation"] = isLandscape ? "landscape" : "portrait";
  doc["index"] = idx;
  doc["count"] = count;

  String payload;
  serializeJson(doc, payload);

  int code = http.POST(payload);
  http.end();
  return code >= 200 && code < 300;
}

void showImage(int idx) {
  if (idx < 0 || idx >= fileCount) return;
  String filename = fileList[idx].name;
  bool   isLandscape = fileList[idx].landscape;

  // Servo + Display Rotation automatisch setzen
  int newRotation = isLandscape ? 1 : 0;
  if (newRotation != currentRotation) {
    // Erst Servo drehen, dann Bild laden
    Serial.println(isLandscape ? "Servo → Querformat" : "Servo → Hochformat");
    servoMove(isLandscape ? servoQuerformatPulse : servoHochformatPulse);
  }
  tft.setRotation(newRotation);
  currentRotation = newRotation;

  String url = serverUrl("/") + filename;
  Serial.println("Lade [" + String(idx+1) + "/" + String(fileCount) + "]: " + filename);

  // Bildnummer anzeigen während geladen wird
  tft.fillScreen(TFT_BLACK);
  tft.setTextColor(TFT_WHITE);
  tft.setTextSize(2);
  tft.setCursor(5, tft.height()/2 - 20);
  tft.print("Lade...");
  tft.setCursor(5, tft.height()/2 + 5);
  tft.setTextSize(1);
  tft.printf("%d / %d", idx+1, fileCount);

  HTTPClient http;
  http.begin(url);
  http.setTimeout(15000);
  int code = http.GET();
  if (code != 200) {
    http.end();
    showStatus("HTTP Fehler!", TFT_RED);
    return;
  }

  const size_t MAX_JPEG_SIZE = 400000;
  int size = http.getSize();
  if (size > (int)MAX_JPEG_SIZE) {
    http.end();
    showStatus("Groesse Fehler!", TFT_YELLOW);
    return;
  }

  if (jpegBuf) { free(jpegBuf); jpegBuf = nullptr; jpegLen = 0; }

  size_t capacity = (size > 0) ? (size_t)size : 16384;
  if (capacity > MAX_JPEG_SIZE) capacity = MAX_JPEG_SIZE;
  jpegBuf = (uint8_t*)malloc(capacity);
  if (!jpegBuf) {
    http.end();
    showStatus("RAM voll!", TFT_RED);
    return;
  }

  WiFiClient* stream = http.getStreamPtr();
  size_t got = 0;
  unsigned long t = millis();
  while (millis() - t < 15000 && got < MAX_JPEG_SIZE) {
    if (size > 0 && got >= (size_t)size) break;

    int avail = stream->available();
    if (avail <= 0) {
      if (!stream->connected()) break;
      delay(2);
      continue;
    }

    size_t want = (size_t)avail;
    if (size > 0) {
      size_t remaining = (size_t)size - got;
      if (want > remaining) want = remaining;
    }
    if (want > (MAX_JPEG_SIZE - got)) want = MAX_JPEG_SIZE - got;
    if (want == 0) break;

    if (got + want > capacity) {
      size_t newCapacity = capacity;
      while (newCapacity < got + want && newCapacity < MAX_JPEG_SIZE) {
        size_t doubled = newCapacity * 2;
        newCapacity = (doubled > MAX_JPEG_SIZE) ? MAX_JPEG_SIZE : doubled;
      }
      if (newCapacity < got + want) break;

      uint8_t* bigger = (uint8_t*)realloc(jpegBuf, newCapacity);
      if (!bigger) {
        http.end();
        free(jpegBuf);
        jpegBuf = nullptr;
        jpegLen = 0;
        showStatus("RAM voll!", TFT_RED);
        return;
      }
      jpegBuf = bigger;
      capacity = newCapacity;
    }

    int r = stream->readBytes(jpegBuf + got, want);
    if (r > 0) {
      got += (size_t)r;
      t = millis();
    } else {
      delay(1);
    }
  }
  http.end();

  jpegLen = got;
  if (got == 0 || got > MAX_JPEG_SIZE || (size > 0 && got < (size_t)size)) {
    showStatus("Download Fehler!", TFT_RED);
    return;
  }

  tft.fillScreen(TFT_BLACK);
  if (jpeg.openRAM(jpegBuf, jpegLen, jpegDraw)) {
    jpeg.setPixelType(RGB565_BIG_ENDIAN);
    int offX = max(0, (int)(tft.width()  - jpeg.getWidth())  / 2);
    int offY = max(0, (int)(tft.height() - jpeg.getHeight()) / 2);
    jpeg.decode(offX, offY, 0);
    jpeg.close();

    // Kleiner Bildnummer-Indikator unten rechts
    tft.setTextColor(0x2104); // sehr dunkelgrau
    tft.setTextSize(1);
    tft.setCursor(tft.width() - 32, tft.height() - 10);
    tft.printf("%d/%d", idx+1, fileCount);

    // Server mitteilen, was aktuell wirklich angezeigt wird
    if (!reportFrameState(filename, isLandscape, idx, fileCount)) {
      Serial.println("Frame-State Report fehlgeschlagen");
    }
  } else {
    showStatus("JPEG Fehler!", TFT_RED);
  }
}

bool refreshSettingsFromServer() {
  HTTPClient http;
  http.begin(serverUrl("/api/config"));
  http.setTimeout(5000);
  int code = http.GET();
  if (code != 200) { http.end(); return false; }

  String body = http.getString();
  http.end();

  JsonDocument doc;
  if (deserializeJson(doc, body)) return false;

  unsigned long newMs = doc["refreshMs"] | DEFAULT_REFRESH_MS;
  // Schutz: nicht kleiner als 10s, nicht größer als 24h
  if (newMs < 10000UL) newMs = 10000UL;
  if (newMs > 24UL * 60UL * 60UL * 1000UL) newMs = 24UL * 60UL * 60UL * 1000UL;

  if (newMs != refreshMs) {
    refreshMs = newMs;
    Serial.println("Neues Refresh-Intervall: " + String(refreshMs / 1000UL) + "s");
  }
  return true;
}


void showUploadProgress(const String& phase, int progress, const String& filename) {
  if (progress < 0) progress = 0;
  if (progress > 100) progress = 100;

  tft.fillScreen(TFT_BLACK);
  tft.setTextColor(TFT_CYAN);
  tft.setTextSize(2);
  tft.setCursor(5, 35);
  tft.print("Upload...");

  tft.setTextColor(TFT_WHITE);
  tft.setTextSize(1);
  tft.setCursor(5, 65);
  tft.print(filename.length() ? filename.substring(0, 28) : String("Datei"));

  int barX = 10;
  int barY = tft.height() / 2;
  int barW = tft.width() - 20;
  int barH = 18;

  tft.drawRect(barX, barY, barW, barH, TFT_WHITE);
  int fillW = (barW - 2) * progress / 100;
  if (fillW > 0) tft.fillRect(barX + 1, barY + 1, fillW, barH - 2, TFT_GREEN);

  tft.setTextSize(2);
  tft.setCursor(5, barY + 26);
  tft.printf("%d%%", progress);

  tft.setTextSize(1);
  tft.setCursor(5, barY + 52);
  if (phase == "done") tft.print("Upload fertig");
  else if (phase == "error") tft.print("Upload Fehler");
  else tft.print("Lade...");
}

bool pollUploadStatus() {
  HTTPClient http;
  http.begin(serverUrl("/api/upload-status"));
  http.setTimeout(2500);
  int code = http.GET();
  if (code != 200) {
    http.end();
    // Falls Status-API kurz spinnt: Upload-Overlay nicht dauerhaft einfrieren
    if (uploadUiVisible) {
      uploadUiVisible = false;
      lastUploadProgress = -1;
      lastUploadPhase = "idle";
    }
    return false;
  }

  String body = http.getString();
  http.end();

  JsonDocument doc;
  if (deserializeJson(doc, body)) {
    if (uploadUiVisible) {
      uploadUiVisible = false;
      lastUploadProgress = -1;
      lastUploadPhase = "idle";
    }
    return false;
  }

  bool show = doc["show"] | false;
  int progress = doc["progress"] | 0;
  String phase = String(doc["phase"] | "idle");
  String filename = String(doc["filename"] | "");

  if (show) {
    if (!uploadUiVisible || progress != lastUploadProgress || phase != lastUploadPhase) {
      showUploadProgress(phase, progress, filename);
      lastUploadProgress = progress;
      lastUploadPhase = phase;
    }
    uploadUiVisible = true;
    return true;
  }

  if (uploadUiVisible) {
    uploadUiVisible = false;
    lastUploadProgress = -1;
    lastUploadPhase = "idle";

    if (ensureWiFiConnected()) {
      refreshSettingsFromServer();
      if (refreshFileList() && fileCount > 0) {
        currentIdx = fileCount - 1;
        showImage(currentIdx);
      }
    }
  }

  return false;
}

void setup() {
  Serial.begin(115200);
  delay(500);

  pinMode(BUTTON_PIN, INPUT_PULLUP);
  pinMode(SIDE_BUTTON_PIN, INPUT_PULLUP);
  attachInterrupt(BUTTON_PIN, bootButtonISR, CHANGE);

  prefs.begin("muffi", false);
  loadNetworkConfigFromPrefs();
  lastWlanSyncToken = prefs.getString("wlanTok", "");
  ledOn = prefs.getBool("ledOn", true);
  ledBrightness = prefs.getUChar("ledBri", 180);
  ledR = prefs.getUChar("ledR", 255);
  ledG = prefs.getUChar("ledG", 214);
  ledB = prefs.getUChar("ledB", 160);
  ledColorIndex = prefs.getInt("ledIdx", 0);
  ledOrder = prefs.getString("ledOrd", "GRB");
  motorEnabled = prefs.getBool("mEn", true);
  servoHochformatPulse = prefs.getInt("mPH", SERVO_HOCHFORMAT_DEFAULT);
  servoQuerformatPulse = prefs.getInt("mPQ", SERVO_QUERFORMAT_DEFAULT);
  uint32_t motorDelay = prefs.getUInt("mDel", SERVO_DELAY_MS_DEFAULT);
  if (servoHochformatPulse < 500) servoHochformatPulse = 500;
  if (servoHochformatPulse > 8000) servoHochformatPulse = 8000;
  if (servoQuerformatPulse < 500) servoQuerformatPulse = 500;
  if (servoQuerformatPulse > 8000) servoQuerformatPulse = 8000;
  if (motorDelay < 120) motorDelay = 120;
  if (motorDelay > 5000) motorDelay = 5000;
  servoMoveDelayMs = uint16_t(motorDelay);
  ledOrder.toUpperCase();
  if (!(ledOrder == "RGB" || ledOrder == "GRB" || ledOrder == "BRG" || ledOrder == "BGR" || ledOrder == "RBG" || ledOrder == "GBR")) {
    ledOrder = "GRB";
  }
  if (ledColorIndex < -1 || ledColorIndex >= LED_CATALOG_COUNT) ledColorIndex = -1;
  applyLed();

  // Servo initialisieren
  ledcAttach(SERVO_PIN, SERVO_FREQ, 16);
  currentServoPulse = servoHochformatPulse;
  servoMove(servoHochformatPulse); // Startposition = Hochformat
  delay(200);

  tft.init();
  tft.setRotation(0);
  tft.setBrightness(220);
  connectWiFi();
  fetchWlanConfigFromServer();

  showStatus("Lade Settings...", TFT_GREEN);
  if (!refreshSettingsFromServer()) {
    showStatus("Settings lokal", TFT_YELLOW);
    delay(300);
  }

  // LED-Config vom Server holen (Web <-> ESP synchron)
  refreshLedFromServer();
  reportLedState("esp-boot");
  refreshMotorFromServer();

  showStatus("Lade Liste...", TFT_GREEN);
  if (refreshFileList()) {
    currentIdx = fileCount - 1; // neuestes Bild zuerst
    showImage(currentIdx);
  } else {
    showStatus("Kein Foto!", TFT_YELLOW);
  }
}

void loop() {
  if (WiFi.status() == WL_CONNECTED && otaReady) {
    ArduinoOTA.handle();
  } else {
    ensureWiFiConnected();
  }

  if (WiFi.status() == WL_CONNECTED && millis() - lastWlanSyncMs > 60000UL) {
    lastWlanSyncMs = millis();
    fetchWlanConfigFromServer();
  }

  // Upload-Status vom Server pollen und auf dem Rahmen anzeigen
  if (millis() - lastUploadPollMs > 1200) {
    lastUploadPollMs = millis();
    if (ensureWiFiConnected()) {
      pollUploadStatus();
    }
  }

  // LED-Einstellungen vom Server holen
  if (millis() - lastLedPollMs > 2000) {
    lastLedPollMs = millis();
    refreshLedFromServer();
  }

  if (millis() - lastMotorPollMs > 2200) {
    lastMotorPollMs = millis();
    refreshMotorFromServer();
  }

  // Während Upload sichtbar ist: Auto-Slideshow pausieren
  if (uploadUiVisible) {
    delay(50);
    return;
  }

  // Wenn wir aktuell kein Foto haben: schneller nachfassen (alle 10s)
  if (fileCount == 0 && millis() - lastNoPhotoRetryMs > 10000) {
    lastNoPhotoRetryMs = millis();
    if (ensureWiFiConnected()) {
      refreshSettingsFromServer();
      if (refreshFileList() && fileCount > 0) {
        currentIdx = fileCount - 1;
        showImage(currentIdx);
      } else {
        showStatus("WLAN OK, kein Foto", TFT_YELLOW);
      }
    } else {
      showStatus("WLAN reconnect...", TFT_YELLOW);
    }
  }

  // Hauptbutton zuverlässig per ISR auswerten (erst nach Boot-Phase)
  if (!bootClickHandlingEnabled && millis() >= 600) {
    bootClickHandlingEnabled = true;
  }
  if (bootClickHandlingEnabled) {
    handleBootClicks();
  }

  // Seitentaste: Farbe weiter
  bool sideDown = (digitalRead(SIDE_BUTTON_PIN) == LOW);
  if (sideDown != sideBtnPressed && millis() - sideBtnLastEdgeMs > DEBOUNCE_MS) {
    sideBtnLastEdgeMs = millis();
    sideBtnPressed = sideDown;
    if (sideDown) {
      sideBtnPressMs = millis();
    } else {
      if (millis() - sideBtnPressMs < LONG_PRESS_MS) {
        Serial.println("Seitentaste: LED Farbe weiter");
        cycleLedColor();
        reportLedState("button-side");
      }
    }
  }

  // Automatisch anhand Server-Setting Liste neu laden
  if (millis() - lastRefresh > refreshMs) {
    lastRefresh = millis();
    if (!ensureWiFiConnected()) {
      showStatus("WLAN reconnect...", TFT_YELLOW);
      delay(100);
      return;
    }

    refreshSettingsFromServer();
    bool ok = refreshFileList();
    if (!ok || fileCount == 0) {
      showStatus("Kein Foto!", TFT_YELLOW);
      return;
    }

    // Immer weiterschalten im eingestellten Intervall
    if (currentIdx >= fileCount || currentIdx < 0) {
      currentIdx = 0;
    } else {
      currentIdx = (currentIdx + 1) % fileCount;
    }
    showImage(currentIdx);
  }

  delay(5);
}
