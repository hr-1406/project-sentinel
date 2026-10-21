"""
Phase 0 - SQLAlchemy 2.0 ORM Models
Project Sentinel: Medallion Architecture Database Schema

Tables
------
raw_document_catalog  — Bronze-layer file registry (SHA-256 dedup, MIME routing)
tenders               — Silver-layer tender metadata (SCD Type 2 versioned)
boq_line_items        — Silver-layer Bill of Quantities line items
audit_logs            — Gold-layer human-in-the-loop decision log

Naming Convention
-----------------
All terminology is strictly neutral (decision-support, not accusation).
We use "anomaly_score", "statistical_outlier", "high_variance" — never
"fraud", "corruption", or "suspicious".
"""

from datetime import datetime, date
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    mapped_column,
    relationship,
)


# ────────────────────────────────────────────────────────────
# Base
# ────────────────────────────────────────────────────────────
class Base(DeclarativeBase):
    """Declarative base for all Project Sentinel models."""
    pass


# ────────────────────────────────────────────────────────────
# Raw / Bronze Layer — Document Catalog
# ────────────────────────────────────────────────────────────
class RawDocumentCatalog(Base):
    """
    Registry of every file extracted from incoming e-Tender ZIPs.

    Files are renamed to their SHA-256 hash on extraction, which serves
    as the natural primary key and mathematically prevents duplicates.

    MIME type (via python-magic) determines routing:
        • application/pdf        → data/bronze/pdfs/
        • spreadsheet types      → data/bronze/boqs/
        • anything else          → data/raw/quarantine/
    """
    __tablename__ = "raw_document_catalog"

    file_hash: Mapped[str] = mapped_column(
        String(64), primary_key=True, comment="SHA-256 hex digest of file content"
    )
    original_zip_name: Mapped[str] = mapped_column(
        String(512), nullable=False, comment="Name of the source ZIP archive"
    )
    original_file_name: Mapped[str] = mapped_column(
        String(512), nullable=False, comment="Original filename inside the ZIP"
    )
    file_type: Mapped[str] = mapped_column(
        String(64), nullable=False,
        comment="MIME type detected by python-magic (e.g. application/pdf)"
    )
    bronze_path: Mapped[str | None] = mapped_column(
        String(1024), nullable=True,
        comment="Relative path in bronze layer (NULL if quarantined)"
    )
    requires_award_data: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false",
        comment="True for pre-bid BOQ templates lacking awarded amounts"
    )
    parse_status: Mapped[str] = mapped_column(
        String(32), default="pending", server_default="pending",
        comment="pending | parsed | failed | quarantined"
    )
    ingested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
        comment="Timestamp of ingestion into the catalog"
    )

    def __repr__(self) -> str:
        return (
            f"<RawDocument hash={self.file_hash[:12]}… "
            f"file={self.original_file_name!r} status={self.parse_status}>"
        )


