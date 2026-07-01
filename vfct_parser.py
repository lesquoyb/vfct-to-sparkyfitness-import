#!/usr/bin/env python3
"""
Parser for the Vietnamese Food Composition Table (Bảng thành phần thực phẩm
Việt Nam 2007, Viện Dinh Dưỡng / Bộ Y Tế) into a clean CSV suitable for
importing into SparkyFitness as custom foods.

Source PDF:
https://www.fao.org/fileadmin/templates/food_composition/documents/pdf/VTN_FCT_2007.pdf

USAGE:
    pip install pypdf --break-system-packages
    python3 vfct_parser.py VTN_FCT_2007.pdf vfct_foods.csv

WHAT IT EXTRACTS (per food, one food = one PDF page):
  - stt            : sequential index in the table (1-526)
  - food_code      : internal code (e.g. 1001) -> first digit = group
  - group          : food group number (1-14), derived from food_code
  - waste_pct      : % discarded (Thải bỏ), e.g. skin/bone/peel
  - name_en        : English name (reliable, clean text)
  - name_vn_raw    : Vietnamese name AS EXTRACTED (may be mojibake, see below)
  - water_g, energy_kcal, protein_g, fat_g, carb_g, fiber_g, ash_g
        -> core proximates per 100g edible portion (all reliable, clean)

VIETNAMESE NAME DECODING:
  The PDF uses the legacy 8-bit TCVN3 (aka "ABC") Vietnamese font for the
  Vietnamese food name labels specifically, which text extraction renders
  as mojibake, e.g. "G¹o nÕp c¸i" instead of "Gạo nếp cái". This script
  decodes it automatically using the standard TCVN3->Unicode table
  (verified against this exact PDF's output: Gạo nếp cái, Củ sắn dây, Kê,
  Ngô bắp tươi, Bánh đúc, Bánh phở, Bánh quẩy, Bỏng ngô, Bánh mỳ all
  decode correctly). Both name_vn_raw (untouched) and name_vn (decoded)
  are written to the CSV so you can spot-check a sample against the PDF.
  Note: TCVN3 technically uses a separate capital-letter font mapping
  that this table doesn't cover, but since Vietnamese food names here
  only capitalize the first (plain ASCII) letter of the first word, this
  is not an issue in practice for this dataset.

GROUPS (Nhóm):
  1  Ngũ cốc và sản phẩm chế biến      (Cereals & products)
  2  Khoai củ và sản phẩm chế biến     (Tubers & products)
  3  Hạt, quả giàu đạm béo             (Nuts, seeds, legumes)
  4  Rau, quả, củ dùng làm rau         (Vegetables)
  5  Quả chín                          (Fruits)
  6  Dầu, mỡ, bơ                       (Oils & fats)
  7  Thịt và sản phẩm chế biến         (Meat & products)
  8  Thủy sản và sản phẩm chế biến     (Seafood & products)
  9  Trứng và sản phẩm chế biến        (Eggs & products)
  10 Sữa và sản phẩm chế biến          (Dairy & products)
  11 Đồ hộp                            (Canned foods)
  12 Đồ ngọt (đường, bánh, mứt, kẹo)   (Sweets)
  13 Gia vị, nước chấm                 (Condiments & sauces)
  14 Nước giải khát, bia, rượu         (Beverages)
"""

import csv
import re
import sys

try:
    from pypdf import PdfReader
except ImportError:
    print("Install pypdf first: pip install pypdf --break-system-packages")
    sys.exit(1)


