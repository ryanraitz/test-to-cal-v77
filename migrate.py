import shutil
from pathlib import Path
from datetime import datetime

# ================================
# CONFIG — ADJUST IF NEEDED
# ================================

PROJECT_ROOT = Path(__file__).resolve().parent
DATA_ROOT = Path.home() / "Library" / "test-to-cal-data"

# Folders inside project root that are GENERATED
GENERATED_DIRS = [
    "reports",
    "output",
    "clients",
    "logs",
    "temp",
]

# File extensions considered GENERATED
GENERATED_EXTENSIONS = {
    ".json",
    ".html",
    ".pdf",
    ".png",
    ".csv",
}

# Safety: do NOT delete originals
DELETE_ORIGINALS = True  # <-- set True only if you're VERY confident

# ================================
# HELPERS
# ================================

def timestamp():
    return datetime.now().strftime("%Y-%m-%d_%H-%M-%S")

def log(msg):
    print(f"[MIGRATE] {msg}")

def move_path(src: Path, dst: Path):
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    log(f"Copied: {src} → {dst}")

    if DELETE_ORIGINALS:
        src.unlink()
        log(f"Deleted original: {src}")

# ================================
# MAIN MIGRATION
# ================================

def main():
    log("Starting one-time migration")
    log(f"Project root: {PROJECT_ROOT}")
    log(f"Data root: {DATA_ROOT}")

    DATA_ROOT.mkdir(parents=True, exist_ok=True)

    migrated_count = 0

    # 1️⃣ Move known generated directories
    for folder in GENERATED_DIRS:
        src_dir = PROJECT_ROOT / folder
        if not src_dir.exists():
            continue

        dst_dir = DATA_ROOT / folder
        log(f"Processing directory: {src_dir}")

        for item in src_dir.rglob("*"):
            if item.is_file():
                rel = item.relative_to(PROJECT_ROOT)
                dst = DATA_ROOT / rel
                move_path(item, dst)
                migrated_count += 1

    # 2️⃣ Sweep loose generated files in project root
    for item in PROJECT_ROOT.iterdir():
        if (
            item.is_file()
            and item.suffix.lower() in GENERATED_EXTENSIONS
        ):
            dst = DATA_ROOT / "misc" / item.name
            move_path(item, dst)
            migrated_count += 1

    log(f"Migration complete — files moved: {migrated_count}")
    log("Original files preserved (DELETE_ORIGINALS = False)")
    log("You may now update your code paths to use DATA_ROOT")

if __name__ == "__main__":
    main()
