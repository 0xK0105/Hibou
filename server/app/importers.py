"""Import d'emplois du temps : iCalendar (.ics) et CSV.

Chaque cours est rattaché à une salle via son champ « salle » (LOCATION en ICS).
Un cours dans plusieurs salles ("A101, A102") est dupliqué dans chacune.
"""
from __future__ import annotations

import csv
import io
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from . import db


@dataclass
class ParsedEvent:
    room: str
    start: datetime
    end: datetime
    title: str = ""
    teacher: str = ""
    grp: str = ""


@dataclass
class ImportReport:
    events: int = 0
    rooms_created: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    range_start: str | None = None
    range_end: str | None = None

    def as_dict(self) -> dict:
        return {
            "events": self.events,
            "rooms_created": self.rooms_created,
            "skipped_count": len(self.skipped),
            "skipped": self.skipped[:30],
            "range": [self.range_start, self.range_end],
        }


ROOM_SPLIT = re.compile(r"\s*[,;/|]\s*")


def split_rooms(location: str) -> list[str]:
    return [re.sub(r"\s+", " ", r).strip() for r in ROOM_SPLIT.split(location or "") if r.strip()]


# --------------------------------------------------------------------------- ICS

def parse_ics(data: bytes, tz_name: str) -> tuple[list[ParsedEvent], list[str]]:
    import icalendar
    import recurring_ical_events

    tz = ZoneInfo(tz_name)
    cal = icalendar.Calendar.from_ical(data)
    today = date.today()
    occurrences = recurring_ical_events.of(cal).between(today - timedelta(days=60), today + timedelta(days=400))

    out, skipped = [], []
    for ev in occurrences:
        summary = str(ev.get("SUMMARY", "")).strip()
        dtstart = ev.get("DTSTART").dt
        dtend_prop = ev.get("DTEND")
        if not isinstance(dtstart, datetime):
            skipped.append(f"« {summary} » : évènement sur la journée entière ignoré")
            continue
        dtend = dtend_prop.dt if dtend_prop else dtstart + (ev.get("DURATION").dt if ev.get("DURATION") else timedelta(hours=1))

        def local(d: datetime) -> datetime:
            return (d.astimezone(tz) if d.tzinfo else d).replace(tzinfo=None, second=0, microsecond=0)

        rooms = split_rooms(str(ev.get("LOCATION", "")))
        if not rooms:
            skipped.append(f"« {summary} » le {local(dtstart):%d/%m %H:%M} : pas de salle (LOCATION vide)")
            continue

        teacher = ""
        org = ev.get("ORGANIZER")
        if org is not None and hasattr(org, "params"):
            teacher = str(org.params.get("CN", "")).strip()

        # ADE / Hyperplanning mettent souvent groupes et enseignants dans DESCRIPTION
        desc_lines = [l.strip() for l in str(ev.get("DESCRIPTION", "")).splitlines()]
        desc_lines = [l for l in desc_lines if l and not l.lower().startswith(("(export", "export", "(modifi"))]
        grp = " · ".join(desc_lines)[:80]

        for r in rooms:
            out.append(ParsedEvent(room=r, start=local(dtstart), end=local(dtend), title=summary, teacher=teacher, grp=grp))
    return out, skipped


# --------------------------------------------------------------------------- CSV

def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower().strip()
    return re.sub(r"[^a-z0-9]+", "_", s).strip("_")


ALIASES = {
    "date": {"date", "jour", "day"},
    "start": {"start", "debut", "heure_debut", "h_debut", "begin", "de", "dtstart", "start_time"},
    "end": {"end", "fin", "heure_fin", "h_fin", "a", "dtend", "end_time"},
    "room": {"room", "salle", "salles", "location", "lieu", "local"},
    "title": {"title", "matiere", "cours", "summary", "intitule", "libelle", "module", "enseignement"},
    "teacher": {"teacher", "enseignant", "enseignants", "prof", "professeur", "intervenant", "formateur"},
    "grp": {"group", "groupe", "groupes", "classe", "promo", "promotion", "grp"},
}

DATE_FORMATS = ["%Y-%m-%d", "%d/%m/%Y", "%d/%m/%y", "%d-%m-%Y", "%d.%m.%Y"]
TIME_FORMATS = ["%H:%M", "%Hh%M", "%H:%M:%S", "%Hh"]


def _parse_date(s: str) -> date:
    for f in DATE_FORMATS:
        try:
            return datetime.strptime(s.strip(), f).date()
        except ValueError:
            pass
    raise ValueError(f"date illisible : {s!r}")


def _parse_time(s: str):
    s = s.strip().lower().replace(" ", "")
    for f in TIME_FORMATS:
        try:
            return datetime.strptime(s, f).time()
        except ValueError:
            pass
    raise ValueError(f"heure illisible : {s!r}")


