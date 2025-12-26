#!/usr/bin/env python3

# Copyright (C) 2025 Suyog Tandel
#
# Unless explicitly acquired and licensed from Licensor under another license,
# the contents of this file are subject to the Reciprocal Public License ("RPL")
# Version 1.5, or subsequent versions as allowed by the RPL, and You may not
# copy or use this file in either source code or executable form, except in
# compliance with the terms and conditions of the RPL.
#
# All software distributed under the RPL is provided strictly on an "AS IS" basis,
# WITHOUT WARRANTY OF ANY KIND, EITHER EXPRESS OR IMPLIED, AND LICENSOR HEREBY
# DISCLAIMS ALL SUCH WARRANTIES, INCLUDING WITHOUT LIMITATION, ANY WARRANTIES
# OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE, QUIET ENJOYMENT, OR
# NON-INFRINGEMENT. See the RPL for specific language governing rights and
# limitations under the RPL.

import argparse
import io
import shutil
import subprocess
import sys
from pathlib import Path

# --- CONFIGURATION ---

# Number of threads for cjxl encoder
CJXL_THREADS = 12

IMAGE_EXTS = {
    ".jpg",
    ".jpeg",
    ".png",
    ".bmp",
    ".webp",
    ".tiff",
    ".tif",
    ".heic",
    ".heif",
    ".jfif",
    ".pjpeg",
    ".pjp",
}

UNSUPPORTED_EXTS = {".svg", ".gif", ".ico", ".psd", ".pdf"}

# ---------------------

try:
    import pillow_heif
    from PIL import Image

    pillow_heif.register_heif_opener()
    HAS_PILLOW = True
except ImportError:
    HAS_PILLOW = False
    print("[WARNING] 'pillow' and 'pillow-heif' not found.")
    print(
        "HEIC conversion will likely fail. Please run: pip install pillow pillow-heif"
    )


def copy_original(input_file, src_root, dst_root, reason="Original kept"):
    rel = input_file.relative_to(src_root)
    out = dst_root / rel
    out.parent.mkdir(parents=True, exist_ok=True)
    if not out.exists():
        out.write_bytes(input_file.read_bytes())
    print(f"[COPY] {input_file.name} ({reason})")


def run_cjxl_in_memory(cmd_list, args, stdin_data=None):
    """
    Runs cjxl.
    stdin_data: Optional bytes to feed into cjxl (e.g. PPM data).
    """
    # Inject threading argument
    if "--num_threads" not in cmd_list:
        cmd_list.insert(1, "--num_threads")
        cmd_list.insert(2, str(CJXL_THREADS))

    # Inject Effort argument
    cmd_list.append("--effort")
    cmd_list.append(str(args.effort))

    result = subprocess.run(cmd_list, input=stdin_data, capture_output=True)

    try:
        stderr_text = result.stderr.decode("utf-8", errors="replace")
    except:
        stderr_text = str(result.stderr)

    return result.returncode, result.stdout, stderr_text


def convert_via_pillow(input_file, args, quality=90):
    """
    Universal Fallback Decoder using Pillow.
    """
    if not HAS_PILLOW:
        raise RuntimeError("Pillow libs missing. Cannot perform fallback conversion.")

    try:
        img = Image.open(input_file)
        ppm_buffer = io.BytesIO()
        img.save(ppm_buffer, format="PPM")
        ppm_data = ppm_buffer.getvalue()

        cjxl_cmd = ["cjxl", "-", "-", "--quality", str(quality), "--lossless_jpeg=0"]
        # Pass args to helper so effort is included
        code, jxl_data, err = run_cjxl_in_memory(cjxl_cmd, args, stdin_data=ppm_data)

        if code != 0:
            raise RuntimeError(f"CJXL failed on Pillow output: {err}")

        return jxl_data

    except Exception as e:
        raise RuntimeError(f"Pillow fallback failed: {e}")


def copy_metadata(src_file, dst_file):
    if shutil.which("exiftool"):
        subprocess.run(
            [
                "exiftool",
                "-overwrite_original",
                "-TagsFromFile",
                str(src_file),
                "-all:all",
                "-ignoreMinorErrors",
                str(dst_file),
            ],
            capture_output=True,
        )


