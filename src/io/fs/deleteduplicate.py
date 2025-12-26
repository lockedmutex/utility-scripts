import os
from pathlib import Path


def clean_duplicates_recursive(target_dir, keep_extension=".jxl", dry_run=True):
    target_path = Path(target_dir)

    if not target_path.exists():
        print(f"Error: Directory '{target_dir}' not found.")
        return

    print(f"Scanning recursively: {target_path.resolve()}")
    print("-" * 40)

    total_deleted = 0

    for root, dirs, files in os.walk(target_path):
        current_dir = Path(root)
        files_map = {}

        for filename in files:
            file_path = current_dir / filename
            base_name = file_path.stem
            ext = file_path.suffix.lower()

            if base_name not in files_map:
                files_map[base_name] = []
            files_map[base_name].append(ext)

        for base_name, extensions in files_map.items():
            if keep_extension in extensions and len(extensions) > 1:
                for ext in extensions:
                    if ext == keep_extension:
                        continue

                    file_to_remove = current_dir / (base_name + ext)

                    if dry_run:
                        print(f"[DRY RUN] Would delete: {file_to_remove}")
                    else:
                        try:
                            os.remove(file_to_remove)
                            print(f"[DELETED] {file_to_remove}")
                            total_deleted += 1
                        except OSError as e:
                            print(f"Error deleting {file_to_remove}: {e}")

    print("-" * 40)
    if dry_run:
        print("Dry run complete. No files were deleted.")
        print("Set 'dry_run=False' to actually delete files.")
    else:
        print(f"Cleanup complete. Deleted {total_deleted} files.")


if __name__ == "__main__":
    TARGET_FOLDER = "./ALL_PHOTOS_PROCESSED"
    clean_duplicates_recursive(TARGET_FOLDER, keep_extension=".jxl", dry_run=True)
