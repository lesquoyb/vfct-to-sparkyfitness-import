#!/usr/bin/env python3
"""
Deletes all foods tagged brand="VFCT 2007" from a SparkyFitness instance.
Use this to clean up a partial/broken import before re-running
push_to_sparkyfitness.py.

Confirmed against SparkyFitness source:
  GET  {server}/api/foods/foods-paginated?searchTerm=VFCT+2007
       -> searchTerm matches CONCAT(brand, ' ', name) ILIKE '%term%'
          (models/food.ts, getFoodsWithPagination), so this reliably
          finds everything imported with brand="VFCT 2007".
  DELETE {server}/api/foods/:id?forceDelete=true
       -> deletes a single food and its variants (routes/foodCrudRoutes.ts)

USAGE:
    python3 cleanup_vfct_import.py \\
        --server https://fitness.internal \\
        --token <your JWT token> \\
        [--insecure] [--dry-run]
"""

import argparse
import sys
import time

import requests


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--server", required=True)
    ap.add_argument("--token", required=True)
    ap.add_argument("--insecure", action="store_true")
    ap.add_argument("--dry-run", action="store_true", help="List what would be deleted, don't actually delete")
    ap.add_argument("--brand", default="VFCT 2007", help="Brand tag to match and delete (default: VFCT 2007)")
    args = ap.parse_args()

    verify = True
    if args.insecure:
        verify = False
        import urllib3
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        print("WARNING: TLS verification disabled (--insecure).")

    headers = {"Authorization": f"Bearer {args.token}"}
    base = args.server.rstrip("/")

    # Page through all matches. itemsPerPage kept modest and deliberate.
    to_delete = []
    page = 1
    items_per_page = 100
    while True:
        resp = requests.get(
            f"{base}/api/foods/foods-paginated",
            params={
                "searchTerm": args.brand,
                "currentPage": page,
                "itemsPerPage": items_per_page,
            },
            headers=headers,
            verify=verify,
            timeout=30,
        )
        if resp.status_code != 200:
            print(f"Failed to list foods ({resp.status_code}): {resp.text[:500]}")
            sys.exit(1)
        data = resp.json()
        foods = data.get("foods", [])
        if not foods:
            break
        # Extra safety: only delete exact brand matches, since searchTerm
        # is a substring match against brand+name combined and could in
        # theory match something unrelated with "VFCT 2007" in the name.
        to_delete.extend(f for f in foods if f.get("brand") == args.brand)
        if len(foods) < items_per_page:
            break
        page += 1

    print(f"Found {len(to_delete)} foods with brand=\"{args.brand}\".")
    if not to_delete:
        return

    if args.dry_run:
        for f in to_delete[:10]:
            print(f"  [dry-run] would delete: {f.get('name')} (id={f.get('id')})")
        if len(to_delete) > 10:
            print(f"  ...and {len(to_delete) - 10} more")
        return

    deleted, failed = 0, 0
    for f in to_delete:
        food_id = f["id"]
        resp = requests.delete(
            f"{base}/api/foods/{food_id}",
            params={"forceDelete": "true"},
            headers=headers,
            verify=verify,
            timeout=30,
        )
        if resp.status_code == 200:
            deleted += 1
        else:
            failed += 1
            print(f"  FAILED to delete {f.get('name')} (id={food_id}): {resp.status_code} {resp.text[:200]}")
        time.sleep(0.05)

    print(f"\nDone. Deleted: {deleted}, Failed: {failed}")


if __name__ == "__main__":
    main()