# ────────────────────────────────────────────────────────────
# Silver Layer — Tenders (SCD Type 2)
# ────────────────────────────────────────────────────────────
class Tender(Base):
    """
    Parsed tender metadata extracted from GePNIC PDF documents.

    Implements Slowly Changing Dimension Type 2:
    - (tender_id, version) is the composite primary key.
    - `is_current` marks the active version for each tender_id.
    - A new version row is inserted whenever re-parsing yields changes.
    """
    __tablename__ = "tenders"

    tender_id: Mapped[str] = mapped_column(
        String(128), primary_key=True,
        comment="GePNIC tender reference number"
    )
    version: Mapped[int] = mapped_column(
        Integer, primary_key=True, default=1,
        comment="SCD Type 2 version number (starts at 1)"
    )
    is_current: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default="true",
        comment="True for the active version of this tender_id"
    )

    # --- Parsed metadata ---
    work_name: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="Name / description of the road work"
    )
    est_pac: Mapped[Decimal | None] = mapped_column(
        Numeric(15, 2), nullable=True,
        comment="Estimated Probable Amount of Contract (INR)"
    )
    publish_date: Mapped[date | None] = mapped_column(
        Date, nullable=True, comment="Tender publication date"
    )
    bid_end_date: Mapped[date | None] = mapped_column(
        Date, nullable=True, comment="Last date/time for bid submission"
    )
    organisation: Mapped[str | None] = mapped_column(
        String(512), nullable=True,
        comment="Procuring LSGD body (Panchayat / Municipality / Corporation)"
    )
    work_category: Mapped[str | None] = mapped_column(
        String(256), nullable=True,
        comment="Category of work (e.g. Road, Bridge, Drain)"
    )
    source_file_hash: Mapped[str | None] = mapped_column(
        String(64), nullable=True,
        comment="SHA-256 hash linking back to raw_document_catalog"
    )
    short_bid_submission_window_days: Mapped[int | None] = mapped_column(
        Integer, nullable=True,
        comment="Delta in days between publish_date and bid_end_date"
    )

    # --- Timestamps ---
    parsed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
        comment="When this version was parsed and inserted"
    )
    valid_from: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
        comment="SCD2: start of validity for this version"
    )
    valid_to: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
        comment="SCD2: end of validity (NULL = currently active)"
    )

    # --- Relationships ---
    boq_items: Mapped[list["BOQLineItem"]] = relationship(
        back_populates="tender", cascade="all, delete-orphan"
    )
    audit_entries: Mapped[list["AuditLog"]] = relationship(
        back_populates="tender"
    )

    __table_args__ = (
        Index("ix_tenders_current", "tender_id", "is_current"),
        UniqueConstraint(
            "tender_id", "is_current",
            name="uq_one_current_per_tender",
            # PostgreSQL partial-unique-index workaround applied via Alembic
            # migration if needed. The ORM constraint covers the common case.
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<Tender {self.tender_id} v{self.version} "
            f"current={self.is_current} PAC={self.est_pac}>"
        )


# ────────────────────────────────────────────────────────────
# Silver Layer — BOQ Line Items
# ────────────────────────────────────────────────────────────
class BOQLineItem(Base):
    """
    Individual line items from a Bill of Quantities.

    Linked to a specific (tender_id, version) composite key.
    Pre-bid templates where awarded amounts are missing should have the
    parent RawDocumentCatalog row flagged with requires_award_data = True.
    """
    __tablename__ = "boq_line_items"

    id: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True
    )
    tender_id: Mapped[str] = mapped_column(
        String(128), nullable=False,
        comment="FK → tenders.tender_id"
    )
    tender_version: Mapped[int] = mapped_column(
        Integer, nullable=False,
        comment="FK → tenders.version"
    )

    item_no: Mapped[str | None] = mapped_column(
        String(32), nullable=True, comment="Item/schedule number from BOQ"
    )
    description: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="Description of work item"
    )
    unit: Mapped[str | None] = mapped_column(
        String(32), nullable=True, comment="Unit of measurement (e.g. cum, sqm, rm)"
    )
    quantity: Mapped[Decimal | None] = mapped_column(
        Numeric(15, 4), nullable=True, comment="Estimated quantity"
    )
    rate: Mapped[Decimal | None] = mapped_column(
        Numeric(15, 2), nullable=True,
        comment="Rate per unit (INR). NULL for pre-bid templates"
    )
    amount: Mapped[Decimal | None] = mapped_column(
        Numeric(15, 2), nullable=True,
        comment="Total amount (INR). NULL for pre-bid templates"
    )

    # --- Relationship ---
    tender: Mapped["Tender"] = relationship(back_populates="boq_items")

    __table_args__ = (
        ForeignKeyConstraint(
            ["tender_id", "tender_version"],
            ["tenders.tender_id", "tenders.version"],
            name="fk_boq_tender",
        ),
        Index("ix_boq_tender", "tender_id", "tender_version"),
    )

    def __repr__(self) -> str:
        return (
            f"<BOQLineItem #{self.item_no} tender={self.tender_id} "
            f"qty={self.quantity} rate={self.rate}>"
        )


