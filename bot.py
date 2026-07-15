"""
Make It Quote — Discord bot
----------------------------
Reply to any message and type:  @YourBot make it quote
The bot grabs the message you replied to, renders it as a styled
black-and-white "quote card" (grayscale avatar + italic text), and
posts the image back in the channel.

100% free to run — no paid API, no paid hosting required
(see README.md for free hosting options).

Requirements: discord.py, Pillow, aiohttp, requests
    pip install -U discord.py Pillow aiohttp
"""

import io
import os
import textwrap

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

# DejaVu Sans is commonly preinstalled on Linux hosts; falls back to
# Pillow's built-in default font if not found (still works, just plainer).
FONT_NAME = ImageFont.truetype(
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 34
) if os.path.exists("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf") else ImageFont.load_default()

# ---------------------------------------------------------------------------
# INTENTS — message content intent MUST also be enabled in the Dev Portal
# ---------------------------------------------------------------------------
intents = discord.Intents.default()
intents.message_content = True
client = discord.Client(intents=intents)


async def fetch_avatar_bytes(session: aiohttp.ClientSession, url: str) -> bytes:
    async with session.get(url) as resp:
        return await resp.read()


def build_quote_card(avatar_bytes: bytes, author_name: str, quote_text: str) -> io.BytesIO:
    # --- avatar: grayscale, cropped to a square, faded on the right edge ---
    avatar = Image.open(io.BytesIO(avatar_bytes)).convert("RGB")
    avatar = ImageOps.fit(avatar, (AVATAR_SIZE, CARD_HEIGHT))
    avatar = ImageOps.grayscale(avatar).convert("RGB")

    card = Image.new("RGB", (CARD_WIDTH, CARD_HEIGHT), "black")
    card.paste(avatar, (0, 0))

    # gradient fade from black (right side of avatar) into pure black background
    fade = Image.new("L", (AVATAR_SIZE, CARD_HEIGHT), 0)
    fade_draw = ImageDraw.Draw(fade)
    fade_width = 220
    for x in range(fade_width):
        alpha = int(255 * (x / fade_width))
        fade_draw.line([(AVATAR_SIZE - fade_width + x, 0), (AVATAR_SIZE - fade_width + x, CARD_HEIGHT)], fill=alpha)
    black_layer = Image.new("RGB", (AVATAR_SIZE, CARD_HEIGHT), "black")
    card.paste(black_layer, (0, 0), fade)

    # --- text ---
    draw = ImageDraw.Draw(card)
    text_x = AVATAR_SIZE - 40
    max_text_width_chars = 30

    wrapped = textwrap.fill(f"\u201c{quote_text}\u201d", width=max_text_width_chars)
    lines = wrapped.split("\n")

    # shrink font if the quote is long so it still fits vertically
    font_size = 54
    while font_size > 22:
        font = ImageFont.truetype(
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Oblique.ttf", font_size
        ) if os.path.exists("/usr/share/fonts/truetype/dejavu/DejaVuSans-Oblique.ttf") else ImageFont.load_default()
        line_height = font_size + 14
        total_height = line_height * len(lines)
        if total_height < CARD_HEIGHT - 160:
            break
        font_size -= 4
        wrapped = textwrap.fill(f"\u201c{quote_text}\u201d", width=max_text_width_chars + (54 - font_size) // 2)
        lines = wrapped.split("\n")

    total_height = line_height * len(lines)
    y = (CARD_HEIGHT - total_height) // 2 - 20
    for line in lines:
        draw.text((text_x, y), line, font=font, fill="white")
        y += line_height

    # author name, right-aligned under the quote
    name_text = f"— {author_name}"
    bbox = draw.textbbox((0, 0), name_text, font=FONT_NAME)
    name_w = bbox[2] - bbox[0]
    draw.text((CARD_WIDTH - name_w - 40, y + 20), name_text, font=FONT_NAME, fill="#B0B0B0")

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
