"""API FastAPI : protocole des terminaux + API d'administration + interface web."""
from __future__ import annotations

import hashlib
import io
import re
from datetime import datetime, timedelta
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import db, importers, render, scheduling

APP_DIR = Path(__file__).resolve().parent
FW_DIR = db.FW_DIR
DISPLAY_BYTES = render.W * render.H // 8

app = FastAPI(title="Hibou — affichage des salles", version="0.2.1")


# ============================================================ utilitaires

# Courbe LiPo approximative (mV -> %), calée sur la table de calibration Seeed (4,15 V = 100 %, 3,27 V = 0 %)
BATTERY_CURVE = [(4150, 100), (4060, 90), (3960, 80), (3850, 70), (3790, 60), (3750, 50),
                 (3710, 40), (3670, 30), (3620, 20), (3500, 10), (3270, 0)]


def battery_pct(mv: int | None) -> int | None:
    if mv is None or mv <= 0:
        return None
    if mv >= BATTERY_CURVE[0][0]:
        return 100
    for (v_hi, p_hi), (v_lo, p_lo) in zip(BATTERY_CURVE, BATTERY_CURVE[1:]):
        if v_lo <= mv <= v_hi:
            return round(p_lo + (p_hi - p_lo) * (mv - v_lo) / (v_hi - v_lo))
    return 0


def _int(v: str | None) -> int | None:
    try:
        return int(v) if v not in (None, "") else None
    except ValueError:
        return None


def norm_mac(mac: str) -> str:
    m = re.sub(r"[^0-9A-Fa-f]", "", mac or "").upper()
    if len(m) != 12:
        raise HTTPException(400, "MAC invalide")
    return ":".join(m[i:i + 2] for i in range(0, 12, 2))


def device_status(d: dict, now: datetime, settings: dict) -> str:
    if not d.get("last_seen"):
        return "jamais vu"
    if not d.get("next_wake"):
        return "en ligne"
    limit = datetime.fromisoformat(d["next_wake"]) + timedelta(minutes=int(settings.get("offline_after_min", "90")))
    return "en ligne" if now <= limit else "hors ligne"


def render_for_device(dev: dict, now: datetime, settings: dict, server_hint: str = ""):
    if not dev.get("room_code"):
        return render.render_unassigned(dev["mac"], dev.get("ip", ""), server_hint)
    room = db.query_one("SELECT * FROM rooms WHERE code = ?", (dev["room_code"],))
    if room is None:
        return render.render_unassigned(dev["mac"], dev.get("ip", ""), server_hint)
    st = scheduling.room_state(room["code"], now)
    low = dev.get("battery_pct") is not None and dev["battery_pct"] <= int(settings.get("low_battery_pct", "15"))
    return render.render_room(room["code"], room["name"], st, settings, room["message"], low_battery=low)


def png_response(img) -> Response:
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return Response(buf.getvalue(), media_type="image/png", headers={"Cache-Control": "no-store"})


# ============================================================ protocole terminal

