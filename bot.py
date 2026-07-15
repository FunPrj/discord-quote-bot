"""
Make It Quote — Discord bot
----------------------------
Reply to any message and type:  .quote
The bot grabs the message you replied to, renders it as a styled
"quote card" (color avatar + wrapped quote text), and posts the
image back in the channel.

100% free to run — no paid API, no paid hosting required
(see README.md for free hosting options).

Requirements: discord.py, Pillow, aiohttp, requests
    pip install -U discord.py Pillow aiohttp

Fonts:
    For best results, drop these two files next to this script:
        Poppins-SemiBold.ttf
        Poppins-Regular.ttf
    (e.g. from https://fonts.google.com/specimen/Poppins)
    If they're not found, the bot falls back to DejaVu Sans so it
    still runs out of the box.
"""

import io
import os

import aiohttp
import discord
from PIL import Image, ImageDraw, ImageFont, ImageOps

# ---------------------------------------------------------------------------
# CONFIG
# ---------------------------------------------------------------------------
TOKEN = os.environ.get("DISCORD_BOT_TOKEN")  # set this as an env variable, never hardcode it
PREFIX = ".quote"  # trigger command

CARD_WIDTH = 1200
CARD_HEIGHT = 675
AVATAR_SIZE = 675  # avatar takes the left square, text sits on the right

# --- Fix 2: nicer display font, with a safe fallback if the .ttf files
# aren't present next to the script -------------------------------------
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
FONT_PATH = os.path.join(SCRIPT_DIR, "Poppins-SemiBold.ttf")
FONT_REGULAR = os.path.join(SCRIPT_DIR, "Poppins-Regular.ttf")

if not os.path.exists(FONT_PATH):
    FONT_PATH = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
if not os.path.exists(FONT_REGULAR):
    FONT_REGULAR = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"

FONT_NAME = ImageFont.truetype(FONT_PATH, 34) if os.path.exists(FONT_PATH) else ImageFont.load_default()

# ---------------------------------------------------------------------------
# INTENTS — message content intent MUST also be enabled in the Dev Portal
# ---------------------------------------------------------------------------
intents = discord.Intents.default()
intents.message_content = True
client = discord.Client(intents=intents)


async def fetch_avatar_bytes(session: aiohttp.ClientSession, url: str) -> bytes:
    async with session.get(url) as resp:
        return await resp.read()


def wrap_text(text, font, max_width, draw):
    """Fix 3: wrap by actual rendered pixel width instead of character count."""
    words = text.split()
    lines = []
    current = ""

    for word in words:
        test = current + (" " if current else "") + word
        if draw.textlength(test, font=font) <= max_width:
            current = test
        else:
            if current:
                lines.append(current)
            current = word

    if current:
        lines.append(current)

    return lines


def build_quote_card(avatar_bytes: bytes, author_name: str, quote_text: str) -> io.BytesIO:
    # --- avatar: color, cropped to a square, faded on the right edge ---
    # Fix 1: keep the avatar in full color (grayscale conversion removed).
    avatar = Image.open(io.BytesIO(avatar_bytes)).convert("RGB")
    avatar = ImageOps.fit(avatar, (AVATAR_SIZE, CARD_HEIGHT))

    card = Image.new("RGB", (CARD_WIDTH, CARD_HEIGHT), "black")
    card.paste(avatar, (0, 0))

    # --- Fix 8: smoother fade from the avatar into the black background ---
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
    # Fix 6: give the text more breathing room instead of hugging the avatar
    text_x = 720
    max_text_width = 470

    # Fix 4: font sizing loop now uses pixel-width wrapping
    font_size = 62
    lines = []
    line_height = 0
    font = None
    while font_size >= 30:
        font = ImageFont.truetype(FONT_PATH, font_size) if os.path.exists(FONT_PATH) else ImageFont.load_default()
        lines = wrap_text(f"\u201c{quote_text}\u201d", font, max_text_width, draw)

        bbox = draw.textbbox((0, 0), "Ay", font=font)
        line_height = (bbox[3] - bbox[1]) + 12

        total_height = len(lines) * line_height
        if total_height < CARD_HEIGHT - 180:
            break
        font_size -= 2

    total_height = len(lines) * line_height
    # Fix 5: perfectly centered vertically (no extra -20 offset)
    y = (CARD_HEIGHT - total_height) // 2
    for line in lines:
        draw.text((text_x, y), line, font=font, fill="white")
        y += line_height

    # --- Fix 7: author name, right-aligned and consistently placed
    # under the quote block ---
    name_font = ImageFont.truetype(FONT_REGULAR, 32) if os.path.exists(FONT_REGULAR) else ImageFont.load_default()
    name_text = f"— {author_name}"
    bbox = draw.textbbox((0, 0), name_text, font=name_font)
    name_width = bbox[2] - bbox[0]
    draw.text(
        (text_x + max_text_width - name_width, y + 30),
        name_text,
        fill=(180, 180, 180),
        font=name_font,
    )

    buf = io.BytesIO()
    card.save(buf, format="PNG")
    buf.seek(0)
    return buf


@client.event
async def on_ready():
    print(f"Logged in as {client.user} — ready to make quotes.")


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
