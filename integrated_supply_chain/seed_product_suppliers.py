"""
seed_product_suppliers.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
One-time utility: assigns a supplier_id to every product.

Matching rule:
  • For each product, find all suppliers whose categories_supplied
    includes the product's category.
  • Pick ONE supplier randomly from the matching list.
  • One product → exactly one supplier (never shared assignment).
  • Already-assigned products are skipped (idempotent).

Run once:
    python seed_product_suppliers.py

Re-running is safe — already-assigned products are left untouched.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""
from __future__ import annotations

import random
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv
load_dotenv()

from core.db import col, ping

# ─── DB guard ─────────────────────────────────────────────────────────────────
if not ping():
    print("ERROR: Cannot connect to MongoDB. Check MONGO_URI in your .env file.")
    sys.exit(1)

print("Connected to MongoDB.\n")

# ─── Load suppliers ───────────────────────────────────────────────────────────
suppliers = list(col("suppliers").find(
    {},
    {"_id": 0, "supplier_id": 1, "supplier_name": 1,
     "categories_supplied": 1, "trust_score": 1}
))
if not suppliers:
    print("ERROR: No suppliers found.")
    sys.exit(1)

print(f"Loaded {len(suppliers)} supplier(s):")
for s in suppliers:
    cats = ", ".join(s.get("categories_supplied", []))
    print(f"  {s['supplier_id']}  |  {s['supplier_name']}  |  [{cats}]")
print()

# ─── Build category → list of supplier_ids ───────────────────────────────────
from collections import defaultdict
from typing import List, Dict

cat_to_suppliers: Dict[str, List[str]] = defaultdict(list)
for s in suppliers:
    for cat in s.get("categories_supplied", []):
        cat_to_suppliers[cat.strip()].append(s["supplier_id"])

# ─── Load products ────────────────────────────────────────────────────────────
products = list(col("products").find(
    {},
    {"_id": 0, "product_id": 1, "name": 1, "category": 1, "supplier_id": 1}
))
if not products:
    print("ERROR: No products found.")
    sys.exit(1)

print(f"Found {len(products)} product(s).\n")

# ─── Assign one random supplier per product ───────────────────────────────────
updated   = 0
skipped   = 0
unmatched = 0

for product in products:
    pid      = product["product_id"]
    name     = product["name"]
    category = product.get("category", "").strip()

    # Skip if already assigned
    if product.get("supplier_id"):
        print(f"  [SKIP]      {pid}  |  {name:<25}  "
              f"already has supplier_id={product['supplier_id']}")
        skipped += 1
        continue

    # Case-insensitive category match
    candidates = next(
        (v for k, v in cat_to_suppliers.items() if k.lower() == category.lower()),
        []
    )

    if not candidates:
        print(f"  [UNMATCHED] {pid}  |  {name:<25}  "
              f"category='{category}' — no supplier covers this category")
        unmatched += 1
        continue

    # Pick one supplier at random
    chosen_sid = random.choice(candidates)
    chosen_sup = next(s for s in suppliers if s["supplier_id"] == chosen_sid)

    col("products").update_one(
        {"product_id": pid},
        {"$set": {"supplier_id": chosen_sid}},
    )
    print(f"  [SET]       {pid}  |  {name:<25}  "
          f"category='{category}'  →  {chosen_sid} ({chosen_sup['supplier_name']})")
    updated += 1

# ─── Summary ──────────────────────────────────────────────────────────────────
print()
print("━" * 64)
print(f"  Set       : {updated}")
print(f"  Skipped   : {skipped}  (already had a supplier_id)")
print(f"  Unmatched : {unmatched}  (no supplier for that category)")
print(f"  Total     : {len(products)}")
print("━" * 64)
print()
if unmatched:
    print("⚠️  Some products have no matching supplier.")
    print("   Add those categories to a supplier's categories_supplied array")
    print("   in MongoDB, then re-run this script.\n")
print("Done — products collection updated with supplier_id.")