def process_file(input_file, src_root, dst_root, args):
    rel = input_file.relative_to(src_root)
    output_file = dst_root / rel.with_suffix(".jxl")
    ext = input_file.suffix.lower()

    # --- CONFLICT RESOLUTION ---
    if output_file.exists():
        if args.skip:
            print(f"[SKIP] {input_file.name} (Already exists)")
            return
        elif args.overwrite:
            pass
        else:
            while True:
                user_input = (
                    input(f"[?] File '{output_file.name}' exists. Overwrite? [y/n]: ")
                    .strip()
                    .lower()
                )
                if user_input == "y":
                    break
                elif user_input == "n":
                    print(f"[SKIP] {input_file.name}")
                    return
    # ---------------------------

    output_file.parent.mkdir(parents=True, exist_ok=True)

    src_size = input_file.stat().st_size
    is_jpeg = ext in {".jpg", ".jpeg", ".jfif", ".pjpeg", ".pjp"}
    is_heic = ext in {".heic", ".heif"}

    # Determine minimum allowed quality based on flags
    match (args.compress_lq, args.compress_mq, args.compress_hq):
        case (True, _, _):
            min_quality = 75
        case (_, True, _):
            min_quality = 80
        case (_, _, True):
            min_quality = 85
        case _:
            min_quality = 90

    current_quality = 90
    final_jxl_data = None
    final_method = "None"

    while True:
        jxl_data = None
        conversion_method = "Standard"

        try:
            # --- ATTEMPT 1: Primary Strategies ---
            if is_heic:
                jxl_data = convert_via_pillow(input_file, args, quality=current_quality)
                conversion_method = f"Pillow-HEIC-Q{current_quality}"

            elif is_jpeg:
                if current_quality == 90:
                    code, data, err = run_cjxl_in_memory(
                        ["cjxl", str(input_file), "-", "--lossless_jpeg=1"], args
                    )
                    if code == 0:
                        jxl_data = data
                        conversion_method = "JPEG-Transcode"
                    else:
                        code, data, err = run_cjxl_in_memory(
                            [
                                "cjxl",
                                str(input_file),
                                "-",
                                "--quality",
                                str(current_quality),
                                "--lossless_jpeg=0",
                            ],
                            args,
                        )
                        if code == 0:
                            jxl_data = data
                            conversion_method = f"JPEG-ReEncode-Q{current_quality}"
                        else:
                            raise RuntimeError(f"Standard CJXL failed: {err.strip()}")
                else:
                    code, data, err = run_cjxl_in_memory(
                        [
                            "cjxl",
                            str(input_file),
                            "-",
                            "--quality",
                            str(current_quality),
                            "--lossless_jpeg=0",
                        ],
                        args,
                    )
                    if code == 0:
                        jxl_data = data
                        conversion_method = f"JPEG-ReEncode-Q{current_quality}"
                    else:
                        raise RuntimeError(f"Standard CJXL failed: {err.strip()}")

            else:
                code, data, err = run_cjxl_in_memory(
                    [
                        "cjxl",
                        str(input_file),
                        "-",
                        "--quality",
                        str(current_quality),
                        "--lossless_jpeg=0",
                    ],
                    args,
                )
                if code == 0:
                    jxl_data = data
                    conversion_method = f"Direct-CJXL-Q{current_quality}"
                else:
                    raise RuntimeError(f"Standard CJXL failed: {err.strip()}")

        except Exception as e_primary:
            # --- ATTEMPT 2: Universal Fallback (Pillow) ---
            try:
                if current_quality == 90:
                    print(
                        f"  [INFO] Standard failed for {input_file.name}. Trying Pillow..."
                    )

                jxl_data = convert_via_pillow(input_file, args, quality=current_quality)
                conversion_method = f"Fallback-Pillow-Q{current_quality}"
            except Exception as e_fallback:
                print(
                    f"[ERROR] Failed {input_file.name}. Primary: {e_primary} | Fallback: {e_fallback}"
                )
                if not args.force_jxl:
                    copy_original(
                        input_file, src_root, dst_root, reason="Conversion Failed"
                    )
                return

        # --- SIZE CHECK LOGIC ---
        if jxl_data:
            jxl_size = len(jxl_data)

            if jxl_size < src_size:
                final_jxl_data = jxl_data
                final_method = conversion_method
                break

            if current_quality > min_quality:
                current_quality -= 5
                continue

            final_jxl_data = jxl_data
            final_method = conversion_method
            break

    # --- FINAL SAVE DECISION ---
    if final_jxl_data:
        jxl_size = len(final_jxl_data)

        if jxl_size < src_size or args.force_jxl:
            output_file.write_bytes(final_jxl_data)

            diff_percent = ((src_size - jxl_size) / src_size) * 100

            status = "[OK]"
            if jxl_size >= src_size:
                status = "[FORCED]"
                print(
                    f"{status} {input_file.name} (+{-diff_percent:.1f}%) [{final_method}]"
                )
            else:
                print(
                    f"{status} {input_file.name} (-{diff_percent:.1f}%) [{final_method}]"
                )

            copy_metadata(input_file, output_file)
        else:
            copy_original(
                input_file, src_root, dst_root, reason="JXL larger & no force"
            )


