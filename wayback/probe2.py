"""Wayback coverage probe for every brand of the 20 panel firms.
Usage: python wayback/probe2.py <FIRM>. Writes out/probe_<FIRM>.json"""
import json, time, urllib.request, urllib.parse, sys, os, re
SITES = {
 "LVMH": [("louisvuitton","us.louisvuitton.com/eng-us/products/*"),("dior","dior.com/en_us/*"),("celine","celine.com/en-us/*")],
 "KER": [("gucci","gucci.com/us/en/pr/*"),("ysl","ysl.com/en-us/*"),("bottega","bottegaveneta.com/en-us/*"),("balenciaga","balenciaga.com/en-us/*")],
 "BRBY": [("burberry","us.burberry.com/*")],
 "TPR": [("coach","coach.com/products/*"),("katespade","katespade.com/products/*"),("stuartweitzman","stuartweitzman.com/products/*")],
 "CPRI": [("michaelkors","michaelkors.com/*"),("versace","versace.com/us/en/*"),("jimmychoo","jimmychoo.com/en-us/*")],
 "RL": [("ralphlauren","ralphlauren.com/*")],
 "PVH": [("tommy","usa.tommy.com/*"),("calvinklein","calvinklein.us/*")],
 "LEVI": [("levi","levi.com/US/en_US/*")],
 "VFC": [("northface","thenorthface.com/*"),("vans","vans.com/*"),("timberland","timberland.com/*")],
 "COLM": [("columbia","columbia.com/*")],
 "LULU": [("lululemon","shop.lululemon.com/p/*")],
 "UAA": [("underarmour","underarmour.com/en-us/*")],
 "GIII": [("dkny","dkny.com/*"),("karllagerfeld","karllagerfeld.com/*")],
 "ITX": [("zara","zara.com/us/en/*")],
 "HM": [("hm","www2.hm.com/en_us/productpage*")],
 "GAP": [("gap","gap.com/browse/product.do*"),("oldnavy","oldnavy.gap.com/browse/product.do*"),("bananarepublic","bananarepublic.gap.com/browse/product.do*"),("athleta","athleta.gap.com/browse/product.do*")],
 "AEO": [("americaneagle","ae.com/us/en/p/*")],
 "ANF": [("abercrombie","abercrombie.com/shop/us/p/*"),("hollister","hollisterco.com/shop/us/p/*")],
 "URBN": [("urbanoutfitters","urbanoutfitters.com/products/*"),("anthropologie","anthropologie.com/shop/*"),("freepeople","freepeople.com/shop/*")],
 "CRI": [("carters","carters.com/*"),("oshkosh","oshkosh.com/*")],
}
PROD = re.compile(r"(/p/|/pr/|/products?/|/shop/|productpage|product\.do|/prod|-p\d|\d{5,}|\.html)", re.I)
def cdx(params):
    u = "https://web.archive.org/cdx/search/cdx?" + urllib.parse.urlencode(params, doseq=True)
    err = ""
    for a in range(4):
        try:
            with urllib.request.urlopen(urllib.request.Request(u, headers={"User-Agent": "dissertation research probe"}), timeout=180) as r:
                return r.read().decode(errors="ignore")
        except Exception as e:
            err = str(e); time.sleep(20 * (a + 1))
    return "ERR " + err
firm = sys.argv[1]
out = {}
for brand, pat in SITES[firm]:
    out[brand] = {"pattern": pat}
    for y in (2018, 2019, 2020, 2024, 2025, 2026):
        t = cdx({"url": pat, "from": y, "to": y, "filter": ["statuscode:200", "mimetype:text/html"], "collapse": "urlkey", "fl": "original", "limit": 5000})
        if t.startswith("ERR"):
            out[brand][y] = {"error": t[:150]}
        else:
            urls = [l for l in t.splitlines() if l]
            prod = [l for l in urls if PROD.search(l)]
            out[brand][y] = {"distinct_urls": len(urls), "product_like": len(prod), "sample": prod[:5]}
        print(firm, brand, y, out[brand][y].get("product_like", out[brand][y].get("error")), flush=True)
        time.sleep(4)
os.makedirs("out", exist_ok=True)
json.dump(out, open(f"out/probe_{firm}.json", "w"), indent=1)
