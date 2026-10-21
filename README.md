# Project Sentinel

Project Sentinel is an explainable decision-support system for triaging statistical outliers in Kerala LSGD public road tenders. It combines a PostgreSQL-backed data pipeline, unsupervised anomaly detection, SHAP-based explanations, a FastAPI backend, and a React dashboard.

> **Decision support, not accusation:** anomaly scores identify records for human review. They are not legal, administrative, or fraud findings.

## Features

- **Raw-to-Bronze ingestion:** processes tender ZIP archives, detects file types from file content, hashes files for deduplication, and quarantines unsupported files.
- **Bronze-to-Silver parsing:** extracts tender metadata from GePNIC PDFs and stores versioned tender records.
- **Gold scoring:** builds a four-feature procurement matrix and combines Isolation Forest and Local Outlier Factor scores.
- **Explainability:** trains a Random Forest surrogate and uses SHAP TreeExplainer to provide per-tender feature contributions.
- **Audit workflow:** exposes tender triage, investigation details, summary metrics, and human audit actions through FastAPI.
- **Dashboard:** provides a Vite/React interface for reviewing ranked tenders and their explanations.

## Architecture

```text
ZIP archives
    │
    ▼
Raw → Bronze ingestion ──► raw_document_catalog
    │
    ▼
Bronze → Silver parsing ─► tenders
    │
    ▼
Gold ML scoring ──────────► gold_tender_scores
    │
    ▼
FastAPI decision-support API
    │
    ▼
React dashboard
```

## Requirements

- Python 3.10 or newer
- Node.js and npm
- PostgreSQL 14 or newer
- `libmagic` support through `python-magic-bin` on Windows

## Setup

### 1. Create and activate a Python environment

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

### 2. Configure PostgreSQL

Create a PostgreSQL database named `sentinel_db`, or use the helper script after updating its local connection settings:

```powershell
python create_db.py
```

Set `DATABASE_URL` to a SQLAlchemy PostgreSQL connection string. Do not commit credentials:

```powershell
$env:DATABASE_URL = "postgresql+psycopg2://USER:PASSWORD@localhost:5432/sentinel_db"
```

Initialize the application tables:

```powershell
python database.py
```

### 3. Install frontend dependencies

```powershell
cd frontend
npm install
cd ..
```

## Data pipeline

Place source ZIP archives in `data/raw/zips/`, then run the stages in order:

```powershell
python ingest_raw.py
python parse_silver.py
python ml_engine.py
```

The pipeline creates or updates these database layers:

| Layer | Purpose | Main script |
| --- | --- | --- |
| Raw/Bronze | File cataloguing, hashing, routing, and quarantine | `ingest_raw.py` |
| Silver | Structured, versioned tender metadata | `parse_silver.py` |
| Gold | Anomaly scores and SHAP explanations | `ml_engine.py` |

The ML engine uses these features:

- `short_bid_submission_window_days`
- `rate_deviation_pct`
- `boq_unbalanced_bidding_index`
- `standard_bitumen_spec_ratio`

The last three are deterministic synthetic feature values generated with seed `42` until source-level procurement data is available.

## Run the application

Start the FastAPI service from the project root:

```powershell
uvicorn main:app --reload --host 127.0.0.1 --port 8000
```

The API is available at <http://localhost:8000>. Interactive API documentation is available at <http://localhost:8000/docs>.

In a second terminal, start the dashboard:

```powershell
cd frontend
npm run dev
```

Open the Vite URL shown in the terminal, normally <http://localhost:5173>.

### API endpoints

| Method | Endpoint | Purpose |
| --- | --- | --- |
| `GET` | `/api/summary` | Dashboard-level triage metrics |
| `GET` | `/api/tenders` | Ranked tender triage queue |
| `GET` | `/api/tenders/{tender_id}` | Tender details and SHAP waterfall |
| `POST` | `/api/tenders/{tender_id}/audit` | Record a human audit action |

## Frontend commands

Run these from `frontend/`:

```powershell
npm run dev      # Start the development server
npm run build    # Type-check and create a production build
npm run lint     # Run Oxlint
npm run preview  # Preview the production build
```

## Project layout

```text
.
├── data/              # Raw, Bronze, Silver, and local pipeline data
├── frontend/          # React + Vite dashboard
├── create_db.py       # Creates the PostgreSQL database
├── database.py        # SQLAlchemy engine and table initialization
├── ingest_raw.py      # ZIP ingestion and Bronze routing
├── parse_silver.py    # PDF parsing and Silver loading
├── ml_engine.py       # Gold feature engineering and ML scoring
├── models.py          # Shared SQLAlchemy models
├── main.py            # FastAPI application
└── requirements.txt   # Python dependencies
```

## Configuration and security

- Keep `DATABASE_URL` and all database passwords in environment variables or a local, untracked configuration file.
- Review the default CORS origins in `main.py` before deploying beyond local development.
- Do not treat model output as a final procurement decision; every flagged record requires qualified human review.

## License

No license has been specified yet. Add a license before distributing or reusing this project.