def main():
    parser = argparse.ArgumentParser(description="Batch Convert Images to JPEG XL")
    parser.add_argument("src_dir", help="Source directory containing images")
    parser.add_argument("dst_dir", help="Destination directory for JXL files")

    parser.add_argument(
        "--force-jxl",
        action="store_true",
        help="Save JXL even if larger than original.",
    )

    parser.add_argument(
        "--copy",
        nargs="+",
        default=[],
        help="List of extensions to copy directly without conversion (e.g. --copy heic png)",
    )

    parser.add_argument(
        "--effort",
        type=int,
        default=7,
        choices=range(1, 10),
        help="Encoder effort 1-9 (Default: 7). Higher = smaller file but slower.",
    )

    conflict_group = parser.add_mutually_exclusive_group()
    conflict_group.add_argument(
        "--overwrite", action="store_true", help="Always overwrite."
    )
    conflict_group.add_argument("--skip", action="store_true", help="Always skip.")

    comp_group = parser.add_mutually_exclusive_group()
    comp_group.add_argument(
        "--compress-hq", action="store_true", help="Retry down to Q85"
    )
    comp_group.add_argument(
        "--compress-mq", action="store_true", help="Retry down to Q80"
    )
    comp_group.add_argument(
        "--compress-lq", action="store_true", help="Retry down to Q75"
    )

    args = parser.parse_args()

    src = Path(args.src_dir)
    dst = Path(args.dst_dir)

    # Process copy arguments: normalize to lowercase and ensure leading dot
    copy_extensions = set()
    for ext in args.copy:
        ext = ext.strip().lower()
        if not ext.startswith("."):
            ext = "." + ext
        copy_extensions.add(ext)

    if not src.is_dir():
        print("Source directory not found.")
        sys.exit(1)

    if not HAS_PILLOW:
        print("\n!!! MISSING LIBRARIES !!!")
        print("Please run: pip install pillow pillow-heif\n")

    all_files = sorted(list(src.rglob("*")))
    print(f"Scanning {src}...")
    print(
        f"Found {len(all_files)} items. Starting conversion ({CJXL_THREADS} threads, Effort {args.effort})..."
    )

    if args.force_jxl:
        print("Mode: FORCE JXL")
    if args.overwrite:
        print("Conflict: OVERWRITE")
    elif args.skip:
        print("Conflict: SKIP")

    if copy_extensions:
        print(f"Direct Copy Mode active for: {', '.join(copy_extensions)}")

    print("-" * 40 + "\n")

    for item in all_files:
        if not item.is_file():
            continue
        ext = item.suffix.lower()

        # Check for explicit copy request OR strictly unsupported formats
        if ext in copy_extensions or ext in UNSUPPORTED_EXTS:
            out = dst / item.relative_to(src)
            out.parent.mkdir(parents=True, exist_ok=True)
            if not out.exists():
                out.write_bytes(item.read_bytes())

                reason = "Explicit Copy" if ext in copy_extensions else "Unsupported"
                print(f"[COPY] {item.name} ({reason})")
            continue

        if ext in IMAGE_EXTS:
            process_file(item, src, dst, args)

    print("\n--- Processing Complete ---")


if __name__ == "__main__":
    main()
