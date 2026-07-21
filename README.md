# vfct-to-sparkyfitness

Import the official **Vietnamese Food Composition Table 2007** (*Bảng thành phần thực phẩm Việt Nam*, Viện Dinh Dưỡng / Bộ Y Tế) into a self-hosted [SparkyFitness](https://github.com/CodeWithCJ/SparkyFitness) instance.

SparkyFitness ships with OpenFoodFacts, USDA, FatSecret, Nutritionix and a few other food-data providers, but none of them cover Vietnamese home-cooked ingredients and dishes well. This repo parses the official 526-food, 86-nutrient reference table (a PDF) into a clean CSV and pushes it into SparkyFitness as custom foods via its actual import API.

## What's here

| File | What it does |
|---|---|
| `vfct_parser.py` | Parses the source PDF into `vfct_foods.csv` (name, group, core macros per 100g) |
| `push_to_sparkyfitness.py` | Pushes the CSV into a running SparkyFitness instance |
| `cleanup_vfct_import.py` | Deletes everything previously imported by this tool, for a clean re-run |

## Source data

Download the PDF first (not included in this repo):

```bash
wget https://www.fao.org/fileadmin/templates/food_composition/documents/pdf/VTN_FCT_2007.pdf
```

526 foods across 14 groups (cereals, tubers, legumes/nuts, vegetables, fruits, oils, meat, seafood, eggs, dairy, canned goods, sweets, condiments, beverages), each with proximates (water, energy, protein, fat, carbs, fiber, ash) plus a much longer list of vitamins/minerals/amino acids/fatty acids that this tool does not currently extract — see [Scope](#scope) below. 

## The TCVN3 encoding problem

The PDF's Vietnamese food *names* are typeset in **TCVN3** (aka "ABC"), a legacy pre-Unicode 8-bit Vietnamese font encoding. Naive text extraction turns `Gạo nếp cái` into mojibake like `G¹o nÕp c¸i`. English names and all numeric nutrient values use a different, standard-encoded font and extract cleanly regardless.

`vfct_parser.py` decodes this automatically using the standard TCVN3→Unicode mapping table, including normalizing several different dash-lookalike characters (soft hyphen, minus sign, etc.) that the PDF extractor inconsistently substitutes for TCVN3's literal `-` (which the font maps to `ư`). Both the raw and decoded Vietnamese name are kept in the output CSV (`name_vn_raw`, `name_vn`) so you can spot-check.

Some pages in the source PDF have a shifted layout where the page's `STT`/food-code header sits on the same line as the food name instead of on its own line. The parser flags any row where this produces a suspicious result (an empty name, or a name that accidentally captured a field label) with `needs_review=True` — these are skipped from the import by default and should be checked by hand against the PDF.

## Usage

### 1. Install dependencies

**Create a virtual environment**
```bash
python3 -m venv venv
```

**Activate it**
in unix systems:
```
source venv/bin/activate
```
on windows:
```
.\venv\bin\activate
```

**Install the requirements**
```
pip install -r requirements.txt
```

### 2. Parse the PDF

```bash
python3 vfct_parser.py VTN_FCT_2007.pdf vfct_foods.csv
```

Prints a summary: total entries parsed, non-food pages skipped (front matter/TOC/group dividers), entries missing energy data, and entries flagged `needs_review`.

#### Example 

```bash
$ python3 vfct_parser.py VTN_FCT_2007.pdf vfct_foods.csv

Parsed 526 food entries -> vfct_foods.csv
Skipped 41 non-food pages (front matter / TOC / group headers)
Entries missing energy_kcal: 0 (check PDF page manually if this seems high)
Entries flagged needs_review=True: 170 (bad name parse - check these rows before importing)
```

### 3. Get a JWT token for your SparkyFitness instance

Log into the SparkyFitness web UI, go to `Settings` tab, `API Key Management` section, and generate a new API key

### 4. Push to SparkyFitness

```bash
# dry run first - prints payloads, touches nothing
python3 push_to_sparkyfitness.py \
  --csv vfct_foods.csv \
  --server https://your-sparkyfitness-domain \
  --token <jwt> \
  --dry-run

# for real
python3 push_to_sparkyfitness.py \
  --csv vfct_foods.csv \
  --server https://your-sparkyfitness-domain \
  --token <jwt>
```

Imports in batches of 20 (`--batch-size` to change). Every food is tagged `brand: "VFCT 2007"` so it can't collide with anything already in your database under a plain name, and can be identified/cleaned up later.

If your instance is behind a self-signed certificate (e.g. an internal Caddy CA on a homelab domain), add `--insecure` to skip TLS verification. Only do this against a host you actually control.

#### Example 

```bash
$ python3 push_to_sparkyfitness.py --csv vfct_foods.csv --server https://fitness.internal --token vYkpoowPvydGwdJP...WAPnyUCgXIHQAmVd --insecure

Skipping 170 rows flagged needs_review by the parser.
Loaded 356 CSV rows, 356 have usable nutrition data.
WARNING: TLS verification disabled (--insecure). Only do this against a domain/host you control.
OK: 20 foods (Gạo nếp cái ... Bún)
OK: 20 foods (Cốm ... Bột khoai lang)
OK: 20 foods (Bột khoai riềng (bột đao) ... Hạt dẻ to)
OK: 20 foods (Hạt dẻ tươi ... Sữa bột đậu nμnh)
OK: 20 foods (Sữa đậu nμnh (100g đậu/lít) ... Cần tây)
OK: 20 foods (Chuối xanh ... Hμnh lá (hμnh hoa))
OK: 20 foods (Hμnh tây ... Ngô bao tử)
OK: 20 foods (Ngó sen ... Rau má, má mơ)
OK: 20 foods (Rau mồng tơi ... Súp lơ trắng)
OK: 20 foods (Súp lơ xanh ... Men bia khô)
OK: 20 foods (Men bia tươi ... Dứa ta)
OK: 20 foods (Dứa tây ... Na)
OK: 20 foods (Nhãn ... Vú sữa)
OK: 20 foods (Xoμi chín ... Thịt bò loại II)
OK: 20 foods (Thịt bò, lưng, nạc ... Thịt trâu bắp)
OK: 20 foods (Thịt trâu cổ ... Lưỡi lợn)
OK: 20 foods (Lòng lợn (ruột giμ) ... Chả quế lợn)
OK: 16 foods (Dăm bông lợn ... Nước mắm loại II)

Done. Imported: 356, Failed batches (foods): 0
```

### 5. Clean up / re-run

The SparkyFitness API rejects an entire batch of 20 if *any* row in it collides with a food already in the database (`(user_id, name, brand)` must be unique). This means a single already-imported or duplicate name can take down 19 unrelated foods with it. If you need to re-run the import — e.g. after fixing a parsing issue — clear out the previous run first:

```bash
# see what would be deleted
python3 cleanup_vfct_import.py --server https://your-sparkyfitness-domain --token <jwt> --insecure --dry-run

# actually delete it
python3 cleanup_vfct_import.py --server https://your-sparkyfitness-domain --token <jwt> --insecure
```

This finds and deletes everything tagged `brand: "VFCT 2007"` (override with `--brand` if you changed it).

#### Example 

```bash
$ python3 cleanup_vfct_import.py --server https://fitness.internal --token vYkpoowPvydGwdJP...WAPnyUCgXIHQAmVd --insecure
WARNING: TLS verification disabled (--insecure).
Found 359 foods with brand="VFCT 2007".

Done. Deleted: 359, Failed: 0
```

## Scope

Currently extracted: Vietnamese name (decoded), English name, food group, % waste (`Thải bỏ`), and the core proximates per 100g edible portion (water, energy, protein, fat, carbohydrate, fiber, ash). The source table has ~80 additional columns (vitamins, minerals, amino acids, fatty acids, isoflavones) that aren't currently parsed — SparkyFitness's food-variant schema supports some of these (sodium, potassium, calcium, iron, vitamin A/C) but not most of the rest, so extending the parser further has diminishing returns unless you specifically need micronutrient tracking.

Composite/home-cooked dishes (e.g. a bowl of phở) aren't in the source table at all — it covers raw ingredients and some prepared foods, not full recipes. Build those as SparkyFitness "recipes" from the imported raw ingredients.

## Data source & license

*Bảng thành phần thực phẩm Việt Nam* (Vietnamese Food Composition Table), 2007, Viện Dinh Dưỡng (National Institute of Nutrition), Bộ Y Tế (Ministry of Health), published by Nhà Xuất Bản Y Học. Mirrored by FAO's INFOODS program. This repo contains no PDF content, only code to parse and import data the user downloads separately.