@app.get("/api/v1/display")
def device_display(request: Request):
    """Appelé par chaque terminal à son réveil.

    En-têtes envoyés par le terminal : X-Device-MAC, X-FW-Version, X-Battery-mV, X-RSSI,
    X-IP, X-Wake-Reason (timer|button|power_on), X-Boot-Count, X-WiFi-ms, X-Fail-Count, If-None-Match.

    Réponse : 200 + bitmap brut 48 000 octets, ou 304 si l'écran affiche déjà la bonne image.
    Dans les deux cas : X-Sleep-Seconds (durée du prochain sommeil), éventuellement X-FW-URL.
    """
    h = request.headers
    mac = norm_mac(h.get("X-Device-MAC", ""))
    settings = db.get_settings()
    now = scheduling.now_local(settings)
    mv = _int(h.get("X-Battery-mV"))
    pct = battery_pct(mv)
    rssi = _int(h.get("X-RSSI"))
    wifi_ms = _int(h.get("X-WiFi-ms"))
    wake = h.get("X-Wake-Reason", "")
    fw = h.get("X-FW-Version", "")
    ip = h.get("X-IP") or (request.client.host if request.client else "")

    with db.tx() as conn:
        conn.execute("INSERT OR IGNORE INTO devices(mac, name) VALUES (?, '')", (mac,))
        conn.execute(
            """UPDATE devices SET ip=?, fw_version=?, battery_mv=?, battery_pct=?, rssi=?, wake_reason=?,
                   boot_count=?, wifi_ms=?, fail_count=?, last_seen=? WHERE mac=?""",
            (ip, fw, mv, pct, rssi, wake, _int(h.get("X-Boot-Count")), wifi_ms,
             _int(h.get("X-Fail-Count")), now.isoformat(), mac),
        )
    dev = db.query_one("SELECT * FROM devices WHERE mac = ?", (mac,))

    hint = str(request.base_url).rstrip("/")
    img = render_for_device(dev, now, settings, server_hint=hint)
    data = render.to_device_bytes(img)
    etag = render.etag_of(data)
    target, sleep_s = scheduling.compute_next_wake(dev.get("room_code"), now, settings)

    headers = {"X-Sleep-Seconds": str(sleep_s), "ETag": etag, "X-Server-Time": now.isoformat()}
    fwrow = db.query_one("SELECT * FROM firmware WHERE active = 1")
    if fwrow and fw and fwrow["version"] != fw:
        headers["X-FW-URL"] = f"/api/v1/firmware/{fwrow['version']}.bin"
        headers["X-FW-Version-Target"] = fwrow["version"]
        headers["X-FW-SHA256"] = fwrow["sha256"]

    client_etag = (h.get("If-None-Match") or "").strip('"')
    force = wake == "button" or dev["force_refresh"] or wake == "power_on"
    refreshed = force or client_etag != etag

    with db.tx() as conn:
        conn.execute(
            "INSERT INTO telemetry(mac, ts, battery_mv, battery_pct, rssi, wifi_ms, refreshed) VALUES (?,?,?,?,?,?,?)",
            (mac, now.isoformat(), mv, pct, rssi, wifi_ms, int(refreshed)),
        )
        conn.execute(
            "UPDATE devices SET next_wake=?, last_etag=?, force_refresh=0"
            + (", last_refresh=?, refresh_count=refresh_count+1" if refreshed else "")
            + " WHERE mac=?",
            (target.isoformat(), etag, now.isoformat(), mac) if refreshed else (target.isoformat(), etag, mac),
        )

    if not refreshed:
        return Response(status_code=304, headers=headers)
    headers["Content-Length"] = str(len(data))
    return Response(content=data, media_type="application/octet-stream", headers=headers)


@app.get("/api/v1/firmware/{version}.bin")
def firmware_download(version: str):
    row = db.query_one("SELECT * FROM firmware WHERE version = ?", (version,))
    if not row:
        raise HTTPException(404)
    return FileResponse(FW_DIR / row["filename"], media_type="application/octet-stream")


# ============================================================ API admin : salles & planning

class RoomIn(BaseModel):
    code: str
    name: str = ""
    building: str = ""
    message: str = ""


class RoomPatch(BaseModel):
    name: str | None = None
    building: str | None = None
    message: str | None = None


class EventIn(BaseModel):
    start: datetime
    end: datetime
    title: str = ""
    teacher: str = ""
    grp: str = ""


@app.get("/api/rooms")
def list_rooms():
    settings = db.get_settings()
    now = scheduling.now_local(settings)
    rooms = db.query(
        """SELECT r.*, (SELECT COUNT(*) FROM events e WHERE e.room_code = r.code AND e.end >= ?) AS upcoming,
                  (SELECT group_concat(mac) FROM devices d WHERE d.room_code = r.code) AS devices
           FROM rooms r ORDER BY r.building, r.code""",
        (now.isoformat(),),
    )
    for r in rooms:
        st = scheduling.room_state(r["code"], now)
        r["today_count"] = len(st.slots)
        r["occupied"] = st.current is not None
        r["current"] = st.current.title if st.current else None
        r["devices"] = r["devices"].split(",") if r["devices"] else []
    return rooms


