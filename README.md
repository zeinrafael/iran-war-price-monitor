# War Price Monitor — Setup Guide

Real-time consumer price tracking across 22 countries, measuring the economic impact of the Iran conflict (from Feb 28, 2026).

## What this is

Two interactive panels:
- **Fuel Panel** — gasoline & diesel pump prices vs pre-war baseline
- **Food Basket Panel** — rice, flour, eggs, beef vs pre-war baseline

Data auto-updates daily/weekly via GitHub Actions. Static/regulated markets are updated manually via the admin page.

---

## Project Structure

```
warprices/
├── index.html              ← Landing page (loads stats from JSON)
├── panels/
│   ├── fuel.html           ← Fuel panel (loads from data/fuel.json)
│   └── food.html           ← Food panel (loads from data/food.json)
├── data/
│   ├── fuel.json           ← Live fuel price data (auto-updated)
│   └── food.json           ← Live food price data (auto-updated)
├── scrapers/
│   ├── fuel_scraper.py     ← Auto-updates fuel.json
│   └── food_scraper.py     ← Auto-updates food.json
├── admin/
│   └── index.html          ← Manual update form for static markets
├── .github/
│   └── workflows/
│       └── update-prices.yml  ← GitHub Actions cron jobs
├── netlify.toml            ← Netlify deployment config
└── README.md               ← This file
```

---

## One-Time Setup (~25 minutes)

### Step 1 — Create a GitHub account (if you don't have one)
Go to https://github.com/join — free, takes 2 minutes.

### Step 2 — Create a new repository
1. Click **New repository** on GitHub
2. Name it `war-price-monitor` (or anything you like)
3. Set it to **Public** (required for free GitHub Pages / Netlify)
4. Click **Create repository**

### Step 3 — Upload the files
The simplest way:
1. On your new repo page, click **uploading an existing file**
2. Drag all the files from this package into the upload area
3. Maintain the folder structure (data/, scrapers/, .github/workflows/, etc.)
4. Click **Commit changes**

Or if you have Git installed:
```bash
git init
git remote add origin https://github.com/YOUR_USERNAME/war-price-monitor.git
git add .
git commit -m "Initial commit"
git push -u origin main
```

### Step 4 — Deploy to Netlify (free)
1. Go to https://netlify.com and sign up (free)
2. Click **Add new site** → **Import an existing project**
3. Connect your GitHub account
4. Select your `war-price-monitor` repo
5. Leave build settings empty (this is a static site)
6. Click **Deploy site**

Your site will be live in ~30 seconds at a URL like `random-name.netlify.app`.

### Step 5 — Connect your custom domain
1. Buy a domain from Namecheap, Cloudflare, or Google Domains (~$10-15/year)
2. In Netlify: **Site settings** → **Domain management** → **Add custom domain**
3. Follow the DNS instructions (add a CNAME record pointing to Netlify)
4. Netlify provides a free SSL certificate automatically

### Step 6 — Enable GitHub Actions (auto-updates)
GitHub Actions is already configured in `.github/workflows/update-prices.yml`.
It will run automatically once you push the files.

To verify it's working:
1. Go to your GitHub repo
2. Click the **Actions** tab
3. You should see "Update Price Data" listed
4. It runs daily at 08:00 UTC

To trigger manually at any time:
1. Go to Actions → Update Price Data
2. Click **Run workflow**

---

## Scraper Coverage

