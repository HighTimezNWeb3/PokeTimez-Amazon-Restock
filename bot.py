import discord
from discord.ext import commands, tasks
import requests
from bs4 import BeautifulSoup
import json
import os
import asyncio

# Bot setup
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='!', intents=intents)

# File to save what we've already seen (so we don't spam the same card)
DATA_FILE = 'data.json'

# Global stuff
CHANNEL_ID = None
KNOWN_PRODUCTS = {}  # asin: {"title": , "availability": , "price": }

def load_data():
    global CHANNEL_ID, KNOWN_PRODUCTS
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, 'r') as f:
            data = json.load(f)
            CHANNEL_ID = data.get('channel_id')
            KNOWN_PRODUCTS = data.get('known_products', {})
    else:
        CHANNEL_ID = None
        KNOWN_PRODUCTS = {}

def save_data():
    data = {
        'channel_id': CHANNEL_ID,
        'known_products': KNOWN_PRODUCTS
    }
    with open(DATA_FILE, 'w') as f:
        json.dump(data, f)

@bot.event
async def on_ready():
    print(f'✅ {bot.user} is online and ready to catch Pokémon drops!')
    load_data()
    check_amazon.start()

# The magic loop that checks Amazon every 30 minutes
@tasks.loop(minutes=30)
async def check_amazon():
    if CHANNEL_ID is None:
        return
    channel = bot.get_channel(CHANNEL_ID)
    if not channel:
        return

    products = scrape_amazon_pokemon_cards()
    
    for product in products:
        asin = product['asin']
        old_data = KNOWN_PRODUCTS.get(asin)
        current_avail = product['availability']
        
        # NEW DROP!
        if asin not in KNOWN_PRODUCTS:
            await send_drop(channel, product, "🚀 **NEW DROP!**")
            KNOWN_PRODUCTS[asin] = product
        # RESTOCK!
        elif old_data and old_data['availability'] != "In Stock" and current_avail == "In Stock":
            await send_drop(channel, product, "🔄 **RESTOCK ALERT!**")
            KNOWN_PRODUCTS[asin] = product
        # Just update price/availability quietly
        else:
            KNOWN_PRODUCTS[asin] = product
    
    save_data()

async def send_drop(channel, product, title_prefix):
    embed = discord.Embed(
        title=f"{title_prefix} {product['title']}",
        url=product['link'],
        description=f"**Price:** {product['price']}\n**Stock:** {product['availability']}",
        color=0x00ff00
    )
    embed.set_footer(text="PokeTimez-Amazon-Restock • Powered by Amazon scraping")
    await channel.send(embed=embed)

def scrape_amazon_pokemon_cards():
    url = "https://www.amazon.com/s?k=pokemon+tcg+cards"  # Pokémon Trading Card Games only
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
        "Accept-Language": "en-US,en;q=0.9",
    }
    
    try:
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')
        
        products = []
        for item in soup.select('div[data-asin]'):
            asin = item.get('data-asin')
            if not asin:
                continue
                
            title_tag = item.select_one('h2 a span')
            title = title_tag.text.strip() if title_tag else "Unknown Pokémon Card"
            
            # Only keep actual Pokémon cards
            if 'pokemon' not in title.lower() and 'pokémon' not in title.lower():
                continue
                
            price_tag = item.select_one('.a-price .a-offscreen')
            price = price_tag.text.strip() if price_tag else "Price unavailable"
            
            link = "https://www.amazon.com" + item.select_one('a.a-link-normal')['href'] if item.select_one('a.a-link-normal') else ""
            
            # Simple stock check (Amazon changes this often - this works pretty well)
            item_text = item.text.lower()
            if any(x in item_text for x in ["in stock", "available", "ships from"]):
                availability = "In Stock ✅"
            elif any(x in item_text for x in ["out of stock", "temporarily unavailable"]):
                availability = "Out of Stock ❌"
            else:
                availability = "Check on Amazon"
            
            products.append({
                'asin': asin,
                'title': title[:100],  # keep it short
                'price': price,
                'link': link,
                'availability': availability
            })
        
        return products[:15]  # limit to top 15 to avoid spam
    
    except Exception as e:
        print(f"Scraping error (Amazon might be blocking): {e}")
        return []

# Command to tell the bot WHERE to post the drops
@bot.command(name='setchannel')
@commands.has_permissions(administrator=True)
async def setchannel(ctx, channel: discord.TextChannel):
    global CHANNEL_ID
    CHANNEL_ID = channel.id
    save_data()
    await ctx.send(f"✅ PokeTimez will now post all Pokémon card drops and restocks in {channel.mention}!")

# Run the bot
if __name__ == "__main__":
    token = os.getenv("DISCORD_TOKEN")
    if not token:
        print("❌ No DISCORD_TOKEN found! Add it in Render environment variables.")
    else:
        bot.run(token)