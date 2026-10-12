"""Profile cards and team banners, drawn with Pillow.

Text uses DejaVu Sans (the Docker image installs fonts-dejavu-core: accents,
Greek, Cyrillic), or Pillow's built-in font if it's missing.

render_card() returns the PNG of a player's card: the frame (a pattern of
game/profiles.py FRAMES), the profile color, avatar, name and team tag, title,
level and XP bar, emeralds, fortune rank, species, bio, showcase and the team
banner. render_banner() returns a team banner alone. Without Pillow, AVAILABLE
is False and the bot shows the profile as text only.
"""
from __future__ import annotations

import io
from dataclasses import dataclass, field

from game.profiles import DYES, FRAMES

try:
    from PIL import Image, ImageDraw, ImageFont

    AVAILABLE = True
except ImportError:  # pragma: no cover - the Docker image installs Pillow
    AVAILABLE = False

W, H, BORDER = 960, 330, 18
PANEL = (32, 34, 40)
MUTED = (170, 175, 190)
TEXT = (235, 236, 240)
GOLD = (255, 200, 80)
GREEN = (120, 230, 160)


@dataclass
class CardData:
    name: str
    level: int
    xp: int
    xp_needed: int
    emeralds: int
    accent: tuple[int, int, int]
    tag: str | None = None
    title: str | None = None
    fortune_rank: int | None = None
    species: str | None = None
    bio: str | None = None
    showcase: list[str] = field(default_factory=list)
    frame: str | None = None
    avatar: bytes | None = None
    banner: dict | None = None  # {"base": dye, "layers": [(pattern, dye), ...]}
    team_name: str | None = None
    champion: bool = False


FONT_DIR = "/usr/share/fonts/truetype/dejavu/"
_fonts: dict[tuple[int, bool], object] = {}
# What the font can draw: Latin (accents included), Greek, Cyrillic, punctuation, currencies. Emoji are dropped.
_RANGES = ((0x20, 0x250), (0x370, 0x500), (0x1E00, 0x1F00), (0x2000, 0x2070), (0x20A0, 0x20D0))


def safe(text: str | None) -> str:
    return "".join(c for c in (text or "") if any(lo <= ord(c) < hi for lo, hi in _RANGES)).strip()


def font(size: int, bold: bool = False):
    key = (size, bold)
    if key not in _fonts:
        try:
            _fonts[key] = ImageFont.truetype(FONT_DIR + ("DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"), size)
        except OSError:
            _fonts[key] = ImageFont.load_default(size=size)
    return _fonts[key]


def _fit(draw, text: str, size: int, width: int, bold: bool = False) -> tuple[str, object]:
    """The text in the biggest font (down to 60%) that fits `width`, cut with … if needed."""
    for s in range(size, int(size * 0.6) - 1, -2):
        f = font(s, bold)
        if draw.textlength(text, font=f) <= width:
            return text, f
    f = font(int(size * 0.6), bold)
    while text and draw.textlength(text + "…", font=f) > width:
        text = text[:-1]
    return text + "…", f


def _wrap(draw, text: str, f, width: int, lines: int) -> list[str]:
    out, line = [], ""
    for word in text.split():
        test = f"{line} {word}".strip()
        if draw.textlength(test, font=f) <= width:
            line = test
            continue
        out.append(line)
        line = word
        if len(out) == lines:
            break
    if len(out) < lines and line:
        out.append(line)
    if len(out) == lines and " ".join(out) != text:
        while out[-1] and draw.textlength(out[-1] + "…", font=f) > width:
            out[-1] = out[-1][:-1]
        out[-1] += "…"
    return [line for line in out if line]


