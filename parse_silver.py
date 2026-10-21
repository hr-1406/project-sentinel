"""
Phase 2 - Bronze to Silver Parsing Pipeline
Project Sentinel: GePNIC PDF Regex Extraction & Silver Loading

Processes every PENDING PDF in raw_document_catalog:
  1. Opens the Bronze-layer PDF with pdfplumber (text extraction only).
  2. Identifies NIT (Notice Inviting Tender) documents by header fingerprint.
  3. Extracts structured fields via Regex (NO geometric table extraction — 
     GePNIC PDFs use borderless tables that break those methods).
  4. Computes the bid submission window in days (publish_date -> bid_end_date).
  5. Loads into the `tenders` table with SCD Type 2 versioning.
  6. Updates parse_status to COMPLETED or FAILED_CORRUPT.

Non-NIT PDFs (affidavits, bid documents, forms) are marked COMPLETED_NON_NIT
since they contain no parseable tender metadata.

Usage:
    python parse_silver.py
"""

import os
import re
import sys
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

import pdfplumber
from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Integer,
    Numeric,
    String,
    Text,
    create_engine,
    func,
    text,
    update,
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
BRONZE_PDFS_DIR = PROJECT_ROOT / "data" / "bronze" / "pdfs"

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+psycopg2://postgres:raphael1111@localhost:5432/sentinel_db",
)


# ────────────────────────────────────────────────────────────
# ORM Models (self-contained mirror of models.py)
# ────────────────────────────────────────────────────────────
class Base(DeclarativeBase):
    pass


class RawDocumentCatalog(Base):
    __tablename__ = "raw_document_catalog"

    file_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    original_zip_name: Mapped[str] = mapped_column(String(512), nullable=False)
    original_file_name: Mapped[str] = mapped_column(String(512), nullable=False)
    file_type: Mapped[str] = mapped_column(String(64), nullable=False)
    bronze_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    requires_award_data: Mapped[bool] = mapped_column(Boolean, default=False)
    parse_status: Mapped[str] = mapped_column(String(32), default="PENDING")
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Tender(Base):
    __tablename__ = "tenders"

    tender_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    version: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    is_current: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")

    work_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    est_pac: Mapped[Decimal | None] = mapped_column(Numeric(15, 2), nullable=True)
    publish_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    bid_end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    organisation: Mapped[str | None] = mapped_column(String(512), nullable=True)
    work_category: Mapped[str | None] = mapped_column(String(256), nullable=True)
    source_file_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # Feature engineering: bid window duration
    short_bid_submission_window_days: Mapped[int | None] = mapped_column(
        Integer, nullable=True,
        comment="Delta in days between publish_date and bid_end_date"
    )

    parsed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    valid_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    valid_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


# ────────────────────────────────────────────────────────────
# Compiled Regex Patterns (GePNIC NIT format)
# ────────────────────────────────────────────────────────────
#
# Sample NIT header block:
#   LSGD Section Mannur
#   No :LSGD/CELSGD/31100/2026-2027 Dated :01-10-2026
#   NOTICE INVITING TENDER
#   e-Government Procurement (e-GP)
#   TENDER NO. :LSGD/CELSGD/TR/79376/2026_5_1_1/1
#   ...
#   1 Name of Work    Annual Plan-Mannur GP 2026-2027 - ...
#   2 Location of Work Ernakulam
#   3 Estimated Cost of Work Rs.184710/-
#   ...
#   9 Last date and time for submission of  08-10-2026 at 17:00
#     bids
#   10 Date and time of opening of tender   19-10-2026 at 11:00

# Tender reference number
RE_TENDER_NO = re.compile(
    r"TENDER\s*NO\.?\s*[:\-]\s*(.+?)(?:\s*$)",
    re.IGNORECASE | re.MULTILINE,
)

# Published / NIT date — appears as "Dated :DD-MM-YYYY" in the header
RE_PUBLISH_DATE = re.compile(
    r"Dated\s*:\s*(\d{2}-\d{2}-\d{4})",
    re.IGNORECASE,
)

# Organisation / LSGD section — "LSGD Section <Name>"
RE_ORGANISATION = re.compile(
    r"LSGD\s+Section\s+(.+?)(?:\s*$)",
    re.IGNORECASE | re.MULTILINE,
)

# Name of Work — numbered item "1 Name of Work <value>"
# The value can span multiple lines until the next numbered item (e.g., "2 Location")
RE_WORK_NAME = re.compile(
    r"1\s+Name\s+of\s+Work\s+(.+?)(?=\n\s*2\s+Location)",
    re.IGNORECASE | re.DOTALL,
)

