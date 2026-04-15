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

# ====================== SCRAPING (Cloudflare-proof with Scrape.do) ======================
def _scrape_with_api(url):
    token = os.environ.get('SCRAPE_DO_TOKEN')
    if not token:
        print("❌ SCRAPE_DO_TOKEN missing! Add it in Render Environment settings.")
        return None
    try:
        time.sleep(random.uniform(1, 2.5))
        encoded_url = urllib.parse.quote_plus(url)
        api_url = f"https://api.scrape.do/?token={token}&url={encoded_url}&super=true"
        response = requests.get(api_url, timeout=20)
        response.raise_for_status()
        return response.text
    except Exception as e:
        print(f"Scrape.do API error: {e}")
        return None

def scrape_search():
    url = "https://www.amazon.com/s?k=pokemon+cards&i=toys-and-games"
    html = _scrape_with_api(url)
    if not html:
        return []
    try:
        soup = BeautifulSoup(html, 'html.parser')
        products = []
        items = soup.select('[data-asin]')[:15] or soup.select('.s-result-item')
        for item in items:
            asin = item.get('data-asin')
            if not asin:
                continue
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
        print(f"Search parsing error: {e}")
        return []

def get_product_status(url):
    html = _scrape_with_api(url)
    if not html:
        return {'title': "Error", 'availability': "Error", 'price': "N/A"}
    try:
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
        print(f"Product parsing error: {e}")
        return {'title': "Error",​​​​​​​​​​​​​​​​​​​​​​​​​​​​​​​​​​​​​​​​​​​​​​​​​​
