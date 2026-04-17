import os
import discord
from discord.ext import commands, tasks
import requests
from bs4 import BeautifulSoup
import json
import re
import threading
import time
import random
import urllib.parse
from flask import Flask

app = Flask(__name__)

@app.route('/')
def home():
    return """
    <h1>🐾 PokeTimez-Amazon-Restock Bot is ALIVE! 🐾</h1>
    <p>New Pokémon card drops and restocks from Amazon.com are being watched 24/7 and sent straight to your Discord!</p>
    """

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='!', intents=intents)

notification_channel_id = None
SEEN_FILE = 'seen_products.json'
MONITORED_FILE = 'monitored_products.json'

# ====================== PERSISTENCE ======================
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

# ====================== SCRAPING (3 automatic retries) ======================
def _scrape_with_api(url):
    token = os.environ.get('SCRAPE_DO_TOKEN')
    if not token:
        print("❌ SCRAPE_DO_TOKEN is MISSING in Render Environment!")
        return None
    for attempt in range(3):
        try:
            time.sleep(random.uniform(1.5, 3.5))
            encoded_url = urllib.parse.quote_plus(url)
            api_url = f"https://api.scrape.do/?token={token}&url={encoded_url}&super=true"
            response = requests.get(api_url, timeout=25)
            response.raise_for_status()
            return response.text
        except Exception as e:
            print(f"Scrape.do attempt {attempt+1}/3 failed for {url}: {e}")
            if attempt < 2:
                time.sleep(2 ** attempt)  # backoff
            else:
                return None
    return None

def scrape_search():
    try:
        url = "https://www.amazon.com/s?k=pokemon+cards&i=toys-and-games"
        html = _scrape_with_api(url)
        if not html: return []
        soup = BeautifulSoup(html, 'html.parser')
        products = []
        items = soup.select('[data-asin]')[:15] or soup.select('.s-result-item')
        for item in items:
            asin = item.get('data-asin')
            if not asin: continue
            title_tag = item.select_one('h2 a span') or item.select_one('h2 a') or item.select_one('.a-size-medium')
            title = title_tag.get_text(strip=True) if title_tag else "Unknown Pokémon Card"
            link_tag = item.select_one('h2 a') or item.select_one('a[href*="/dp/"]')
            link = f"https://www.amazon.com{link_tag['href']}" if link_tag and link_tag.get('href') else ""
            price_tag = item.select_one('.a-price .a-offscreen') or item.select_one('span.a-price-whole') or item.select_one('.a-color-price')
            price = price_tag.get_text(strip=True) if price_tag else "Price N/A"
            img_tag = item.select_one('img')
            img = img_tag['src'] if img_tag and 'src' in img_tag.attrs else ""
            products.append({'asin': asin, 'title': title, 'link': link, 'price': price, 'img': img})
        return products
    except Exception as e:
        print(f"scrape_search error: {e}")
        return []

def get_product_status(url):
    try:
        html = _scrape_with_api(url)
        if not html:
            return {'title': "Error", 'availability': "Error", 'price': "N/A"}
        soup = BeautifulSoup(html, 'html.parser')
        title_tag = soup.find('span', id='productTitle') or soup.find('h1', id='title')
        title = title_tag.get_text(strip=True) if title_tag else "Unknown Product"
        avail = "Unknown"
        avail_section = soup.find('div', id='availability') or soup.find('div', id='buybox')
        if avail_section:
            avail_text = avail_section.get_text(strip=True).lower()
            if any(word in avail_text for word in ['in stock', 'available', 'ships from', 'add to cart', 'buy now']):
                avail = "In Stock"
            elif any(word in avail_text for word in ['unavailable', 'out of stock', 'currently unavailable']):
                avail = "Out of Stock"
        else:
            page_text = html.lower()
            if any(word in page_text for word in ['add to cart', 'in stock', 'ships from amazon']):
                avail = "In Stock"
            elif any(word in page_text for word in ['out of stock', 'unavailable']):
                avail = "Out of Stock"
        price_tag = soup.select_one('.a-price .a-offscreen') or soup.select_one('span.a-price-whole')
        price = price_tag.get_text(strip=True) if price_tag else "N/A"
        return {'title': title, 'availability': avail, 'price': price}
    except Exception as e:
        print(f"get_product_status error for {url}: {e}")
        return {'title': "Error", 'availability': "Error", 'price': "N/A"}

