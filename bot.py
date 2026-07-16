"""
Make It Quote — Discord bot
----------------------------
Reply to any message and type:  .quote
The bot grabs the message you replied to, renders it as a styled
"quote card" (color avatar + wrapped quote text), and posts the
image back in the channel.

100% free to run — no paid API, no paid hosting required
(see README.md for free hosting options).

Requirements: discord.py, Pillow, aiohttp, requests, fonttools
    pip install -U discord.py Pillow aiohttp requests fonttools

Fonts:
    For best results, drop these files next to this script:
        Poppins-SemiBold.ttf   (headline / quote text)
        Poppins-Regular.ttf    (author name)
    (Poppins: https://fonts.google.com/specimen/Poppins)

    On first run, the bot automatically DOWNLOADS two wide-coverage
    fallback fonts into this same folder if they aren't already there:
        NotoSans-Regular.ttf   (accented Latin, Cyrillic, Greek, etc.)
        NotoEmoji-Regular.ttf  (monochrome emoji outlines)
    This is what makes non-English text and emoji actually render
    instead of showing blank boxes. If your bot host has no outbound
    internet access, download them yourself from
    https://github.com/notofonts/noto-fonts and
    https://github.com/googlefonts/noto-emoji and place them next to
    this script — the bot will use the local copies and skip downloading.

    NOTE ON EMOJI: Pillow can only reliably render *monochrome* emoji
    glyphs unless your local libfreetype build was compiled with color
    bitmap/CBDT support (most pip-installed Pillow wheels are NOT), so
    we use the monochrome "NotoEmoji-Regular.ttf" rather than
    "NotoColorEmoji.ttf". If you need full color emoji, you'd need to
    composite pre-rendered emoji PNGs (e.g. Twemoji) on top of the text
    instead of drawing glyphs.

    NOTE ON CJK / ARABIC / DEVANAGARI ETC.: NotoSans-Regular.ttf only
    covers Latin/Cyrillic/Greek-family scripts. If you need Chinese,
    Japanese, Korean, Arabic, or other scripts, download the matching
    Noto font (e.g. "Noto Sans SC", "Noto Sans Arabic") and add its
    path to FALLBACK_FONT_CANDIDATES below — the glyph-picking logic
    will automatically pick it up per-character.
"""

import io
import os

import aiohttp
import discord
import requests
from PIL import Image, ImageDraw, ImageFont, ImageOps

# ---------------------------------------------------------------------------
# CONFIG
# ---------------------------------------------------------------------------
TOKEN = os.environ.get("DISCORD_BOT_TOKEN")  # set this as an env variable, never hardcode it
PREFIX = ".quote"  # trigger command

CARD_WIDTH = 1200
CARD_HEIGHT = 675
AVATAR_SIZE = 675  # avatar takes the left square, text sits on the right

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# ---------------------------------------------------------------------------
# AUTO-DOWNLOAD WIDE-COVERAGE FALLBACK FONTS
# ---------------------------------------------------------------------------
# These are the two files that actually make emoji / accented / non-Latin
# text render instead of showing blank tofu boxes. Most people never
# manually download and place them next to the script, so we fetch them
# automatically the first time the bot starts (best-effort — if there's
# no internet access, we just skip and fall back to system fonts).
_AUTO_FONTS = {
    "NotoSans-Regular.ttf": (
        "https://raw.githubusercontent.com/notofonts/noto-fonts/main/"
        "hinted/ttf/NotoSans/NotoSans-Regular.ttf"
    ),
    "NotoEmoji-Regular.ttf": (
        "https://raw.githubusercontent.com/google/fonts/main/"
        "ofl/notoemoji/NotoEmoji%5Bwght%5D.ttf"
    ),
}


def _ensure_fallback_fonts():
    for filename, url in _AUTO_FONTS.items():
        dest = os.path.join(SCRIPT_DIR, filename)
        if os.path.exists(dest):
            continue
        try:
            resp = requests.get(url, timeout=15)
            resp.raise_for_status()
            tmp = dest + ".part"
            with open(tmp, "wb") as f:
                f.write(resp.content)
            os.replace(tmp, dest)
            print(f"[make_it_quote] Downloaded fallback font: {filename}")
        except Exception as exc:
            print(
                f"[make_it_quote] Could not auto-download {filename} ({exc}). "
                "Emoji/unicode coverage may be limited unless you place it "
                "next to this script manually."
            )


_ensure_fallback_fonts()