# ---------------- frames ----------------
def _frame(img, key: str | None, accent: tuple[int, int, int]) -> None:
    d = ImageDraw.Draw(img)
    frame = FRAMES.get(key or "")
    if frame is None:
        d.rectangle([0, 0, W, H], fill=(24, 25, 30))
        d.rectangle([4, 4, W - 5, H - 5], outline=accent, width=3)
        return
    base, light, dark = frame.colors
    d.rectangle([0, 0, W, H], fill=base)
    step = 6

    def border(x: int, y: int) -> bool:
        return not (BORDER <= x < W - BORDER and BORDER <= y < H - BORDER)

    for y in range(0, H, step):
        for x in range(0, W, step):
            if not border(x, y):
                continue
            i, j = x // step, y // step
            color = None
            if frame.style == "ore":
                k = (i * 7 + j * 13 + (i * j) % 5) % 11
                color = light if k in (0, 3) else dark if k in (5, 8) else None
            elif frame.style == "bricks":
                row = j // 2
                color = dark if j % 2 == 1 or (i + (row % 2) * 2) % 4 == 0 else (light if (i + j) % 7 == 0 else None)
            elif frame.style == "checker":
                color = light if (i + j) % 2 == 0 else dark
            elif frame.style == "stripes":
                color = light if (i + j) % 4 < 2 else dark
            elif frame.style == "stars":
                k = (i * 31 + j * 17) % 23
                color = light if k == 0 else (dark if k in (5, 11) else None)
            elif frame.style == "flames":
                edge = min(j, H // step - 1 - j, i, W // step - 1 - i)
                k = (i * 5 + j * 3) % 7
                color = light if edge == 0 and k < 3 else dark if (edge == 1 and k < 4) or k == 0 else None
            if color:
                d.rectangle([x, y, x + step - 1, y + step - 1], fill=color)


# ---------------- banners ----------------
def _banner_layer(size: tuple[int, int], pattern: str, rgb: tuple[int, int, int]):
    w, h = size
    layer = Image.new("RGBA", size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    c = rgb + (255,)
    t3w, t3h = w / 3, h / 3
    if pattern == "stripe_top":
        d.rectangle([0, 0, w, t3h * 0.7], fill=c)
    elif pattern == "stripe_bottom":
        d.rectangle([0, h - t3h * 0.7, w, h], fill=c)
    elif pattern == "stripe_left":
        d.rectangle([0, 0, t3w, h], fill=c)
    elif pattern == "stripe_right":
        d.rectangle([w - t3w, 0, w, h], fill=c)
    elif pattern == "stripe_center":
        d.rectangle([t3w, 0, 2 * t3w, h], fill=c)
    elif pattern == "stripe_middle":
        d.rectangle([0, h * 0.42, w, h * 0.58], fill=c)
    elif pattern == "straight_cross":
        d.rectangle([w * 0.4, 0, w * 0.6, h], fill=c)
        d.rectangle([0, h * 0.42, w, h * 0.58], fill=c)
    elif pattern == "cross":
        d.line([(0, 0), (w, h)], fill=c, width=max(4, w // 6))
        d.line([(w, 0), (0, h)], fill=c, width=max(4, w // 6))
    elif pattern == "chevron":
        d.polygon([(0, h), (w / 2, h * 0.62), (w, h)], fill=c)
    elif pattern == "inverted_chevron":
        d.polygon([(0, 0), (w / 2, h * 0.38), (w, 0)], fill=c)
    elif pattern == "half_top":
        d.rectangle([0, 0, w, h / 2], fill=c)
    elif pattern == "half_left":
        d.rectangle([0, 0, w / 2, h], fill=c)
    elif pattern == "border":
        b = max(3, w // 10)
        d.rectangle([0, 0, w, h], outline=c, width=b)
    elif pattern == "circle":
        r = w * 0.22
        d.ellipse([w / 2 - r, h / 2 - r, w / 2 + r, h / 2 + r], fill=c)
    elif pattern == "rhombus":
        d.polygon([(w / 2, h * 0.3), (w * 0.85, h / 2), (w / 2, h * 0.7), (w * 0.15, h / 2)], fill=c)
    elif pattern == "gradient":
        for y in range(h):
            d.line([(0, y), (w, y)], fill=rgb + (int(255 * (1 - y / h)),))
    elif pattern == "bricks":
        bh = h / 12
        for row in range(12):
            y = row * bh
            d.line([(0, y), (w, y)], fill=c, width=2)
            off = (w / 4) * (row % 2)
            for x in range(4):
                xx = off + x * w / 2
                d.line([(xx, y), (xx, y + bh)], fill=c, width=2)
    elif pattern == "small_stripes":
        for i in range(0, 8, 2):
            d.rectangle([i * w / 8, 0, (i + 1) * w / 8, h * 0.85], fill=c)
    elif pattern == "triangle_top":
        n = 4
        for i in range(n):
            d.polygon([(i * w / n, 0), ((i + 0.5) * w / n, h * 0.1), ((i + 1) * w / n, 0)], fill=c)
    elif pattern == "creeper":
        u = w / 8
        y0 = h * 0.3
        for x0, y1, x1, y2 in ((1.5, 0, 3, 1.5), (5, 0, 6.5, 1.5), (3, 1.5, 5, 3), (2.2, 2.5, 3, 4.2), (5, 2.5, 5.8, 4.2)):
            d.rectangle([x0 * u, y0 + y1 * u, x1 * u, y0 + y2 * u], fill=c)
    return layer


def banner_image(banner: dict, size: tuple[int, int] = (100, 200)):
    """A banner (RGBA): the base color, its patterns, a pole on top."""
    w, h = size
    img = Image.new("RGBA", (w, h + 12), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rectangle([-2, 0, w + 2, 7], fill=(110, 75, 40, 255))  # the bar it hangs from
    cloth = Image.new("RGBA", size, DYES.get(banner.get("base"), DYES["white"])[1] + (255,))
    for pattern, dye in banner.get("layers", []):
        if dye in DYES:
            cloth = Image.alpha_composite(cloth, _banner_layer(size, pattern, DYES[dye][1]))
    ImageDraw.Draw(cloth).rectangle([0, 0, w - 1, h - 1], outline=(15, 15, 18, 255), width=2)
    img.paste(cloth, (0, 10), cloth)
    return img


def render_banner(banner: dict, size: tuple[int, int] = (120, 240)) -> bytes:
    out = io.BytesIO()
    banner_image(banner, size).save(out, "PNG")
    return out.getvalue()


# ---------------- the card ----------------
def _avatar(raw: bytes | None, name: str, accent, size: int = 140):
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).ellipse([0, 0, size - 1, size - 1], fill=255)
    face = None
    if raw:
        try:
            face = Image.open(io.BytesIO(raw)).convert("RGBA").resize((size, size))
        except Exception:  # a bad image: initials instead
            face = None
    if face is None:
        face = Image.new("RGBA", (size, size), (70, 140, 90, 255))
        d = ImageDraw.Draw(face)
        initials = "".join(w[0] for w in safe(name).split()[:2]).upper() or "?"
        f = font(int(size * 0.32))
        tw = d.textlength(initials, font=f)
        d.text(((size - tw) / 2, size * 0.32), initials, font=f, fill=TEXT)
    img.paste(face, (0, 0), mask)
    ring = ImageDraw.Draw(img)
    ring.ellipse([1, 1, size - 2, size - 2], outline=accent + (255,), width=5)
    return img


def render_card(c: CardData) -> bytes:
    img = Image.new("RGB", (W, H))
    _frame(img, c.frame, c.accent)
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([BORDER, BORDER, W - BORDER, H - BORDER], radius=14, fill=PANEL)
    d.rectangle([BORDER, BORDER + 10, BORDER + 7, H - BORDER - 10], fill=c.accent)

    avatar = _avatar(c.avatar, c.name, c.accent)
    img.paste(avatar, (52, 50), avatar)
    if c.champion:
        d.text((80, 196), "CHAMPION", font=font(16, True), fill=GOLD)

    left = 215
    right = W - BORDER - (150 if c.banner else 30)
    x = left
    name, f = _fit(d, safe(c.name) or "Player", 40, right - left - (90 if c.tag else 0), bold=True)
    d.text((x, 38), name, font=f, fill=TEXT)
    if c.tag:
        d.text((x + d.textlength(name, font=f) + 14, 50), f"[{c.tag}]", font=font(24), fill=MUTED)
    if c.title:
        title, f = _fit(d, f"« {safe(c.title)} »", 24, right - left)
        d.text((x, 92), title, font=f, fill=GOLD)

    y = 135
    lvl = f"Level {c.level}"
    d.text((x, y), lvl, font=font(24, True), fill=TEXT)
    bar_x = x + d.textlength(lvl, font=font(24, True)) + 16
    xp_text = f"{c.xp:,} / {c.xp_needed:,} XP"
    bar_end = right - d.textlength(xp_text, font=font(18)) - 12
    d.rounded_rectangle([bar_x, y + 6, bar_end, y + 28], radius=10, fill=(60, 63, 72))
    share = max(0.0, min(1.0, c.xp / c.xp_needed)) if c.xp_needed else 1.0
    if share > 0:
        d.rounded_rectangle([bar_x, y + 6, bar_x + max(20, (bar_end - bar_x) * share), y + 28], radius=10, fill=c.accent)
    d.text((bar_end + 10, y + 7), xp_text, font=font(18), fill=MUTED)

    bits = [f"{c.emeralds:,} emeralds"]
    if c.fortune_rank:
        bits.append(f"#{c.fortune_rank} fortune")
    if c.species:
        bits.append(safe(c.species))
    stats, f = _fit(d, "   ·   ".join(bits), 22, right - left)
    d.text((x, 180), stats, font=f, fill=GREEN)

    bio = safe(c.bio)
    if bio:
        f = font(20)
        for i, line in enumerate(_wrap(d, f"“{bio}”", f, right - left, 2)):
            d.text((x, 218 + i * 26), line, font=f, fill=(210, 210, 220))

    pill_x = 52
    f = font(15)
    for label in [safe(s) for s in c.showcase[:3] if safe(s)]:
        label, _ = _fit(d, label, 15, 150)
        tw = d.textlength(label, font=f)
        if pill_x + tw + 20 > right:
            break
        d.rounded_rectangle([pill_x, 274, pill_x + tw + 20, 300], radius=12, fill=(55, 58, 68), outline=c.accent, width=2)
        d.text((pill_x + 10, 278), label, font=f, fill=TEXT)
        pill_x += tw + 30

    if c.banner:
        b = banner_image(c.banner, (84, 168))
        bx = W - BORDER - 120
        img.paste(b, (bx, 32), b)
        if c.team_name:
            f = font(14)
            for i, line in enumerate(_wrap(d, safe(c.team_name), f, 110, 2)):
                tw = d.textlength(line, font=f)
                d.text((bx + 42 - tw / 2, 220 + i * 18), line, font=f, fill=MUTED)

    out = io.BytesIO()
    img.save(out, "PNG", optimize=True)
    return out.getvalue()
