import os
import tempfile
from datetime import datetime
from pathlib import Path

import pytest

TMP = tempfile.mkdtemp()
os.environ["EPAPER_DB"] = str(Path(TMP) / "test.db")

from fastapi.testclient import TestClient  # noqa: E402

from app import db, main, scheduling  # noqa: E402

CSV = """date;debut;fin;salle;matiere;enseignant;groupe
16/11/2026;08:00;10:00;A101;Réseaux IP avancés;M. Martin;TD1
16/11/2026;10:15;12:15;A101;Cybersécurité — Pentest;Mme Leroy;TP A
16/11/2026;13:30;15:30;A101;Anglais technique;Mme Brown;TD2
16/11/2026;08:00;12:00;B204, Labo Réseaux;Projet tutoré;M. Bernard;Promo 2A
""".encode()

ICS = b"""BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//t//t//FR
BEGIN:VEVENT
UID:1@t
DTSTAMP:20261101T000000Z
DTSTART;TZID=Europe/Paris:20261116T160000
DTEND;TZID=Europe/Paris:20261116T180000
SUMMARY:Cryptographie appliquee
LOCATION:A101
ORGANIZER;CN=Mme Laurent:mailto:x@y.z
DESCRIPTION:TD3\\n(Export\xc3\xa9 le:01/11/2026)
END:VEVENT
BEGIN:VEVENT
UID:2@t
DTSTAMP:20261101T000000Z
DTSTART:20261117T070000Z
DTEND:20261117T090000Z
SUMMARY:Systemes Linux
LOCATION:A101
END:VEVENT
END:VCALENDAR
"""

MAC = "AA:BB:CC:DD:EE:01"


@pytest.fixture(scope="module")
def client():
    return TestClient(main.app)


def fixed_now(monkeypatch, iso):
    monkeypatch.setattr(scheduling, "now_local", lambda settings=None: datetime.fromisoformat(iso))


def test_import_csv_and_ics(client):
    r = client.post("/api/import", files={"file": ("edt.csv", CSV)}, data={"mode": "replace_all"})
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["events"] == 5  # 3 + 1 cours dupliqué dans 2 salles
    assert set(j["rooms_created"]) == {"A101", "B204", "Labo Réseaux"}

    r = client.post("/api/import", files={"file": ("edt.ics", ICS)}, data={"mode": "append"})
    assert r.status_code == 200, r.text
    assert r.json()["events"] == 2
    ev = client.get("/api/rooms/A101/events", params={"day": "2026-11-17"}).json()
    assert ev[0]["start"] == "2026-11-17T08:00:00"  # UTC -> Europe/Paris
    ev = client.get("/api/rooms/A101/events", params={"day": "2026-11-16"}).json()
    assert len(ev) == 4
    assert ev[-1]["teacher"] == "Mme Laurent" and ev[-1]["grp"] == "TD3"


def test_unknown_device_gets_pairing_screen(client, monkeypatch):
    fixed_now(monkeypatch, "2026-11-16T09:00:00")
    h = {"X-Device-MAC": MAC, "X-Battery-mV": "3900", "X-RSSI": "-61", "X-FW-Version": "0.1.0",
         "X-Wake-Reason": "power_on", "X-IP": "10.20.0.31"}
    r = client.get("/api/v1/display", headers=h)
    assert r.status_code == 200
    assert len(r.content) == 48000
    assert int(r.headers["X-Sleep-Seconds"]) == 300
    d = client.get(f"/api/devices/{MAC}").json()
    assert d["battery_pct"] == 75 and d["ip"] == "10.20.0.31"


def test_assigned_device_and_304(client, monkeypatch):
    assert client.patch(f"/api/devices/{MAC}", json={"room_code": "A101", "name": "Porte A101"}).status_code == 200
    fixed_now(monkeypatch, "2026-11-16T09:00:00")
    h = {"X-Device-MAC": MAC, "X-Battery-mV": "3890", "X-RSSI": "-60", "X-FW-Version": "0.1.0", "X-Wake-Reason": "timer"}
    r = client.get("/api/v1/display", headers=h)
    assert r.status_code == 200 and len(r.content) == 48000
    etag = r.headers["ETag"]
    # Prochain réveil : fin du cours à 10h00 (+10 s), cap 30 min -> 9h30
    assert int(r.headers["X-Sleep-Seconds"]) == 1800  # cap de 30 min, avant la fin du cours à 10h

    # Réveil de sécurité, rien n'a changé -> 304
    fixed_now(monkeypatch, "2026-11-16T09:30:05")
    r = client.get("/api/v1/display", headers={**h, "If-None-Match": etag})
    assert r.status_code == 304
    assert int(r.headers["X-Sleep-Seconds"]) == 1800  # cap 30 min (10:00:05) avant la frontière 10:00:10

    # Bouton -> rafraîchissement forcé même si identique
    r = client.get("/api/v1/display", headers={**h, "If-None-Match": etag, "X-Wake-Reason": "button"})
    assert r.status_code == 200

    # Changement de créneau -> nouvelle image
    fixed_now(monkeypatch, "2026-11-16T10:00:10")
    r = client.get("/api/v1/display", headers={**h, "If-None-Match": etag})
    assert r.status_code == 200 and r.headers["ETag"] != etag


