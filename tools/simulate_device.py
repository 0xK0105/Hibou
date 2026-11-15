#!/usr/bin/env python3
"""Simule un ou plusieurs terminaux reTerminal E1001 (sans matériel).

Fait exactement ce que fait le firmware : appelle /api/v1/display avec la
télémétrie, et enregistre l'image reçue en PNG.

    python3 tools/simulate_device.py --server http://localhost:8000 --count 3
    python3 tools/simulate_device.py --mac AA:BB:CC:00:00:01 --battery 3650 --button
"""
import argparse
import random
import urllib.error
import urllib.request
from pathlib import Path

W, H = 800, 480


def save_png(data: bytes, path: Path) -> None:
    try:
        from PIL import Image
    except ImportError:
        path.with_suffix(".bin").write_bytes(data)
        return
    # bit 1 = noir côté terminal ; Pillow '1' : bit 1 = blanc -> inversion
    img = Image.frombytes("1", (W, H), bytes(b ^ 0xFF for b in data))
    img.save(path)


def wake(server: str, mac: str, battery: int, rssi: int, fw: str, reason: str, etag: str, ip: str, out: Path):
    req = urllib.request.Request(server.rstrip("/") + "/api/v1/display", headers={
        "X-Device-MAC": mac, "X-Battery-mV": str(battery), "X-RSSI": str(rssi), "X-FW-Version": fw,
        "X-Wake-Reason": reason, "X-IP": ip, "X-Boot-Count": "1", "X-WiFi-ms": str(random.randint(250, 900)),
        "X-Fail-Count": "0", **({"If-None-Match": etag} if etag else {}),
    })
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            data = r.read()
            hdr = r.headers
            status = r.status
    except urllib.error.HTTPError as e:
        if e.code != 304:
            raise
        data, hdr, status = b"", e.headers, 304
    msg = f"{mac}  HTTP {status}  sommeil={hdr.get('X-Sleep-Seconds')} s"
    if hdr.get("X-FW-URL"):
        msg += f"  OTA -> {hdr.get('X-FW-URL')}"
    if status == 200:
        assert len(data) == W * H // 8, f"taille inattendue : {len(data)}"
        p = out / f"{mac.replace(':', '')}.png"
        save_png(data, p)
        msg += f"  image -> {p}"
    print(msg)
    return hdr.get("ETag", "")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--server", default="http://localhost:8000")
    ap.add_argument("--mac", help="MAC d'un terminal précis")
    ap.add_argument("--count", type=int, default=1, help="nombre de terminaux simulés (MAC générées)")
    ap.add_argument("--battery", type=int, help="tension batterie en mV (défaut : aléatoire)")
    ap.add_argument("--fw", default="0.1.0")
    ap.add_argument("--button", action="store_true", help="simule un appui sur le bouton (rafraîchissement forcé)")
    ap.add_argument("--etag", default="", help="ETag de l'image affichée (pour tester le 304)")
    ap.add_argument("--out", default="sim_out")
    a = ap.parse_args()

    out = Path(a.out)
    out.mkdir(exist_ok=True)
    macs = [a.mac] if a.mac else [f"AA:BB:CC:00:00:{i:02X}" for i in range(1, a.count + 1)]
    for i, mac in enumerate(macs):
        wake(a.server, mac, a.battery or random.randint(3550, 4150), random.randint(-82, -48), a.fw,
             "button" if a.button else "timer", a.etag, f"10.20.0.{31 + i}", out)


if __name__ == "__main__":
    main()