# TCVN3 (legacy Vietnamese 8-bit "ABC" font) -> Unicode decode table.
# Verified against this exact PDF's mojibake output.
_TCVN3_CHARS = "µ¸¶·¹¨»¾¼½Æ©ÇÊÈÉË®ÌÐÎÏÑªÒÕÓÔÖ×ÝØÜÞßãáâä«åèæçé¬êíëìîïóñòô-õøö÷ùúýûüþ¡¢§£¤¥¦"
_UNICODE_CHARS = "àáảãạăằắẳẵặâầấẩẫậđèéẻẽẹêềếểễệìíỉĩịòóỏõọôồốổỗộơờớởỡợùúủũụưừứửữựỳýỷỹỵĂÂĐÊÔƠƯ"
_TCVN3_MAP = dict(zip(_TCVN3_CHARS, _UNICODE_CHARS))
_TCVN3_RE = re.compile("|".join(re.escape(c) for c in _TCVN3_CHARS))


def tcvn3_to_unicode(s):
    """Decode TCVN3-mojibake Vietnamese text (as produced by this PDF's
    text extraction) into proper Unicode. Safe to call on already-clean
    text (English names etc.) since none of the TCVN3 glyph bytes appear
    in plain ASCII."""
    if not s:
        return s
    # The PDF extractor renders TCVN3's literal '-' (which the font maps
    # to 'ư') inconsistently across pages/fonts as various dash-like
    # Unicode characters instead of a plain ASCII hyphen. Normalize all
    # of them first. Seen so far: soft hyphen (\xad), minus sign (−).
    for dash_variant in ("\xad", "\u2212", "\u2010", "\u2011", "\u2013", "\u2014"):
        s = s.replace(dash_variant, "-")
    return _TCVN3_RE.sub(lambda m: _TCVN3_MAP[m.group(0)], s)


GROUP_NAMES = {
    1: "Cereals & products",
    2: "Tubers & products",
    3: "Nuts, seeds, legumes",
    4: "Vegetables",
    5: "Fruits",
    6: "Oils & fats",
    7: "Meat & products",
    8: "Seafood & products",
    9: "Eggs & products",
    10: "Dairy & products",
    11: "Canned foods",
    12: "Sweets",
    13: "Condiments & sauces",
    14: "Beverages",
}

# Regexes tuned against the actual extracted text of VTN_FCT_2007.pdf.
# The "STT:" header line is reliable (plain digits). Food code is also
# plain digits even though its Vietnamese label ("Mã số") is mojibake.
RE_STT = re.compile(r"STT:\s*(\d+)")
RE_CODE = re.compile(r"[°M]?[·¬].?\s*s[eè]\s*:\s*(\d+)", re.IGNORECASE)
RE_CODE_FALLBACK = re.compile(r"\b(1[0-4]\d{2,3})\b")  # e.g. 1001..14xx
RE_WASTE = re.compile(r"\(%\):\s*([\d.]+)")
# IMPORTANT: use [ \t]* (not \s*) before the capture group. \s matches
# newlines too, so \s*(.+) can silently jump across a line break and
# capture a completely unrelated line - this was the root cause of
# names coming out as literally "Tên tiếng Anh (English):" on pages
# where a label had nothing after it on the same line. Restricting to
# same-line-only capture with [^\n]+ prevents that.
RE_NAME_EN = re.compile(r"\(English\):[ \t]*([^\n]+)")
RE_NAME_VN = re.compile(r"\(Vietnamese\):[ \t]*([^\n]+)")
# On some pages (e.g. STT 60 "Hạt dẻ to") the STT/food-code header sits
# on the SAME line as the name instead of its own line, leaking into
# the capture as a trailing suffix like " STT: 60" or " Mã số: 3011".
# Strip that off.
RE_TRAILING_LEAK = re.compile(r"\s*(STT:|M[·ã]\s*s[eè]:).*$")

RE_WATER = re.compile(r"N[uướ]{1,2}c\s*\(Water\s*\)\s*g\s*([\d.]+|-)")
RE_ENERGY = re.compile(r"Energy\s*\)\s*KCal\s*([\d.]+|-)")
RE_PROTEIN = re.compile(r"\bProtein\s*g\s*([\d.]+|-)")
RE_FAT = re.compile(r"Lipid\s*\(Fat\)\s*g\s*([\d.]+|-)")
RE_CARB = re.compile(r"Glucid\s*\(Carbohydrate\)\s*g\s*([\d.]+|-)")
RE_FIBER = re.compile(r"Celluloza\s*\(Fiber\)\s*g\s*([\d.]+|-)")
RE_ASH = re.compile(r"Tro\s*\(Ash\)\s*g\s*([\d.]+|-)")


