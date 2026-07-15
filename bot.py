import io
import os
import discord
import aiohttp
from PIL import Image, ImageDraw, ImageFont, ImageOps

# ---------------------------------------------------------------------------
# CONFIG
# ---------------------------------------------------------------------------
TOKEN = os.environ.get("DISCORD_BOT_TOKEN")
PREFIX = ".quote"
FONT_BOLD = "Poppins-SemiBold.ttf"
FONT_REGULAR = "Poppins-Regular.ttf"

CARD_WIDTH = 1200
CARD_HEIGHT = 675
AVATAR_SIZE = 675

# ---------------------------------------------------------------------------
# INTENTS
# ---------------------------------------------------------------------------
intents = discord.Intents.default()
intents.message_content = True
client = discord.Client(intents=intents)

def wrap_text(text, font, max_width, draw):
    words = text.split()
    lines = []
    current = ""
    for word in words:
        test = current + (" " if current else "") + word
        if draw.textlength(test, font=font) <= max_width:
            current = test
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines

async def fetch_avatar_bytes(session, url):
    async with session.get(url) as resp:
        return await resp.read()

def build_quote_card(avatar_bytes, author_name, quote_text):
    # Avatar setup
    avatar = Image.open(io.BytesIO(avatar_bytes)).convert("RGB")
    avatar = ImageOps.fit(avatar, (AVATAR_SIZE, CARD_HEIGHT))
    
    card = Image.new("RGB", (CARD_WIDTH, CARD_HEIGHT), "black")
    card.paste(avatar, (0, 0))

    # Improve fade
    fade_width = 180
    mask = Image.new("L", (fade_width, CARD_HEIGHT))
    for x in range(fade_width):
        alpha = int(255 * (x / fade_width))
        ImageDraw.Draw(mask).line([(x, 0), (x, CARD_HEIGHT)], fill=alpha)
    black = Image.new("RGB", (fade_width, CARD_HEIGHT), "black")
    card.paste(black, (AVATAR_SIZE - fade_width, 0), mask)

    # Text rendering
    draw = ImageDraw.Draw(card)
    text_x = 720
    
    font_size = 62
    lines = []
    font = None
    
    # Better font sizing and wrapping
    while font_size >= 30:
        font = ImageFont.truetype(FONT_BOLD, font_size)
        lines = wrap_text(f'“{quote_text}”', font, 470, draw)
        bbox = draw.textbbox((0, 0), "Ay", font=font)
        line_height = bbox[3] - bbox[1] + 12
        total_height = len(lines) * line_height
        if total_height < CARD_HEIGHT - 180:
            break
        font_size -= 2

    # Perfect vertical centering
    total_height = len(lines) * line_height
    y = (CARD_HEIGHT - total_height) // 2
    for line in lines:
        draw.text((text_x, y), line, font=font, fill="white")
        y += line_height

    # Author name
    name_font = ImageFont.truetype(FONT_REGULAR, 32)
    name_str = f"— {author_name}"
    bbox = draw.textbbox((0, 0), name_str, font=name_font)
    name_width = bbox[2] - bbox[0]
    draw.text((text_x + 470 - name_width, y + 30), name_str, fill=(180, 180, 180), font=name_font)

    buf = io.BytesIO()
    card.save(buf, format="PNG")
    buf.seek(0)
    return buf

@client.event
async def on_ready():
    print(f"Logged in as {client.user} — ready to make quotes.")

@client.event
async def on_message(message):
    if message.author.bot: return
    content = message.content.strip()
    if not content.startswith(PREFIX): return

    typed_text = content[len(PREFIX):].strip()
    if typed_text:
        author, quote_text = message.author, typed_text
    elif message.reference:
        quoted_msg = await message.channel.fetch_message(message.reference.message_id)
        if not quoted_msg.content: return
        author, quote_text = quoted_msg.author, quoted_msg.content
    else: return

    avatar_url = str(author.display_avatar.replace(size=512).url)
    async with aiohttp.ClientSession() as session:
        avatar_bytes = await fetch_avatar_bytes(session, avatar_url)
    
    card_buf = build_quote_card(avatar_bytes, author.display_name, quote_text)
    await message.channel.send(file=discord.File(card_buf, filename="quote.png"))

if __name__ == "__main__":
    if not TOKEN: raise SystemExit("Set DISCORD_BOT_TOKEN environment variable.")
    client.run(TOKEN)
