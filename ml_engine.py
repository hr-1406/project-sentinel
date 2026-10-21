"""
Phase 3 - Gold Feature Matrix & Surrogate Explainability Engine
Project Sentinel: Unsupervised Ensemble (IF + LOF) & SHAP Global Surrogate

Workflow:
  1. Data Fetching & Scaling:
     - Query active tenders (is_current = True) from the Silver layer.
     - Apply RobustScaler to the financial pac column (est_pac) for distributional stability.
  2. Gold Feature Matrix Construction:
     - 4 locked procurement features:
       * short_bid_submission_window_days (Silver table)
       * rate_deviation_pct (synthetic float [-15.0, +25.0], seed 42)
       * boq_unbalanced_bidding_index (synthetic float [0.0, 1.0], seed 42)
       * standard_bitumen_spec_ratio (synthetic float [0.1, 0.9], seed 42)
  3. Unsupervised Anomaly Ensemble:
     - IsolationForest(contamination=0.05, random_state=42)
     - LocalOutlierFactor(n_neighbors=20, novelty=False)
     - Score inversion & independent MinMaxScaler [0.00, 1.00]
     - Combined anomaly_score = exact arithmetic mean of normalized IF and LOF scores.
  4. Global Surrogate Explainability (LOF/SHAP Workaround):
     - Train RandomForestRegressor(n_estimators=100, max_depth=5, random_state=42)
       to predict anomaly_score from the 4 Gold features.
     - Pass the surrogate into shap.TreeExplainer to compute exact per-feature contributions.
  5. Gold Layer Persistence:
     - Upsert scored records and SHAP impact json into the PostgreSQL table `gold_tender_scores`.

Usage:
    python ml_engine.py
"""

import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import shap
from sklearn.ensemble import IsolationForest, RandomForestRegressor
from sklearn.neighbors import LocalOutlierFactor
from sklearn.preprocessing import MinMaxScaler, RobustScaler
from sqlalchemy import (
    DateTime,
    Float,
    Integer,
    String,
    create_engine,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, insert as pg_insert
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

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+psycopg2://postgres:raphael1111@localhost:5432/sentinel_db",
)

FEATURE_COLUMNS = [
    "short_bid_submission_window_days",
    "rate_deviation_pct",
    "boq_unbalanced_bidding_index",
    "standard_bitumen_spec_ratio",
]


# ────────────────────────────────────────────────────────────
# ORM Model for Gold Layer Persistence
# ────────────────────────────────────────────────────────────
class Base(DeclarativeBase):
    pass


class GoldTenderScore(Base):
    __tablename__ = "gold_tender_scores"

    tender_id: Mapped[str] = mapped_column(
        String(128), primary_key=True, comment="FK -> tenders.tender_id"
    )
    anomaly_score: Mapped[float] = mapped_column(
        Float, nullable=False, comment="Combined ensemble anomaly score [0.0, 1.0]"
    )
    if_score_norm: Mapped[float] = mapped_column(
        Float, nullable=False, comment="Normalized inverted Isolation Forest score [0.0, 1.0]"
    )
    lof_score_norm: Mapped[float] = mapped_column(
        Float, nullable=False, comment="Normalized inverted Local Outlier Factor score [0.0, 1.0]"
    )
    short_bid_submission_window_days: Mapped[int] = mapped_column(
        Integer, nullable=False, comment="Bid submission window duration in days"
    )
    rate_deviation_pct: Mapped[float] = mapped_column(
        Float, nullable=False, comment="Percentage rate deviation relative to baseline"
    )
    boq_unbalanced_bidding_index: Mapped[float] = mapped_column(
        Float, nullable=False, comment="BOQ unit rate variance index [0.0, 1.0]"
    )
    standard_bitumen_spec_ratio: Mapped[float] = mapped_column(
        Float, nullable=False, comment="Standard bitumen specification ratio [0.0, 1.0]"
    )
    shap_base_value: Mapped[float] = mapped_column(
        Float, nullable=False, comment="Expected base value from surrogate TreeExplainer"
    )
    shap_values_json: Mapped[dict] = mapped_column(
        JSONB, nullable=False, comment="Per-feature SHAP impact dictionary"
    )
    scored_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), comment="Scoring timestamp"
    )


# ────────────────────────────────────────────────────────────
# Pipeline Functions
# ────────────────────────────────────────────────────────────
def fetch_silver_tenders(engine) -> pd.DataFrame:
    """Fetch all active tenders from the Silver layer."""
    query = """
        SELECT
            tender_id,
            est_pac,
            publish_date,
            bid_end_date,
            short_bid_submission_window_days,
            work_name,
            organisation
        FROM tenders
        WHERE is_current = true
        ORDER BY publish_date ASC, tender_id ASC
    """
    df = pd.read_sql(query, engine)
    if df.empty:
        raise ValueError("No active tender records found in Silver layer (tenders table).")
    return df


