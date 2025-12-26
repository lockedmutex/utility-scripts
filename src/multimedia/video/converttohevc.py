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


def get_video_codec(input_file: Path) -> str:
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
        return "10" in out or "yuv420p10" in out or "p010" in out
    except subprocess.CalledProcessError:
        return False


def check_and_clean_destination(mkv_path: Path, orig_path: Path) -> bool:
    """
    Checks if output exists (either as .mkv or original extension).
    Returns True if a valid file exists (skip processing).
    Returns False if no file exists (proceed processing).
    Deletes 0KB files if found.
    """
    targets = [mkv_path, orig_path]

    for target in targets:
        if target.exists():
            size = target.stat().st_size
            if size == 0:
                print(f"[DELETE] Found 0KB file, removing to re-process: {target.name}")
                try:
                    target.unlink()
                except OSError as e:
                    print(f"[ERROR] Could not delete empty file {target.name}: {e}")
                # We deleted it, so we continue to return False (process it)
            else:
                # File exists and has data
                print(f"[SKIP] {target.name} (Already exists)")
                return True

    return False


def convert_video(input_file: Path, output_file_mkv: Path):
    try:
        # Ensure parent directory exists
        os.makedirs(output_file_mkv.parent, exist_ok=True)

        # 1. CHECK DESTINATION EXISTENCE
        output_file_orig = output_file_mkv.with_suffix(input_file.suffix)

        if check_and_clean_destination(output_file_mkv, output_file_orig):
            return

        # 2. CHECK CODEC
        codec = get_video_codec(input_file)

        # --- SMART COPY LOGIC (VP9 + HEVC/H.265) ---
        # If it's already compressed efficiently (VP9) or already in target format (HEVC), just copy.
        if codec in ["vp9", "hevc", "h265", "av1"]:
            shutil.copy2(input_file, output_file_orig)
            print(f"[COPY] {output_file_orig.name} ({codec.upper()} direct copy)")
            return
        # -------------------------------------------

        # 3. START PROCESSING
        hdr = is_hdr_or_10bit(input_file)

        cmd = [
            "ffmpeg",
            "-threads",
            "0",
            "-hwaccel",
            "cuda",
            "-i",
            str(input_file),
            "-map_metadata",
            "0",
            # ---- NVENC HEVC MAX COMPRESSION ----
            "-c:v",
            "hevc_nvenc",
            "-preset",
            "p7",  # Slowest/Best quality preset
            "-tier",
            "high",  # Allow high peak bitrate for complex scenes
            "-rc",
            "vbr",
            "-multipass",
            "fullres",  # 2-Pass encoding
            "-cq:v",
            "18",
            "-b:v",
            "0",
            "-bf",
            "3",  # Use 3 B-frames
            "-b_ref_mode",
            "middle",
            "-look_ahead",
            "32",
            "-spatial_aq",
            "1",
            "-temporal_aq",
            "1",
            "-aq-strength",
            "10",
        ]

        if hdr:
            cmd += [
                "-profile:v",
                "main10",
                "-pix_fmt",
                "p010le",
            ]
        else:
            cmd += [
                "-pix_fmt",
                "yuv420p",
            ]

        cmd += [
            "-c:a",
            "copy",
            str(output_file_mkv),
        ]

        subprocess.run(cmd, check=True)
        print(f"[OK] {output_file_mkv.name} ({'HDR' if hdr else 'SDR'})")

    except subprocess.CalledProcessError as e:
        print(f"[ERROR] Processing failed for {input_file}\n{e}")
        if output_file_mkv.exists():
            try:
                output_file_mkv.unlink()
            except OSError:
                pass


def main(src_dir: str, dst_dir: str):
    src_path = Path(src_dir)
    dst_path = Path(dst_dir)

    if not src_path.is_dir():
        print("Source directory not found.")
        sys.exit(1)

    for item in src_path.rglob("*"):
        if item.is_file() and item.suffix.lower() in VIDEO_EXTS:
            out_file = dst_path / item.relative_to(src_path).with_suffix(".mkv")
            convert_video(item, out_file)


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print(f"Usage: {sys.argv[0]} <source_dir> <destination_dir>")
        sys.exit(1)

    main(sys.argv[1], sys.argv[2])
