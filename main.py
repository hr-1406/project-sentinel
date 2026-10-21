"""
Phase 4 - FastAPI Decision-Support Backend
Project Sentinel: Explainable AI-Based Road Tender Anomaly Detection System

Provides decision-support APIs for human procurement auditors:
  - GET /api/tenders: Ranked triage queue by anomaly_score
  - GET /api/tenders/{tender_id:path}: Deep investigation data with SHAP attributions
  - POST /api/tenders/{tender_id:path}/audit: Human-in-the-loop audit resolution
  - GET /api/summary: High-level triage metrics for the dashboard header

Terminology is strictly neutral: 'Statistical Outlier', 'Elevated Variance',
'Within Normal Baseline', 'Triage Priority'.
"""

import os
from datetime import datetime, timezone
from typing import Any, List, Optional

from fastapi import FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from sqlalchemy import desc, func, select, text
from sqlalchemy.orm import Session

from database import SessionLocal, engine
from models import AuditLog, GoldTenderScore, RawDocumentCatalog, Tender

# ────────────────────────────────────────────────────────────
# FastAPI App Initialization
# ────────────────────────────────────────────────────────────
app = FastAPI(
    title="Project Sentinel - Procurement Decision Support API",
    description="Explainable Anomaly Detection System for Kerala LSGD Road Tenders",
    version="1.0.0",
)

# Enable CORS for local Vite development
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ────────────────────────────────────────────────────────────
# Pydantic Schemas
# ────────────────────────────────────────────────────────────
class AuditLogSchema(BaseModel):
    id: int
    tender_id: str
    tender_version: int
    auditor_name: Optional[str] = None
    auditor_action: str
    justification: Optional[str] = None
    timestamp: datetime

    class Config:
        from_attributes = True


class AuditCreateRequest(BaseModel):
    auditor_action: str = Field(..., description="E.g. 'Acknowledge & Clear', 'Escalate for Technical Review'")
    justification: str = Field(..., min_length=3, description="Justification for the decision")
    auditor_name: Optional[str] = Field("Auditor (Decision Support)", description="Auditor identifier")


class TenderListItem(BaseModel):
    tender_id: str
    version: int
    work_name: Optional[str] = None
    est_pac: Optional[float] = None
    publish_date: Optional[str] = None
    bid_end_date: Optional[str] = None
    organisation: Optional[str] = None
    short_bid_submission_window_days: int
    anomaly_score: float
    if_score_norm: float
    lof_score_norm: float
    status_badge: str
    requires_award_data: bool
    audit_count: int
    latest_audit_action: Optional[str] = None


class ShapWaterfallItem(BaseModel):
    feature: str
    label: str
    value: float
    impact: float
    direction: str  # "elevating" or "moderating"
    plain_english: str


class TenderDetailResponse(BaseModel):
    tender_id: str
    version: int
    work_name: Optional[str] = None
    est_pac: Optional[float] = None
    publish_date: Optional[str] = None
    bid_end_date: Optional[str] = None
    organisation: Optional[str] = None
    work_category: Optional[str] = None
    short_bid_submission_window_days: int
    requires_award_data: bool

    # Anomaly Metrics
    anomaly_score: float
    if_score_norm: float
    lof_score_norm: float
    status_badge: str

    # Gold Feature Values
    rate_deviation_pct: float
    boq_unbalanced_bidding_index: float
    standard_bitumen_spec_ratio: float

    # SHAP Explanations
    shap_base_value: float
    shap_waterfall: List[ShapWaterfallItem]

    # Audit Logs
    audit_logs: List[AuditLogSchema]


class SummaryMetricsResponse(BaseModel):
    total_tenders: int
    high_variance_count: int
    moderate_variance_count: int
    baseline_normal_count: int
    audited_count: int
    avg_anomaly_score: float


# ────────────────────────────────────────────────────────────
# Neutral Labeling & Translation Helpers
# ────────────────────────────────────────────────────────────
def derive_status_badge(anomaly_score: float) -> str:
    """Derive strictly neutral decision-support tier based on score."""
    if anomaly_score >= 0.75:
        return "High Statistical Variance"
    elif anomaly_score >= 0.50:
        return "Moderate Variance"
    return "Baseline Normal"


FEATURE_LABELS = {
    "short_bid_submission_window_days": "Short Bid Submission Window",
    "rate_deviation_pct": "Rate Deviation Baseline",
    "boq_unbalanced_bidding_index": "BOQ Unbalanced Rate Index",
    "standard_bitumen_spec_ratio": "Standard Bitumen Spec Ratio",
}


