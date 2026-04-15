import os
import discord
from discord.ext import commands, tasks
import requests
from bs4 import BeautifulSoup
import json
import re
import threading
from flask import Flask

app = Flask(__name__)

@app.route('/')
def home():
    return """
    <h1>🐾 PokeTimez-Amazon-Restock Bot is ALIVE! 🐾</h1>
    <p>New Pokémon card drops and restocks from Amazon.com are being watched 24/7 and sent straight to your Discord!</p>
    """

intents = discord.Intents.default()  # NO privileged intent needed anymore
bot = discord.Client(intents=intents)  # Using Client + tree for slash commands
tree = discord.app_commands.CommandTree(bot)

notification_channel_id = None
SEEN_FILE = 'seen_products.json'
MONITORED_FILE = 'monitored_products.json'

def load_seen():
    try:
        if os.path.exists(SEEN_FILE):
            with open(SEEN_FILE, 'r') as f:
                return set(json.load(f))
        return set()
    except:
        return set()

def save_seen(seen):
    try:
        with open(SEEN_FILE, 'w') as f:
            json.dump(list(seen), f)
    except:
        pass

def load_monitored():
    try:
        if os.path.exists(MONITORED_FILE):
            with open(MONITORED_FILE, 'r') as f:
                return json.load(f)
        return {}
    except:
        return {}

def save_monitored(monitored):
    try:
        with open(MONITORED_FILE, 'w') as f:
            json.dump(monitored, f)
    except:
        pass

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
}

def scrape_search():
    url = "https://www.amazon.com/s?k=pokemon+cards&i=toys-and-games"
    try:
        response = requests.get(url, headers=HEADERS, timeout=10)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')
        products = []
        for item in soup.select('[data-asin]')[:15]:
            asin = item.get('data-asin')
            if not asin:
                continue
            title_tag = item.select_one('h2 a span')
            title = title_tag.get_text(strip=True) if title_tag else "Unknown Pokémon Card"
            link_tag = item.select_one('h2 a')
            link = f"https://www.amazon.com{link_tag['href']}" if link_tag else ""
            price_tag = item.select_one('.a-price .a-offscreen')
            price = price_tag.get_text(strip=True) if price_tag else "Price N/A"
            img_tag = item.select_one('img')
            img = img_tag['src'] if img_tag and 'src' in img_tag.attrs else ""
            products.append({'asin': asin, 'title': title, 'link': link, 'price': price, 'img': img})
        return products
    except Exception as e:
        print(f"Search error: {e}")
        return []

def get_product_status(url):
    try:
        response = requests.get(url, headers=HEADERS, timeout=10)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')
        title_tag = soup.find('span', id='productTitle')
        title = title_tag.get_text(strip=True) if title_tag else "Unknown Product"
        avail = "Unknown"
        avail_section = soup.find('div', id='availability')
        if avail_section:
            avail_text = avail_section.get_text(strip=True).lower()
            if any(word in avail_text for word in ['in stock', 'available', 'ships from']):
                avail = "In Stock"
            elif any(word in avail_text for word in ['unavailable', 'out of stock']):
                avail = "Out of Stock"
        else:
            if any(word in response.text.lower() for word in ['add to cart', 'in stock']):
                avail = "In Stock"
        price_tag = soup.select_one('.a-price .a-offscreen')
        price = price_tag.get_text(strip=True) if price_tag else "N/A"
        return {'title': title, 'availability': avail, 'price': price}
    except Exception as e:
        print(f"Product error: {e}")
        return {'title': "Error", 'availability': "Error", 'price': "N/A"}

@bot.event
async def on_ready():
    print(f'{bot.user} is ready and hunting Pokémon cards on Amazon!')
    await tree.sync()  # Registers the slash commands
    check_new_drops.start()
    check_monitored_restock.start()

