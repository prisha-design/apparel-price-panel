#!/usr/bin/env python3
"""
Quick health check and first-pass statistics from data/observations.csv.

    python summarise.py

Prints, per retailer: days observed, products with a price today, share with an
origin label, origin mix, and a chained daily price index (geometric mean of
matched-product price relatives, Cavallo-style). No plots; this is a check that
the panel is accumulating, not the analysis.
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

p = Path(__file__).resolve().parent / "data" / "observations.csv"
if not p.exists():
    sys.exit("no data yet")
df = pd.read_csv(p, dtype=str)
df["price"] = pd.to_numeric(df["price"], errors="coerce")
df = df[df["price"].notna()]
df["date"] = pd.to_datetime(df["date"])
df["pid"] = df["sku"].where(df["sku"].notna() & (df["sku"] != ""), df["url"])

print(f"{len(df)} priced observations, {df['date'].nunique()} days, "
      f"{df['retailer'].nunique()} retailers\n")

for key, g in df.groupby("retailer"):
    days = g["date"].nunique()
    last = g[g["date"] == g["date"].max()]
    with_origin = (g["origin"].fillna("") != "").mean()
    mix = g.drop_duplicates("pid")["origin"].fillna("none").value_counts().head(6).to_dict()
    # Chained index: mean log price change of products seen on consecutive days.
    wide = g.pivot_table(index="date", columns="pid", values="price", aggfunc="first").sort_index()
    rel = np.log(wide).diff()
    idx = np.exp(rel.mean(axis=1).fillna(0).cumsum()) * 100
    print(f"{key:16s} days={days:3d} products_today={len(last):4d} "
          f"origin_share={with_origin:5.1%} index_latest={idx.iloc[-1]:.1f}")
    print(f"{'':16s} origin mix: {mix}")