# Every place we'll look for a real, scalable .ttf, in priority order.
# These are the "primary" display fonts (used first for any glyph they contain).
BOLD_FONT_CANDIDATES = [
    os.path.join(SCRIPT_DIR, "Poppins-SemiBold.ttf"),
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",              # Linux
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",       # Linux
    "/Library/Fonts/Arial Bold.ttf",                                     # macOS
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",                 # macOS
    "C:\\Windows\\Fonts\\arialbd.ttf",                                   # Windows
]
REGULAR_FONT_CANDIDATES = [
    os.path.join(SCRIPT_DIR, "Poppins-Regular.ttf"),
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",                   # Linux
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",    # Linux
    "/Library/Fonts/Arial.ttf",                                          # macOS
    "/System/Library/Fonts/Supplemental/Arial.ttf",                      # macOS
    "C:\\Windows\\Fonts\\arial.ttf",                                     # Windows
]

# Fallback fonts used ONLY for characters the primary font doesn't contain
# (wide-coverage Latin/Cyrillic/Greek/etc + emoji). The two Noto files are
# auto-downloaded above if missing. Add more Noto script fonts here (e.g.
# Noto Sans SC/JP/KR/Arabic) if you need those scripts.
FALLBACK_FONT_CANDIDATES = [
    os.path.join(SCRIPT_DIR, "NotoSans-Regular.ttf"),
    os.path.join(SCRIPT_DIR, "NotoEmoji-Regular.ttf"),
    "/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf",               # Linux
    "/usr/share/fonts/truetype/noto/NotoEmoji-Regular.ttf",              # Linux
    "C:\\Windows\\Fonts\\segoeui.ttf",                                   # Windows wide-coverage
]
# Deliberately NOT included: NotoColorEmoji.ttf, Apple Color Emoji.ttc,
# seguiemj.ttf. Those are bitmap-strike (CBDT) or COLR color fonts —
# freetype can only rasterize them at the fixed pixel sizes baked into
# the file, so ImageFont.truetype(path, our_arbitrary_size) throws
# "OSError: invalid pixel size" for almost every size we ask for. That
# error used to get silently caught and fall back to Pillow's tiny
# built-in font mid-render, which reported wildly wrong glyph widths
# and threw off the line-wrapping math. NotoEmoji-Regular.ttf (outline,
# not bitmap) is what actually renders emoji reliably at any size.


def _first_existing(paths):
    for p in paths:
        if os.path.exists(p) and _font_is_usable(p):
            return p
    return None


def _all_existing(paths):
    return [p for p in paths if os.path.exists(p) and _font_is_usable(p)]


_USABLE_FONT_CACHE = {}


def _font_is_usable(path):
    """Confirm Pillow can actually load this font file across the range
    of sizes we render at. This is what catches bitmap/color emoji
    fonts (or any other incompatible font) BEFORE they ever get added
    to a chain, instead of discovering the failure mid-render."""
    if path in _USABLE_FONT_CACHE:
        return _USABLE_FONT_CACHE[path]
    ok = True
    for test_size in (22, 32, 62):
        try:
            ImageFont.truetype(path, test_size)
        except Exception:
            ok = False
            break
    _USABLE_FONT_CACHE[path] = ok
    if not ok:
        print(f"[make_it_quote] Skipping font (can't load at needed sizes): {path}")
    return ok


FONT_PATH = _first_existing(BOLD_FONT_CANDIDATES)
FONT_REGULAR = _first_existing(REGULAR_FONT_CANDIDATES)
FALLBACK_FONTS = _all_existing(FALLBACK_FONT_CANDIDATES)

# Full lookup chains, in the order glyphs should be searched for.
BOLD_CHAIN = [p for p in [FONT_PATH] + FALLBACK_FONTS if p]
REGULAR_CHAIN = [p for p in [FONT_REGULAR] + FALLBACK_FONTS if p]

if FONT_PATH is None or FONT_REGULAR is None:
    print(
        "[make_it_quote] WARNING: no .ttf font found on this system. "
        "Quote cards will use Pillow's tiny built-in font. "
        "Fix this by placing Poppins-SemiBold.ttf and Poppins-Regular.ttf "
        "(https://fonts.google.com/specimen/Poppins) next to this script."
    )

# ---------------------------------------------------------------------------
# FONT / GLYPH HANDLING
# ---------------------------------------------------------------------------
_FONT_OBJ_CACHE = {}
_FONT_CMAP_CACHE = {}


