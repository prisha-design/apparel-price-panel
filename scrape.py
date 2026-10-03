#!/usr/bin/env python3
"""
Daily price and country-of-origin scraper for US apparel storefronts.

Design
------
Two stages per retailer, both with a real headless Chromium (Playwright):

1. Listing stage. Visit each listing URL in retailers.yaml, collect every link
   that matches product_url_re. On the first run these become the retailer's
   fixed panel (panel/<key>.csv). On later runs the panel is kept and new links
   are appended up to max_products, so the same products are followed daily
   and product turnover is observed rather than hidden.

2. Product stage. Visit each panel URL. Extract:
     - schema.org Product JSON-LD (name, sku, brand, price, currency, availability)
     - fallback price from meta tags / visible text if JSON-LD is absent
     - country of origin: "Made in <Country>" or "Imported" from the product
       details block (origin_selector) or, failing that, the whole page text
   Append one row per product per day to data/observations.csv and write a
   dated snapshot to data/YYYY-MM-DD/<key>.csv.

Run:  python scrape.py                # all retailers
      python scrape.py --only gap hm  # subset
      python scrape.py --listing-only # rebuild panels, no product visits

The scraper must run from a US IP. UK visitors are redirected to UK
storefronts (GBP prices). GitHub Actions runners are in the US.
"""

import argparse
import asyncio
import csv
import datetime as dt
import json
import os
import random
import re
import sys
from pathlib import Path

import yaml
from playwright.async_api import async_playwright, TimeoutError as PWTimeout

ROOT = Path(__file__).resolve().parent
PANEL_DIR = ROOT / "panel"
DATA_DIR = ROOT / "data"
LOG_DIR = ROOT / "logs"

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36")

COUNTRIES = (
    "Italy|France|Spain|Portugal|Turkey|Türkiye|China|Vietnam|Viet Nam|Bangladesh|"
    "India|Indonesia|Cambodia|Pakistan|Sri Lanka|Mexico|Guatemala|Honduras|"
    "El Salvador|Nicaragua|Egypt|Morocco|Tunisia|Jordan|Myanmar|Thailand|"
    "Philippines|Malaysia|Peru|Colombia|Brazil|Romania|Bulgaria|Poland|Germany|"
    "United Kingdom|UK|USA|U\\.S\\.A\\.|United States|Japan|Korea|South Korea|"
    "Taiwan|Hong Kong|Madagascar|Mauritius|Kenya|Ethiopia|Lesotho|Haiti|"
    "Dominican Republic|Uzbekistan|Ukraine|Greece|Lithuania|Serbia|Bosnia|"
    "North Macedonia|Albania|Moldova|Croatia|Slovakia|Czech Republic|Hungary|"
    "Switzerland|Austria|Netherlands|Belgium|Denmark|Sweden|Canada|Laos|Nepal"
)
ORIGIN_RE = re.compile(
    r"(?:made|manufactured|produced|crafted)\s+in\s+(?:the\s+)?(" + COUNTRIES + r")\b",
    re.IGNORECASE,
)
IMPORTED_RE = re.compile(r"\bimported\b", re.IGNORECASE)
PRICE_TXT_RE = re.compile(r"\$\s?(\d{1,4}(?:,\d{3})*(?:\.\d{2})?)")

FIELDS = [
    "date", "retailer", "parent", "segment", "url", "final_url", "sku", "name",
    "brand", "price", "list_price", "currency", "availability", "origin",
    "origin_text", "category", "http_status", "note",
]


def log(msg):
    print(f"[{dt.datetime.now(dt.UTC).strftime('%H:%M:%S')}] {msg}", flush=True)


def load_config(path):
    with open(path) as f:
        cfg = yaml.safe_load(f)
    rets = cfg["retailers"]
    if os.environ.get("INCLUDE_CANDIDATES") and cfg.get("candidates"):
        rets = rets + (cfg.get("candidates") or [])
    return rets


def read_panel(key):
    p = PANEL_DIR / f"{key}.csv"
    if not p.exists():
        return []
    with open(p, newline="") as f:
        return [r for r in csv.DictReader(f)]