# Estimated PAC — "3 Estimated Cost of Work Rs.184710/-"
RE_EST_PAC = re.compile(
    r"(?:Estimated\s+(?:Cost|Amount)\s+(?:of\s+)?(?:Work|Contract))\s+(?:Rs\.?\s*)?([0-9,]+(?:\.\d+)?)",
    re.IGNORECASE,
)

# Bid submission end date — "9 Last date and time for submission of DD-MM-YYYY at HH:MM"
RE_BID_END = re.compile(
    r"(?:Last\s+date\s+and\s+time\s+for\s+submission\s+of)\s+(\d{2}-\d{2}-\d{4})",
    re.IGNORECASE,
)

# Location of work — "2 Location of Work <district>"
RE_LOCATION = re.compile(
    r"2\s+Location\s+of\s+Work\s+(.+?)(?:\s*$)",
    re.IGNORECASE | re.MULTILINE,
)

# NIT fingerprint — quick check to identify NIT documents
RE_NIT_FINGERPRINT = re.compile(
    r"NOTICE\s+INVITING\s+TENDER",
    re.IGNORECASE,
)


# ────────────────────────────────────────────────────────────
# Parsing Helpers
# ────────────────────────────────────────────────────────────
def parse_date_ddmmyyyy(date_str: str) -> date | None:
    """Parse 'DD-MM-YYYY' to a date object."""
    try:
        return datetime.strptime(date_str.strip(), "%d-%m-%Y").date()
    except (ValueError, AttributeError):
        return None


def clean_currency(raw: str) -> Decimal | None:
    """Strip Rs., commas, /-, lakhs notation and return a Decimal."""
    try:
        cleaned = raw.strip()
        cleaned = re.sub(r"[Rs.\s,/\-]+", "", cleaned)
        if not cleaned:
            return None
        return Decimal(cleaned)
    except (InvalidOperation, ValueError):
        return None


def clean_work_name(raw: str) -> str:
    """Collapse whitespace and newlines in multi-line work names."""
    return re.sub(r"\s+", " ", raw).strip().rstrip("-").strip()


def extract_text_from_pdf(pdf_path: Path, max_pages: int = 5) -> str | None:
    """
    Extract text from a PDF using pdfplumber (first max_pages pages).
    Returns concatenated text, or None on failure.

    CRITICAL: We use .extract_text() only — NOT .extract_table().
    GePNIC PDFs have borderless tables that break geometric parsers.
    NIT details are always located within the first 1-3 pages.
    """
    with pdfplumber.open(pdf_path) as pdf:
        pages_text = []
        for page in pdf.pages[:max_pages]:
            text = page.extract_text()
            if text:
                pages_text.append(text)
        return "\n".join(pages_text) if pages_text else None


def extract_tender_fields(full_text: str) -> dict | None:
    """
    Apply regex patterns to extract structured fields from NIT text.

    Returns a dict of parsed fields, or None if this isn't an NIT document
    or mandatory fields (tender_id) couldn't be extracted.
    """
    # Quick check: is this an NIT document?
    if not RE_NIT_FINGERPRINT.search(full_text):
        return None

    # --- Tender Reference Number (mandatory) ---
    m_tender = RE_TENDER_NO.search(full_text)
    if not m_tender:
        return None
    tender_id = m_tender.group(1).strip()

    # --- Work Name ---
    m_work = RE_WORK_NAME.search(full_text)
    work_name = clean_work_name(m_work.group(1)) if m_work else None

    # --- Estimated PAC ---
    m_pac = RE_EST_PAC.search(full_text)
    est_pac = clean_currency(m_pac.group(1)) if m_pac else None

    # --- Published Date ---
    m_pub = RE_PUBLISH_DATE.search(full_text)
    publish_date = parse_date_ddmmyyyy(m_pub.group(1)) if m_pub else None

    # --- Bid End Date ---
    m_bid = RE_BID_END.search(full_text)
    bid_end_date = parse_date_ddmmyyyy(m_bid.group(1)) if m_bid else None

    # --- Organisation (LSGD Section) ---
    m_org = RE_ORGANISATION.search(full_text)
    organisation = m_org.group(1).strip() if m_org else None

    # --- Location (used as work_category proxy) ---
    m_loc = RE_LOCATION.search(full_text)
    work_category = m_loc.group(1).strip() if m_loc else None

    # --- Feature Engineering: bid window in days ---
    bid_window_days = None
    if publish_date and bid_end_date:
        delta = (bid_end_date - publish_date).days
        bid_window_days = delta if delta >= 0 else None

    return {
        "tender_id": tender_id,
        "work_name": work_name,
        "est_pac": est_pac,
        "publish_date": publish_date,
        "bid_end_date": bid_end_date,
        "organisation": organisation,
        "work_category": work_category,
        "short_bid_submission_window_days": bid_window_days,
    }