def construct_gold_feature_matrix(df: pd.DataFrame) -> tuple[pd.DataFrame, np.ndarray]:
    """
    Scale financial pac and construct the locked 4-feature Gold matrix.

    Returns:
        (augmented_df, X_matrix)
    """
    n_samples = len(df)
    rng = np.random.default_rng(seed=42)

    # 1. Apply RobustScaler to est_pac for procurement scale stability
    pac_values = df["est_pac"].astype(float).values.reshape(-1, 1)
    robust_scaler = RobustScaler()
    df["est_pac_scaled"] = robust_scaler.fit_transform(pac_values).flatten()

    # 2. Extract / Generate the 4 locked procurement features
    # (a) short_bid_submission_window_days from Silver
    # If any nulls exist, fallback to median
    if df["short_bid_submission_window_days"].isnull().any():
        median_window = int(df["short_bid_submission_window_days"].median())
        df["short_bid_submission_window_days"] = df["short_bid_submission_window_days"].fillna(median_window)
    df["short_bid_submission_window_days"] = df["short_bid_submission_window_days"].astype(int)

    # (b) rate_deviation_pct: synthetic float between -15.0 and +25.0 (seed 42)
    df["rate_deviation_pct"] = np.round(rng.uniform(-15.0, 25.0, size=n_samples), 2)

    # (c) boq_unbalanced_bidding_index: synthetic float between 0.0 and 1.0 (seed 42)
    df["boq_unbalanced_bidding_index"] = np.round(rng.uniform(0.0, 1.0, size=n_samples), 4)

    # (d) standard_bitumen_spec_ratio: synthetic float between 0.1 and 0.9 (seed 42)
    df["standard_bitumen_spec_ratio"] = np.round(rng.uniform(0.1, 0.9, size=n_samples), 4)

    X = df[FEATURE_COLUMNS].to_numpy(dtype=float)
    return df, X