def get_font(path, size):
    """Load (and cache) a TrueType font at a given size."""
    key = (path, size)
    if key not in _FONT_OBJ_CACHE:
        if path:
            try:
                _FONT_OBJ_CACHE[key] = ImageFont.truetype(path, size)
            except OSError:
                _FONT_OBJ_CACHE[key] = _load_default(size)
        else:
            _FONT_OBJ_CACHE[key] = _load_default(size)
    return _FONT_OBJ_CACHE[key]


def _load_default(size):
    try:
        return ImageFont.load_default(size=size)  # Pillow >= 10.1
    except TypeError:
        return ImageFont.load_default()


def get_font_cmap(path):
    """Return the set of unicode codepoints a font file actually contains,
    so we can decide whether it can render a given character at all.
    Returns None if we couldn't determine this (fonttools missing, or an
    unreadable/variable font) — callers must NOT treat that as "supports
    everything", or every character silently gets stuck on the first font
    in the chain and never reaches the emoji/unicode fallback fonts."""
    if path is None:
        return set()
    if path in _FONT_CMAP_CACHE:
        return _FONT_CMAP_CACHE[path]
    codepoints = set()
    try:
        from fontTools.ttLib import TTFont

        tt = TTFont(path, lazy=True, fontNumber=0)
        cmap = tt.getBestCmap()
        if cmap:
            codepoints = set(cmap.keys())
        else:
            codepoints = None
    except Exception:
        codepoints = None
    _FONT_CMAP_CACHE[path] = codepoints
    return codepoints


def pick_font_path(ch, chain):
    """Pick the first font in `chain` that's *confirmed* (via cmap) to
    contain a glyph for `ch`. Fonts whose cmap we couldn't read are kept
    as a last-resort fallback rather than being assumed to support the
    character — this is what lets emoji / accented / non-Latin
    characters actually fall through to NotoSans / NotoEmoji instead of
    getting stuck on the primary font and rendering as a blank box."""
    if ch.isspace():
        return chain[0] if chain else None

    unknown_cmap_fallback = None
    for path in chain:
        cmap = get_font_cmap(path)
        if cmap is None:
            if unknown_cmap_fallback is None:
                unknown_cmap_fallback = path
            continue
        if ord(ch) in cmap:
            return path

    if unknown_cmap_fallback is not None:
        return unknown_cmap_fallback
    # Nothing in the chain claims to support it — use the first font
    # anyway (best effort; may show a tofu box, but won't crash).
    return chain[0] if chain else None


def char_width(ch, chain, size, draw):
    font = get_font(pick_font_path(ch, chain), size)
    return draw.textlength(ch, font=font)


def text_run_width(text, chain, size, draw):
    return sum(char_width(ch, chain, size, draw) for ch in text)


def draw_mixed_text(draw, xy, text, chain, size, fill):
    """Draw a line of text where each character may come from a
    different font in `chain`, and return the total width drawn."""
    x, y = xy
    for ch in text:
        font = get_font(pick_font_path(ch, chain), size)
        draw.text((x, y), ch, font=font, fill=fill)
        x += draw.textlength(ch, font=font)
    return x - xy[0]


# ---------------------------------------------------------------------------
# INTENTS — message content intent MUST also be enabled in the Dev Portal
# ---------------------------------------------------------------------------
intents = discord.Intents.default()
intents.message_content = True
client = discord.Client(intents=intents)


async def fetch_avatar_bytes(session: aiohttp.ClientSession, url: str) -> bytes:
    async with session.get(url) as resp:
        return await resp.read()


def wrap_text(text, chain, size, max_width, draw):
    """Wrap text by actual rendered pixel width (accounting for mixed
    fonts), and hard-break any single "word" that's too wide to ever
    fit on its own line (e.g. long strings with no spaces)."""
    lines = []
    current = ""

    for word in text.split(" "):
        candidate = f"{current} {word}" if current else word
        if text_run_width(candidate, chain, size, draw) <= max_width:
            current = candidate
            continue

        if current:
            lines.append(current)
            current = ""

        if text_run_width(word, chain, size, draw) <= max_width:
            current = word
            continue

        # The word itself is wider than the max width — break it up
        # character by character instead of letting it overflow.
        chunk = ""
        for ch in word:
            test = chunk + ch
            if text_run_width(test, chain, size, draw) <= max_width:
                chunk = test
            else:
                if chunk:
                    lines.append(chunk)
                chunk = ch
        current = chunk

    if current:
        lines.append(current)

    return lines