# ====================== TASKS ======================
@bot.event
async def on_ready():
    print(f'✅ {bot.user} is ready and hunting Pokémon cards on Amazon!')
    check_new_drops.start()
    check_monitored_restock.start()

@tasks.loop(minutes=45)
async def check_new_drops():
    try:
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
            print(f"Posted {posted} new drops")
    except Exception as e:
        print(f"check_new_drops error: {e}")

@tasks.loop(minutes=15)
async def check_monitored_restock():
    try:
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
    except Exception as e:
        print(f"check_monitored_restock error: {e}")

# ====================== COMMANDS ======================
@bot.command()
async def setchannel(ctx):
    global notification_channel_id
    notification_channel_id = ctx.channel.id
    await ctx.send(f"✅ All Pokémon card alerts will now be posted right here in {ctx.channel.mention}!")

@bot.command()
async def monitor(ctx, url: str):
    try:
        if not notification_channel_id:
            await ctx.send("Please run **!setchannel** first!")
            return
        asin_match = re.search(r'/dp/([A-Z0-9]{10})', url)
        if not asin_match:
            await ctx.send("❌ Use a full Amazon link like https://amazon.com/dp/B0ABC12345")
            return
        asin = asin_match.group(1)
        status = get_product_status(url)
        if status['title'] == "Error":
            await ctx.send("❌ Couldn't reach that product right now. Try again in a minute.")
            return
        monitored = load_monitored()
        monitored[asin] = {'url': url, 'last_available': status['availability'] == "In Stock", 'title': status['title'], 'price': status['price']}
        save_monitored(monitored)
        await ctx.send(f"✅ Now watching **{status['title']}** for restocks! Current status: {status['availability']}")
    except Exception as e:
        print(f"❌ !monitor error: {e}")
        await ctx.send("❌ Error in !monitor. Check Render logs.")

@bot.command()
async def listmonitored(ctx):
    try:
        monitored = load_monitored()
        if not monitored:
            await ctx.send("No items being watched yet. Use **!monitor <amazon-url>**")
            return
        msg = "**📋 Currently monitoring these Pokémon items:**\n"
        for data in monitored.values():
            status = "✅ In Stock" if data.get('last_available') else "❌ Out of Stock"
            msg += f"• [{data['title']}]({data['url']}) — {status}\n"
        await ctx.send(msg)
    except Exception as e:
        print(f"❌ !listmonitored error: {e}")
        await ctx.send("❌ Error listing monitored items.")

@bot.command()
async def ping(ctx):
    await ctx.send("🏓 Pong! Bot is alive and responding.")

def run_flask():
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)

def run_discord_bot():
    token = os.environ.get('DISCORD_TOKEN')
    if not token:
        print("❌ DISCORD_TOKEN missing!")
        return
    while True:
        try:
            print("🔄 Attempting Discord login...")
            bot.run(token, reconnect=True)
            break
        except Exception as e:
            error_str = str(e).lower()
            if "429" in error_str or "1015" in error_str or "rate limited" in error_str:
                wait = 300
                print(f"⚠️ Rate limit hit — waiting {wait//60} minutes...")
                time.sleep(wait)
            else:
                print(f"❌ Login error: {e}")
                time.sleep(60)

if __name__ == "__main__":
    print("🚀 Starting PokeTimez Amazon Restock Bot (stable mode)...")
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()
    run_discord_bot()
