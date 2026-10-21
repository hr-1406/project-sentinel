"""
Phase 1 - Raw to Bronze Ingestion Pipeline
Project Sentinel: Kerala e-Tender ZIP Processing

Processes every ZIP in data/raw/zips/:
  1. Extracts each file from the archive into memory.
  2. Detects true MIME type via python-magic (binary inspection, not extension).
  3. Computes SHA-256 hash for cryptographic deduplication.
  4. Routes to the correct Bronze-layer directory (or Quarantine).
  5. Logs each file into the raw_document_catalog table.

Routing Rules:
  application/pdf                            → data/bronze/pdfs/   (type: PDF)
  application/vnd.ms-excel, .xlsx variants   → data/bronze/boqs/   (type: XLS, requires_award_data=True)
  anything else                              → data/raw/quarantine/ (type: UNKNOWN, parse_status=QUARANTINED)

Deduplication:
  Files are saved as {type_lower}_{sha256_hash}{ext}.
  INSERT ... ON CONFLICT (file_hash) DO NOTHING skips exact binary duplicates.

Usage:
    python ingest_raw.py
"""

import hashlib
import os
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import magic
from sqlalchemy import (
    Boolean,
    DateTime,
    String,
    Text,
    create_engine,
    func,
)
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    Session,
    mapped_column,
    sessionmaker,
)

# ────────────────────────────────────────────────────────────
# Configuration
# ────────────────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent

RAW_ZIPS_DIR       = PROJECT_ROOT / "data" / "raw" / "zips"
QUARANTINE_DIR     = PROJECT_ROOT / "data" / "raw" / "quarantine"
BRONZE_PDFS_DIR    = PROJECT_ROOT / "data" / "bronze" / "pdfs"
BRONZE_BOQS_DIR    = PROJECT_ROOT / "data" / "bronze" / "boqs"

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+psycopg2://postgres:raphael1111@localhost:5432/sentinel_db",
)

# MIME types considered as spreadsheet / BOQ files
SPREADSHEET_MIMES = {
    "application/vnd.ms-excel",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.oasis.opendocument.spreadsheet",
    "application/x-ole-storage",  # python-magic sometimes returns this for .xls
}

# Extension mapping for routed files
EXTENSION_MAP = {
    "PDF": ".pdf",
    "XLS": ".xls",
    "UNKNOWN": "",
}


# ────────────────────────────────────────────────────────────
# Database Setup (self-contained — creates table if absent)
# ────────────────────────────────────────────────────────────
class Base(DeclarativeBase):
    pass


class RawDocumentCatalog(Base):
    """Mirrors the raw_document_catalog table from models.py."""
    __tablename__ = "raw_document_catalog"

    file_hash: Mapped[str] = mapped_column(
        String(64), primary_key=True,
    )
    original_zip_name: Mapped[str] = mapped_column(
        String(512), nullable=False,
    )
    original_file_name: Mapped[str] = mapped_column(
        String(512), nullable=False,
    )
    file_type: Mapped[str] = mapped_column(
        String(64), nullable=False,
    )
    bronze_path: Mapped[str | None] = mapped_column(
        String(1024), nullable=True,
    )
    requires_award_data: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false",
    )
    parse_status: Mapped[str] = mapped_column(
        String(32), default="PENDING", server_default="PENDING",
    )
    ingested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
    )


# ────────────────────────────────────────────────────────────
# Helper Functions
# ────────────────────────────────────────────────────────────
def sha256_hash(data: bytes) -> str:
    """Return the SHA-256 hex digest of raw bytes."""
    return hashlib.sha256(data).hexdigest()


def detect_mime(data: bytes) -> str:
    """Detect the true MIME type from binary content using libmagic."""
    return magic.from_buffer(data, mime=True)


def classify_file(mime_type: str, original_name: str) -> tuple[str, Path, bool, str]:
    """
    Determine file type, target directory, award-data flag, and parse status
    based on the detected MIME type.

    Returns:
        (file_type, target_dir, requires_award_data, parse_status)
    """
    if mime_type == "application/pdf":
        return ("PDF", BRONZE_PDFS_DIR, False, "PENDING")

    if mime_type in SPREADSHEET_MIMES:
        return ("XLS", BRONZE_BOQS_DIR, True, "PENDING")

    # Fallback: check file extension as a secondary signal for edge cases
    # where python-magic returns a generic type for valid spreadsheets
    ext_lower = Path(original_name).suffix.lower()
    if ext_lower in (".xls", ".xlsx", ".ods", ".csv"):
        return ("XLS", BRONZE_BOQS_DIR, True, "PENDING")

    # Everything else goes to quarantine
    return ("UNKNOWN", QUARANTINE_DIR, False, "QUARANTINED")


def build_filename(file_type: str, file_hash: str, original_name: str) -> str:
    """
    Build the deduplicated filename: {type_lower}_{hash}{ext}

    Uses the original extension when available, otherwise falls back
    to a default from EXTENSION_MAP.
    """
    original_ext = Path(original_name).suffix.lower()
    ext = original_ext if original_ext else EXTENSION_MAP.get(file_type, "")
    return f"{file_type.lower()}_{file_hash}{ext}"


def save_file(data: bytes, target_dir: Path, filename: str) -> Path:
    """Write file bytes to the target directory. Returns the full path."""
    target_dir.mkdir(parents=True, exist_ok=True)
    dest = target_dir / filename
    if not dest.exists():
        dest.write_bytes(data)
    return dest