def build_quote_card(avatar_bytes: bytes, author_name: str, quote_text: str) -> io.BytesIO:
    # --- avatar: color, cropped to a square, faded on the right edge ---
    avatar = Image.open(io.BytesIO(avatar_bytes)).convert("RGB")
    avatar = ImageOps.fit(avatar, (AVATAR_SIZE, CARD_HEIGHT))

    card = Image.new("RGB", (CARD_WIDTH, CARD_HEIGHT), "black")
    card.paste(avatar, (0, 0))

    # --- smooth fade from the avatar into the black background ---
    fade_width = 180
    mask = Image.new("L", (fade_width, CARD_HEIGHT))
    mask_draw = ImageDraw.Draw(mask)
    for x in range(fade_width):
        alpha = int(255 * (x / fade_width))
        mask_draw.line([(x, 0), (x, CARD_HEIGHT)], fill=alpha)
    black_layer = Image.new("RGB", (fade_width, CARD_HEIGHT), "black")
    card.paste(black_layer, (AVATAR_SIZE - fade_width, 0), mask)

    # --- text ---
    draw = ImageDraw.Draw(card)
    text_x = 720
    max_text_width = 470

    # Auto-size font: shrink until EVERY wrapped line fits both the
    # width and the overall block fits the height (previously only
    # height was checked, which let long words overflow sideways).
    font_size = 62
    lines = []
    line_height = 0
    while font_size >= 22:
        lines = wrap_text(f"\u201c{quote_text}\u201d", BOLD_CHAIN, font_size, max_text_width, draw)

        ref_font = get_font(BOLD_CHAIN[0] if BOLD_CHAIN else None, font_size)
        bbox = draw.textbbox((0, 0), "Ay", font=ref_font)
        line_height = (bbox[3] - bbox[1]) + 12

        total_height = len(lines) * line_height
        widest_line = max(
            (text_run_width(line, BOLD_CHAIN, font_size, draw) for line in lines),
            default=0,
        )

        if total_height < CARD_HEIGHT - 180 and widest_line <= max_text_width:
            break
        font_size -= 2

    total_height = len(lines) * line_height
    y = (CARD_HEIGHT - total_height) // 2
    for line in lines:
        draw_mixed_text(draw, (text_x, y), line, BOLD_CHAIN, font_size, "white")
        y += line_height

    # --- author name, centered under the quote block ---
    name_size = 32
    name_text = f"— {author_name}"
    name_width = text_run_width(name_text, REGULAR_CHAIN, name_size, draw)
    draw_mixed_text(
        draw,
        (text_x + (max_text_width - name_width) / 2, y + 30),
        name_text,
        REGULAR_CHAIN,
        name_size,
        (180, 180, 180),
    )

    buf = io.BytesIO()
    card.save(buf, format="PNG")
    buf.seek(0)
    return buf


@client.event
async def on_ready():
    print(f"Logged in as {client.user} — ready to make quotes v5.")


@client.event
async def on_message(message: discord.Message):
    if message.author.bot:
        return

    content = message.content.strip()
    if content != PREFIX and not content.startswith(PREFIX + " "):
        return

    typed_text = content[len(PREFIX):].strip()  # non-empty if user typed text after .quote

    if typed_text:
        # Mode 2: ".quote some text" — quote the typed text, attributed to the sender
        author = message.author
        quote_text = typed_text
    elif message.reference is not None:
        # Mode 1: bare ".quote" as a reply — quote the message being replied to
        try:
            quoted_msg = await message.channel.fetch_message(message.reference.message_id)
        except discord.NotFound:
            await message.reply("Couldn't find that message anymore.")
            return
        if not quoted_msg.content:
            await message.reply("That message has no text to quote (maybe it's just an image/embed?).")
            return
        author = quoted_msg.author
        quote_text = quoted_msg.content
    else:
        await message.reply(
            f"Reply to a message with `{PREFIX}`, or type `{PREFIX} your text` to quote yourself."
        )
        return

    avatar_url = str(author.display_avatar.replace(size=512).url)

    async with aiohttp.ClientSession() as session:
        avatar_bytes = await fetch_avatar_bytes(session, avatar_url)

    card_buf = build_quote_card(avatar_bytes, author.display_name, quote_text)

    await message.channel.send(file=discord.File(card_buf, filename="quote.png"))


if __name__ == "__main__":
    if not TOKEN:
        raise SystemExit(
            "Set your bot token first:  export DISCORD_BOT_TOKEN='your-token-here'"
        )
    client.run(TOKEN)