@app.post("/api/rooms")
def create_room(room: RoomIn):
    code = room.code.strip()
    if not code:
        raise HTTPException(400, "code requis")
    try:
        with db.tx() as conn:
            conn.execute("INSERT INTO rooms(code, name, building, message) VALUES (?,?,?,?)",
                         (code, room.name, room.building, room.message))
    except Exception:
        raise HTTPException(409, "cette salle existe déjà")
    return {"ok": True}


@app.patch("/api/rooms/{code}")
def update_room(code: str, p: RoomPatch):
    fields = {k: v for k, v in p.model_dump().items() if v is not None}
    if fields:
        with db.tx() as conn:
            conn.execute(f"UPDATE rooms SET {', '.join(f'{k}=?' for k in fields)} WHERE code=?", (*fields.values(), code))
            # Le contenu change : on force le rafraîchissement au prochain réveil
            conn.execute("UPDATE devices SET force_refresh = 1 WHERE room_code = ?", (code,))
    return {"ok": True}


@app.delete("/api/rooms/{code}")
def delete_room(code: str):
    with db.tx() as conn:
        conn.execute("DELETE FROM rooms WHERE code = ?", (code,))
    return {"ok": True}


@app.get("/api/rooms/{code}/events")
def room_events(code: str, day: str | None = None, days: int = 1):
    settings = db.get_settings()
    d0 = datetime.fromisoformat(day).date() if day else scheduling.now_local(settings).date()
    lo = datetime.combine(d0, datetime.min.time())
    hi = lo + timedelta(days=max(1, min(days, 60)))
    return db.query("SELECT * FROM events WHERE room_code=? AND start < ? AND end > ? ORDER BY start",
                    (code, hi.isoformat(), lo.isoformat()))


@app.post("/api/rooms/{code}/events")
def add_event(code: str, e: EventIn):
    if e.end <= e.start:
        raise HTTPException(400, "la fin doit être après le début")
    if not db.query_one("SELECT 1 FROM rooms WHERE code=?", (code,)):
        raise HTTPException(404, "salle inconnue")
    with db.tx() as conn:
        conn.execute("INSERT INTO events(room_code, start, end, title, teacher, grp, source) VALUES (?,?,?,?,?,?, 'manuel')",
                     (code, e.start.replace(tzinfo=None).isoformat(timespec="minutes"),
                      e.end.replace(tzinfo=None).isoformat(timespec="minutes"), e.title, e.teacher, e.grp))
    return {"ok": True}


@app.delete("/api/events/{event_id}")
def delete_event(event_id: int):
    with db.tx() as conn:
        conn.execute("DELETE FROM events WHERE id = ?", (event_id,))
    return {"ok": True}


@app.delete("/api/events")
def purge_events():
    with db.tx() as conn:
        conn.execute("DELETE FROM events")
    return {"ok": True}


@app.get("/api/rooms/{code}/preview.png")
def room_preview(code: str, at: str | None = None):
    settings = db.get_settings()
    room = db.query_one("SELECT * FROM rooms WHERE code = ?", (code,))
    if not room:
        raise HTTPException(404)
    now = datetime.fromisoformat(at) if at else scheduling.now_local(settings)
    st = scheduling.room_state(code, now)
    return png_response(render.render_room(room["code"], room["name"], st, settings, room["message"]))