def _parse_dt(value: str, day: date | None) -> datetime:
    value = value.strip()
    if day is None:
        # "2026-11-16 08:00" / "16/11/2026 08h00" / ISO "2026-11-16T08:00"
        value = value.replace("T", " ")
        d, _, t = value.partition(" ")
        return datetime.combine(_parse_date(d), _parse_time(t))
    return datetime.combine(day, _parse_time(value))


def parse_csv(data: bytes) -> tuple[list[ParsedEvent], list[str]]:
    text = data.decode("utf-8-sig", errors="replace")
    try:
        dialect = csv.Sniffer().sniff(text[:4096], delimiters=";,\t")
    except csv.Error:
        class dialect(csv.excel):  # noqa: N801
            delimiter = ";" if text.count(";") > text.count(",") else ","
    reader = csv.reader(io.StringIO(text), dialect)
    rows = list(reader)
    if not rows:
        return [], ["fichier vide"]

    header = [_norm(h) for h in rows[0]]
    col = {}
    for key, names in ALIASES.items():
        for i, h in enumerate(header):
            if h in names:
                col[key] = i
                break
    missing = [k for k in ("start", "end", "room") if k not in col]
    if missing:
        raise ValueError(
            "Colonnes manquantes : " + ", ".join(missing)
            + f". En-têtes trouvés : {rows[0]}. Attendu au minimum : date (optionnel), debut, fin, salle."
        )

    out, skipped = [], []
    for n, row in enumerate(rows[1:], start=2):
        if not any(c.strip() for c in row):
            continue
        get = lambda k: row[col[k]].strip() if k in col and col[k] < len(row) else ""
        try:
            day = _parse_date(get("date")) if get("date") else None
            start = _parse_dt(get("start"), day)
            end = _parse_dt(get("end"), day)
            if end <= start:
                raise ValueError("fin avant début")
        except ValueError as e:
            skipped.append(f"ligne {n} : {e}")
            continue
        rooms = split_rooms(get("room"))
        if not rooms:
            skipped.append(f"ligne {n} : pas de salle")
            continue
        for r in rooms:
            out.append(ParsedEvent(room=r, start=start, end=end, title=get("title"), teacher=get("teacher"), grp=get("grp")))
    return out, skipped


# --------------------------------------------------------------------------- écriture

def store(events: list[ParsedEvent], skipped: list[str], mode: str, source: str,
          create_rooms: bool = True) -> ImportReport:
    """mode = 'replace_range' (défaut) | 'append' | 'replace_all'."""
    rep = ImportReport(skipped=list(skipped))
    if not events:
        return rep

    known = {r["code"] for r in db.query("SELECT code FROM rooms")}
    known_ci = {c.lower(): c for c in known}

    with db.tx() as conn:
        resolved: list[tuple[str, ParsedEvent]] = []
        for e in events:
            code = known_ci.get(e.room.lower())
            if code is None:
                if not create_rooms:
                    rep.skipped.append(f"salle inconnue « {e.room} » ({e.title} {e.start:%d/%m %H:%M})")
                    continue
                conn.execute("INSERT INTO rooms(code, name) VALUES (?, '')", (e.room,))
                known_ci[e.room.lower()] = e.room
                rep.rooms_created.append(e.room)
                code = e.room
            resolved.append((code, e))

        if not resolved:
            return rep
        lo = min(e.start for _, e in resolved).date()
        hi = max(e.end for _, e in resolved).date() + timedelta(days=1)
        rep.range_start, rep.range_end = lo.isoformat(), (hi - timedelta(days=1)).isoformat()

        if mode == "replace_all":
            conn.execute("DELETE FROM events")
        elif mode == "replace_range":
            rooms = sorted({c for c, _ in resolved})
            q = ",".join("?" * len(rooms))
            conn.execute(
                f"DELETE FROM events WHERE room_code IN ({q}) AND start >= ? AND start < ?",
                (*rooms, lo.isoformat(), hi.isoformat()),
            )

        seen = set()
        for code, e in resolved:
            key = (code, e.start, e.end, e.title)
            if key in seen:
                continue
            seen.add(key)
            conn.execute(
                "INSERT INTO events(room_code, start, end, title, teacher, grp, source) VALUES (?,?,?,?,?,?,?)",
                (code, e.start.isoformat(), e.end.isoformat(), e.title, e.teacher, e.grp, source),
            )
            rep.events += 1
    return rep


def import_file(filename: str, data: bytes, mode: str = "replace_range", create_rooms: bool = True) -> ImportReport:
    settings = db.get_settings()
    lower = filename.lower()
    if lower.endswith((".ics", ".ical", ".ifb")) or data.lstrip()[:15].upper().startswith(b"BEGIN:VCALENDAR"):
        events, skipped = parse_ics(data, settings.get("timezone", "Europe/Paris"))
    else:
        events, skipped = parse_csv(data)
    return store(events, skipped, mode, source=filename, create_rooms=create_rooms)
