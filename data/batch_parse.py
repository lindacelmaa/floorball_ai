"""
Batch-convert every match-report .html file in a folder into parsed .json,
skipping any that already have a matching .json (so it's safe to rerun after
adding new games each week).

Usage (run from the project root):
    python data/batch_parse.py data/games/2025-2026

Or convert a single file, same as before:
    python data/parse_match.py data/games/2025-2026/2025-10-03_knss-balozi.html data/games/2025-2026/2025-10-03_knss-balozi.json
"""

import glob
import os
import sys

from parse_match import parse_match


def main():
    if len(sys.argv) != 2:
        print("Usage: python data/batch_parse.py <folder>")
        print("Example: python data/batch_parse.py data/games/2025-2026")
        sys.exit(1)

    folder = sys.argv[1]
    html_files = sorted(glob.glob(os.path.join(folder, "*.html")))

    if not html_files:
        print(f"No .html files found in {folder}")
        return

    converted, skipped = 0, 0
    for html_path in html_files:
        json_path = os.path.splitext(html_path)[0] + ".json"
        if os.path.exists(json_path):
            print(f"skip (already parsed): {os.path.basename(html_path)}")
            skipped += 1
            continue

        with open(html_path, encoding="utf-8") as f:
            html = f.read()

        try:
            data = parse_match(html)
        except ValueError as e:
            print(f"FAILED to parse {os.path.basename(html_path)}: {e}")
            continue

        import json
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        print(f"parsed: {os.path.basename(html_path)} -> {os.path.basename(json_path)}")
        converted += 1

    print(f"\nDone. Converted {converted}, skipped {skipped} (already had .json).")


if __name__ == "__main__":
    main()