"""Pull archived US list prices for long-running products from the Wayback Machine.
Usage: python wayback/prices.py <brand> <cdx url prefix> [n_products]
1. Lists every archived product URL for the brand, month by month, in two windows:
   A = 2018-01 to 2020-02 (first tariff episode) and B = 2024-06 to 2026-09 (second).
2. Keeps products archived in both windows (same URL), ranked by how many months they appear.
3. Fetches one raw snapshot per product per month and reads the listed price from
   structured data on the page (JSON-LD offers, product meta tags, itemprop), recording
   which method found it. Nothing is cleaned here: every row keeps the snapshot URL."""
import csv, json, re, sys, time, os, urllib.request, urllib.parse, html
from collections import defaultdict
brand, pat = sys.argv[1], sys.argv[2]
N = int(sys.argv[3]) if len(sys.argv) > 3 else 10
UA = {"User-Agent": "Cambridge undergraduate dissertation research (archived price history)"}
def get(u, timeout=120, tries=4):
    for a in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=timeout) as r:
                return r.read().decode("utf-8", errors="ignore")
        except Exception as e:
            err = str(e); time.sleep(10 * (a + 1))
    return None
def cdx(frm, to):
    p = {"url": pat, "from": frm, "to": to, "filter": ["statuscode:200", "mimetype:text/html"],
         "collapse": "timestamp:6", "fl": "urlkey,timestamp,original", "limit": 60000}
    t = get("https://web.archive.org/cdx/search/cdx?" + urllib.parse.urlencode(p, doseq=True), timeout=300)
    rows = defaultdict(dict)
    for line in (t or "").splitlines():
        parts = line.split(" ")
        if len(parts) != 3: continue
        k, ts, orig = parts
        k = k.split("?")[0]
        rows[k].setdefault(ts[:6], (ts, orig))
    return rows
os.makedirs("out", exist_ok=True)
A = cdx("201801", "202002"); time.sleep(5)
B = cdx("202406", "202609")
both = [(min(len(A[k]), len(B[k])), k) for k in A if k in B and len(A[k]) >= 2 and len(B[k]) >= 2]
both.sort(reverse=True)
chosen = [k for _, k in both[:N]]
summary = {"brand": brand, "pattern": pat, "urls_window_A": len(A), "urls_window_B": len(B),
           "urls_in_both": len(both), "chosen": [(k, len(A[k]), len(B[k])) for k in chosen]}
json.dump(summary, open(f"out/summary_{brand}.json", "w"), indent=1)
print(json.dumps(summary)[:1500], flush=True)
PRICE_PATTERNS = [
  ("jsonld_offer_price", re.compile(r'"offers"\s*:\s*[\[{].{0,600}?"price"\s*:\s*"?([0-9][0-9,]*\.?[0-9]*)"?', re.S)),
  ("meta_product_price", re.compile(r'(?:product:price:amount|og:price:amount)"\s+content="([0-9][0-9,]*\.?[0-9]*)"', re.I)),
  ("meta_product_price_rev", re.compile(r'content="([0-9][0-9,]*\.?[0-9]*)"\s+(?:property|name)="(?:product:price:amount|og:price:amount)"', re.I)),
  ("itemprop_price", re.compile(r'itemprop="price"[^>]*content="([0-9][0-9,]*\.?[0-9]*)"', re.I)),
  ("json_price_field", re.compile(r'"(?:salePrice|listPrice|regularPrice|price|currentPrice|formattedPrice)"\s*:\s*"?\$?([0-9][0-9,]*\.[0-9]{2})"?')),
]
CUR = re.compile(r'"priceCurrency"\s*:\s*"([A-Z]{3})"|product:price:currency"\s+content="([A-Z]{3})"')
TITLE = re.compile(r"<title[^>]*>(.*?)</title>", re.S | re.I)
with open(f"out/prices_{brand}.csv", "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["brand", "product_urlkey", "window", "month", "snapshot_timestamp", "snapshot_url", "page_title", "price", "currency", "method"])
    for k in chosen:
        for win, D in (("A_2018_2020", A), ("B_2024_2026", B)):
            for month, (ts, orig) in sorted(D[k].items()):
                snap = f"https://web.archive.org/web/{ts}id_/{orig}"
                page = get(snap, timeout=90, tries=2) or ""
                price = method = cur = ""
                for name, rx in PRICE_PATTERNS:
                    m = rx.search(page)
                    if m:
                        price, method = m.group(1).replace(",", ""), name; break
                c = CUR.search(page)
                if c: cur = c.group(1) or c.group(2)
                t = TITLE.search(page)
                title = html.unescape(re.sub(r"\s+", " ", t.group(1)).strip())[:150] if t else ""
                w.writerow([brand, k, win, month, ts, f"https://web.archive.org/web/{ts}/{orig}", title, price, cur, method or ("no_price_found" if page else "fetch_failed")])
                f.flush(); time.sleep(1.5)
        print("done", k, flush=True)