def write_panel(key, rows):
    PANEL_DIR.mkdir(exist_ok=True)
    with open(PANEL_DIR / f"{key}.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["url", "category", "first_seen"])
        w.writeheader()
        w.writerows(rows)


async def new_context(pw, headless=True):
    browser = await pw.chromium.launch(headless=headless)
    ctx = await browser.new_context(
        user_agent=UA,
        viewport={"width": 1366, "height": 900},
        locale="en-US",
        timezone_id="America/New_York",
        extra_http_headers={"Accept-Language": "en-US,en;q=0.9"},
    )
    # Light-touch stealth: hide the automation flag most bot filters check first.
    await ctx.add_init_script(
        "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"
    )
    return browser, ctx


async def polite_goto(page, url, timeout=45000, idle=False):
    resp = await page.goto(url, wait_until="domcontentloaded", timeout=timeout)
    if idle:
        try:
            await page.wait_for_load_state("networkidle", timeout=12000)
        except Exception:
            pass
    await page.wait_for_timeout(random.randint(1500, 3500))
    # Nudge lazy loaders.
    try:
        await page.mouse.wheel(0, 1200)
        await page.wait_for_timeout(800)
        await page.mouse.wheel(0, 1600)
        await page.wait_for_timeout(800)
    except Exception:
        pass
    return resp


async def harvest_listing(page, url, pattern):
    """Return product URLs found on one listing page."""
    try:
        await polite_goto(page, url, idle=True)
    except PWTimeout:
        log(f"  timeout on listing {url}")
        return []
    hrefs = await page.eval_on_selector_all("a[href]", "els => els.map(e => e.href)")
    rx = re.compile(pattern)
    if os.environ.get("DIAG"):
        try:
            title = await page.title()
            body = (await page.inner_text("body"))[:300].replace("\n", " ")
        except Exception:
            title, body = "?", "?"
        same = [h for h in hrefs if re.search(r"/p/|product|/pr/|-p\d|\.html|/products/|pid=", h)]
        cats = [h for h in hrefs if re.search(r"category|/c/|/browse/|/collections/|/shop/|/plp/", h)]
        for h in list(dict.fromkeys(cats))[:10]:
            log(f"  DIAG cat {h}")
        log(f"  DIAG url={page.url} title={title!r} anchors={len(hrefs)}")
        log(f"  DIAG body={body!r}")
        for h in list(dict.fromkeys(same))[:12]:
            log(f"  DIAG href {h}")
    out = []
    seen = set()
    for h in hrefs:
        h = h.split("#")[0]
        if rx.search(h) and h not in seen:
            seen.add(h)
            out.append(h)
    return out


def _walk_ld(obj):
    """Yield every dict inside a JSON-LD blob (handles @graph and lists)."""
    if isinstance(obj, dict):
        yield obj
        for v in obj.values():
            yield from _walk_ld(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _walk_ld(v)


def parse_product_ld(blobs):
    """Pick the schema.org Product (or ProductGroup) out of the page's JSON-LD."""
    for raw in blobs:
        try:
            data = json.loads(raw)
        except Exception:
            continue
        for d in _walk_ld(data):
            t = d.get("@type")
            types = t if isinstance(t, list) else [t]
            if any(x in ("Product", "ProductGroup", "ProductModel") for x in types if x):
                return d
    return None


def offer_fields(prod):
    price = list_price = currency = availability = None
    offers = prod.get("offers")
    if isinstance(offers, list):
        offers = offers[0] if offers else None
    if isinstance(offers, dict):
        currency = offers.get("priceCurrency")
        availability = str(offers.get("availability", "")).split("/")[-1] or None
        if "price" in offers:
            price = offers.get("price")
        elif "lowPrice" in offers:
            price = offers.get("lowPrice")
            list_price = offers.get("highPrice")
        ps = offers.get("priceSpecification")
        if isinstance(ps, list):
            for spec in ps:
                if isinstance(spec, dict) and spec.get("priceType", "").endswith("ListPrice"):
                    list_price = spec.get("price")
    return price, list_price, currency, availability


async def scrape_product(page, ret, url, category):
    row = {k: "" for k in FIELDS}
    row.update(date=dt.date.today().isoformat(), retailer=ret["key"],
               parent=ret["parent"], segment=ret["segment"], url=url,
               category=category)
    try:
        resp = await polite_goto(page, url)
        row["http_status"] = resp.status if resp else ""
    except PWTimeout:
        row["note"] = "timeout"
        return row
    except Exception as e:  # noqa
        row["note"] = f"nav_error:{type(e).__name__}"
        return row

    row["final_url"] = page.url
    if not re.search(ret["product_url_re"], page.url):
        row["note"] = "redirected_off_product"  # geo-redirect or 404 landing

    blobs = await page.eval_on_selector_all(
        'script[type="application/ld+json"]', "els => els.map(e => e.textContent)")
    prod = parse_product_ld(blobs)
    if prod:
        row["name"] = (prod.get("name") or "").strip()
        row["sku"] = str(prod.get("sku") or prod.get("productID") or prod.get("mpn") or "")
        b = prod.get("brand")
        row["brand"] = b.get("name") if isinstance(b, dict) else (b or "")
        price, list_price, cur, avail = offer_fields(prod)
        row["price"], row["list_price"] = price or "", list_price or ""
        row["currency"], row["availability"] = cur or "", avail or ""
    else:
        row["note"] = (row["note"] + ";no_jsonld").strip(";")
        # Fallbacks: OpenGraph / meta price tags, then visible "$" text.
        meta = await page.evaluate(
            """() => {
              const g = s => { const e = document.querySelector(s); return e ? (e.content || e.textContent) : null };
              return {
                price: g('meta[property="product:price:amount"]') || g('meta[property="og:price:amount"]') || g('[itemprop=price]'),
                currency: g('meta[property="product:price:currency"]') || g('meta[property="og:price:currency"]') || g('[itemprop=priceCurrency]'),
                name: g('meta[property="og:title"]') || document.title,
                sku: g('[itemprop=sku]')
              }}""")
        row["name"] = (meta.get("name") or "").strip()
        row["sku"] = meta.get("sku") or ""
        row["price"] = meta.get("price") or ""
        row["currency"] = meta.get("currency") or ""
        if not row["price"]:
            txt = await page.inner_text("body")
            m = PRICE_TXT_RE.search(txt)
            if m:
                row["price"], row["currency"] = m.group(1).replace(",", ""), "USD"

    # Shopify stores (e.g. Everlane) expose /products/<handle>.js with prices in cents.
    if not row["price"] and "/products/" in page.url:
        try:
            js = await page.evaluate("""async (u) => { const r = await fetch(u); return r.ok ? await r.json() : null }""",
                                     page.url.split("?")[0].rstrip("/") + ".js")
            if js:
                row["price"] = f"{js.get('price', 0) / 100:.2f}"
                if js.get("compare_at_price"):
                    row["list_price"] = f"{js['compare_at_price'] / 100:.2f}"
                row["currency"] = row["currency"] or "USD"
                row["name"] = row["name"] or js.get("title", "")
                row["note"] = (row["note"] + ";shopify_js").strip(";")
        except Exception:
            pass

    # Country of origin. Try the details block first, then the whole page.
    origin_text = ""
    sel = ret.get("origin_selector")
    if sel:
        try:
            origin_text = await page.inner_text(sel, timeout=3000)
        except Exception:
            origin_text = ""
    if not origin_text:
        # Many sites hide details behind an accordion; try to open likely ones.
        for label in ("Details", "Product details", "Composition", "Materials & Care",
                      "Materials", "Fabric & Care", "Product Details", "Fit & Care"):
            try:
                btn = page.get_by_role("button", name=re.compile(label, re.I)).first
                if await btn.count():
                    await btn.click(timeout=1500)
                    await page.wait_for_timeout(400)
            except Exception:
                pass
        try:
            origin_text = await page.inner_text("body")
        except Exception:
            origin_text = ""
    m = ORIGIN_RE.search(origin_text)
    if m:
        row["origin"] = m.group(1)
        s = max(0, m.start() - 40)
        row["origin_text"] = origin_text[s:m.end() + 40].replace("\n", " ")
    elif IMPORTED_RE.search(origin_text):
        row["origin"] = "Imported"
        mm = IMPORTED_RE.search(origin_text)
        s = max(0, mm.start() - 40)
        row["origin_text"] = origin_text[s:mm.end() + 40].replace("\n", " ")
    return row


async def run_retailer(pw, ret, listing_only, headless):
    key = ret["key"]
    log(f"== {ret['name']} ({key})")
    browser, ctx = await new_context(pw, headless)
    page = await ctx.new_page()
    panel = read_panel(key)
    known = {r["url"] for r in panel}
    today = dt.date.today().isoformat()

    # Stage 1: listings. Top up the panel with anything new.
    added = 0
    for lurl in ret["listing_urls"]:
        if len(panel) >= ret["max_products"]:
            break
        found = await harvest_listing(page, lurl, ret["product_url_re"])
        log(f"  listing {lurl} -> {len(found)} product links")
        for u in found:
            if u not in known and len(panel) < ret["max_products"]:
                panel.append({"url": u, "category": lurl, "first_seen": today})
                known.add(u)
                added += 1
        await page.wait_for_timeout(random.randint(1000, 2500))
    write_panel(key, panel)
    log(f"  panel size {len(panel)} (+{added} new)")

    rows = []
    if not listing_only:
        for i, item in enumerate(panel, 1):
            row = await scrape_product(page, ret, item["url"], item["category"])
            rows.append(row)
            if i % 25 == 0:
                log(f"  {i}/{len(panel)} products")
            await page.wait_for_timeout(random.randint(1200, 3000))
        ok = sum(1 for r in rows if r["price"])
        org = sum(1 for r in rows if r["origin"])
        log(f"  done: {ok}/{len(rows)} with price, {org} with origin")
    await browser.close()
    return rows


def append_rows(rows):
    if not rows:
        return
    DATA_DIR.mkdir(exist_ok=True)
    master = DATA_DIR / "observations.csv"
    new = not master.exists()
    with open(master, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        if new:
            w.writeheader()
        w.writerows(rows)
    day_dir = DATA_DIR / rows[0]["date"]
    day_dir.mkdir(exist_ok=True)
    by_ret = {}
    for r in rows:
        by_ret.setdefault(r["retailer"], []).append(r)
    for k, rs in by_ret.items():
        with open(day_dir / f"{k}.csv", "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=FIELDS)
            w.writeheader()
            w.writerows(rs)


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=str(ROOT / "retailers.yaml"))
    ap.add_argument("--only", nargs="*", help="retailer keys to run")
    ap.add_argument("--listing-only", action="store_true")
    ap.add_argument("--headed", action="store_true", help="show the browser (local debugging)")
    args = ap.parse_args()

    retailers = load_config(args.config)
    # One full run per day: a second run on the same UTC date is skipped unless FORCE=1
    if not os.environ.get("MAX_PRODUCTS") and not os.environ.get("ONLY") and not os.environ.get("FORCE"):
        if (DATA_DIR / dt.date.today().isoformat()).exists():
            log("today's data already collected; skipping (set FORCE=1 to override)")
            return
    # Optional cap for test runs: MAX_PRODUCTS=10 python scrape.py
    cap = os.environ.get("MAX_PRODUCTS")
    if cap:
        for r in retailers:
            r["max_products"] = min(int(cap), r["max_products"])
    if os.environ.get("ONLY"):
        args.only = os.environ["ONLY"].split()
    if args.only:
        retailers = [r for r in retailers if r["key"] in set(args.only)]
    LOG_DIR.mkdir(exist_ok=True)
    all_rows = []
    async with async_playwright() as pw:
        for ret in retailers:
            try:
                rows = await run_retailer(pw, ret, args.listing_only, not args.headed)
                all_rows.extend(rows)
                append_rows(rows)  # write per retailer so a crash keeps earlier work
            except Exception as e:  # noqa
                log(f"  FAILED {ret['key']}: {type(e).__name__}: {e}")
    with open(LOG_DIR / f"{dt.date.today().isoformat()}.txt", "a") as f:
        f.write(f"{dt.datetime.now(dt.UTC).isoformat()} rows={len(all_rows)}\n")
    log(f"finished, {len(all_rows)} rows")


if __name__ == "__main__":
    asyncio.run(main())