| Country | Source | Cadence | Auto? |
|---------|--------|---------|-------|
| 🇺🇸 USA | AAA + EIA | Daily | ✅ |
| 🇬🇧 UK | Fuel Finder UK + GOV.UK | Daily | ✅ |
| 🇫🇷 France | prix-carburants.gouv.fr | Daily | ✅ |
| 🇪🇸 Spain | Geoportal Gasolineras | Daily | ✅ |
| 🇩🇪 Germany | ADAC | Daily | ✅ |
| 🇮🇳 India | PPAC | Daily | ✅ |
| 🇦🇺 Australia | FuelCheck NSW | Daily | ✅ |
| 🇰🇷 South Korea | Opinet | Daily | ✅ |
| 🇯🇵 Japan | METI | Weekly | ✅ |
| 🇧🇷 Brazil | ANP | Weekly | ✅ |
| 🇨🇱 Chile | CNE/ENAP | Weekly | ✅ |
| 🇲🇦 Morocco | GlobalPetrolPrices | Weekly | ✅ |
| 🇿🇦 South Africa | DMRE | Monthly | 🔶 Manual |
| 🇰🇪 Kenya | EPRA | Monthly | 🔶 Manual |
| 🇵🇭 Philippines | DOE | Weekly | 🔶 Manual |
| 🇱🇧 Lebanon | Min. Energy | Weekly | 🔶 Manual |
| 🇳🇿 New Zealand | MBIE | Weekly | 🔶 Manual |
| 🇨🇳 China | NDRC | 10-day | 🔶 Manual |
| 🇦🇹 Austria | ÖAMTC | Daily | ✅ |
| 🇪🇬 Egypt | Min. Petroleum | Quarterly | 🔴 Static |
| 🇸🇳 Senegal | ANSD | Monthly | 🔴 Static |
| 🇮🇩 Indonesia | Pertamina | Monthly | 🔴 Static |

---

## Manual Updates (Regulated Markets)

When an official price announcement drops for Egypt, Senegal, Indonesia, Kenya, or South Africa:

1. Go to `your-site.com/admin/`
2. Enter the new prices in USD/litre
3. Click **Generate JSON Patch**
4. Copy the output
5. Update `data/fuel.json` or `data/food.json` in your GitHub repo
6. Commit → site updates in ~30 seconds via Netlify

---

## Customising the Panels

All panel content is driven by the JSON files in `data/`. To change displayed data:

**Update a country's prices manually:**
Edit `data/fuel.json` directly — find the country by `id` and update `gasoline` and `diesel`.

**Change the pre-war baseline:**
The `gasoline_base` and `diesel_base` fields in `fuel.json` are the Feb 24, 2026 reference prices. Don't change these unless you want to reset the baseline date.

**Add a new country:**
Add a new object to the `countries` array in the JSON with all required fields. The panel will automatically include it.

---

## Scrapers — If They Break

Web scrapers can break when sites change their HTML structure. If a scraper fails:

1. Check the GitHub Actions log (Actions tab → failed run → view logs)
2. The scraper will log which source failed
3. It falls back gracefully — existing data is kept, only failed sources are skipped
4. Fix the regex/selector in `scrapers/fuel_scraper.py` and push

Scraper failures do NOT take the site down — the panels show the last successfully fetched data with a timestamp.

---

## Cost Summary

| Item | Cost |
|------|------|
| GitHub repo + Actions | Free |
| Netlify hosting | Free |
| SSL certificate | Free (via Netlify) |
| Custom domain | ~$10-15/year |
| GlobalPetrolPrices API (optional) | ~$50/month |
| Numbeo API (optional) | ~$50/month |
| **Total (without paid APIs)** | **~$10-15/year** |

---

## Data Sources & Attribution

- **AAA GasPrices** — gasprices.aaa.com
- **US EIA** — eia.gov (public domain)
- **GOV.UK Fuel Statistics** — gov.uk/government/statistics/weekly-road-fuel-prices (OGL v3)
- **Fuel Finder UK** — fuel-finder.uk
- **Prix Carburants France** — prix-carburants.gouv.fr (open data)
- **Geoportal Gasolineras Spain** — sedeaplicaciones.minetur.gob.es (open data)
- **ADAC Germany** — adac.de
- **GlobalPetrolPrices** — globalpetrolprices.com (CC BY-NC-ND 3.0 for non-commercial)
- **Numbeo** — numbeo.com (CC BY 4.0 for non-commercial)
- **PPAC India** — ppac.gov.in (public)
- **FAO Food Price Index** — fao.org (CC BY-NC-SA 3.0)

**Note on scraping terms of service:** GlobalPetrolPrices and Numbeo permit non-commercial research use. If this site grows in audience or becomes commercial in nature, consider purchasing their APIs (~$50/month each) for a fully legitimate setup.

---

## Questions

Built with Claude (Anthropic). Pre-war baselines: Feb 24, 2026. War start: Feb 28, 2026.