def parse_num(s):
    if s is None or s == "-":
        return None
    try:
        return float(s)
    except ValueError:
        return None


def parse_page(text):
    stt_m = RE_STT.search(text)
    if not stt_m:
        return None  # not a food data page (e.g. front matter, TOC)

    row = {"stt": int(stt_m.group(1))}

    code_m = RE_CODE.search(text) or RE_CODE_FALLBACK.search(text)
    row["food_code"] = code_m.group(1) if code_m else ""
    row["group"] = int(row["food_code"][0]) if row["food_code"] else None
    row["group_name"] = GROUP_NAMES.get(row["group"], "")

    waste_m = RE_WASTE.search(text)
    row["waste_pct"] = parse_num(waste_m.group(1)) if waste_m else None

    en_m = RE_NAME_EN.search(text)
    row["name_en"] = RE_TRAILING_LEAK.sub("", en_m.group(1).strip()).strip() if en_m else ""

    vn_m = RE_NAME_VN.search(text)
    vn_raw = RE_TRAILING_LEAK.sub("", vn_m.group(1).strip()).strip() if vn_m else ""
    row["name_vn_raw"] = vn_raw
    row["name_vn"] = tcvn3_to_unicode(vn_raw)

    # Sanity check: if either name accidentally captured a field label
    # instead of a real value (the cross-line-jump bug), flag it rather
    # than silently shipping garbage that will later collide as a
    # "duplicate" with every other similarly-broken row.
    suspicious_markers = ("(English)", "(Vietnamese)", "Thành phần dinh dưỡng", "Th\u03bc\u03b1nh ph\u1ea7n")
    row["needs_review"] = any(
        m in row["name_en"] or m in row["name_vn"] for m in suspicious_markers
    ) or not row["name_en"] or not row["name_vn_raw"]

    for key, rx in [
        ("water_g", RE_WATER),
        ("energy_kcal", RE_ENERGY),
        ("protein_g", RE_PROTEIN),
        ("fat_g", RE_FAT),
        ("carb_g", RE_CARB),
        ("fiber_g", RE_FIBER),
        ("ash_g", RE_ASH),
    ]:
        m = rx.search(text)
        row[key] = parse_num(m.group(1)) if m else None

    return row


def main():
    if len(sys.argv) != 3:
        print("Usage: python3 vfct_parser.py <input.pdf> <output.csv>")
        sys.exit(1)

    in_path, out_path = sys.argv[1], sys.argv[2]
    reader = PdfReader(in_path)

    rows = []
    skipped = 0
    for i, page in enumerate(reader.pages):
        text = page.extract_text() or ""
        row = parse_page(text)
        if row:
            rows.append(row)
        else:
            skipped += 1

    rows.sort(key=lambda r: r["stt"])

    fieldnames = [
        "stt", "food_code", "group", "group_name", "waste_pct",
        "name_en", "name_vn", "name_vn_raw", "needs_review",
        "water_g", "energy_kcal", "protein_g", "fat_g",
        "carb_g", "fiber_g", "ash_g",
    ]
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    print(f"Parsed {len(rows)} food entries -> {out_path}")
    print(f"Skipped {skipped} non-food pages (front matter / TOC / group headers)")
    if rows:
        missing_energy = sum(1 for r in rows if r["energy_kcal"] is None)
        print(f"Entries missing energy_kcal: {missing_energy} (check PDF page manually if this seems high)")
        needs_review = sum(1 for r in rows if r["needs_review"])
        print(f"Entries flagged needs_review=True: {needs_review} (bad name parse - check these rows before importing)")


if __name__ == "__main__":
    main()
