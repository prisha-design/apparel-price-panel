"""Probe: how much of each brand's US site does the Wayback Machine hold, by year?"""
import json, time, urllib.request, urllib.parse, sys, os
SITES = {
 "levi": "levi.com/US/en_US/*",
 "ralphlauren": "ralphlauren.com/*",
 "gap": "gap.com/browse/product.do*",
 "lululemon": "shop.lululemon.com/p/*",
 "coach": "coach.com/products/*",
 "michaelkors": "michaelkors.com/*",
 "louisvuitton": "us.louisvuitton.com/eng-us/products/*",
 "zara": "zara.com/us/en/*",
 "hm": "www2.hm.com/en_us/productpage*",
 "burberry": "us.burberry.com/*",
 "americaneagle": "ae.com/us/en/p/*",
 "columbia": "columbia.com/p/*",
}
def cdx(params):
    u = "https://web.archive.org/cdx/search/cdx?" + urllib.parse.urlencode(params)
    for a in range(4):
        try:
            with urllib.request.urlopen(urllib.request.Request(u, headers={"User-Agent":"research-probe (student dissertation)"}), timeout=120) as r:
                return r.read().decode()
        except Exception as e:
            err = str(e); time.sleep(15)
    return "ERR " + err
out = {}
for name, pat in SITES.items():
    out[name] = {}
    for y in (2018, 2019, 2020, 2024, 2025, 2026):
        t = cdx({"url": pat, "from": y, "to": y, "filter": "statuscode:200", "collapse": "urlkey", "fl": "original", "limit": 3000, "showResumeKey": "false"})
        lines = [l for l in t.splitlines() if l and not l.startswith("ERR")]
        out[name][y] = {"distinct_urls": len(lines), "sample": lines[:3], "err": t[:120] if t.startswith("ERR") else ""}
        print(name, y, len(lines), flush=True)
        time.sleep(3)
os.makedirs("out", exist_ok=True)
json.dump(out, open("out/wayback_probe.json", "w"), indent=1)
