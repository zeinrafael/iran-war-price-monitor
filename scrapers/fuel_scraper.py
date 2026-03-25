"""
warprices/scrapers/fuel_scraper.py

Scrapes fuel prices from free public sources and updates data/fuel.json.
Run by GitHub Actions on schedule. Falls back gracefully if a source fails.

Sources used:
  - AAA (US daily)              : JSON API endpoint
  - EIA (US weekly)             : REST API (free, no key needed)
  - GOV.UK fuel stats (UK)      : CSV download
  - Fuel Finder UK (UK)         : JSON endpoint
  - GlobalPetrolPrices (multi)  : HTML parse (weekly Mon)
  - Reuters/FX rates            : For USD conversion

Install: pip install requests beautifulsoup4 lxml
"""

import json, os, sys, re, logging
from datetime import datetime, timezone
from pathlib import Path

import requests
from bs4 import BeautifulSoup

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

DATA_DIR = Path(__file__).parent.parent / "data"
FUEL_JSON = DATA_DIR / "fuel.json"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; WarPriceMonitor/1.0; research use)"
}

# ── helpers ──────────────────────────────────────────────────────────────────

def load_data():
    with open(FUEL_JSON) as f:
        return json.load(f)

def save_data(data):
    data["meta"]["last_updated"] = datetime.now(timezone.utc).isoformat()
    with open(FUEL_JSON, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    log.info(f"Saved {FUEL_JSON}")

def get_country(data, country_id):
    for c in data["countries"]:
        if c["id"] == country_id:
            return c
    return None

def gal_to_litre(price_per_gallon):
    """Convert USD/gallon to USD/litre."""
    return round(price_per_gallon / 3.785, 4)

def fetch(url, timeout=15):
    try:
        r = requests.get(url, headers=HEADERS, timeout=timeout)
        r.raise_for_status()
        return r
    except Exception as e:
        log.warning(f"Fetch failed {url}: {e}")
        return None

def get_fx_rate(currency):
    """
    Get USD exchange rate for a currency via exchangerate.host (free, no key).
    Returns float: 1 {currency} = X USD
    Falls back to 1.0 if unavailable.
    """
    try:
        r = requests.get(
            f"https://api.exchangerate.host/latest?base={currency}&symbols=USD",
            timeout=10
        )
        return r.json()["rates"]["USD"]
    except Exception as e:
        log.warning(f"FX rate fetch failed for {currency}: {e}")
        return None

# ── USA — AAA + EIA ───────────────────────────────────────────────────────────

def scrape_usa(data):
    """
    AAA publishes a JSON feed with national average gas and diesel.
    EIA publishes weekly CSV data (no API key needed).
    We prefer AAA for daily cadence; fall back to EIA.
    """
    log.info("Scraping USA (AAA + EIA)...")
    country = get_country(data, "us")
    if not country:
        return

    # --- AAA ---
    # AAA's public JSON endpoint used by their website widget
    aaa_url = "https://gasprices.aaa.com/api/?state=US"
    r = fetch(aaa_url)
    if r:
        try:
            d = r.json()
            # AAA returns cents per gallon in some endpoints; prices in USD in others
            # Structure: { "regular": "3.977", "diesel": "5.345", ... }
            reg = float(d.get("regular") or d.get("gas_price") or 0)
            diesel = float(d.get("diesel") or d.get("diesel_price") or 0)
            if reg > 1:  # sanity check — it's USD/gal not cents
                country["gasoline"] = gal_to_litre(reg)
                country["diesel"] = gal_to_litre(diesel)
                log.info(f"  USA AAA: gas ${reg:.3f}/gal → ${country['gasoline']:.4f}/L, diesel ${diesel:.3f}/gal → ${country['diesel']:.4f}/L")
                return
        except Exception as e:
            log.warning(f"  AAA parse failed: {e}")

    # --- EIA fallback — CSV download ---
    # EIA weekly gasoline: https://www.eia.gov/petroleum/gasdiesel/
    # Direct CSV endpoint for US regular gas weekly
    eia_gas_url = "https://www.eia.gov/dnav/pet/hist/LeafHandler.ashx?n=PET&s=EMM_EPMR_PTE_NUS_DPG&f=W"
    eia_diesel_url = "https://www.eia.gov/dnav/pet/hist/LeafHandler.ashx?n=pet&s=emd_epd2d_pte_nus_dpg&f=w"

    for fuel_type, url, key in [("gasoline", eia_gas_url, "gasoline"), ("diesel", eia_diesel_url, "diesel")]:
        r = fetch(url)
        if r:
            try:
                lines = r.text.strip().split("\n")
                # Format: Date,Price  — last non-empty line is most recent
                last = [l for l in lines if l.strip() and "," in l][-1]
                price_gal = float(last.split(",")[-1].strip())
                country[key] = gal_to_litre(price_gal)
                log.info(f"  USA EIA {fuel_type}: ${price_gal:.3f}/gal → ${country[key]:.4f}/L")
            except Exception as e:
                log.warning(f"  EIA {fuel_type} parse failed: {e}")

# ── UK — Fuel Finder UK ───────────────────────────────────────────────────────

def scrape_uk(data):
    """
    Fuel Finder UK publishes a JSON API with live UK average pump prices.
    Updated every 5 minutes from 7,441 stations.
    """
    log.info("Scraping UK (Fuel Finder)...")
    country = get_country(data, "uk")
    if not country:
        return

    url = "https://www.fuel-finder.uk/api/uk-average"
    r = fetch(url)
    if r:
        try:
            d = r.json()
            # Response: { "petrol_ppl": 149.5, "diesel_ppl": 175.6, ... }
            petrol_ppl = float(d.get("petrol_ppl") or d.get("petrol") or 0)
            diesel_ppl = float(d.get("diesel_ppl") or d.get("diesel") or 0)
            if petrol_ppl > 50:  # sanity: pence per litre
                fx = get_fx_rate("GBP") or 1.26
                country["gasoline"] = round((petrol_ppl / 100) * fx, 4)
                country["diesel"] = round((diesel_ppl / 100) * fx, 4)
                log.info(f"  UK: {petrol_ppl}p/L petrol → ${country['gasoline']:.4f}/L, {diesel_ppl}p/L diesel → ${country['diesel']:.4f}/L")
                return
        except Exception as e:
            log.warning(f"  Fuel Finder parse failed: {e}")

    # Fallback: GOV.UK weekly CSV
    log.info("  UK fallback: GOV.UK CSV...")
    gov_url = "https://assets.publishing.service.gov.uk/media/fuel-prices-data.csv"
    r = fetch(gov_url)
    if r:
        try:
            lines = r.text.strip().split("\n")
            last = [l for l in lines if l.strip() and "," in l][-1]
            cols = last.split(",")
            petrol_ppl = float(cols[1])
            diesel_ppl = float(cols[2])
            fx = get_fx_rate("GBP") or 1.26
            country["gasoline"] = round((petrol_ppl / 100) * fx, 4)
            country["diesel"] = round((diesel_ppl / 100) * fx, 4)
            log.info(f"  UK GOV: {petrol_ppl}p/L → ${country['gasoline']:.4f}/L")
        except Exception as e:
            log.warning(f"  GOV.UK CSV parse failed: {e}")

# ── France — prix-carburants.gouv.fr ─────────────────────────────────────────

def scrape_france(data):
    """
    France's official fuel price portal has a public JSON/XML API.
    Updated daily. No key required.
    """
    log.info("Scraping France (prix-carburants.gouv.fr)...")
    country = get_country(data, "fr")
    if not country:
        return

    # Official instantaneous prices API (national averages)
    url = "https://www.prix-carburants.gouv.fr/rubrique/opendata/"
    r = fetch(url)
    if not r:
        log.warning("  France: no response from prix-carburants API")
        return

    try:
        # The site returns an XML feed of stations; we parse national averages
        soup = BeautifulSoup(r.content, "xml")
        sp95_prices, diesel_prices = [], []

        for pdv in soup.find_all("pdv")[:500]:  # sample 500 stations
            for prix in pdv.find_all("prix"):
                nom = prix.get("nom", "")
                val = prix.get("valeur", "")
                if val:
                    try:
                        v = float(val) / 1000  # values in millicentimes → EUR/L
                        if nom in ("SP95", "SP95-E10", "E10"):
                            sp95_prices.append(v)
                        elif nom == "Gazole":
                            diesel_prices.append(v)
                    except:
                        pass

        if sp95_prices and diesel_prices:
            fx = get_fx_rate("EUR") or 1.085
            avg_petrol = sum(sp95_prices) / len(sp95_prices)
            avg_diesel = sum(diesel_prices) / len(diesel_prices)
            country["gasoline"] = round(avg_petrol * fx, 4)
            country["diesel"] = round(avg_diesel * fx, 4)
            log.info(f"  France: €{avg_petrol:.3f}/L petrol → ${country['gasoline']:.4f}/L")
    except Exception as e:
        log.warning(f"  France parse failed: {e}")

# ── Spain — Geoportal Gasolineras ─────────────────────────────────────────────

def scrape_spain(data):
    """
    Spain's Ministry of Industry publishes real-time fuel prices via REST API.
    No authentication required.
    """
    log.info("Scraping Spain (Geoportal)...")
    country = get_country(data, "es")
    if not country:
        return

    # Average prices endpoint
    url = "https://sedeaplicaciones.minetur.gob.es/ServiciosRESTCarburantes/PreciosCarburantes/EstacionesTerrestres/"
    r = fetch(url)
    if not r:
        return

    try:
        d = r.json()
        sp95_prices, diesel_prices = [], []
        for station in d.get("ListaEESSPrecio", [])[:1000]:
            try:
                sp95 = station.get("Precio Gasolina 95 E5", "").replace(",", ".")
                dsl = station.get("Precio Gasoleo A", "").replace(",", ".")
                if sp95:
                    sp95_prices.append(float(sp95))
                if dsl:
                    diesel_prices.append(float(dsl))
            except:
                pass

        if sp95_prices:
            fx = get_fx_rate("EUR") or 1.085
            avg_gas = sum(sp95_prices) / len(sp95_prices)
            avg_diesel = sum(diesel_prices) / len(diesel_prices) if diesel_prices else 0
            country["gasoline"] = round(avg_gas * fx, 4)
            if avg_diesel:
                country["diesel"] = round(avg_diesel * fx, 4)
            log.info(f"  Spain: €{avg_gas:.3f}/L → ${country['gasoline']:.4f}/L ({len(sp95_prices)} stations)")
    except Exception as e:
        log.warning(f"  Spain parse failed: {e}")

# ── Germany — ADAC ────────────────────────────────────────────────────────────

def scrape_germany(data):
    """
    ADAC publishes daily average pump prices. Scraped from their tracker page.
    """
    log.info("Scraping Germany (ADAC)...")
    country = get_country(data, "de")
    if not country:
        return

    url = "https://www.adac.de/verkehr/tanken-kraftstoff-und-antrieb/kraftstoff/kraftstoffpreisentwicklung/"
    r = fetch(url)
    if not r:
        return

    try:
        soup = BeautifulSoup(r.text, "lxml")
        # ADAC shows current price in a prominent element with data attribute
        # Pattern: "Super E10: X,XX €/L" and "Diesel: X,XX €/L"
        text = soup.get_text()
        super_match = re.search(r"Super E10[:\s]+(\d+[,\.]\d+)\s*€", text)
        diesel_match = re.search(r"Diesel[:\s]+(\d+[,\.]\d+)\s*€", text)

        fx = get_fx_rate("EUR") or 1.085
        if super_match:
            val = float(super_match.group(1).replace(",", "."))
            country["gasoline"] = round(val * fx, 4)
            log.info(f"  Germany: €{val}/L Super E10 → ${country['gasoline']:.4f}/L")
        if diesel_match:
            val = float(diesel_match.group(1).replace(",", "."))
            country["diesel"] = round(val * fx, 4)
            log.info(f"  Germany: €{val}/L Diesel → ${country['diesel']:.4f}/L")
    except Exception as e:
        log.warning(f"  Germany parse failed: {e}")

# ── India — PPAC ──────────────────────────────────────────────────────────────

def scrape_india(data):
    """
    PPAC (Petroleum Planning and Analysis Cell) publishes daily fuel prices.
    Delhi prices used as representative.
    """
    log.info("Scraping India (PPAC)...")
    country = get_country(data, "in")
    if not country:
        return

    url = "https://ppac.gov.in/consumer-info/fuel-prices"
    r = fetch(url)
    if not r:
        return

    try:
        soup = BeautifulSoup(r.text, "lxml")
        text = soup.get_text()
        # Look for Delhi petrol price pattern: "Delhi  94.72"
        delhi_petrol = re.search(r"Delhi.*?(\d{2,3}\.\d{2})\s*\d{2,3}\.\d{2}", text)
        if delhi_petrol:
            price_inr = float(delhi_petrol.group(1))
            fx = get_fx_rate("INR") or 0.012
            country["gasoline"] = round(price_inr * fx, 4)
            log.info(f"  India: ₹{price_inr}/L → ${country['gasoline']:.4f}/L")
    except Exception as e:
        log.warning(f"  India parse failed: {e}")

# ── Australia — FuelCheck NSW API ─────────────────────────────────────────────

def scrape_australia(data):
    """
    NSW FuelCheck has a public API. Average of all Sydney stations used.
    """
    log.info("Scraping Australia (FuelCheck NSW API)...")
    country = get_country(data, "au")
    if not country:
        return

    # FuelCheck NSW open data API - no key needed for summary
    url = "https://api.onegov.nsw.gov.au/FuelPriceCheck/v2/fuel/prices/average"
    r = fetch(url)
    if not r:
        return

    try:
        d = r.json()
        # Response: list of fuel type averages in AUD cents per litre
        for item in d.get("prices", []):
            fuel = item.get("fueltype", "")
            price_cpl = item.get("price", 0)  # cents per litre
            if fuel == "P" and price_cpl:  # Regular Petrol
                fx = get_fx_rate("AUD") or 0.635
                country["gasoline"] = round((price_cpl / 100) * fx, 4)
                log.info(f"  Australia: {price_cpl}c/L → ${country['gasoline']:.4f}/L")
            elif fuel == "DL" and price_cpl:  # Diesel
                fx = get_fx_rate("AUD") or 0.635
                country["diesel"] = round((price_cpl / 100) * fx, 4)
    except Exception as e:
        log.warning(f"  Australia parse failed: {e}")

# ── South Korea — Opinet ──────────────────────────────────────────────────────

def scrape_south_korea(data):
    """
    Opinet (Korea National Oil Corporation) publishes daily average prices.
    """
    log.info("Scraping South Korea (Opinet)...")
    country = get_country(data, "kr")
    if not country:
        return

    url = "https://www.opinet.co.kr/api/avgRecentPrice.do?code=F006&out=json"
    r = fetch(url)
    if not r:
        return

    try:
        d = r.json()
        for item in d.get("OIL", {}).get("OIL_PRICE", []):
            prod_cd = item.get("PROD_CD", "")
            price = float(item.get("PRICE", 0))
            fx = get_fx_rate("KRW") or 0.000725
            if prod_cd == "B034" and price:  # Regular gasoline
                country["gasoline"] = round(price * fx, 4)
                log.info(f"  S.Korea: ₩{price}/L → ${country['gasoline']:.4f}/L")
            elif prod_cd == "D047" and price:  # Diesel
                country["diesel"] = round(price * fx, 4)
    except Exception as e:
        log.warning(f"  South Korea parse failed: {e}")

# ── Japan — METI ──────────────────────────────────────────────────────────────

def scrape_japan(data):
    """
    METI publishes weekly petroleum statistics including retail prices.
    """
    log.info("Scraping Japan (METI)...")
    country = get_country(data, "jp")
    if not country:
        return

    # METI weekly gasoline price survey (publicly accessible)
    url = "https://www.enecho.meti.go.jp/statistics/petroleum_and_lpgas/pl007/xls/week.csv"
    r = fetch(url)
    if not r:
        return

    try:
        lines = r.content.decode("shift-jis", errors="replace").split("\n")
        for line in reversed(lines):
            cols = [c.strip() for c in line.split(",")]
            if len(cols) >= 3:
                try:
                    price_jpy = float(cols[1])  # Regular gasoline JPY/L
                    if 100 < price_jpy < 400:  # sanity check
                        fx = get_fx_rate("JPY") or 0.0067
                        country["gasoline"] = round(price_jpy * fx, 4)
                        log.info(f"  Japan: ¥{price_jpy}/L → ${country['gasoline']:.4f}/L")
                        break
                except:
                    continue
    except Exception as e:
        log.warning(f"  Japan parse failed: {e}")

# ── Brent crude reference ─────────────────────────────────────────────────────

def update_brent(data):
    """
    Update Brent crude reference price from EIA open data API.
    No API key needed.
    """
    log.info("Fetching Brent crude price...")
    url = "https://api.eia.gov/v2/petroleum/pri/spt/data/?api_key=DEMO&frequency=daily&data[0]=value&facets[series][]=RBRTE&sort[0][column]=period&sort[0][direction]=desc&length=1"
    r = fetch(url)
    if r:
        try:
            d = r.json()
            price = d["response"]["data"][0]["value"]
            data["meta"]["brent_now"] = float(price)
            log.info(f"  Brent: ${price:.2f}/bbl")
        except Exception as e:
            log.warning(f"  Brent parse failed: {e}")

# ── main ──────────────────────────────────────────────────────────────────────

def run():
    log.info("=== War Prices Fuel Scraper starting ===")
    data = load_data()

    scrapers = [
        scrape_usa,
        scrape_uk,
        scrape_france,
        scrape_spain,
        scrape_germany,
        scrape_india,
        scrape_australia,
        scrape_south_korea,
        scrape_japan,
        update_brent,
    ]

    for scraper in scrapers:
        try:
            scraper(data)
        except Exception as e:
            log.error(f"Scraper {scraper.__name__} failed: {e}")

    save_data(data)
    log.info("=== Done ===")

if __name__ == "__main__":
    run()