@tasks.loop(minutes=45)
async def check_new_drops():
    if not notification_channel_id: return
    channel = bot.get_channel(notification_channel_id)
    if not channel: return
    new_products = scrape_search()
    seen = load_seen()
    posted = 0
    for prod in new_products:
        if prod['asin'] in seen: continue
        embed = discord.Embed(title="🆕 NEW POKÉMON DROP ON AMAZON!", description=prod['title'], url=prod['link'], color=0x00ff00)
        embed.add_field(name="Price", value=prod['price'], inline=True)
        if prod['img']: embed.set_image(url=prod['img'])
        embed.set_footer(text="PokeTimez-Amazon-Restock Bot")
        await channel.send(embed=embed)
        seen.add(prod['asin'])
        posted += 1
        if posted >= 3: break
    if posted > 0:
        save_seen(seen)

@tasks.loop(minutes=15)
async def check_monitored_restock():
    if not notification_channel_id: return
    channel = bot.get_channel(notification_channel_id)
    if not channel: return
    monitored = load_monitored()
    updated = False
    for asin, data in list(monitored.items()):
        status = get_product_status(data['url'])
        current_available = status['availability'] == "In Stock"
        if current_available and not data.get('last_available', False):
            embed = discord.Embed(title="🔥 RESTOCK ALERT! 🔥", description=f"{status['title']}\n**NOW IN STOCK!**", url=data['url'], color=0xff0000)
            embed.add_field(name="Price", value=status['price'], inline=True)
            embed.set_footer(text="PokeTimez-Amazon-Restock Bot • Grab it fast!")
            await channel.send(embed=embed)
            monitored[asin]['last_available'] = True
            updated = True
        elif not current_available and data.get('last_available', True):
            monitored[asin]['last_available'] = False
            updated = True
        monitored[asin]['title'] = status['title']
        monitored[asin]['price'] = status['price']
    if updated:
        save_monitored(monitored)

@tree.command(name="setchannel", description="Tell the bot to post all Pokémon alerts in this channel")
async def setchannel(interaction: discord.Interaction):
    global notification_channel_id
    notification_channel_id = interaction.channel.id
    await interaction.response.send_message(f"✅ All Pokémon card alerts will now be posted right here in {interaction.channel.mention}!")

@tree.command(name="monitor", description="Watch a specific Amazon Pokémon product for restocks")
async def monitor(interaction: discord.Interaction, url: str):
    if not notification_channel_id:
        await interaction.response.send_message("Please run **/setchannel** first in the channel you want alerts!")
        return
    asin_match = re.search(r'/dp/([A-Z0-9]{10})', url)
    if not asin_match:
        await interaction.response.send_message("❌ Oops! Use a full Amazon link like https://amazon.com/dp/B0ABC12345")
        return
    asin = asin_match.group(1)
    status = get_product_status(url)
    if status['title'] == "Error":
        await interaction.response.send_message("❌ Couldn't reach that product. Double-check the URL!")
        return
    monitored = load_monitored()
    monitored[asin] = {'url': url, 'last_available': status['availability'] == "In Stock", 'title': status['title'], 'price': status['price']}
    save_monitored(monitored)
    await interaction.response.send_message(f"✅ Now watching **{status['title']}** for restocks! Current status: {status['availability']}")

@tree.command(name="listmonitored", description="See all Pokémon items being watched for restocks")
async def listmonitored(interaction: discord.Interaction):
    monitored = load_monitored()
    if not monitored:
        await interaction.response.send_message("No items being watched yet. Use **/monitor <amazon-url>**")
        return
    msg = "**📋 Currently monitoring these Pokémon items:**\n"
    for data in monitored.values():
        status = "✅ In Stock" if data.get('last_available') else "❌ Out of Stock"
        msg += f"• [{data['title']}]({data['url']}) — {status}\n"
    await interaction.response.send_message(msg)

def run_discord_bot():
    token = os.environ.get('DISCORD_TOKEN')
    if not token:
        print("❌ DISCORD_TOKEN is missing! Add it in Render settings.")
        return
    bot.run(token)

if __name__ == "__main__":
    bot_thread = threading.Thread(target=run_discord_bot)
    bot_thread.daemon = True
    bot_thread.start()
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
