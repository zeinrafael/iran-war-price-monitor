"""
warprices/scrapers/commodities_scraper.py

Fetches commodity futures prices from Yahoo Finance (free, no key needed)
and updates data/commodities.json.

Run daily by GitHub Actions.

Yahoo Finance tickers used:
  BZ=F   Brent Crude futures
  CL=F   WTI Crude futures
  NG=F   Henry Hub Natural Gas futures (NYMEX)
  ZC=F   Corn futures (CBOT)
  ZS=F   Soybean futures (CBOT)
  ZW=F   Wheat (Chicago SRW) futures (CBOT)
  ZL=F   Soybean Oil futures (CBOT)

TTF gas and fertiliser require web scraping (no clean free API).

Install: pip install requests beautifulsoup4 lxml
"""

import json, logging, re
from datetime import datetime, timezone
from pathlib import Path
import requests

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

DATA_DIR = Path(__file__).parent.parent / "data"
COMMODITIES_JSON = DATA_DIR / "commodities.json"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; WarPriceMonitor/1.0; research use)"
}

# Yahoo Finance ticker mapping
YAHOO_TICKERS = {
    "brent":     "BZ=F",
    "wti":       "CL=F",
    "henry_hub": "NG=F",
    "corn":      "ZC=F",
    "soybeans":  "ZS=F",
    "wheat":     "ZW=F",
    "soy_oil":   "ZL=F",
}

def load_data():
    with open(COMMODITIES_JSON) as f:
        return json.load(f)

def save_data(data):
    data["meta"]["last_updated"] = datetime.now(timezone.utc).isoformat()
    with open(COMMODITIES_JSON, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    log.info(f"Saved {COMMODITIES_JSON}")

def fetch_yahoo_price(ticker):
    """
    Fetch current futures price from Yahoo Finance.
    Uses the summary endpoint — no API key needed.
    Returns float price or None.
    """
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?interval=1d&range=1d"
    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        r.raise_for_status()
        d = r.json()
        # Extract latest close price
        result = d.get("chart", {}).get("result", [])
        if result:
            meta = result[0].get("meta", {})
            price = meta.get("regularMarketPrice") or meta.get("previousClose")
            if price:
                return float(price)
    except Exception as e:
        log.warning(f"  Yahoo Finance fetch failed for {ticker}: {e}")
    return None

def fetch_ttf_price():
    """
    Fetch TTF European gas price.
    Try Trading Economics or ICE data page.
    Returns price in EUR/MWh or None.
    """
    # Try Trading Economics
    url = "https://tradingeconomics.com/commodity/eu-natural-gas"
    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(r.text, "lxml")
        # Look for price in meta or data elements
        text = soup.get_text()
        match = re.search(r"EU Natural Gas.*?(\d+\.\d+)", text[:2000])
        if match:
            return float(match.group(1))
    except Exception as e:
        log.warning(f"  TTF fetch failed: {e}")
    return None

def update_commodity_price(data, section, commodity_id, new_price):
    """Update a commodity's current price and append to history."""
    items = data.get(section, [])
    for item in items:
        if item["id"] == commodity_id:
            old_price = item["now"]
            item["now"] = round(new_price, 4)

            # Update history — append today if date not already there
            today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            history = item.get("history", [])

            # Check if today already has an entry
            if history and isinstance(history[-1], dict):
                if history[-1].get("date") == today:
                    history[-1]["price"] = round(new_price, 4)
                else:
                    history.append({"date": today, "price": round(new_price, 4)})
            elif history and isinstance(history[-1], (int, float)):
                # Legacy format — just update last value
                history[-1] = round(new_price, 4)

            if abs(old_price - new_price) > 0.001:
                log.info(f"  Updated {commodity_id}: {old_price} → {new_price}")
            else:
                log.info(f"  {commodity_id}: no change ({new_price})")
            return True
    return False

def run():
    log.info("=== War Prices Commodities Scraper starting ===")
    data = load_data()

    # ── Energy futures via Yahoo Finance ──────────────────────────────────────
    energy_map = {
        "brent":     ("energy", "BZ=F"),
        "wti":       ("energy", "CL=F"),
        "henry_hub": ("energy", "NG=F"),
    }

    for commodity_id, (section, ticker) in energy_map.items():
        log.info(f"Fetching {commodity_id} ({ticker})...")
        price = fetch_yahoo_price(ticker)
        if price:
            update_commodity_price(data, section, commodity_id, price)
        else:
            log.warning(f"  Could not fetch {commodity_id}")

    # ── Grains via Yahoo Finance ───────────────────────────────────────────────
    grains_map = {
        "corn":      "ZC=F",
        "soybeans":  "ZS=F",
        "wheat":     "ZW=F",
        "soy_oil":   "ZL=F",
    }

    for commodity_id, ticker in grains_map.items():
        log.info(f"Fetching {commodity_id} ({ticker})...")
        price = fetch_yahoo_price(ticker)
        if price:
            update_commodity_price(data, "agriculture", commodity_id, price)
        else:
            log.warning(f"  Could not fetch {commodity_id}")

    # ── TTF European gas ───────────────────────────────────────────────────────
    log.info("Fetching TTF European gas...")
    ttf_price = fetch_ttf_price()
    if ttf_price:
        update_commodity_price(data, "energy", "ttf", ttf_price)
    else:
        log.warning("  TTF price not available — keeping existing value")

    # ── Fertiliser — manual/static for now ────────────────────────────────────
    # Urea prices require subscription data (Green Markets, ICIS)
    # Will remain static until manually updated via admin page
    log.info("  Fertiliser prices: static (require manual update from Green Markets/ICIS)")

    save_data(data)
    log.info("=== Done ===")

if __name__ == "__main__":
    run()
