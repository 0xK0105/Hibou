"""Commandes d'exploitation, utilisables dans le conteneur :

    docker compose exec server python -m app.cli backup
    docker compose exec server python -m app.cli import /data/imports/edt.ics --mode replace_range
    docker compose exec server python -m app.cli info
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

from . import db, importers


def cmd_backup(a) -> None:
    dest = Path(a.dest) if a.dest else db.DATA_DIR / "backups" / f"epaper-{datetime.now():%Y%m%d-%H%M%S}.db"
    dest.parent.mkdir(parents=True, exist_ok=True)
    src = db.get_conn()
    out = sqlite3.connect(dest)
    with out:
        src.backup(out)  # sauvegarde cohérente, même serveur en marche
    out.close()
    print(dest)
    if a.keep:
        backups = sorted(dest.parent.glob("epaper-*.db"))
        for old in backups[:-a.keep]:
            old.unlink()
            print(f"supprimé : {old}")


def cmd_import(a) -> None:
    p = Path(a.file)
    rep = importers.import_file(p.name, p.read_bytes(), mode=a.mode, create_rooms=not a.no_create_rooms)
    d = rep.as_dict()
    print(f"{d['events']} cours importés, salles créées : {d['rooms_created'] or 'aucune'}, "
          f"lignes ignorées : {d['skipped_count']}")
    for s in d["skipped"]:
        print("  -", s)
    with db.tx() as conn:
        conn.execute("UPDATE devices SET force_refresh = 1 WHERE room_code IS NOT NULL")


def cmd_info(_a) -> None:
    print(f"Base     : {db.DB_PATH}")
    print(f"Firmware : {db.FW_DIR}")
    for t in ("rooms", "events", "devices", "telemetry", "firmware"):
        print(f"{t:10s}: {db.query_one(f'SELECT COUNT(*) AS n FROM {t}')['n']}")


def cmd_purge_telemetry(a) -> None:
    with db.tx() as conn:
        n = conn.execute("DELETE FROM telemetry WHERE ts < datetime('now', ?)", (f"-{a.days} days",)).rowcount
    print(f"{n} mesures supprimées (plus de {a.days} jours)")


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(prog="python -m app.cli")
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("backup", help="sauvegarde à chaud de la base SQLite")
    b.add_argument("dest", nargs="?", help="fichier de destination (défaut : /data/backups/epaper-<date>.db)")
    b.add_argument("--keep", type=int, default=0, help="ne conserver que les N dernières sauvegardes")
    b.set_defaults(func=cmd_backup)
    i = sub.add_parser("import", help="importer un emploi du temps (ICS/CSV)")
    i.add_argument("file")
    i.add_argument("--mode", default="replace_range", choices=["replace_range", "append", "replace_all"])
    i.add_argument("--no-create-rooms", action="store_true")
    i.set_defaults(func=cmd_import)
    sub.add_parser("info", help="état de la base").set_defaults(func=cmd_info)
    p = sub.add_parser("purge-telemetry", help="supprimer l'historique de télémétrie ancien")
    p.add_argument("--days", type=int, default=180)
    p.set_defaults(func=cmd_purge_telemetry)
    a = ap.parse_args(argv)
    a.func(a)


if __name__ == "__main__":
    sys.exit(main())