@app.post("/api/import")
async def import_timetable(file: UploadFile = File(...), mode: str = Form("replace_range"),
                           create_rooms: bool = Form(True)):
    if mode not in ("replace_range", "append", "replace_all"):
        raise HTTPException(400, "mode invalide")
    data = await file.read()
    try:
        rep = importers.import_file(file.filename or "import", data, mode=mode, create_rooms=create_rooms)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:  # fichier ICS corrompu, encodage…
        raise HTTPException(400, f"Fichier illisible : {e}")
    with db.tx() as conn:
        conn.execute("UPDATE devices SET force_refresh = 1 WHERE room_code IS NOT NULL")
    return rep.as_dict()


# ============================================================ API admin : écrans

class DevicePatch(BaseModel):
    name: str | None = None
    room_code: str | None = None
    notes: str | None = None


@app.get("/api/devices")
def list_devices():
    settings = db.get_settings()
    now = scheduling.now_local(settings)
    devs = db.query("SELECT d.*, r.name AS room_name FROM devices d LEFT JOIN rooms r ON r.code = d.room_code ORDER BY d.room_code IS NULL, d.room_code, d.mac")
    for d in devs:
        d["status"] = device_status(d, now, settings)
        d["low_battery"] = d["battery_pct"] is not None and d["battery_pct"] <= int(settings.get("low_battery_pct", "15"))
    return devs


@app.get("/api/devices/{mac}")
def get_device(mac: str):
    mac = norm_mac(mac)
    d = db.query_one("SELECT * FROM devices WHERE mac = ?", (mac,))
    if not d:
        raise HTTPException(404)
    settings = db.get_settings()
    d["status"] = device_status(d, scheduling.now_local(settings), settings)
    return d


@app.patch("/api/devices/{mac}")
def update_device(mac: str, p: DevicePatch):
    mac = norm_mac(mac)
    fields = p.model_dump(exclude_unset=True)
    if "room_code" in fields:
        rc = (fields["room_code"] or "").strip() or None
        if rc and not db.query_one("SELECT 1 FROM rooms WHERE code=?", (rc,)):
            raise HTTPException(404, "salle inconnue")
        fields["room_code"] = rc
        fields["force_refresh"] = 1
    with db.tx() as conn:
        # Permet de pré-enregistrer un écran (provision.py --name/--room) avant son premier réveil
        conn.execute("INSERT OR IGNORE INTO devices(mac, name) VALUES (?, '')", (mac,))
        if fields:
            conn.execute(f"UPDATE devices SET {', '.join(f'{k}=?' for k in fields)} WHERE mac=?", (*fields.values(), mac))
    return {"ok": True}


@app.delete("/api/devices/{mac}")
def delete_device(mac: str):
    with db.tx() as conn:
        conn.execute("DELETE FROM devices WHERE mac = ?", (norm_mac(mac),))
    return {"ok": True}


@app.post("/api/devices/{mac}/refresh")
def force_refresh(mac: str):
    with db.tx() as conn:
        conn.execute("UPDATE devices SET force_refresh = 1 WHERE mac = ?", (norm_mac(mac),))
    return {"ok": True, "note": "Rafraîchissement au prochain réveil (ou appui sur le bouton blanc de droite)."}


@app.get("/api/devices/{mac}/telemetry")
def device_telemetry(mac: str, days: int = 14):
    mac = norm_mac(mac)
    settings = db.get_settings()
    since = (scheduling.now_local(settings) - timedelta(days=max(1, min(days, 120)))).isoformat()
    return db.query("SELECT ts, battery_mv, battery_pct, rssi, wifi_ms, refreshed FROM telemetry WHERE mac=? AND ts>=? ORDER BY ts",
                    (mac, since))


@app.get("/api/devices/{mac}/preview.png")
def device_preview(mac: str, request: Request):
    mac = norm_mac(mac)
    d = db.query_one("SELECT * FROM devices WHERE mac = ?", (mac,))
    if not d:
        raise HTTPException(404)
    settings = db.get_settings()
    return png_response(render_for_device(d, scheduling.now_local(settings), settings, str(request.base_url).rstrip("/")))


