#!/usr/bin/env python3
"""Configure un reTerminal E1001 en USB (IP statique, Wi-Fi, serveur) après le flash.

Le firmware écoute le port série pendant 3 s à chaque démarrage à froid. Ce script
redémarre la carte (lignes DTR/RTS), ouvre la session, écrit la config en NVS, puis
peut pré-enregistrer l'écran sur le serveur (nom + salle) pour qu'il affiche
directement la bonne salle à son premier réveil.

    pip install pyserial
    python3 tools/provision.py --port /dev/ttyUSB0 --ip 10.20.0.31 --name "Porte A101" --room A101
    python3 tools/provision.py --port COM5 --get           # lire la config actuelle

Les valeurs communes (SSID, mot de passe, passerelle…) peuvent être compilées dans
firmware/include/config_local.h, ou passées ici (--ssid, --password, --server…).
"""
import argparse
import json
import sys
import time
import urllib.request

try:
    import serial
except ImportError:
    sys.exit("pyserial manquant : pip install pyserial")


def reset_board(ser):
    # Séquence de reset type esptool : EN bas puis haut, GPIO0 laissé haut (démarrage normal)
    ser.dtr = False
    ser.rts = True
    time.sleep(0.15)
    ser.rts = False


def read_until(ser, prefix, timeout):
    deadline = time.time() + timeout
    while time.time() < deadline:
        line = ser.readline().decode(errors="replace").strip()
        if line:
            print("  <", line)
        if line.startswith(prefix):
            return line
    return None


def cmd(ser, text, expect=("OK", "ERR", "CFG", "INFO"), timeout=3):
    print("  >", text if not text.startswith("SET pass=") else "SET pass=***")
    ser.write((text + "\n").encode())
    deadline = time.time() + timeout
    while time.time() < deadline:
        line = ser.readline().decode(errors="replace").strip()
        if not line:
            continue
        print("  <", line)
        if line.startswith(expect):
            if line.startswith("ERR"):
                raise SystemExit(f"Erreur renvoyée par l'écran : {line}")
            return line
    raise SystemExit(f"Pas de réponse à « {text} »")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", required=True, help="/dev/ttyUSB0, /dev/ttyACM0, COM5…")
    ap.add_argument("--ip", help="IP statique de cet écran (vide = DHCP)")
    ap.add_argument("--gw"); ap.add_argument("--mask"); ap.add_argument("--dns")
    ap.add_argument("--ssid"); ap.add_argument("--password")
    ap.add_argument("--server", help="URL du serveur, ex : http://10.20.0.10:8000")
    ap.add_argument("--dhcp", action="store_true", help="repasser en DHCP")
    ap.add_argument("--clear", action="store_true", help="effacer toute la config (retour aux valeurs compilées)")
    ap.add_argument("--get", action="store_true", help="afficher la config et quitter")
    ap.add_argument("--name", help="nom de l'écran à pré-enregistrer sur le serveur")
    ap.add_argument("--room", help="salle à affecter sur le serveur (code, ex : A101)")
    ap.add_argument("--no-reset", action="store_true", help="ne pas redémarrer la carte (appuyez sur reset vous-même)")
    a = ap.parse_args()

    ser = serial.Serial(a.port, 115200, timeout=0.2)
    if not a.no_reset:
        reset_board(ser)
    else:
        print("Appuyez sur le bouton reset de l'écran…")

    line = read_until(ser, "PROVISION READY", timeout=8 if not a.no_reset else 30)
    if not line:
        sys.exit("L'écran n'a pas annoncé « PROVISION READY ». Vérifiez le port, ou relancez avec --no-reset "
                 "et appuyez sur reset.")
    mac = line.split("mac=")[1].split()[0]
    cmd(ser, "INFO")  # ouvre la session (le firmware prolonge alors la fenêtre à 60 s)

    if a.clear:
        cmd(ser, "CLEAR")
    sets = {
        "ssid": a.ssid, "pass": a.password, "server": a.server,
        "ip": "" if a.dhcp else a.ip, "gw": a.gw, "mask": a.mask, "dns": a.dns,
    }
    if not a.get:
        for k, v in sets.items():
            if v is not None:
                cmd(ser, f"SET {k}={v}")
    cfg_line = cmd(ser, "GET", expect=("CFG",))
    cmd(ser, "DONE")
    ser.close()

    print(f"\nÉcran {mac} configuré.")
    if a.name or a.room:
        server = a.server or dict(kv.split("=", 1) for kv in cfg_line[4:].split() if "=" in kv).get("server")
        body = {k: v for k, v in (("name", a.name), ("room_code", a.room)) if v}
        req = urllib.request.Request(f"{server.rstrip('/')}/api/devices/{mac}", method="PATCH",
                                     data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
        try:
            urllib.request.urlopen(req, timeout=5).read()
            print(f"Pré-enregistré sur {server} : {body}")
        except Exception as e:
            print(f"(Pré-enregistrement sur le serveur impossible : {e} — affectez-le depuis l'interface.)")


if __name__ == "__main__":
    main()