# ────────────────────────────────────────────────────────────
# Core Ingestion Logic
# ────────────────────────────────────────────────────────────
def process_zip(zip_path: Path, session: Session, stats: dict) -> None:
    """
    Extract all files from a single ZIP, classify, deduplicate, route,
    and catalog each one.
    """
    zip_name = zip_path.name

    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            for entry in zf.infolist():
                # Skip directories and macOS resource forks
                if entry.is_dir() or entry.filename.startswith("__MACOSX"):
                    continue

                original_name = Path(entry.filename).name
                if not original_name:
                    continue

                # Read binary content
                try:
                    data = zf.read(entry.filename)
                except Exception as e:
                    print(f"    [WARN] Could not read {entry.filename}: {e}")
                    stats["errors"] += 1
                    continue

                # Skip empty files
                if len(data) == 0:
                    stats["skipped"] += 1
                    continue

                # Compute SHA-256 hash
                file_hash = sha256_hash(data)

                # Detect MIME type
                mime_type = detect_mime(data)

                # Classify and route
                file_type, target_dir, requires_award, parse_status = classify_file(
                    mime_type, original_name
                )

                # Build deduplicated filename and save
                dest_filename = build_filename(file_type, file_hash, original_name)
                dest_path = save_file(data, target_dir, dest_filename)

                # Compute relative path from project root for the catalog
                try:
                    relative_path = str(dest_path.relative_to(PROJECT_ROOT))
                except ValueError:
                    relative_path = str(dest_path)

                # Upsert into catalog (ON CONFLICT DO NOTHING for dedup)
                stmt = pg_insert(RawDocumentCatalog).values(
                    file_hash=file_hash,
                    original_zip_name=zip_name,
                    original_file_name=original_name,
                    file_type=file_type,
                    bronze_path=relative_path if file_type != "UNKNOWN" else None,
                    requires_award_data=requires_award,
                    parse_status=parse_status,
                ).on_conflict_do_nothing(index_elements=["file_hash"])

                result = session.execute(stmt)

                # Track stats
                if result.rowcount > 0:
                    stats[file_type] = stats.get(file_type, 0) + 1
                    stats["new_files"] += 1
                else:
                    stats["duplicates"] += 1

    except zipfile.BadZipFile:
        print(f"    [ERROR] Bad ZIP file: {zip_name} — skipping entirely")
        stats["bad_zips"] += 1
    except Exception as e:
        print(f"    [ERROR] Unexpected error processing {zip_name}: {e}")
        stats["errors"] += 1


def run_ingestion() -> None:
    """Main entry point: iterate all ZIPs and ingest into Bronze layer."""
    print("=" * 65)
    print("  Project Sentinel - Phase 1: Raw -> Bronze Ingestion Pipeline")
    print("=" * 65)

    # Verify raw directory exists
    if not RAW_ZIPS_DIR.exists():
        print(f"\n[FATAL] Raw ZIPs directory not found: {RAW_ZIPS_DIR}")
        print("  Run setup_directories.py first, then place ZIPs in data/raw/zips/")
        sys.exit(1)

    # Collect all ZIP files
    zip_files = sorted(RAW_ZIPS_DIR.glob("*.zip"))
    if not zip_files:
        print(f"\n[WARN] No ZIP files found in {RAW_ZIPS_DIR}")
        print("  Place your e-Tender ZIP archives there and re-run.")
        sys.exit(0)

    print(f"\n  Source:  {RAW_ZIPS_DIR}")
    print(f"  ZIPs:   {len(zip_files)}")
    print(f"  Target: PDFs -> {BRONZE_PDFS_DIR}")
    print(f"          BOQs -> {BRONZE_BOQS_DIR}")
    print(f"          Unknown -> {QUARANTINE_DIR}")
    print()

    # Connect to database
    engine = create_engine(DATABASE_URL, echo=False, pool_pre_ping=True)
    Base.metadata.create_all(bind=engine)  # Ensure table exists
    SessionFactory = sessionmaker(bind=engine)

    stats = {
        "new_files": 0,
        "duplicates": 0,
        "skipped": 0,
        "errors": 0,
        "bad_zips": 0,
        "PDF": 0,
        "XLS": 0,
        "UNKNOWN": 0,
    }

    # Process each ZIP
    with SessionFactory() as session:
        for i, zip_path in enumerate(zip_files, 1):
            print(f"  [{i:3d}/{len(zip_files)}] {zip_path.name}")
            process_zip(zip_path, session, stats)

            # Commit in batches of 25 ZIPs for a balance between
            # atomicity and not losing progress on large runs
            if i % 25 == 0:
                session.commit()
                print(f"          ... committed batch ({i} ZIPs processed)")

        # Final commit
        session.commit()

    # Summary
    print()
    print("-" * 65)
    print("  INGESTION SUMMARY")
    print("-" * 65)
    print(f"  ZIPs processed:       {len(zip_files)}")
    print(f"  New files cataloged:  {stats['new_files']}")
    print(f"    PDFs -> bronze:     {stats['PDF']}")
    print(f"    BOQs -> bronze:     {stats['XLS']}  (requires_award_data = True)")
    print(f"    Unknown -> quarantine: {stats['UNKNOWN']}")
    print(f"  Duplicates skipped:   {stats['duplicates']}")
    print(f"  Empty files skipped:  {stats['skipped']}")
    print(f"  Errors:               {stats['errors']}")
    print(f"  Bad ZIPs:             {stats['bad_zips']}")
    print("-" * 65)
    print("  Phase 1 complete.")
    print()


if __name__ == "__main__":
    run_ingestion()
