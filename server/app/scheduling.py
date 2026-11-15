"""Calcul de l'état d'une salle et de l'heure du prochain réveil d'un écran.

Principe : l'écran ne se réveille que lorsque ce qu'il affiche doit changer
(début/fin de cours), avec un réveil de sécurité toutes les `max_awake_interval`
minutes en journée pour prendre en compte les modifications de dernière minute.
La nuit et les jours non ouvrés, il dort jusqu'au prochain `day_start`.

L'horloge RTC interne de l'ESP32 peut dériver de quelques % en deep sleep : pour
les longs sommeils on vise volontairement un peu tôt. Si l'écran se réveille trop
tôt, le serveur répond 304 (pas de rafraîchissement) avec le temps restant —
le système se corrige tout seul.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from . import db

LOOKAHEAD = timedelta(seconds=60)   # on rend l'état "dans 60 s" pour absorber les réveils un peu précoces
WAKE_MARGIN = timedelta(seconds=10) # on se réveille 10 s après une frontière de créneau
MIN_SLEEP = 60
MAX_SLEEP = 3 * 24 * 3600
DRIFT_COMPENSATION = 0.97           # on vise 3 % plus tôt sur les longs sommeils
DRIFT_THRESHOLD = 1800


@dataclass
class Slot:
    start: datetime
    end: datetime
    title: str
    teacher: str = ""
    grp: str = ""

    @classmethod
    def from_row(cls, r: dict) -> "Slot":
        return cls(
            start=datetime.fromisoformat(r["start"]),
            end=datetime.fromisoformat(r["end"]),
            title=r.get("title") or "",
            teacher=r.get("teacher") or "",
            grp=r.get("grp") or "",
        )


@dataclass
class RoomState:
    now: datetime
    day: date
    slots: list[Slot] = field(default_factory=list)
    current: Slot | None = None
    next: Slot | None = None

    @property
    def free_until(self) -> datetime | None:
        return self.next.start if (self.current is None and self.next) else None


def parse_hhmm(s: str) -> time:
    h, m = s.strip().split(":")
    return time(int(h), int(m))


def now_local(settings: dict | None = None) -> datetime:
    settings = settings or db.get_settings()
    tz = ZoneInfo(settings.get("timezone", "Europe/Paris"))
    return datetime.now(tz).replace(tzinfo=None, microsecond=0)


def slots_for_day(room_code: str, day: date) -> list[Slot]:
    start = datetime.combine(day, time.min).isoformat()
    end = datetime.combine(day + timedelta(days=1), time.min).isoformat()
    rows = db.query(
        "SELECT * FROM events WHERE room_code = ? AND start < ? AND end > ? ORDER BY start",
        (room_code, end, start),
    )
    return [Slot.from_row(r) for r in rows]


def room_state(room_code: str, now: datetime) -> RoomState:
    eff = now + LOOKAHEAD
    slots = slots_for_day(room_code, eff.date())
    current = next((s for s in slots if s.start <= eff < s.end), None)
    upcoming = next((s for s in slots if s.start > eff), None)
    return RoomState(now=eff, day=eff.date(), slots=slots, current=current, next=upcoming)


def _active_days(settings: dict) -> set[int]:
    return {int(x) for x in settings.get("active_days", "1,2,3,4,5").split(",") if x.strip()}


def _next_day_start(now: datetime, settings: dict, include_today: bool) -> datetime:
    ds = parse_hhmm(settings["day_start"])
    days = _active_days(settings) or set(range(1, 8))
    d = now.date() if include_today else now.date() + timedelta(days=1)
    for _ in range(8):
        if d.isoweekday() in days:
            cand = datetime.combine(d, ds)
            if cand > now:
                return cand
        d += timedelta(days=1)
    return now + timedelta(hours=24)


def compute_next_wake(room_code: str | None, now: datetime, settings: dict | None = None) -> tuple[datetime, int]:
    """Retourne (heure cible du prochain réveil, secondes de sommeil à envoyer au terminal)."""
    settings = settings or db.get_settings()

    if not room_code:
        secs = int(settings.get("unassigned_sleep", "300"))
        return now + timedelta(seconds=secs), secs

    today_active = now.isoweekday() in _active_days(settings)
    ds = datetime.combine(now.date(), parse_hhmm(settings["day_start"]))
    de = datetime.combine(now.date(), parse_hhmm(settings["day_end"]))

    if today_active and now < ds:
        target = ds
    elif not today_active or now >= de:
        target = _next_day_start(now, settings, include_today=False)
    else:
        eff = now + LOOKAHEAD
        slots = slots_for_day(room_code, now.date())
        boundaries = sorted({b for s in slots for b in (s.start, s.end) if b > eff})
        if not boundaries:
            # Plus aucun changement prévu aujourd'hui : on dort jusqu'au prochain jour ouvré.
            target = _next_day_start(now, settings, include_today=False)
        else:
            cap = now + timedelta(minutes=int(settings.get("max_awake_interval", "30")))
            target = min(cap, boundaries[0] + WAKE_MARGIN)

    secs = int((target - now).total_seconds())
    if secs > DRIFT_THRESHOLD:
        secs = int(secs * DRIFT_COMPENSATION)
    secs = max(MIN_SLEEP, min(MAX_SLEEP, secs))
    return target, secs
