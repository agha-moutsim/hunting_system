"""Debug: test fetching a single eBay listing page."""
import sys
sys.path.insert(0, '.')
import requests

url = "https://www.ebay.co.uk/itm/385329859103"
headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-GB,en;q=0.9",
}
resp = requests.get(url, headers=headers, timeout=15)
print(f"Status: {resp.status_code}")
print(f"Length: {len(resp.text)}")
if "captcha" in resp.text.lower() or "robot" in resp.text.lower():
    print("BOT DETECTED")
else:
    print("NO BOT DETECTION")
# Check for key elements
from bs4 import BeautifulSoup
soup = BeautifulSoup(resp.text, "html.parser")
title = soup.select_one("h1.x-item-title__mainTitle")
price = soup.select_one("div.x-price-primary span")
print(f"Title element: {'YES' if title else 'NO'}")
print(f"Price element: {'YES' if price else 'NO'}")
if title:
    print(f"Title: {title.get_text(strip=True)[:80]}")
if price:
    print(f"Price: {price.get_text(strip=True)}")
