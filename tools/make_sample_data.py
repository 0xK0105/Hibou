#!/usr/bin/env python3
"""Génère un emploi du temps d'exemple (ICS + CSV) pour la semaine en cours (ou la suivante le week-end),
afin de tester l'import et le rendu sans données réelles.

    python3 tools/make_sample_data.py   ->  tools/sample_data/edt_exemple.ics / .csv
"""
from datetime import date, datetime, timedelta
from pathlib import Path
import random

OUT = Path(__file__).resolve().parent / "sample_data"
ROOMS = ["A101", "A102", "B204", "Labo Réseaux"]
COURSES = [
    ("Réseaux IP avancés", "M. Martin"), ("Cybersécurité — Pentest", "Mme Leroy"),
    ("Anglais technique", "Mme Brown"), ("Systèmes Linux", "M. Garcia"),
    ("Télécoms — Radio", "M. Petit"), ("Mathématiques du signal", "Mme Roux"),
    ("Projet tutoré", "M. Bernard"), ("Cryptographie appliquée", "Mme Laurent"),
]
SLOTS = [("08:00", "10:00"), ("10:15", "12:15"), ("13:30", "15:30"), ("15:45", "17:45")]
GROUPS = ["TD1", "TD2", "TP A", "TP B", "Promo 2A"]


def week_dates():
    today = date.today()
    monday = today - timedelta(days=today.weekday())
    if today.weekday() >= 5:  # le week-end, on génère la semaine suivante
        monday += timedelta(days=7)
    return [monday + timedelta(days=i) for i in range(5)]


def main():
    random.seed(42)
    OUT.mkdir(exist_ok=True)
    rows = []
    for d in week_dates():
        for room in ROOMS:
            for a, b in SLOTS:
                if random.random() < 0.65:
                    title, teacher = random.choice(COURSES)
                    rows.append((d, a, b, room, title, teacher, random.choice(GROUPS)))

    with open(OUT / "edt_exemple.csv", "w", encoding="utf-8") as f:
        f.write("date;debut;fin;salle;matiere;enseignant;groupe\n")
        for d, a, b, room, title, teacher, grp in rows:
            f.write(f"{d:%d/%m/%Y};{a};{b};{room};{title};{teacher};{grp}\n")

    ics = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//exemple//edt//FR"]
    for i, (d, a, b, room, title, teacher, grp) in enumerate(rows):
        s = datetime.combine(d, datetime.strptime(a, "%H:%M").time())
        e = datetime.combine(d, datetime.strptime(b, "%H:%M").time())
        ics += [
            "BEGIN:VEVENT", f"UID:exemple-{i}@edt", f"DTSTAMP:{datetime.now():%Y%m%dT%H%M%S}",
            f"DTSTART;TZID=Europe/Paris:{s:%Y%m%dT%H%M%S}", f"DTEND;TZID=Europe/Paris:{e:%Y%m%dT%H%M%S}",
            f"SUMMARY:{title}", f"LOCATION:{room}", f"ORGANIZER;CN={teacher}:mailto:noreply@example.org",
            f"DESCRIPTION:{grp}\\n(Exporté le:{date.today():%d/%m/%Y})", "END:VEVENT",
        ]
    ics.append("END:VCALENDAR")
    (OUT / "edt_exemple.ics").write_text("\r\n".join(ics) + "\r\n", encoding="utf-8")
    print(f"{len(rows)} cours générés dans {OUT}")


if __name__ == "__main__":
    main()