# ────────────────────────────────────────────────────────────
# Silver Layer Loading (SCD Type 2)
# ────────────────────────────────────────────────────────────
def upsert_tender_scd2(session: Session, fields: dict, file_hash: str) -> None:
    """
    Insert or version-update a tender using SCD Type 2 logic.

    - If the tender_id doesn't exist yet: INSERT with version=1, is_current=True.
    - If it exists and data has changed: mark old version as not current,
      insert new version with incremented version number.
    - If it exists and data is identical: skip (no new version needed).
    """
    tender_id = fields["tender_id"]
    now = datetime.utcnow()

    # Check for an existing current record
    existing = session.execute(
        text("""
            SELECT version, work_name, est_pac, publish_date, bid_end_date,
                   organisation, work_category, short_bid_submission_window_days
            FROM tenders
            WHERE tender_id = :tid AND is_current = true
        """),
        {"tid": tender_id},
    ).fetchone()

    if existing is not None:
        # Compare key fields to decide if a new version is needed
        old = {
            "work_name": existing[1],
            "est_pac": existing[2],
            "publish_date": existing[3],
            "bid_end_date": existing[4],
            "organisation": existing[5],
            "work_category": existing[6],
            "short_bid_submission_window_days": existing[7],
        }
        new = {
            "work_name": fields.get("work_name"),
            "est_pac": fields.get("est_pac"),
            "publish_date": fields.get("publish_date"),
            "bid_end_date": fields.get("bid_end_date"),
            "organisation": fields.get("organisation"),
            "work_category": fields.get("work_category"),
            "short_bid_submission_window_days": fields.get("short_bid_submission_window_days"),
        }

        # Normalize for comparison (Decimal vs float, etc.)
        changed = False
        for key in old:
            o_val = old[key]
            n_val = new[key]
            if o_val is None and n_val is None:
                continue
            if o_val is None or n_val is None:
                changed = True
                break
            if str(o_val).strip() != str(n_val).strip():
                changed = True
                break

        if not changed:
            # Identical data — no new version needed
            return

        # Retire the old version
        old_version = existing[0]
        session.execute(
            text("""
                UPDATE tenders
                SET is_current = false, valid_to = :now
                WHERE tender_id = :tid AND version = :ver
            """),
            {"now": now, "tid": tender_id, "ver": old_version},
        )
        new_version = old_version + 1
    else:
        new_version = 1

    # Insert the new (or first) version
    session.execute(
        text("""
            INSERT INTO tenders
                (tender_id, version, is_current, work_name, est_pac,
                 publish_date, bid_end_date, organisation, work_category,
                 source_file_hash, short_bid_submission_window_days,
                 parsed_at, valid_from, valid_to)
            VALUES
                (:tender_id, :version, true, :work_name, :est_pac,
                 :publish_date, :bid_end_date, :organisation, :work_category,
                 :source_file_hash, :bid_window,
                 :now, :now, NULL)
        """),
        {
            "tender_id": tender_id,
            "version": new_version,
            "work_name": fields.get("work_name"),
            "est_pac": fields.get("est_pac"),
            "publish_date": fields.get("publish_date"),
            "bid_end_date": fields.get("bid_end_date"),
            "organisation": fields.get("organisation"),
            "work_category": fields.get("work_category"),
            "source_file_hash": file_hash,
            "bid_window": fields.get("short_bid_submission_window_days"),
            "now": now,
        },
    )


# ────────────────────────────────────────────────────────────
# Status Update Helper
# ────────────────────────────────────────────────────────────
def update_parse_status(session: Session, file_hash: str, status: str) -> None:
    """Update the parse_status of a catalog entry."""
    session.execute(
        update(RawDocumentCatalog)
        .where(RawDocumentCatalog.file_hash == file_hash)
        .values(parse_status=status)
    )


