#!/usr/bin/env python3
"""
Probe one retailer before trusting it in the daily run.

    python probe.py gap            # harvest first listing, scrape 3 products, print what came back
    python probe.py gap --headed   # watch the browser do it

Reads retailers.yaml. Writes nothing. Use it to fix listing URLs, product_url_re
and origin_selector until price and origin come back for the sample.
"""
import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from playwright.async_api import async_playwright  # noqa: E402
import scrape  # noqa: E402


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("key")
    ap.add_argument("--n", type=int, default=3)
    ap.add_argument("--headed", action="store_true")
    args = ap.parse_args()
    rets = {r["key"]: r for r in scrape.load_config(scrape.ROOT / "retailers.yaml")}
    if args.key not in rets:
        sys.exit(f"unknown key {args.key}; choose from {sorted(rets)}")
    ret = rets[args.key]
    async with async_playwright() as pw:
        browser, ctx = await scrape.new_context(pw, headless=not args.headed)
        page = await ctx.new_page()
        lurl = ret["listing_urls"][0]
        found = await scrape.harvest_listing(page, lurl, ret["product_url_re"])
        print(f"listing {lurl}\n  landed on {page.url}\n  {len(found)} product links")
        if page.url.rstrip("/") != lurl.rstrip("/"):
            print("  WARNING: landed somewhere else. If that is a UK/other-country storefront,"
                  " you are not on a US IP. Run from GitHub Actions or a US VPN.")
        for u in found[:5]:
            print("   ", u)
        for u in found[: args.n]:
            row = await scrape.scrape_product(page, ret, u, lurl)
            print(json.dumps({k: v for k, v in row.items() if v}, indent=2))
        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