# ────────────────────────────────────────────────────────────
# Gold Layer — Audit Log (Human-in-the-Loop)
# ────────────────────────────────────────────────────────────
class AuditLog(Base):
    """
    Tracks every human auditor action on a flagged tender.

    This is the accountability backbone — every "dismiss" or "escalate"
    decision must include a written justification. This table is
    append-only by design.
    """
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True
    )
    tender_id: Mapped[str] = mapped_column(
        String(128), nullable=False,
        comment="FK → tenders.tender_id (links to the logical tender)"
    )
    tender_version: Mapped[int] = mapped_column(
        Integer, nullable=False,
        comment="FK → tenders.version (the exact version being reviewed)"
    )

    auditor_name: Mapped[str | None] = mapped_column(
        String(256), nullable=True, comment="Name or ID of the reviewing auditor"
    )
    auditor_action: Mapped[str] = mapped_column(
        String(64), nullable=False,
        comment="Action taken: reviewed | escalated | dismissed | noted"
    )
    justification: Mapped[str | None] = mapped_column(
        Text, nullable=True,
        comment="Free-text explanation for the action (mandatory for dismiss/escalate)"
    )
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
        comment="When the audit action was recorded"
    )

    # --- Relationship ---
    tender: Mapped["Tender"] = relationship(back_populates="audit_entries")

    __table_args__ = (
        ForeignKeyConstraint(
            ["tender_id", "tender_version"],
            ["tenders.tender_id", "tenders.version"],
            name="fk_audit_tender",
        ),
        Index("ix_audit_tender", "tender_id"),
        Index("ix_audit_timestamp", "timestamp"),
    )

    def __repr__(self) -> str:
        return (
            f"<AuditLog tender={self.tender_id} action={self.auditor_action} "
            f"at={self.timestamp}>"
        )


# ────────────────────────────────────────────────────────────
# Gold Layer — Tender Anomaly Scores & Surrogate Explanations
# ────────────────────────────────────────────────────────────
class GoldTenderScore(Base):
    """
    Gold-layer feature matrix, anomaly ensemble scores, and SHAP explanations.

    Scores are produced by an ensemble of Isolation Forest and Local Outlier Factor,
    with local feature attributions generated via a RandomForest surrogate model
    fitted on the combined anomaly_score and explained via shap.TreeExplainer.

    Terminology is strictly neutral: 'anomaly_score', 'outlier', 'variance'.
    """
    __tablename__ = "gold_tender_scores"

    tender_id: Mapped[str] = mapped_column(
        String(128), primary_key=True,
        comment="FK → tenders.tender_id"
    )

    # --- Ensemble Anomaly Metrics ---
    anomaly_score: Mapped[float] = mapped_column(
        Float, nullable=False,
        comment="Ensemble score: arithmetic mean of normalized IF and LOF scores [0.0, 1.0]"
    )
    if_score_norm: Mapped[float] = mapped_column(
        Float, nullable=False,
        comment="Normalized inverted Isolation Forest anomaly score [0.0, 1.0]"
    )
    lof_score_norm: Mapped[float] = mapped_column(
        Float, nullable=False,
        comment="Normalized inverted Local Outlier Factor anomaly score [0.0, 1.0]"
    )

    # --- Gold Feature Matrix Values ---
    short_bid_submission_window_days: Mapped[int] = mapped_column(
        Integer, nullable=False,
        comment="Bid window duration in days"
    )
    rate_deviation_pct: Mapped[float] = mapped_column(
        Float, nullable=False,
        comment="Percentage rate deviation relative to estimate baseline"
    )
    boq_unbalanced_bidding_index: Mapped[float] = mapped_column(
        Float, nullable=False,
        comment="Index quantifying variance/imbalance across BOQ unit rates [0.0, 1.0]"
    )
    standard_bitumen_spec_ratio: Mapped[float] = mapped_column(
        Float, nullable=False,
        comment="Ratio of standard bitumen specification compliance [0.0, 1.0]"
    )

    # --- SHAP Global Surrogate Attributions ---
    shap_base_value: Mapped[float] = mapped_column(
        Float, nullable=False,
        comment="Expected base value from the TreeExplainer surrogate model"
    )
    shap_values_json: Mapped[dict] = mapped_column(
        JSONB, nullable=False,
        comment="Per-feature SHAP impact dictionary {feature_name: contribution_value}"
    )

    scored_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
        comment="Timestamp of ML scoring and explainability calculation"
    )

    def __repr__(self) -> str:
        return (
            f"<GoldTenderScore tender={self.tender_id} "
            f"score={self.anomaly_score:.4f} base={self.shap_base_value:.4f}>"
        )

