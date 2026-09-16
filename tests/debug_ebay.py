"""Debug eBay HTML structure."""
import sys
sys.path.insert(0, '.')
import asyncio
from scrapers.ebay import EbayScraper

async def debug():
    scraper = EbayScraper()
    html = await scraper.fetch('https://www.ebay.co.uk/sch/i.html?_nkw=stainless+steel+water+bottle&LH_BIN=1&LH_PrefLoc=1')
    soup = scraper.parse(html)
    for sel in ['li.s-item', 'div.s-item__wrapper', 'li[data-view]', 'ul.srp-results li', 'div.srp-river-results li', 'div.srp-river-results > ul > li']:
        items = soup.select(sel)
        print(f'{sel}: {len(items)} items')
    if 'captcha' in str(soup).lower() or 'robot' in str(soup).lower():
        print('CAPTCHA/BOT DETECTED')
    title = soup.select_one('title')
    print(f'Page title: {title.get_text() if title else "none"}')
    await scraper.close()

asyncio.run(debug())
