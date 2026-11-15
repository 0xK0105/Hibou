"""Rendu des écrans 800x480 en noir et blanc (Pillow).

Le terminal reçoit un bitmap brut de 48 000 octets : 1 bit par pixel,
ligne par ligne, MSB en premier, bit à 1 = pixel noir. Pas de décodage
PNG à faire sur l'ESP32.
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timedelta
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from .scheduling import RoomState, Slot, parse_hhmm

W, H = 800, 480
BLACK, WHITE = 0, 255
FONT_DIR = Path(__file__).resolve().parent / "fonts"

JOURS = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
MOIS = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet",
        "août", "septembre", "octobre", "novembre", "décembre"]


@lru_cache(maxsize=64)
def font(size: int, bold: bool = False, condensed: bool = False) -> ImageFont.FreeTypeFont:
    name = "DejaVuSans" + ("Condensed" if condensed else "") + ("-Bold" if bold else "") + ".ttf"
    return ImageFont.truetype(str(FONT_DIR / name), size)


def hm(dt: datetime) -> str:
    return f"{dt.hour}h{dt.minute:02d}"


def date_fr(d) -> str:
    return f"{JOURS[d.weekday()].capitalize()} {d.day} {MOIS[d.month - 1]}"


def fit(draw: ImageDraw.ImageDraw, text: str, f, max_w: int) -> str:
    if draw.textlength(text, font=f) <= max_w:
        return text
    while text and draw.textlength(text + "…", font=f) > max_w:
        text = text[:-1]
    return text.rstrip() + "…"


def _canvas() -> tuple[Image.Image, ImageDraw.ImageDraw]:
    img = Image.new("L", (W, H), WHITE)
    return img, ImageDraw.Draw(img)


def _finish(img: Image.Image) -> Image.Image:
    # Seuil franc (pas de tramage) : le texte reste net sur l'e-paper.
    return img.point(lambda p: 255 if p >= 128 else 0).convert("1", dither=Image.Dither.NONE)


def _hatch(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int], step: int = 6) -> None:
    x0, y0, x1, y1 = box
    pts = [(x, y) for y in range(y0, y1 + 1) for x in range(x0, x1 + 1) if (x + y) % step == 0]
    draw.point(pts, fill=BLACK)


def _header(draw: ImageDraw.ImageDraw, code: str, name: str, day) -> None:
    draw.rectangle([0, 0, W, 86], fill=BLACK)
    f_code = font(54, bold=True)
    draw.text((24, 43), code, font=f_code, fill=WHITE, anchor="lm")
    x = 24 + int(draw.textlength(code, font=f_code)) + 20
    f_date = font(24, bold=True)
    date_txt = date_fr(day)
    date_w = int(draw.textlength(date_txt, font=f_date))
    draw.text((W - 24, 43), date_txt, font=f_date, fill=WHITE, anchor="rm")
    if name:
        draw.text((x, 45), fit(draw, name, font(24), W - 24 - date_w - 24 - x), font=font(24), fill=WHITE, anchor="lm")


def _status(draw: ImageDraw.ImageDraw, st: RoomState, day_end: datetime, message: str) -> int:
    y = 104
    if message:
        draw.rectangle([24, y, W - 24, y + 46], outline=BLACK, width=3)
        draw.text((W // 2, y + 23), fit(draw, "⚠ " + message, font(24, bold=True), W - 80),
                  font=font(24, bold=True), fill=BLACK, anchor="mm")
        y += 60

    if st.current:
        s = st.current
        tag = "OCCUPÉE"
        f_tag = font(26, bold=True)
        tw = int(draw.textlength(tag, font=f_tag)) + 28
        draw.rounded_rectangle([24, y, 24 + tw, y + 42], radius=8, fill=BLACK)
        draw.text((24 + tw // 2, y + 21), tag, font=f_tag, fill=WHITE, anchor="mm")
        draw.text((24 + tw + 16, y + 21), f"jusqu'à {hm(s.end)}", font=font(28, bold=True), fill=BLACK, anchor="lm")
        f_title = font(32, bold=True)
        title = fit(draw, s.title or "Cours", f_title, W - 48)
        draw.text((24, y + 56), title, font=f_title, fill=BLACK)
        extra = " · ".join(x for x in (s.teacher, s.grp) if x)
        if extra:
            x = 24 + int(draw.textlength(title, font=f_title)) + 16
            room_left = W - 24 - x
            if room_left > 160:
                draw.text((x, y + 66), fit(draw, extra, font(22), room_left), font=font(22), fill=BLACK)
        return y + 104
    else:
        tag = "LIBRE"
        f_tag = font(26, bold=True)
        tw = int(draw.textlength(tag, font=f_tag)) + 28
        draw.rounded_rectangle([24, y, 24 + tw, y + 42], radius=8, outline=BLACK, width=3)
        draw.text((24 + tw // 2, y + 21), tag, font=f_tag, fill=BLACK, anchor="mm")
        if st.next:
            sub = f"jusqu'à {hm(st.next.start)}"
            nxt = f"Ensuite : {st.next.title or 'Cours'}"
        else:
            sub = "pour le reste de la journée" if st.slots else "toute la journée"
            nxt = ""
        draw.text((24 + tw + 16, y + 21), sub, font=font(28, bold=True), fill=BLACK, anchor="lm")
        if nxt:
            draw.text((24, y + 58), fit(draw, nxt, font(24), W - 48), font=font(24), fill=BLACK)
            return y + 100
        return y + 64


def _slot_list(draw: ImageDraw.ImageDraw, st: RoomState, top: int, bottom: int) -> None:
    draw.line([(24, top), (W - 24, top)], fill=BLACK, width=2)
    top += 8
    slots = st.slots
    if not slots:
        draw.text((W // 2, (top + bottom) // 2), "Aucun cours prévu aujourd'hui",
                  font=font(28), fill=BLACK, anchor="mm")
        return

    row_h = 36
    max_rows = max(1, (bottom - top) // row_h)
    # Si trop de créneaux : on garde le créneau courant/suivant visible
    if len(slots) > max_rows:
        pivot = next((i for i, s in enumerate(slots) if s.end > st.now), len(slots) - 1)
        first = max(0, min(pivot - 1, len(slots) - max_rows))
        slots = slots[first:first + max_rows]

    f_time = font(22, bold=True, condensed=True)
    f_txt = font(22, condensed=True)
    f_txt_b = font(22, bold=True, condensed=True)
    time_w = 170
    for i, s in enumerate(slots):
        y = top + i * row_h
        is_cur = st.current is s or (st.current and s.start == st.current.start and s.title == st.current.title)
        is_past = s.end <= st.now
        fg = BLACK
        if is_cur:
            draw.rectangle([24, y, W - 24, y + row_h - 4], fill=BLACK)
            fg = WHITE
        t = f"{hm(s.start)} – {hm(s.end)}"
        draw.text((36, y + (row_h - 4) // 2), t, font=f_time, fill=fg, anchor="lm")
        label = s.title or "Cours"
        extra = " · ".join(x for x in (s.teacher, s.grp) if x)
        txt = f"{label}  —  {extra}" if extra else label
        draw.text((36 + time_w, y + (row_h - 4) // 2), fit(draw, txt, f_txt_b if is_cur else f_txt, W - 60 - time_w - 36),
                  font=f_txt_b if is_cur else f_txt, fill=fg, anchor="lm")
        if is_past:
            mid = y + (row_h - 4) // 2
            tw = int(draw.textlength(t, font=f_time))
            draw.line([(32, mid), (40 + tw, mid)], fill=BLACK, width=2)
        elif not is_cur and i < len(slots) - 1:
            draw.line([(36, y + row_h - 2), (W - 36, y + row_h - 2)], fill=BLACK, width=1)


def _timeline(draw: ImageDraw.ImageDraw, st: RoomState, day_start: datetime, day_end: datetime, y: int) -> None:
    """Barre d'occupation de la journée : blocs pleins = occupé, partie hachurée = passé."""
    x0, x1 = 60, W - 40
    h = 26
    span = (day_end - day_start).total_seconds()

    def X(dt: datetime) -> int:
        r = (dt - day_start).total_seconds() / span
        return int(x0 + max(0.0, min(1.0, r)) * (x1 - x0))

    draw.rectangle([x0, y, x1, y + h], outline=BLACK, width=2)
    # Le "passé" s'arrête à la dernière frontière de créneau franchie (et pas à l'heure exacte),
    # pour que l'image ne change qu'aux changements de créneau -> 304 au lieu d'un rafraîchissement.
    past = [b for s in st.slots for b in (s.start, s.end) if b <= st.now]
    marker = max(past) if past else day_start
    for s in st.slots:
        a, b = X(s.start), X(s.end)
        if b <= a:
            continue
        if s.end <= marker:  # créneau passé : hachuré
            draw.rectangle([a, y, b, y + h], outline=BLACK, width=1)
            _hatch(draw, (a + 1, y + 1, b - 1, y + h - 1), step=5)
        else:
            draw.rectangle([a, y, b, y + h], fill=BLACK)
            if a > x0:
                draw.line([(a, y), (a, y + h)], fill=WHITE, width=1)
    if st.current:
        a, b = X(st.current.start), X(st.current.end)
        draw.polygon([((a + b) // 2 - 8, y - 12), ((a + b) // 2 + 8, y - 12), ((a + b) // 2, y - 1)], fill=BLACK)

    f = font(16, condensed=True)
    hour = day_start.replace(minute=0)
    if hour < day_start:
        hour += timedelta(hours=1)
    while hour <= day_end:
        x = X(hour)
        draw.line([(x, y + h), (x, y + h + 5)], fill=BLACK, width=1)
        draw.text((x, y + h + 7), f"{hour.hour}h", font=f, fill=BLACK, anchor="mt")
        hour += timedelta(hours=1)


def render_room(code: str, name: str, st: RoomState, settings: dict, message: str = "",
                low_battery: bool = False) -> Image.Image:
    img, draw = _canvas()
    _header(draw, code, name, st.day)
    ds = datetime.combine(st.day, parse_hhmm(settings.get("day_start", "07:30")))
    de = datetime.combine(st.day, parse_hhmm(settings.get("day_end", "19:00")))
    # La frise couvre au minimum les créneaux du jour
    if st.slots:
        ds = min(ds, min(s.start for s in st.slots))
        de = max(de, max(s.end for s in st.slots))
    ds = ds.replace(minute=0)

    y = _status(draw, st, de, message)
    _slot_list(draw, st, y + 4, 392)
    _timeline(draw, st, ds, de, 404)

    f = font(15, condensed=True)
    site = settings.get("site_name", "")
    if site:
        draw.text((24, H - 6), site, font=f, fill=BLACK, anchor="ls")
    if low_battery:
        txt = "Batterie faible — à recharger"
        tw = int(draw.textlength(txt, font=font(15, bold=True)))
        draw.rectangle([W - 32 - tw, H - 24, W - 16, H - 2], fill=BLACK)
        draw.text((W - 24, H - 6), txt, font=font(15, bold=True), fill=WHITE, anchor="rs")
    return _finish(img)


def render_unassigned(mac: str, ip: str, server_hint: str = "") -> Image.Image:
    img, draw = _canvas()
    draw.rectangle([0, 0, W, 86], fill=BLACK)
    draw.text((24, 43), "Écran non affecté", font=font(40, bold=True), fill=WHITE, anchor="lm")
    lines = [
        ("Identifiant", mac),
        ("Adresse IP", ip or "—"),
    ]
    y = 140
    for k, v in lines:
        draw.text((48, y), k, font=font(24), fill=BLACK)
        draw.text((260, y), v, font=font(30, bold=True), fill=BLACK)
        y += 60
    draw.text((48, y + 30), "Affectez cet écran à une salle dans l'onglet « Écrans »", font=font(22), fill=BLACK)
    if server_hint:
        draw.text((48, y + 66), server_hint, font=font(22, bold=True), fill=BLACK)
    return _finish(img)


def to_device_bytes(img: Image.Image) -> bytes:
    """Pillow mode '1' : bit 1 = blanc. Le firmware attend bit 1 = noir → on inverse."""
    assert img.size == (W, H) and img.mode == "1"
    return bytes(b ^ 0xFF for b in img.tobytes())


def etag_of(data: bytes) -> str:
    return hashlib.sha1(data).hexdigest()[:16]