# ============================================================ API admin : firmware OTA

@app.get("/api/firmware")
def list_firmware():
    return db.query("SELECT * FROM firmware ORDER BY uploaded_at DESC")


@app.post("/api/firmware")
async def upload_firmware(file: UploadFile = File(...), version: str = Form(...),
                          factory: UploadFile | None = File(None), notes: str = Form("")):
    """`file` = firmware.bin (image applicative, pour l'OTA).
    `factory` (optionnel) = image fusionnée bootloader+partitions+app, pour le premier flash depuis le navigateur."""
    version = version.strip()
    if not re.fullmatch(r"[0-9A-Za-z._-]{1,31}", version):
        raise HTTPException(400, "version invalide (lettres, chiffres, . _ - ; 31 car. max)")
    data = await file.read()
    if len(data) < 64 * 1024 or data[0] != 0xE9:
        raise HTTPException(400, "ce fichier ne ressemble pas à un firmware ESP32 (firmware.bin attendu)")
    fdata = await factory.read() if factory is not None else None
    if fdata is not None and (len(fdata) < 0x10000 + len(data) or fdata[0] != 0xE9):
        raise HTTPException(400, "image factory invalide (factory.bin fusionné attendu, offset 0x0)")
    FW_DIR.mkdir(parents=True, exist_ok=True)
    fn = f"fw-{version}.bin"
    (FW_DIR / fn).write_bytes(data)
    ffn = None
    if fdata is not None:
        ffn = f"fw-{version}-factory.bin"
        (FW_DIR / ffn).write_bytes(fdata)
    with db.tx() as conn:
        prev = conn.execute("SELECT active FROM firmware WHERE version=?", (version,)).fetchone()
        conn.execute(
            "INSERT OR REPLACE INTO firmware(version, filename, factory_filename, notes, size, sha256, active, uploaded_at)"
            " VALUES (?,?,?,?,?,?,?, datetime('now'))",
            (version, fn, ffn, notes, len(data), hashlib.sha256(data).hexdigest(), prev[0] if prev else 0),
        )
    return {"ok": True, "size": len(data), "factory": ffn is not None}


@app.get("/api/v1/firmware/{version}/factory.bin")
def firmware_factory(version: str):
    row = db.query_one("SELECT * FROM firmware WHERE version = ?", (version,))
    if not row or not row["factory_filename"]:
        raise HTTPException(404, "pas d'image factory pour cette version")
    return FileResponse(FW_DIR / row["factory_filename"], media_type="application/octet-stream")


@app.get("/api/v1/firmware/{version}/manifest.json")
def firmware_manifest(version: str):
    """Manifeste ESP Web Tools (flash depuis le navigateur)."""
    row = db.query_one("SELECT * FROM firmware WHERE version = ?", (version,))
    if not row or not row["factory_filename"]:
        raise HTTPException(404)
    return {
        "name": "Hibou — reTerminal E1001",
        "version": version,
        "new_install_prompt_erase": True,
        "builds": [{"chipFamily": "ESP32-S3", "parts": [{"path": "factory.bin", "offset": 0}]}],
    }


@app.post("/api/firmware/{version}/activate")
def activate_firmware(version: str):
    if not db.query_one("SELECT 1 FROM firmware WHERE version=?", (version,)):
        raise HTTPException(404)
    with db.tx() as conn:
        conn.execute("UPDATE firmware SET active = (version = ?)", (version,))
    return {"ok": True}


@app.post("/api/firmware/deactivate")
def deactivate_firmware():
    with db.tx() as conn:
        conn.execute("UPDATE firmware SET active = 0")
    return {"ok": True}


@app.delete("/api/firmware/{version}")
def delete_firmware(version: str):
    row = db.query_one("SELECT * FROM firmware WHERE version=?", (version,))
    if row:
        (FW_DIR / row["filename"]).unlink(missing_ok=True)
        if row["factory_filename"]:
            (FW_DIR / row["factory_filename"]).unlink(missing_ok=True)
        with db.tx() as conn:
            conn.execute("DELETE FROM firmware WHERE version=?", (version,))
    return {"ok": True}


