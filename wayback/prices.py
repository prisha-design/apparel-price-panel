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
def cdx_chunk(frm, to):
    p = {"url": pat, "from": frm, "to": to, "filter": ["statuscode:200", "mimetype:text/html"],
         "collapse": "timestamp:6", "fl": "urlkey,timestamp,original", "limit": 25000}
    return get("https://web.archive.org/cdx/search/cdx?" + urllib.parse.urlencode(p, doseq=True), timeout=300, tries=5) or ""
def cdx(frm, to):
    """Query the archive index in three-month pieces (whole windows time out on big sites)."""
    rows = defaultdict(dict)
    y, m = int(frm[:4]), int(frm[4:6])
    while (y, m) <= (int(to[:4]), int(to[4:6])):
        y2, m2 = (y, m + 2) if m <= 10 else (y + 1, m - 10)
        t = cdx_chunk(f"{y}{m:02d}", f"{y2}{m2:02d}")
        time.sleep(3)
        for line in t.splitlines():
            parts = line.split(" ")
            if len(parts) != 3: continue
            k, ts, orig = parts
            code = product_code(orig)
            if code:
                rows[code].setdefault(ts[:6], (ts, orig))
            sl = slug(orig)
            if sl:
                rows["SLUG:" + sl].setdefault(ts[:6], (ts, orig))
        y, m = (y, m + 3) if m <= 9 else (y + 1, m - 9)
    return rows
def slug(url):
    """Product name part of the address with any codes removed, e.g. neverfull-mm-monogram."""
    path = url.split("?")[0].split("#")[0]
    if not PRODLIKE.search(url):
        return None
    segs = [x for x in path.split("/") if x]
    if not segs: return None
    last = segs[-1].replace(".html", "")
    if len(last) < 12 and len(segs) > 1: last = segs[-2]
    toks = [t for t in re.split(r"[-_.]", last.lower()) if t and not any(ch.isdigit() for ch in t) and t not in ("p", "prod", "html")]
    return "-".join(toks) if len(toks) >= 3 else None
# Product pages change address over the years (new site designs), but the style
# number in the address usually survives. Match products across years on that code.
PRODLIKE = re.compile(r"(/p/|/pr/|/products?/|/shop/|productpage|product\.do|/prod|-p\d|\.html)", re.I)
CODE = re.compile(r"[A-Za-z]{0,6}\d{4,}[A-Za-z0-9]{0,10}")
def product_code(url):
    u = url.split("#")[0]
    path, _, query = u.partition("?")
    if not PRODLIKE.search(u):
        return None
    segs = [x for x in path.split("/") if x][-3:]
    cands = []
    for sg in reversed(segs):
        for tok in reversed(re.split(r"[-_.]", sg)):
            if CODE.fullmatch(tok) and sum(ch.isdigit() for ch in tok) >= 4:
                cands.append(tok)
    for m in re.finditer(r"(?:pid|productId|prod|style)=([A-Za-z0-9]{5,})", query):
        cands.append(m.group(1))
    cands = [c for c in cands if not re.fullmatch(r"20[12]\d{3,}", c)]
    return cands[0].upper() if cands else None
os.makedirs("out", exist_ok=True)
A = cdx("201801", "202002"); time.sleep(5)
B = cdx("202406", "202609")
both = [(min(len(A[k]), len(B[k])), k) for k in A if k in B and len(A[k]) >= 2 and len(B[k]) >= 2]
# prefer style-code matches; use name matches only where no code match exists
both.sort(key=lambda x: (not x[1].startswith("SLUG:"), x[0]), reverse=True)
chosen = [k for _, k in both[:N]]
summary = {"brand": brand, "pattern": pat, "codes_window_A": len(A), "codes_window_B": len(B),
           "codes_in_both": len(both), "chosen": [(k, len(A[k]), len(B[k])) for k in chosen]}
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
    w.writerow(["brand", "product_code", "window", "month", "snapshot_timestamp", "snapshot_url", "page_title", "price", "currency", "method"])
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