def score_unsupervised_ensemble(X: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """
    Score the dataset using Isolation Forest and Local Outlier Factor,
    inverting and normalizing scores so higher values indicate higher anomaly severity.

    Returns:
        (anomaly_score, if_score_norm, lof_score_norm)
    """
    min_max_scaler_if = MinMaxScaler(feature_range=(0.0, 1.0))
    min_max_scaler_lof = MinMaxScaler(feature_range=(0.0, 1.0))

    # 1. Isolation Forest
    # score_samples returns negative scores; inverting (-score) yields higher values for outliers
    if_model = IsolationForest(contamination=0.05, random_state=42)
    if_model.fit(X)
    if_raw = if_model.score_samples(X)
    if_inverted = -if_raw
    if_score_norm = min_max_scaler_if.fit_transform(if_inverted.reshape(-1, 1)).flatten()

    # 2. Local Outlier Factor
    # negative_outlier_factor_ is negative with large magnitude for outliers; inverting yields higher values
    n_neighbors = min(20, max(2, len(X) - 1))
    lof_model = LocalOutlierFactor(n_neighbors=n_neighbors, novelty=False)
    lof_model.fit(X)
    lof_raw = lof_model.negative_outlier_factor_
    lof_inverted = -lof_raw
    lof_score_norm = min_max_scaler_lof.fit_transform(lof_inverted.reshape(-1, 1)).flatten()

    # 3. Exact arithmetic mean
    anomaly_score = (if_score_norm + lof_score_norm) / 2.0

    return anomaly_score, if_score_norm, lof_score_norm


def explain_with_surrogate(
    X: np.ndarray, y: np.ndarray, feature_names: list[str]
) -> tuple[float, list[dict]]:
    """
    Fit a RandomForestRegressor surrogate on (X, y) to bypass LOF SHAP limitations,
    then compute local feature contributions using shap.TreeExplainer.

    Returns:
        (base_value, per_sample_shap_dicts)
    """
    # 1. Train surrogate model
    surrogate_rf = RandomForestRegressor(
        n_estimators=100, max_depth=5, random_state=42
    )
    surrogate_rf.fit(X, y)

    # 2. TreeExplainer calculation
    explainer = shap.TreeExplainer(surrogate_rf)
    shap_values = explainer.shap_values(X)

    # Extract base value
    raw_base = explainer.expected_value
    base_value = float(np.ravel(raw_base)[0])

    # 3. Format per-sample dictionary
    per_sample_shap = []
    for i in range(len(X)):
        row_dict = {
            feature_names[j]: round(float(shap_values[i, j]), 6)
            for j in range(len(feature_names))
        }
        per_sample_shap.append(row_dict)

    return base_value, per_sample_shap


def persist_gold_scores(
    engine, df: pd.DataFrame, base_value: float, per_sample_shap: list[dict]
) -> int:
    """Save scored feature matrix and SHAP explanations to gold_tender_scores."""
    Base.metadata.create_all(bind=engine)
    SessionFactory = sessionmaker(bind=engine)

    records_written = 0
    now = datetime.now(timezone.utc)

    with SessionFactory() as session:
        for idx, row in df.iterrows():
            stmt = pg_insert(GoldTenderScore).values(
                tender_id=row["tender_id"],
                anomaly_score=round(float(row["anomaly_score"]), 6),
                if_score_norm=round(float(row["if_score_norm"]), 6),
                lof_score_norm=round(float(row["lof_score_norm"]), 6),
                short_bid_submission_window_days=int(row["short_bid_submission_window_days"]),
                rate_deviation_pct=round(float(row["rate_deviation_pct"]), 4),
                boq_unbalanced_bidding_index=round(float(row["boq_unbalanced_bidding_index"]), 4),
                standard_bitumen_spec_ratio=round(float(row["standard_bitumen_spec_ratio"]), 4),
                shap_base_value=round(base_value, 6),
                shap_values_json=per_sample_shap[idx],
                scored_at=now,
            ).on_conflict_do_update(
                index_elements=["tender_id"],
                set_={
                    "anomaly_score": round(float(row["anomaly_score"]), 6),
                    "if_score_norm": round(float(row["if_score_norm"]), 6),
                    "lof_score_norm": round(float(row["lof_score_norm"]), 6),
                    "short_bid_submission_window_days": int(row["short_bid_submission_window_days"]),
                    "rate_deviation_pct": round(float(row["rate_deviation_pct"]), 4),
                    "boq_unbalanced_bidding_index": round(float(row["boq_unbalanced_bidding_index"]), 4),
                    "standard_bitumen_spec_ratio": round(float(row["standard_bitumen_spec_ratio"]), 4),
                    "shap_base_value": round(base_value, 6),
                    "shap_values_json": per_sample_shap[idx],
                    "scored_at": now,
                },
            )
            session.execute(stmt)
            records_written += 1

        session.commit()

    return records_written


# ────────────────────────────────────────────────────────────
# Main Execution Entry Point
# ────────────────────────────────────────────────────────────
def run_ml_engine() -> None:
    print("=" * 70)
    print("  Project Sentinel - Phase 3: Gold Feature Matrix & ML Scoring")
    print("=" * 70)

    engine = create_engine(DATABASE_URL, echo=False, pool_pre_ping=True)

    # 1. Fetch Silver records
    print("\n[Step 1/5] Fetching active tender records from Silver layer...")
    df = fetch_silver_tenders(engine)
    print(f"  Loaded {len(df)} active tenders.")

    # 2. Build Gold Feature Matrix
    print("\n[Step 2/5] Scaling PAC and building locked 4-feature Gold matrix...")
    df, X = construct_gold_feature_matrix(df)
    print(f"  Matrix shape: {X.shape} (Features: {', '.join(FEATURE_COLUMNS)})")

    # 3. Unsupervised Ensemble (IF + LOF)
    print("\n[Step 3/5] Scoring with Isolation Forest + Local Outlier Factor ensemble...")
    anomaly_score, if_norm, lof_norm = score_unsupervised_ensemble(X)
    df["anomaly_score"] = anomaly_score
    df["if_score_norm"] = if_norm
    df["lof_score_norm"] = lof_norm
    print(f"  Ensemble score range: [{anomaly_score.min():.4f}, {anomaly_score.max():.4f}]")
    print(f"  Ensemble score mean:  {anomaly_score.mean():.4f} (std: {anomaly_score.std():.4f})")

    # 4. Global Surrogate Model (Random Forest + SHAP TreeExplainer)
    print("\n[Step 4/5] Training Global Surrogate Model for explainability...")
    base_value, per_sample_shap = explain_with_surrogate(X, anomaly_score, FEATURE_COLUMNS)
    print(f"  Surrogate trained. SHAP Base Value (Expected Score): {base_value:.4f}")
    print(f"  Generated SHAP attributions for {len(per_sample_shap)} tenders.")

    # 5. Gold Layer Persistence
    print("\n[Step 5/5] Persisting Gold records into PostgreSQL (gold_tender_scores)...")
    records_saved = persist_gold_scores(engine, df, base_value, per_sample_shap)
    print(f"  Successfully upserted {records_saved} records into gold_tender_scores.")

    print("\n" + "-" * 70)
    print("  PHASE 3 COMPLETE: TOP 5 STATISTICAL OUTLIERS (DECISION SUPPORT)")
    print("-" * 70)
    top_outliers = df.sort_values(by="anomaly_score", ascending=False).head(5)
    for rank, (_, row) in enumerate(top_outliers.iterrows(), 1):
        idx = row.name
        shap_info = per_sample_shap[idx]
        top_driver = max(shap_info.items(), key=lambda kv: abs(kv[1]))
        print(
            f"  #{rank} | Tender: {row['tender_id']}\n"
            f"      Score: {row['anomaly_score']:.4f} (IF: {row['if_score_norm']:.4f}, LOF: {row['lof_score_norm']:.4f})\n"
            f"      Bid Window: {row['short_bid_submission_window_days']}d | Rate Dev: {row['rate_deviation_pct']:+.2f}%\n"
            f"      Top Explanatory Factor: {top_driver[0]} (SHAP impact: {top_driver[1]:+.4f})\n"
        )
    print("=" * 70)


if __name__ == "__main__":
    run_ml_engine()
