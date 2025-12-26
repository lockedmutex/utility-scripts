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
import os
import shutil
import subprocess
import sys
from pathlib import Path

VIDEO_EXTS = {
    ".mp4",
    ".mov",
    ".mkv",
    ".avi",
    ".webm",
    ".flv",
    ".m4v",
    ".mts",
    ".m2ts",
    ".3gp",
}

# --- QUALITY PRESETS ---
# Format: "name": ("preset", "crf")
QUALITY_MAP = {
    "hq": ("3", "26"),  # High Quality: Slow, archival (Retains grain)
    "mq": ("8", "28"),  # Medium Quality: Sweet spot (Default)
    "lq": ("9", "30"),  # Low Quality: Faster, smaller
}


def get_video_codec(input_file: Path) -> str:
    """Detects the video codec (hevc, h264, vp9, av1, etc.)"""
    try:
        result = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-select_streams",
                "v:0",
                "-show_entries",
                "stream=codec_name",
                "-of",
                "default=nokey=1:noprint_wrappers=1",
                str(input_file),
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout.strip().lower()
    except subprocess.CalledProcessError:
        return ""


def is_hdr_or_10bit(input_file: Path) -> bool:
    """
    Checks if video is HDR or 10-bit.
    (Note: We now force 10-bit output for AV1 anyway, but this is kept for reference).
    """
    try:
        result = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-select_streams",
                "v:0",
                "-show_entries",
                "stream=pix_fmt,bits_per_raw_sample",
                "-of",
                "default=nokey=1:noprint_wrappers=1",
                str(input_file),
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        out = result.stdout.lower()
        return "10" in out or "p010" in out or "yuv420p10" in out
    except subprocess.CalledProcessError:
        return False


def check_and_clean_destination(targets: list[Path]) -> bool:
    """
    Checks if any file in the 'targets' list exists.
    Returns True if a valid file exists (skip processing).
    Returns False if no file exists (proceed processing).
    Deletes 0KB files if found.
    """
    targets = list(set(targets))  # Remove duplicates

    for target in targets:
        if target.exists():
            size = target.stat().st_size
            if size == 0:
                print(f"[DELETE] Found 0KB file, removing to re-process: {target.name}")
                try:
                    target.unlink()
                except OSError as e:
                    print(f"[ERROR] Could not delete empty file {target.name}: {e}")
            else:
                # File exists and has data
                print(f"[SKIP] {target.name} (Already exists)")
                return True

    return False


def convert_video(input_file: Path, output_file: Path, preset: str, crf: str):
    """
    input_file: The source video file.
    output_file: The destination path.
    preset: AV1 preset (0-13)
    crf: Constant Rate Factor
    """
    try:
        # Ensure parent directory exists
        if output_file.parent.name:
            os.makedirs(output_file.parent, exist_ok=True)

        # 1. CHECK DESTINATION EXISTENCE
        output_file_orig = output_file.with_suffix(input_file.suffix)
        targets_to_check = [output_file]

        # Don't check source file as target if converting in-place
        if output_file_orig.resolve() != input_file.resolve():
            targets_to_check.append(output_file_orig)

        if check_and_clean_destination(targets_to_check):
            return

        # 2. CHECK CODEC (Restore VP9/AV1 Logic)
        codec = get_video_codec(input_file)

        # If already VP9 or AV1, copy it instead of converting?
        # (Original script only checked VP9, but adding AV1 check is smart too)
        if codec == "vp9" or codec == "av1":
            if output_file_orig.resolve() == input_file.resolve():
                print(f"[SKIP] {input_file.name} is already {codec} (In-place)")
                return

            shutil.copy2(input_file, output_file_orig)
            print(f"[COPY] {output_file_orig.name} (Already {codec} - direct copy)")
            return

        # 3. START CONVERSION
        print(f"--> Processing: {input_file.name}")
        print(f"    [Settings: Preset {preset} | CRF {crf}]")

        cmd = [
            "ffmpeg",
            "-threads",
            "0",
            "-i",
            str(input_file),
            "-map_metadata",
            "0",
            "-c:v",
            "libsvtav1",
            "-preset",
            preset,
            "-crf",
            crf,
            "-g",
            "240",
            # Use 10-bit color for everything (prevents banding, efficient)
            "-pix_fmt",
            "yuv420p10le",
            "-c:a",
            "copy",
            str(output_file),
        ]

        subprocess.run(cmd, check=True)
        print(f"[OK] {output_file.name}")

    except subprocess.CalledProcessError:
        print(f"[ERROR] Failed: {input_file.name}")
        # Cleanup partial file if ffmpeg fails
        if output_file.exists():
            output_file.unlink()
    except OSError as e:
        print(f"[ERROR] OS Error: {e}")


def main():
    parser = argparse.ArgumentParser(description="Convert videos to AV1 using SVT-AV1.")

    # Positional arguments
    parser.add_argument("source", help="Input file or directory")
    parser.add_argument("destination", help="Output file or directory")

    # Optional Quality Flag
    parser.add_argument(
        "-q",
        "--quality",
        choices=["hq", "mq", "lq"],
        default="mq",
        help="Quality Level: hq (Preset 3/CRF 26), mq (Preset 8/CRF 30) [Default], lq (Preset 9/CRF 32)",
    )

    args = parser.parse_args()

    src_path = Path(args.source)
    dst_path = Path(args.destination)

    # Map quality string to numbers
    preset, crf = QUALITY_MAP[args.quality]

    # --- MODE 1: SINGLE FILE ---
    if src_path.is_file():
        convert_video(src_path, dst_path, preset, crf)

    # --- MODE 2: DIRECTORY (Recursive) ---
    elif src_path.is_dir():
        if not src_path.exists():
            sys.exit("Source directory not found.")

        for item in src_path.rglob("*"):
            if not item.is_file():
                continue

            if item.suffix.lower() in VIDEO_EXTS:
                out_file = dst_path / item.relative_to(src_path).with_suffix(".mkv")
                convert_video(item, out_file, preset, crf)

    else:
        sys.exit("Error: Source is not a valid file or directory.")


if __name__ == "__main__":
    main()