# ────────────────────────────────────────────────────────────
# Main Pipeline
# ────────────────────────────────────────────────────────────
def run_parser() -> None:
    """Process all pending PDFs from Bronze layer into Silver."""
    print("=" * 65)
    print("  Project Sentinel - Phase 2: Bronze -> Silver Parsing Pipeline")
    print("=" * 65)

    engine = create_engine(DATABASE_URL, echo=False, pool_pre_ping=True)
    Base.metadata.create_all(bind=engine)
    SessionFactory = sessionmaker(bind=engine)

    with SessionFactory() as session:
        # Fetch all pending PDFs
        pending = session.execute(
            text("""
                SELECT file_hash, bronze_path, original_file_name
                FROM raw_document_catalog
                WHERE file_type = 'PDF' AND parse_status = 'PENDING'
                ORDER BY ingested_at
            """)
        ).fetchall()

        total = len(pending)
        if total == 0:
            print("\n  No pending PDFs found. Nothing to parse.")
            return

        print(f"\n  Pending PDFs to parse: {total}")
        print(f"  Source: {BRONZE_PDFS_DIR}")
        print()

        stats = {
            "nit_parsed": 0,
            "non_nit": 0,
            "failed_corrupt": 0,
            "failed_no_fields": 0,
            "file_not_found": 0,
        }

        for i, row in enumerate(pending, 1):
            file_hash = row[0]
            bronze_path = row[1]
            original_name = row[2]

            # Resolve the PDF path
            if bronze_path:
                pdf_path = PROJECT_ROOT / bronze_path
            else:
                # Fallback: try to find by hash in bronze/pdfs
                candidates = list(BRONZE_PDFS_DIR.glob(f"pdf_{file_hash}.*"))
                pdf_path = candidates[0] if candidates else None

            if pdf_path is None or not Path(pdf_path).exists():
                print(f"  [{i:3d}/{total}] SKIP (file not found): {original_name}")
                update_parse_status(session, file_hash, "FAILED_CORRUPT")
                stats["file_not_found"] += 1
                continue

            # Attempt text extraction
            try:
                full_text = extract_text_from_pdf(Path(pdf_path))
            except Exception as e:
                print(f"  [{i:3d}/{total}] FAILED_CORRUPT (pdfplumber error): {original_name}")
                update_parse_status(session, file_hash, "FAILED_CORRUPT")
                stats["failed_corrupt"] += 1
                continue

            if not full_text:
                print(f"  [{i:3d}/{total}] FAILED_CORRUPT (no text): {original_name}")
                update_parse_status(session, file_hash, "FAILED_CORRUPT")
                stats["failed_corrupt"] += 1
                continue

            # Attempt regex extraction
            try:
                fields = extract_tender_fields(full_text)
            except Exception as e:
                print(f"  [{i:3d}/{total}] FAILED_CORRUPT (regex error): {original_name}")
                update_parse_status(session, file_hash, "FAILED_CORRUPT")
                stats["failed_corrupt"] += 1
                continue

            if fields is None:
                # Regex failed to find NIT fields (affidavit, non-NIT form, etc.)
                update_parse_status(session, file_hash, "FAILED_CORRUPT")
                stats["failed_no_fields"] += 1
                if i % 50 == 0 or i == total:
                    print(f"  [{i:3d}/{total}] ... {stats['nit_parsed']} tenders parsed, {stats['failed_no_fields']} unparsed/failed")
                if i % 25 == 0:
                    session.commit()
                continue

            # Validate mandatory fields
            mandatory_missing = not all([
                fields.get("tender_id"),
                fields.get("work_name"),
                fields.get("est_pac"),
                fields.get("publish_date"),
                fields.get("bid_end_date"),
            ])
            if mandatory_missing:
                update_parse_status(session, file_hash, "FAILED_CORRUPT")
                stats["failed_no_fields"] += 1
                if i % 25 == 0:
                    session.commit()
                continue

            # Load into Silver layer with SCD Type 2
            try:
                upsert_tender_scd2(session, fields, file_hash)
                update_parse_status(session, file_hash, "COMPLETED")
                stats["nit_parsed"] += 1
            except Exception as e:
                print(f"  [{i:3d}/{total}] FAILED (DB error): {original_name} — {e}")
                session.rollback()
                update_parse_status(session, file_hash, "FAILED_CORRUPT")
                stats["failed_corrupt"] += 1
                continue

            # Progress logging & periodic commit
            if i % 25 == 0 or i == total:
                session.commit()
                if i % 50 == 0 or i == total:
                    print(f"  [{i:3d}/{total}] ... {stats['nit_parsed']} tenders parsed, {stats['failed_no_fields']} non-NIT/failed")

        # Final commit
        session.commit()

    # Summary
    print()
    print("-" * 65)
    print("  PARSING SUMMARY")
    print("-" * 65)
    print(f"  Total PDFs processed:    {total}")
    print(f"  NIT tenders parsed:      {stats['nit_parsed']}")
    print(f"  Non-NIT docs (skipped):  {stats['non_nit']}")
    print(f"  Failed (corrupt/empty):  {stats['failed_corrupt']}")
    print(f"  Failed (missing fields): {stats['failed_no_fields']}")
    print(f"  File not found:          {stats['file_not_found']}")
    print("-" * 65)
    print("  Phase 2 complete.")
    print()


if __name__ == "__main__":
    run_parser()