def test_night_and_weekend_sleep(monkeypatch):
    s = db.get_settings()
    # Vendredi 20 novembre 2026, 20h -> lundi 23 à 7h30 (≈ 59,5 h, compensée de 3 %)
    target, secs = scheduling.compute_next_wake("A101", datetime(2026, 11, 20, 20, 0), s)
    assert target == datetime(2026, 11, 23, 7, 30)
    assert secs == int((target - datetime(2026, 11, 20, 20, 0)).total_seconds() * 0.97)
    # Lundi 16, 15h31 : prochain cours à 16h00 -> réveil 16:00:10
    target, _ = scheduling.compute_next_wake("A101", datetime(2026, 11, 16, 15, 31), s)
    assert target == datetime(2026, 11, 16, 16, 0, 10)
    # Lundi 16, 18h05 : dernier cours fini à 18h -> demain 7h30
    target, _ = scheduling.compute_next_wake("A101", datetime(2026, 11, 16, 18, 5), s)
    assert target == datetime(2026, 11, 17, 7, 30)


def test_previews_and_ui(client):
    r = client.get("/api/rooms/A101/preview.png", params={"at": "2026-11-16T11:00"})
    assert r.status_code == 200 and r.headers["content-type"] == "image/png"
    out = Path(TMP)
    (out / "preview_occupee.png").write_bytes(r.content)
    (out / "preview_libre.png").write_bytes(client.get("/api/rooms/A101/preview.png", params={"at": "2026-11-16T12:40"}).content)
    (out / "preview_vide.png").write_bytes(client.get("/api/rooms/B204/preview.png", params={"at": "2026-11-18T09:00"}).content)
    assert client.get("/").status_code == 200
    ov = client.get("/api/overview").json()
    assert ov["devices"] == 1 and ov["rooms"] == 3
    print("previews in", out)


def test_firmware_ota_header(client, monkeypatch):
    fixed_now(monkeypatch, "2026-11-16T09:00:00")
    fake = bytes([0xE9]) + b"\x00" * (70 * 1024)
    assert client.post("/api/firmware", files={"file": ("firmware.bin", fake)}, data={"version": "0.2.0"}).status_code == 200
    assert client.post("/api/firmware/0.2.0/activate").status_code == 200
    r = client.get("/api/v1/display", headers={"X-Device-MAC": MAC, "X-FW-Version": "0.1.0", "X-Wake-Reason": "timer"})
    assert r.headers["X-FW-URL"] == "/api/v1/firmware/0.2.0.bin"
    assert len(client.get("/api/v1/firmware/0.2.0.bin").content) == len(fake)


def test_preregister_device(client):
    mac = "AA:BB:CC:DD:EE:42"
    assert client.patch(f"/api/devices/{mac}", json={"name": "Porte B204", "room_code": "B204"}).status_code == 200
    d = client.get(f"/api/devices/{mac}").json()
    assert d["room_code"] == "B204" and d["status"] == "jamais vu"


def test_real_firmware_upload(client):
    fw = Path(__file__).resolve().parents[2] / "firmware/.pio/build/reterminal_e1001/firmware.bin"
    if not fw.exists():
        pytest.skip("firmware non compilé")
    r = client.post("/api/firmware", files={"file": ("firmware.bin", fw.read_bytes())}, data={"version": "0.1.1"})
    assert r.status_code == 200, r.text


def test_factory_manifest_and_provisioning(client):
    app_bin = bytes([0xE9]) + b"\x01" * (80 * 1024)
    factory = bytes([0xE9]) + b"\x00" * (0x10000 - 1) + app_bin
    r = client.post("/api/firmware", files={"file": ("firmware.bin", app_bin), "factory": ("factory.bin", factory)},
                    data={"version": "0.3.0"})
    assert r.status_code == 200 and r.json()["factory"] is True
    m = client.get("/api/v1/firmware/0.3.0/manifest.json").json()
    assert m["builds"][0]["chipFamily"] == "ESP32-S3"
    assert client.get("/api/v1/firmware/0.3.0/factory.bin").content == factory
    assert client.get("/healthz").json()["status"] == "ok"

    client.put("/api/settings", json={"prov_ip_first": "10.20.0.31", "prov_ip_last": "10.20.0.33"})
    first = client.get("/api/provision/next-ip").json()["ip"]
    assert first == "10.20.0.31"
    r = client.post("/api/provision/AA:BB:CC:DD:EE:50", params={"ip": first}, json={"name": "Porte X", "room_code": "A101"})
    assert r.status_code == 200
    assert client.get("/api/provision/next-ip").json()["ip"] == "10.20.0.32"
    assert client.get("/flash").status_code == 200


def test_cli_backup(tmp_path):
    from app import cli
    dest = tmp_path / "b.db"
    cli.main(["backup", str(dest)])
    assert dest.stat().st_size > 0