def translate_shap_item(feature_key: str, feature_val: float, impact: float) -> ShapWaterfallItem:
    """Translate raw SHAP contribution to human-readable decision support text."""
    label = FEATURE_LABELS.get(feature_key, feature_key)
    direction = "elevating" if impact >= 0 else "moderating"
    abs_impact = abs(impact)

    if feature_key == "short_bid_submission_window_days":
        if impact > 0:
            text = f"Short window ({int(feature_val)} days) contributed +{abs_impact:.3f} toward outlier threshold."
        else:
            text = f"Bid submission window of {int(feature_val)} days is consistent with standard statutory notice."
    elif feature_key == "rate_deviation_pct":
        if impact > 0:
            text = f"Rate deviation of {feature_val:+.1f}% pushed anomaly score up by +{abs_impact:.3f} relative to baseline."
        else:
            text = f"Rate deviation of {feature_val:+.1f}% is aligned with regional cost estimates ({impact:.3f})."
    elif feature_key == "boq_unbalanced_bidding_index":
        if impact > 0:
            text = f"Item rate distribution variance index ({feature_val:.3f}) added +{abs_impact:.3f} to overall score."
        else:
            text = f"Balanced BOQ line item rate dispersion across schedules ({impact:.3f})."
    elif feature_key == "standard_bitumen_spec_ratio":
        if impact > 0:
            text = f"Bitumen specification ratio of {feature_val:.2f} contributed +{abs_impact:.3f} to score divergence."
        else:
            text = f"Bitumen specification compliance ratio of {feature_val:.2f} moderated the anomaly index."
    else:
        text = f"{label} (value: {feature_val}) had {impact:+.3f} impact on score."

    return ShapWaterfallItem(
        feature=feature_key,
        label=label,
        value=float(feature_val),
        impact=round(float(impact), 6),
        direction=direction,
        plain_english=text,
    )


# ────────────────────────────────────────────────────────────
# API Endpoints
# ────────────────────────────────────────────────────────────
@app.get("/api/summary", response_model=SummaryMetricsResponse)
def get_triage_summary():
    """Returns high-level triage metrics for the dashboard header."""
    with SessionLocal() as session:
        scores = session.execute(
            select(GoldTenderScore.anomaly_score)
        ).scalars().all()

        total = len(scores)
        if total == 0:
            return SummaryMetricsResponse(
                total_tenders=0,
                high_variance_count=0,
                moderate_variance_count=0,
                baseline_normal_count=0,
                audited_count=0,
                avg_anomaly_score=0.0,
            )

        high = sum(1 for s in scores if s >= 0.75)
        moderate = sum(1 for s in scores if 0.50 <= s < 0.75)
        baseline = sum(1 for s in scores if s < 0.50)
        avg_score = sum(scores) / total

        audited_count = session.execute(
            select(func.count(func.distinct(AuditLog.tender_id)))
        ).scalar() or 0

        return SummaryMetricsResponse(
            total_tenders=total,
            high_variance_count=high,
            moderate_variance_count=moderate,
            baseline_normal_count=baseline,
            audited_count=audited_count,
            avg_anomaly_score=round(avg_score, 4),
        )


@app.get("/api/tenders", response_model=List[TenderListItem])
def list_triage_queue():
    """
    Returns the triage queue sorted by anomaly_score descending.
    Joins tenders (is_current = True) with gold_tender_scores.
    """
    with SessionLocal() as session:
        query = text("""
            SELECT
                t.tender_id,
                t.version,
                t.work_name,
                t.est_pac,
                TO_CHAR(t.publish_date, 'YYYY-MM-DD') as pub_date,
                TO_CHAR(t.bid_end_date, 'YYYY-MM-DD') as end_date,
                t.organisation,
                g.short_bid_submission_window_days,
                g.anomaly_score,
                g.if_score_norm,
                g.lof_score_norm,
                COALESCE((
                    SELECT r.requires_award_data
                    FROM raw_document_catalog r
                    WHERE r.file_hash = t.source_file_hash
                    LIMIT 1
                ), true) as requires_award_data,
                (SELECT COUNT(*) FROM audit_logs a WHERE a.tender_id = t.tender_id) as audit_count,
                (
                    SELECT a.auditor_action
                    FROM audit_logs a
                    WHERE a.tender_id = t.tender_id
                    ORDER BY a.timestamp DESC
                    LIMIT 1
                ) as latest_audit_action
            FROM tenders t
            JOIN gold_tender_scores g ON t.tender_id = g.tender_id
            WHERE t.is_current = true
            ORDER BY g.anomaly_score DESC
        """)

        results = session.execute(query).fetchall()
        items = []
        for r in results:
            items.append(
                TenderListItem(
                    tender_id=r[0],
                    version=r[1],
                    work_name=r[2],
                    est_pac=float(r[3]) if r[3] is not None else None,
                    publish_date=r[4],
                    bid_end_date=r[5],
                    organisation=r[6],
                    short_bid_submission_window_days=r[7],
                    anomaly_score=round(float(r[8]), 4),
                    if_score_norm=round(float(r[9]), 4),
                    lof_score_norm=round(float(r[10]), 4),
                    status_badge=derive_status_badge(float(r[8])),
                    requires_award_data=bool(r[11]),
                    audit_count=int(r[12]),
                    latest_audit_action=r[13],
                )
            )
        return items


