"""Look for Wayback Machine snapshots of the panel products on one missed day.
Usage: python wayback/backfill_day.py 2026-10-05
For every URL in panel/*.csv, asks the archive index for a snapshot taken on that UTC date
and, where one exists, reads the listed price from the page (same patterns as prices.py).
Writes out/backfill_<date>.csv. It does NOT touch data/observations.csv: the rows are
archive prices, not prices the scraper saw, so they stay separate until checked."""
import csv, glob, html, json, os, re, sys, time, urllib.parse, urllib.request

day = sys.argv[1]
ymd = day.replace("-", "")
UA = {"User-Agent": "Cambridge undergraduate dissertation research (archived price history)"}


def get(u, timeout=90, tries=3):
    for a in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=timeout) as r:
                return r.read().decode("utf-8", errors="ignore")
        except Exception:
            time.sleep(10 * (a + 1))
    return None


def snapshot(url):
    p = {"url": url, "from": ymd, "to": ymd, "output": "json", "filter": "statuscode:200",
         "fl": "timestamp,original", "limit": "1"}
    t = get("https://web.archive.org/cdx/search/cdx?" + urllib.parse.urlencode(p))
    if t is None:
        return "cdx_failed", None
    rows = json.loads(t) if t.strip() else []
    return ("ok", rows[1]) if len(rows) > 1 else ("no_snapshot", None)


PRICE_PATTERNS = [
    ("jsonld_offer_price", re.compile(r'"offers"\s*:\s*[\[{].{0,600}?"price"\s*:\s*"?([0-9][0-9,]*\.?[0-9]*)"?', re.S)),
    ("meta_product_price", re.compile(r'(?:product:price:amount|og:price:amount)"\s+content="([0-9][0-9,]*\.?[0-9]*)"', re.I)),
    ("itemprop_price", re.compile(r'itemprop="price"[^>]*content="([0-9][0-9,]*\.?[0-9]*)"', re.I)),
    ("json_price_field", re.compile(r'"(?:salePrice|listPrice|regularPrice|price|currentPrice)"\s*:\s*"?\$?([0-9][0-9,]*\.[0-9]{2})"?')),
]
TITLE = re.compile(r"<title[^>]*>(.*?)</title>", re.S | re.I)

os.makedirs("out", exist_ok=True)
counts = {}
with open(f"out/backfill_{day}.csv", "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["date", "retailer", "url", "snapshot_timestamp", "snapshot_url", "page_title", "price", "method", "status"])
    for path in sorted(glob.glob("panel/*.csv")):
        key = os.path.basename(path)[:-4]
        for r in csv.DictReader(open(path)):
            url = r["url"]
            status, snap = snapshot(url)
            ts = snap_url = title = price = method = ""
            if snap:
                ts, orig = snap
                page = get(f"https://web.archive.org/web/{ts}id_/{orig}") or ""
                snap_url = f"https://web.archive.org/web/{ts}/{orig}"
                for name, rx in PRICE_PATTERNS:
                    m = rx.search(page)
                    if m:
                        price, method = m.group(1).replace(",", ""), name
                        break
                t = TITLE.search(page)
                title = html.unescape(re.sub(r"\s+", " ", t.group(1)).strip())[:150] if t else ""
                status = "priced" if price else ("no_price_found" if page else "fetch_failed")
            w.writerow([day, key, url, ts, snap_url, title, price, method, status])
            f.flush()
            counts.setdefault(key, {}).setdefault(status, 0)
            counts[key][status] += 1
            time.sleep(1.5)
        print(key, counts[key], flush=True)
json.dump(counts, open(f"out/backfill_{day}_summary.json", "w"), indent=1)
