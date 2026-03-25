"""
warprices/scrapers/food_scraper.py

Updates food basket prices from Numbeo and national CPI data.
Run weekly (Mondays) by GitHub Actions.

Note: Food prices update monthly via official CPI releases.
This scraper primarily refreshes Numbeo data (continuous crowdsourced updates)
and flags when official CPI data may be stale.

Install: pip install requests beautifulsoup4 lxml
"""

import json, logging, re
from datetime import datetime, timezone
from pathlib import Path
import requests
from bs4 import BeautifulSoup

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

DATA_DIR = Path(__file__).parent.parent / "data"
FOOD_JSON = DATA_DIR / "food.json"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; WarPriceMonitor/1.0; research use)"}

NUMBEO_ITEMS = {
    "rice":  115,   # White Rice (1kg)
    "eggs":  11,    # Eggs (12 large)
    "beef":  121,   # Beef round (1kg)
    "flour": 114,   # Flour (1kg) — Numbeo item ID
}

NUMBEO_CITIES = {
    "us": "Washington-DC", "uk": "London", "fr": "Paris", "es": "Madrid",
    "de": "Berlin", "at": "Vienna", "br": "Sao-Paulo", "cl": "Santiago",
    "za": "Johannesburg", "ke": "Nairobi", "ma": "Casablanca", "eg": "Cairo",
    "lb": "Beirut", "in": "New-Delhi", "ph": "Manila", "id": "Jakarta",
    "au": "Sydney", "nz": "Wellington", "cn": "Beijing", "kr": "Seoul", "jp": "Tokyo",
}

def load_data():
    with open(FOOD_JSON) as f:
        return json.load(f)

def save_data(data):
    data["meta"]["last_updated"] = datetime.now(timezone.utc).isoformat()
    with open(FOOD_JSON, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    log.info(f"Saved {FOOD_JSON}")

def fetch(url, timeout=15):
    try:
        r = requests.get(url, headers=HEADERS, timeout=timeout)
        r.raise_for_status()
        return r
    except Exception as e:
        log.warning(f"Fetch failed {url}: {e}")
        return None

def scrape_numbeo_city(city_slug):
    """
    Fetch food prices for a city from Numbeo.
    Returns dict with rice, flour, eggs, beef prices in USD or None.
    """
    url = f"https://www.numbeo.com/cost-of-living/in/{city_slug}"
    r = fetch(url)
    if not r:
        return None

    try:
        soup = BeautifulSoup(r.text, "lxml")
        prices = {}

        # Find the markets table
        table = soup.find("table", {"class": "data_wide_table"})
        if not table:
            # Try alternative structure
            text = soup.get_text()
            patterns = {
                "rice":  r"White Rice.*?(\d+\.\d+)",
                "eggs":  r"Eggs.*?12.*?(\d+\.\d+)",
                "beef":  r"Beef.*?(\d+\.\d+)",
                "flour": r"Flour.*?(\d+\.\d+)",
            }
            for key, pattern in patterns.items():
                m = re.search(pattern, text)
                if m:
                    prices[key] = float(m.group(1))
            return prices if prices else None

        for row in table.find_all("tr"):
            cells = row.find_all("td")
            if len(cells) >= 2:
                item_name = cells[0].get_text(strip=True).lower()
                price_text = cells[1].get_text(strip=True)
                # Extract numeric price
                price_match = re.search(r"(\d+\.?\d*)", price_text.replace(",", ""))
                if price_match:
                    price = float(price_match.group(1))
                    if "rice" in item_name and "white" in item_name:
                        prices["rice"] = price
                    elif "egg" in item_name:
                        prices["eggs"] = price
                    elif "beef" in item_name or "red meat" in item_name:
                        prices["beef"] = price
                    elif "flour" in item_name:
                        prices["flour"] = price

        return prices if prices else None
    except Exception as e:
        log.warning(f"  Numbeo parse failed for {city_slug}: {e}")
        return None

def run():
    log.info("=== War Prices Food Scraper starting ===")
    data = load_data()

    for country in data["countries"]:
        if not country.get("auto_update", False):
            log.info(f"  Skipping {country['country']} (static/manual)")
            continue

        city_slug = NUMBEO_CITIES.get(country["id"])
        if not city_slug:
            log.info(f"  No Numbeo mapping for {country['id']}")
            continue

        log.info(f"  Scraping {country['country']} ({city_slug})...")
        prices = scrape_numbeo_city(city_slug)

        if prices:
            updated = []
            for key in ["rice", "flour", "eggs", "beef"]:
                if key in prices and prices[key] > 0:
                    old = country[key]["now"]
                    country[key]["now"] = round(prices[key], 2)
                    if abs(old - prices[key]) > 0.01:
                        updated.append(f"{key}: ${old:.2f}→${prices[key]:.2f}")
            if updated:
                log.info(f"    Updated: {', '.join(updated)}")
            else:
                log.info(f"    No changes detected")
        else:
            log.info(f"    No data retrieved — keeping existing values")

    save_data(data)
    log.info("=== Done ===")

if __name__ == "__main__":
    run()