# ============================================================ réglages & vue d'ensemble

@app.get("/api/settings")
def get_settings():
    return db.get_settings()


@app.put("/api/settings")
def put_settings(values: dict[str, str]):
    allowed = set(db.DEFAULT_SETTINGS)
    bad = set(values) - allowed
    if bad:
        raise HTTPException(400, f"clés inconnues : {sorted(bad)}")
    for k in ("day_start", "day_end"):
        if k in values:
            try:
                scheduling.parse_hhmm(values[k])
            except Exception:
                raise HTTPException(400, f"{k} : format HH:MM attendu")
    if "timezone" in values:
        from zoneinfo import ZoneInfo
        try:
            ZoneInfo(values["timezone"])
        except Exception:
            raise HTTPException(400, "fuseau horaire inconnu")
    with db.tx() as conn:
        for k, v in values.items():
            conn.execute("INSERT OR REPLACE INTO settings(key, value) VALUES (?, ?)", (k, str(v)))
        conn.execute("UPDATE devices SET force_refresh = 1")
    return db.get_settings()


@app.get("/api/overview")
def overview():
    devs = list_devices()
    return {
        "now": scheduling.now_local().isoformat(),
        "rooms": db.query_one("SELECT COUNT(*) AS n FROM rooms")["n"],
        "events": db.query_one("SELECT COUNT(*) AS n FROM events")["n"],
        "devices": len(devs),
        "online": sum(d["status"] == "en ligne" for d in devs),
        "offline": sum(d["status"] == "hors ligne" for d in devs),
        "unassigned": sum(not d["room_code"] for d in devs),
        "low_battery": sum(bool(d["low_battery"]) for d in devs),
    }


# ============================================================ mise en service

@app.get("/api/provision/next-ip")
def next_free_ip():
    """Prochaine IP libre dans la plage prov_ip_first..prov_ip_last (réglages)."""
    import ipaddress
    s = db.get_settings()
    if not s.get("prov_ip_first") or not s.get("prov_ip_last"):
        return {"ip": None, "reason": "plage non configurée (Réglages)"}
    try:
        first, last = ipaddress.ip_address(s["prov_ip_first"]), ipaddress.ip_address(s["prov_ip_last"])
    except ValueError:
        return {"ip": None, "reason": "plage invalide"}
    used = {d["ip"] for d in db.query("SELECT ip FROM devices WHERE ip != ''")}
    ip = first
    while ip <= last:
        if str(ip) not in used:
            return {"ip": str(ip), "reason": None}
        ip += 1
    return {"ip": None, "reason": "plage épuisée"}


@app.post("/api/provision/{mac}")
def provisioned(mac: str, p: DevicePatch, ip: str = ""):
    """Appelé par la page de mise en service après configuration USB : enregistre l'écran et son IP."""
    mac = norm_mac(mac)
    update_device(mac, p)
    if ip:
        with db.tx() as conn:
            conn.execute("UPDATE devices SET ip = ? WHERE mac = ?", (ip, mac))
    return {"ok": True, "mac": mac}


# ============================================================ santé

@app.get("/healthz", include_in_schema=False)
def healthz():
    db.query_one("SELECT 1 AS ok")
    return {"status": "ok", "version": app.version}


# ============================================================ interface web

app.mount("/static", StaticFiles(directory=APP_DIR / "static"), name="static")


@app.get("/", include_in_schema=False)
def index():
    return FileResponse(APP_DIR / "static" / "index.html")


@app.get("/flash", include_in_schema=False)
def flash_page():
    return FileResponse(APP_DIR / "static" / "flash.html")


@app.exception_handler(ValueError)
def value_error(_, exc: ValueError):
    return JSONResponse({"detail": str(exc)}, status_code=400)
