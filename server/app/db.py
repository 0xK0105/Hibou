"""Couche SQLite minimaliste (stdlib uniquement)."""
from __future__ import annotations

import os
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path

DATA_DIR = Path(os.environ.get("EPAPER_DATA_DIR", Path(__file__).resolve().parent.parent / "data"))
DB_PATH = Path(os.environ.get("EPAPER_DB", DATA_DIR / "epaper.db"))
FW_DIR = DATA_DIR / "firmware"

SCHEMA = """
CREATE TABLE IF NOT EXISTS rooms (
    code        TEXT PRIMARY KEY,          -- identifiant tel qu'il apparaît dans l'EDT (ex: "A101")
    name        TEXT NOT NULL DEFAULT '',  -- libellé affiché (ex: "Salle de TP réseaux")
    building    TEXT NOT NULL DEFAULT '',
    message     TEXT NOT NULL DEFAULT '',  -- bandeau ponctuel (ex: "Salle fermée pour travaux")
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    room_code   TEXT NOT NULL REFERENCES rooms(code) ON DELETE CASCADE,
    start       TEXT NOT NULL,             -- ISO 8601 heure locale (naïve, fuseau = settings.timezone)
    end         TEXT NOT NULL,
    title       TEXT NOT NULL DEFAULT '',
    teacher     TEXT NOT NULL DEFAULT '',
    grp         TEXT NOT NULL DEFAULT '',
    source      TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_events_room_start ON events(room_code, start);

CREATE TABLE IF NOT EXISTS devices (
    mac           TEXT PRIMARY KEY,
    name          TEXT NOT NULL DEFAULT '',
    room_code     TEXT REFERENCES rooms(code) ON DELETE SET NULL,
    ip            TEXT NOT NULL DEFAULT '',
    fw_version    TEXT NOT NULL DEFAULT '',
    battery_mv    INTEGER,
    battery_pct   INTEGER,
    rssi          INTEGER,
    wake_reason   TEXT NOT NULL DEFAULT '',
    boot_count    INTEGER,
    wifi_ms       INTEGER,                 -- durée de connexion Wi-Fi mesurée par le terminal
    fail_count    INTEGER,                 -- échecs consécutifs avant ce réveil
    last_seen     TEXT,
    next_wake     TEXT,
    last_etag     TEXT NOT NULL DEFAULT '',
    last_refresh  TEXT,                    -- dernier vrai rafraîchissement de l'écran
    refresh_count INTEGER NOT NULL DEFAULT 0,
    force_refresh INTEGER NOT NULL DEFAULT 0,
    notes         TEXT NOT NULL DEFAULT '',
    created_at    TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS telemetry (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    mac         TEXT NOT NULL REFERENCES devices(mac) ON DELETE CASCADE,
    ts          TEXT NOT NULL,
    battery_mv  INTEGER,
    battery_pct INTEGER,
    rssi        INTEGER,
    wifi_ms     INTEGER,
    refreshed   INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_telemetry_mac_ts ON telemetry(mac, ts);

CREATE TABLE IF NOT EXISTS firmware (
    version     TEXT PRIMARY KEY,
    filename    TEXT NOT NULL,             -- image applicative (OTA)
    factory_filename TEXT,                 -- image complète fusionnée (premier flash via navigateur)
    notes       TEXT NOT NULL DEFAULT '',
    size        INTEGER NOT NULL,
    sha256      TEXT NOT NULL,
    active      INTEGER NOT NULL DEFAULT 0, -- 1 = version poussée aux terminaux
    uploaded_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""

DEFAULT_SETTINGS = {
    "timezone": "Europe/Paris",
    "day_start": "07:30",        # premier réveil de la journée
    "day_end": "19:00",          # après cette heure, l'écran dort jusqu'au lendemain
    "active_days": "1,2,3,4,5",  # jours ouvrés (1 = lundi … 7 = dimanche)
    "max_awake_interval": "30",  # minutes max entre deux réveils en journée (prise en compte des modifs)
    "unassigned_sleep": "300",   # secondes de sommeil pour un écran non affecté
    "low_battery_pct": "15",
    "offline_after_min": "90",   # au-delà de ce délai après next_wake, l'écran est marqué hors ligne
    "site_name": "",
    "prov_ip_first": "",         # plage d'IP statiques pour la mise en service (suggestion automatique)
    "prov_ip_last": "",
}

# Valeurs initiales surchargeables par variables d'environnement au premier démarrage :
#   EPAPER_DEFAULT_SITE_NAME="Lycée X", EPAPER_DEFAULT_DAY_START=08:00, …
for _k in list(DEFAULT_SETTINGS):
    _env = os.environ.get(f"EPAPER_DEFAULT_{_k.upper()}")
    if _env is not None:
        DEFAULT_SETTINGS[_k] = _env
if os.environ.get("TZ") and "EPAPER_DEFAULT_TIMEZONE" not in os.environ:
    DEFAULT_SETTINGS["timezone"] = os.environ["TZ"]

MIGRATIONS = [
    "ALTER TABLE firmware ADD COLUMN factory_filename TEXT",
    "ALTER TABLE firmware ADD COLUMN notes TEXT NOT NULL DEFAULT ''",
]

_lock = threading.Lock()


def connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


_conn: sqlite3.Connection | None = None


def get_conn() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        _conn = connect()
        init(_conn)
    return _conn


def reset_connection() -> None:
    """Utilisé par les tests pour repartir d'une base vierge."""
    global _conn
    if _conn is not None:
        _conn.close()
    _conn = None


def init(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    for m in MIGRATIONS:  # bases créées par une version antérieure
        try:
            conn.execute(m)
        except sqlite3.OperationalError:
            pass
    for k, v in DEFAULT_SETTINGS.items():
        conn.execute("INSERT OR IGNORE INTO settings(key, value) VALUES (?, ?)", (k, v))
    conn.commit()


@contextmanager
def tx():
    conn = get_conn()
    with _lock:
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise


def query(sql: str, params: tuple | dict = ()) -> list[dict]:
    with _lock:
        return [dict(r) for r in get_conn().execute(sql, params).fetchall()]


def query_one(sql: str, params: tuple | dict = ()) -> dict | None:
    rows = query(sql, params)
    return rows[0] if rows else None


def get_settings() -> dict[str, str]:
    return {r["key"]: r["value"] for r in query("SELECT key, value FROM settings")}