@app.get("/api/tenders/{tender_id:path}", response_model=TenderDetailResponse)
def get_tender_investigation(tender_id: str):
    """
    Returns complete tender metadata, Gold feature values, IF/LOF sub-scores,
    SHAP waterfall chart items, and historical audit logs.
    """
    with SessionLocal() as session:
        # Query tender + gold score
        query = text("""
            SELECT
                t.tender_id,
                t.version,
                t.work_name,
                t.est_pac,
                TO_CHAR(t.publish_date, 'YYYY-MM-DD') as pub_date,
                TO_CHAR(t.bid_end_date, 'YYYY-MM-DD') as end_date,
                t.organisation,
                t.work_category,
                g.short_bid_submission_window_days,
                g.anomaly_score,
                g.if_score_norm,
                g.lof_score_norm,
                g.rate_deviation_pct,
                g.boq_unbalanced_bidding_index,
                g.standard_bitumen_spec_ratio,
                g.shap_base_value,
                g.shap_values_json,
                COALESCE((
                    SELECT r.requires_award_data
                    FROM raw_document_catalog r
                    WHERE r.file_hash = t.source_file_hash
                    LIMIT 1
                ), true) as requires_award_data
            FROM tenders t
            JOIN gold_tender_scores g ON t.tender_id = g.tender_id
            WHERE t.tender_id = :tid AND t.is_current = true
        """)

        r = session.execute(query, {"tid": tender_id}).fetchone()
        if not r:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Tender record '{tender_id}' not found in Gold scores.",
            )

        shap_json = r[16] or {}
        feature_values = {
            "short_bid_submission_window_days": r[8],
            "rate_deviation_pct": r[12],
            "boq_unbalanced_bidding_index": r[13],
            "standard_bitumen_spec_ratio": r[14],
        }

        # Build waterfall items sorted by magnitude of impact
        waterfall_items = []
        for feat_key, feat_val in feature_values.items():
            impact = float(shap_json.get(feat_key, 0.0))
            waterfall_items.append(translate_shap_item(feat_key, feat_val, impact))

        # Sort waterfall items so largest positive drivers appear first
        waterfall_items.sort(key=lambda x: x.impact, reverse=True)

        # Query past audit logs
        logs_query = text("""
            SELECT id, tender_id, tender_version, auditor_name,
                   auditor_action, justification, timestamp
            FROM audit_logs
            WHERE tender_id = :tid
            ORDER BY timestamp DESC
        """)
        log_rows = session.execute(logs_query, {"tid": tender_id}).fetchall()
        audit_logs = [
            AuditLogSchema(
                id=lr[0],
                tender_id=lr[1],
                tender_version=lr[2],
                auditor_name=lr[3],
                auditor_action=lr[4],
                justification=lr[5],
                timestamp=lr[6],
            )
            for lr in log_rows
        ]

        return TenderDetailResponse(
            tender_id=r[0],
            version=r[1],
            work_name=r[2],
            est_pac=float(r[3]) if r[3] is not None else None,
            publish_date=r[4],
            bid_end_date=r[5],
            organisation=r[6],
            work_category=r[7],
            short_bid_submission_window_days=r[8],
            requires_award_data=bool(r[17]),
            anomaly_score=round(float(r[9]), 4),
            if_score_norm=round(float(r[10]), 4),
            lof_score_norm=round(float(r[11]), 4),
            status_badge=derive_status_badge(float(r[9])),
            rate_deviation_pct=round(float(r[12]), 2),
            boq_unbalanced_bidding_index=round(float(r[13]), 4),
            standard_bitumen_spec_ratio=round(float(r[14]), 4),
            shap_base_value=round(float(r[15]), 4),
            shap_waterfall=waterfall_items,
            audit_logs=audit_logs,
        )


@app.post("/api/tenders/{tender_id:path}/audit", response_model=List[AuditLogSchema])
def add_audit_decision(tender_id: str, payload: AuditCreateRequest):
    """
    Records an auditor action and written justification into audit_logs.
    Returns the complete updated history of audit actions for this tender.
    """
    with SessionLocal() as session:
        # Verify tender exists and retrieve active version
        tender_res = session.execute(
            select(Tender.version).where(
                Tender.tender_id == tender_id, Tender.is_current == True
            )
        ).scalar()

        if tender_res is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Cannot record audit: Tender '{tender_id}' not found.",
            )

        new_entry = AuditLog(
            tender_id=tender_id,
            tender_version=tender_res,
            auditor_name=payload.auditor_name or "Auditor (Decision Support)",
            auditor_action=payload.auditor_action,
            justification=payload.justification,
            timestamp=datetime.now(timezone.utc),
        )
        session.add(new_entry)
        session.commit()

        # Return updated log entries
        updated_logs = session.execute(
            select(AuditLog)
            .where(AuditLog.tender_id == tender_id)
            .order_by(desc(AuditLog.timestamp))
        ).scalars().all()

        return [AuditLogSchema.model_validate(log) for log in updated_logs]


@app.get("/")
def root():
    return {
        "system": "Project Sentinel",
        "description": "Explainable Anomaly Detection Decision Support API",
        "endpoints": [
            "/api/summary",
            "/api/tenders",
            "/api/tenders/{tender_id}",
            "/api/tenders/{tender_id}/audit",
            "/docs",
        ],
    }
