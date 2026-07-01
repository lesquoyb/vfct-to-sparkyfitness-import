#!/usr/bin/env python3
"""
Pushes vfct_foods.csv (produced by vfct_parser.py) into a running
SparkyFitness instance via its actual bulk-import endpoint.

Confirmed against SparkyFitness source (routes/foodCrudRoutes.ts,
models/food.ts, as of the CodeWithCJ/SparkyFitness repo):

  POST {server}/api/foods/import-from-csv
  Auth: JWT bearer token (Authorization: Bearer <token>)
  Body: { "foods": [ {name, brand, serving_size, serving_unit,
                       calories, protein, carbs, fat, dietary_fiber,
                       source, ...}, ... ] }

  Note the /api/ prefix: SparkyFitness's nginx only reverse-proxies
  paths under /api/ to the Node backend; everything else falls through
  to the static SPA file server (which returns a plain nginx 405 for
  any non-GET request). The Express app itself mounts the food routes
  at app.use('/api/foods', foodRoutes) - confirmed in
  SparkyFitnessServer/SparkyFitnessServer.ts.

IMPORTANT - duplicate check:
  The server does a pre-flight check on (user_id, name, brand). If ANY
  row in a batch collides with an existing food, the ENTIRE batch is
  rejected (no partial import). This script:
    - tags every row with brand="VFCT 2007" to avoid colliding with
      anything you already have under a plain name
    - sends in small batches so one collision doesn't nuke the whole run
    - on a batch failure, prints the batch so you can inspect/retry it

USAGE:
    python3 push_to_sparkyfitness.py \\
        --csv vfct_foods.csv \\
        --server https://sparkyfitness.yourdomain.com \\
        --token <your JWT token> \\
        [--batch-size 20] [--dry-run]

GETTING A JWT TOKEN:
  Easiest: log into the SparkyFitness web UI, open browser dev tools ->
  Network tab, make any request, and copy the Authorization: Bearer
  header value. Tokens expire, so re-grab it if you get 401s partway
  through a long import.
"""

import argparse
import csv
import sys
import time

import requests


def to_food_row(csv_row):
    def num(key):
        v = csv_row.get(key, "")
        if v in ("", None):
            return None
        try:
            return float(v)
        except ValueError:
            return None

    name = csv_row.get("name_vn") or csv_row.get("name_en") or "Unknown"
    group_name = csv_row.get("group_name", "")

    return {
        "name": name,
        "brand": "VFCT 2007",
        "serving_size": 100,
        "serving_unit": "g",
        "calories": num("energy_kcal"),
        "protein": num("protein_g"),
        "carbs": num("carb_g"),
        "fat": num("fat_g"),
        "dietary_fiber": num("fiber_g"),
        # DB check constraint food_variants_source_check only allows
        # 'manual' | 'ai_estimate' | 'imported' - confirmed in
        # SparkyFitnessServer/db/migrations/20260523120000_ai_assisted_conversions.sql
        "source": "imported",
    }


def chunked(seq, n):
    for i in range(0, len(seq), n):
        yield seq[i:i + n]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", required=True, help="Path to vfct_foods.csv")
    ap.add_argument("--server", required=True, help="Base URL, e.g. https://sparkyfitness.example.com")
    ap.add_argument("--token", required=True, help="JWT bearer token")
    ap.add_argument("--batch-size", type=int, default=20)
    ap.add_argument("--dry-run", action="store_true", help="Print payloads instead of sending them")
    ap.add_argument("--insecure", action="store_true",
                     help="Skip TLS certificate verification (self-signed certs).")
    args = ap.parse_args()

    with open(args.csv, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    flagged = sum(1 for r in rows if r.get("needs_review") == "True")
    if flagged:
        print(f"Skipping {flagged} rows flagged needs_review by the parser.")
    rows = [r for r in rows if r.get("needs_review") != "True"]

    foods = [to_food_row(r) for r in rows]
    # Skip rows with no usable calorie data - nothing meaningful to import
    foods = [f for f in foods if f["calories"] is not None]

    # Dedupe on (name, brand): the server's duplicate check operates on
    # this pair and rejects the ENTIRE batch if any row collides with
    # something already in the DB (including an earlier row in this same
    # run). A stray duplicate name would otherwise take a whole 20-food
    # batch down with it.
    seen = set()
    deduped = []
    dupes = 0
    for f in foods:
        key = (f["name"], f["brand"])
        if key in seen:
            dupes += 1
            continue
        seen.add(key)
        deduped.append(f)
    if dupes:
        print(f"Skipping {dupes} duplicate (name, brand) rows.")
    foods = deduped

    print(f"Loaded {len(rows)} CSV rows, {len(foods)} have usable nutrition data.")

    url = args.server.rstrip("/") + "/api/foods/import-from-csv"
    headers = {
        "Authorization": f"Bearer {args.token}",
        "Content-Type": "application/json",
    }

    verify = True
    if args.insecure:
        verify = False
        import urllib3
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        print("WARNING: TLS verification disabled (--insecure). Only do this against a domain/host you control.")

    total_ok = 0
    total_fail = 0
    for batch in chunked(foods, args.batch_size):
        if args.dry_run:
            print(f"[dry-run] would POST {len(batch)} foods, e.g. {batch[0]}")
            total_ok += len(batch)
            continue

        resp = requests.post(url, json={"foods": batch}, headers=headers, timeout=30, verify=verify)
        if resp.status_code == 200:
            total_ok += len(batch)
            print(f"OK: {len(batch)} foods ({batch[0]['name']} ... {batch[-1]['name']})")
        else:
            total_fail += len(batch)
            print(f"FAILED ({resp.status_code}) batch starting at {batch[0]['name']}:")
            print(f"  {resp.text[:500]}")
            print("  Skipping this batch, continuing with the next one.")
        time.sleep(0.2)  # be gentle on the server

    print(f"\nDone. Imported: {total_ok}, Failed batches (foods): {total_fail}")


if __name__ == "__main__":
    main()
