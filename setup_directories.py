"""
Phase 0 - Directory Structure Setup
Project Sentinel: Medallion Architecture (Raw -> Bronze -> Silver -> Gold)

Creates the local data directories required by the ingestion pipeline.
Run once from the project root:
    python setup_directories.py
"""

from pathlib import Path

# All paths are relative to this script's location (project root)
PROJECT_ROOT = Path(__file__).resolve().parent

DIRECTORIES = [
    # Raw layer — untouched source files
    "data/raw/zips",         # Incoming e-Tender ZIP archives
    "data/raw/quarantine",   # Files that failed MIME validation

    # Bronze layer — extracted & hash-renamed, not yet parsed
    "data/bronze/pdfs",      # Validated PDF tender documents
    "data/bronze/boqs",      # Validated BOQ spreadsheets (xlsx/csv)
]


def create_directories() -> None:
    """Create all medallion-architecture data directories."""
    print("=" * 50)
    print("Project Sentinel — Directory Setup")
    print("=" * 50)

    for dir_path in DIRECTORIES:
        full_path = PROJECT_ROOT / dir_path
        full_path.mkdir(parents=True, exist_ok=True)
        if full_path.exists():
            try:
                status = "[OK] exists" if any(full_path.iterdir()) else "[OK] created"
            except PermissionError:
                status = "[OK] created"
        else:
            status = "[FAIL]"
        print(f"  {status:<14} {dir_path}")

    print()
    print("Directory setup complete.")
    print(f"Drop your e-Tender ZIPs into: {PROJECT_ROOT / 'data' / 'raw' / 'zips'}")


if __name__ == "__main__":
    create_directories()
