# Apparel retail price and origin scraper

Built 17 September 2026 on Alberto Cavallo's advice: scrape ten US apparel storefronts daily for a few months and build your own panel of posted prices and country-of-origin labels. This kit does that. It is tested end to end against a local test site; it is not yet tested against the ten live sites, because nothing in the session that built it could reach them. Your first job is the probe step below.

## What it collects

One row per product per day (data/observations.csv): date, retailer, parent company, segment, product URL, SKU, name, brand, price, list price where the site exposes one, currency, availability, and country of origin ("Made in Vietnam", or "Imported" when that is all the site says), plus the snippet of page text the origin came from so you can audit it.

Each retailer gets a fixed panel of products (panel/<key>.csv) fixed on the first run and topped up with new arrivals up to max_products. The same products are revisited every day. That is what makes it a price panel rather than a series of cross-sections: you observe price changes on identical items, disappearance (product turnover), and origin changes on replacement items.

What it cannot give you: quantities sold, margins, wholesale prices. Margins still come from filings and Compustat.

## Why it must run from the US

UK visitors are redirected to UK storefronts with GBP prices. Confirmed on gap.com and ralphlauren.com on 17 September. GitHub Actions runners are in the US, so the workflow file runs it there daily and commits the data back to the repository. Do not rely on running it from your laptop in Cambridge unless you are on a US VPN.

## Set-up, once (about 30 minutes)

1. Create a private GitHub repository, e.g. `apparel-price-panel`. Copy the contents of this folder into it (including the hidden `.github` folder; in Finder press Cmd+Shift+. to see it).
2. On your laptop, in the repository folder:
   ```
   python3 -m venv .venv && source .venv/bin/activate
   pip install -r requirements.txt
   python -m playwright install chromium
   ```
3. Probe each retailer. This is the step that matters. The listing URLs and URL patterns in retailers.yaml are starting guesses and some will be wrong or blocked.
   ```
   python probe.py gap --headed
   ```
   You want to see: the listing page loading on the US site, a non-zero count of product links, and three product rows with a price. If you are on a UK IP you will see the geo-redirect warning; that is expected at home, and the probe still tells you whether the page structure works. Fix any retailer that returns zero links (wrong listing URL or wrong `product_url_re`) or no price (site blocks headless browsers or has no JSON-LD; add `origin_selector` or try a different category page). Sites that block outright after two or three attempts: drop them and substitute (Uniqlo US, J.Crew, Abercrombie, Nordstrom are candidates).
4. Push to GitHub. Go to Actions, select "daily-apparel-scrape", press "Run workflow". Watch the log. Fix and re-run until every retailer reports "N/N with price" for most of its panel.
5. Leave it. Check the Actions tab twice a week. A retailer that starts failing usually means the site changed its HTML or started blocking; re-probe it.

Cost: GitHub gives private repositories 2,000 Actions minutes a month free. A run of ten retailers at 150 products each with the built-in delays takes roughly 60 to 90 minutes, so a daily run fits with room to spare. If it does not, cut `max_products` to 100.

## Files

- retailers.yaml: the ten sites, segment and parent labels, listing pages, URL patterns.
- scrape.py: the scraper. `python scrape.py --only hm zara` runs a subset.
- probe.py: test one retailer and print what comes back.
- summarise.py: health check and a chained daily price index per retailer.
- .github/workflows/scrape.yml: the daily schedule (11:00 UTC) and the commit step.
- panel/, data/, logs/: created on the first run.

## Design choices you should be able to defend

- Product-level fixed panel, revisited daily, so price changes are on identical items. This is the Cavallo, Gopinath, Neiman and Tang (2021) approach at small scale.
- Three category pages per retailer (tops, dresses or sweaters, jeans) rather than everything: comparable product types across segments, and knits versus wovens versus denim map onto distinct HTS headings in chapters 61 and 62, so you can attach product-level tariff rates.
- Old Navy and Gap are the same parent at different price points: a within-firm test of whether brand position, not firm-level cost, drives pass-through.
- Origin labels are the sourcing-relocation observable Cavallo mentioned. Coverage will be uneven: luxury sites state "Made in Italy"; mass-market sites often say only "Imported". Record the coverage rate per retailer and report it. An "Imported"-only retailer still gives you prices.

## Ethics and terms

Read each site's robots.txt and terms before the first live run. The scraper reads public product pages at a slow rate (one page every 2 to 5 seconds, one browser per retailer, no logins, no purchases). Do not raise the rate. Cite the data as self-collected and describe the method in the dissertation appendix. If a site's terms prohibit automated access and you are uncomfortable, drop it.

## Data protection

No personal data is collected. Keep the repository private anyway.
