#!/usr/bin/env python3

import sys
from collections import defaultdict
from pathlib import Path


def collect_files(root: Path):
    """
    Returns a mapping:
    key   = relative path WITHOUT extension
    value = set of original extensions found
    """
    files = defaultdict(set)

    for f in root.rglob("*"):
        if not f.is_file():
            continue

        rel = f.relative_to(root)
        key = rel.with_suffix("")  # remove extension
        files[key].add(f.suffix.lower())

    return files


def main(dir1: str, dir2: str):
    d1 = Path(dir1).resolve()
    d2 = Path(dir2).resolve()

    if not d1.is_dir() or not d2.is_dir():
        print("Both arguments must be directories")
        sys.exit(1)

    files1 = collect_files(d1)
    files2 = collect_files(d2)

    keys1 = set(files1.keys())
    keys2 = set(files2.keys())

    missing_in_dir2 = sorted(keys1 - keys2)
    missing_in_dir1 = sorted(keys2 - keys1)

    print("\n=== Missing in DIR2 ===")
    if missing_in_dir2:
        for k in missing_in_dir2:
            exts = ", ".join(files1[k])
            print(f"{k}   (found in DIR1 as: {exts})")
    else:
        print("None ✅")

    print("\n=== Missing in DIR1 ===")
    if missing_in_dir1:
        for k in missing_in_dir1:
            exts = ", ".join(files2[k])
            print(f"{k}   (found in DIR2 as: {exts})")
    else:
        print("None ✅")

    if not missing_in_dir1 and not missing_in_dir2:
        print("\n✔ Directories match (path-aware, extension ignored)")
    else:
        print("\n✘ Directories differ")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print(f"Usage: {sys.argv[0]} <dir1> <dir2>")
        sys.exit(1)

    main(sys.argv[1], sys.argv[2])
