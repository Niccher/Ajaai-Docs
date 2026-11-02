# Ajaia Docs — Collaborative Document Editor

A lightweight, production-grade collaborative document editor inspired by Google Docs, built for the **Ajaia AI-Native Full Stack Product Engineer** evaluation.

![Ajaia Docs Banner](https://img.shields.io/badge/Architecture-FastAPI%20%2B%20PostgreSQL%20%2B%20MinIO%20%2B%20Bootstrap-blue)
![Tests](https://img.shields.io/badge/Tests-29%2F29%20Pytest%20Passing-brightgreen)
![Security](https://img.shields.io/badge/Security-Rust%20nh3%20%2B%20CSP%20%2B%20RBAC-success)
![Docker](https://img.shields.io/badge/Deploy-Docker%20Compose-2496ED)

---

## 🌟 Key Capabilities

1. **Rich-Text Document Editing:**
   - Powered by Quill.js with Google Docs-inspired clean paper canvas styling.
   - Formatting: **Bold**, *Italic*, <u>Underline</u>, Strikethrough, Headings (H1, H2, H3), Bulleted Lists, Numbered Lists, Blockquotes, and Code blocks.
   - Debounced autosave (800ms) with visual status indicator (`Saving...` / `Saved`).
   - Race-condition hardened: `saveQueued` lock flag serializes concurrent in-flight updates, and `flushPendingSave()` guarantees no data loss when switching views or personas.
   - Inline document title renaming directly in the navigation bar with 255-character length validation.

2. **File Ingestion with MinIO S3 Object Storage:**
   - Drag & drop or batch upload `.md` (Markdown) and `.txt` (Plain text) files up to **20MB per file**.
   - **Atomic Batch Validation:** Pre-validates file types and sizes across the entire batch before writing to MinIO or PostgreSQL.
   - Raw uploaded files are preserved in **MinIO S3 Object Storage** (`ajaia-documents` bucket).
   - Ingested files are automatically parsed into editable HTML for immediate rich-text modification.
   - Download the original raw file directly from MinIO or export as Markdown (`.md`), Plain Text (`.txt`), or HTML (`.html`).

3. **Role-Based Sharing Model & Persona Switcher:**
   - Multi-tenant isolation: Clear UI separation between **"My Documents"** (owned) and **"Shared with Me"** (collaborative).
   - One-click **Persona Switcher** in the top navbar:
     - 👤 **Alice Johnson** (`alice@ajaia.test` — Owner persona)
     - 👤 **Bob Smith** (`bob@ajaia.test` — Collaborator / Reviewer persona)
   - Granular permission levels: **Editor** (read/write) vs. **Viewer** (read-only enforcement in both backend API and Quill UI).
   - Instant permission revocation by document owner.

4. **Hardened Security & Modular Architecture:**
   - **HTML Sanitization:** Mozilla/Rust-backed `nh3` allowlist sanitizer strips `<script>`, inline event handlers (`onclick`, `onerror`), and `javascript:` URIs.
   - **Defense-in-Depth HTTP Headers:** Injects `Content-Security-Policy`, `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, and `Referrer-Policy: strict-origin-when-cross-origin`.
   - **Alembic Database Migrations:** Programmatic Alembic migrations execute automatically on startup before seeding.

5. **API Contract & Interactive Swagger Authentication:**
   - Versioned API under `/api/v1/...`.
   - Swagger OpenAPI UI at `http://localhost:5588/docs` featuring the green **Authorize** button powered by `APIKeyHeader(name="X-User-Email")`.
   - Strict `401 Unauthorized` responses on missing or unseeded personas.

---

## 🚀 Quickstart via Docker Compose (Recommended)

The easiest way to run the entire stack (FastAPI web app, PostgreSQL database, and MinIO object storage):

```bash
# 1. Clone the repository
git clone <repo-url>
cd Ajaia

# 2. Run the automated one-click deployment pipeline (or docker compose up -d --build)
bash scripts/deploy.sh
```

That's it! All 3 containers automatically boot, verify dependencies, run migrations, seed data, and execute preflight checks:
- **Web App & Editor:** [http://localhost:5588](http://localhost:5588) *(Configurable via `PORT` env var, defaults to 5588)*
- **Interactive Swagger Docs:** [http://localhost:5588/docs](http://localhost:5588/docs)
- **Service Healthcheck:** [http://localhost:5588/api/v1/health](http://localhost:5588/api/v1/health)
- **MinIO S3 Console:** [http://localhost:9001](http://localhost:9001) *(User: `minioadmin`, Pass: `minioadminpassword`)*

---

## 🔐 Swagger UI & API Authentication

When testing the interactive Swagger documentation at [http://localhost:5588/docs](http://localhost:5588/docs):

1. Click the green **Authorize** button at the top-right.
2. In the `Value` field for **APIKeyHeader (apiKey)**, enter one of the test personas:
   - `alice@ajaia.test`
   - `bob@ajaia.test`
3. Click **Authorize**, then **Close**.
4. You can now execute any endpoint (e.g., `POST /api/v1/documents`, `POST /api/v1/documents/upload`, `GET /api/v1/documents`) directly from Swagger UI!
5. Requests without an authorized header return `401 Unauthorized`.

---

## 💻 Alternative: Running Locally without Docker

If you prefer running directly in Python:

```bash
# 1. Create and activate a virtual environment
python3 -m venv .venv
source .venv/bin/activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. Set SQLite fallback (or point to local Postgres)
export DATABASE_URL="sqlite:///./ajaia_docs.db"

# 4. Start the server
uvicorn backend.main:app --reload --port 5588
```
Open [http://localhost:5588](http://localhost:5588) in your browser.

---

## 🧪 Running Automated Tests

A comprehensive suite of **29 automated tests** verifies access boundaries, sharing permissions, XSS sanitization, atomic upload rollbacks, and exports:

```bash
source .venv/bin/activate
pytest backend/tests/test_api.py -v
```

### Test Suite Summary (29/29 Passing):
- **Authentication:** Seeded personas, 401 on missing `X-User-Email`, 401 on unknown personas, `GET /api/v1/users/me`.
- **Validation:** 255-character title limit, empty title rejection, 404 on missing documents.
- **RBAC & Sharing:** 403 isolation on unshared documents, collaborative read/write grants, read-only viewer modification blocks, non-owner delete restrictions, owner delete rights, self-share prevention, invalid email rejection, share revocation.
- **Security & XSS:** Script tag stripping, event handler neutralization, `javascript:` protocol elimination, defense-in-depth security headers, and OpenAPI security scheme presence.
- **Uploads & Exports:** Markdown conversion, plain text ingestion, 400 on unsupported extensions, 413 on oversized files (>20MB), multi-file batch uploads, atomic batch validation rollback on error, Markdown export with list preservation, Plain text export, and MinIO raw download.

---

## ⚠️ Known Security Limitations & Local Dev Trade-offs

This project is tailored for a rapid, friction-free take-home evaluation. The following architectural decisions were intentional for local assessment:

1. **Exposed Local Ports (5432 & 9000/9001):**
   - *Local Rationale:* PostgreSQL (`5432`) and MinIO Console (`9001`) are bound to `0.0.0.0` so reviewers can directly inspect database tables (via TablePlus/DBeaver) and S3 buckets (via browser).
   - *Production Hardening:* In production, database and object storage ports are placed exclusively on an internal private Docker bridge network (`internal: true`) and never exposed to the host network.
2. **Default Credentials in Docker Compose:**
   - *Local Rationale:* Default credentials (`postgrespassword`, `minioadminpassword`) are provided in `.env.example` and `docker-compose.yml` to allow zero-config execution.
   - *Production Hardening:* Use an external secrets manager (AWS Secrets Manager, HashiCorp Vault, or Kubernetes Secrets) with rotation policies.
3. **Persona-Based Authentication (`X-User-Email`):**
   - *Local Rationale:* High-leverage 1-click persona switcher avoids the UX friction of full password-login screens or external OAuth setup during a timed review.
   - *Production Hardening:* Replace `X-User-Email` with signed JWTs (RS256) issued via an OpenID Connect (OIDC) provider (Auth0, Okta, Google OAuth) with HTTP-only, Secure cookies and CSRF tokens.

---

## 📂 Project Architecture

```
Ajaia/
├── docker-compose.yml       # Orchestrates Web (5588), PostgreSQL 16 (5432), and MinIO (9000/9001)
├── Dockerfile               # Python 3.11-slim container with multi-stage layer caching
├── requirements.txt         # Pinned production dependencies (FastAPI, SQLAlchemy, nh3, MinIO)
├── requirements-dev.txt     # Test dependencies (pytest, httpx)
├── alembic.ini              # Alembic database migration configuration
├── alembic/                 # Schema migration versions
│   └── versions/
│       └── 001_initial_schema.py
├── backend/
│   ├── main.py              # Modular FastAPI endpoints, batch upload, and static routes
│   ├── security.py          # Rust-backed nh3 sanitizer & SecurityHeadersMiddleware
│   ├── converters.py        # HTML-to-Markdown, HTML-to-Text, and File-to-HTML transformers
│   ├── deps.py              # APIKeyHeader, get_current_user, and RBAC authorization helpers
│   ├── models.py            # SQLAlchemy relational models (User, Document, DocumentShare)
│   ├── database.py          # Connection pool, Alembic auto-upgrade, and persona seeding
│   ├── schemas.py           # Pydantic v2 schemas with title limits & email validation
│   ├── storage.py           # MinIO S3 object storage driver
│   └── tests/
│       ├── conftest.py      # Shared test fixtures & MinIO mock storage
│       └── test_api.py      # 29 automated Pytest test cases
├── frontend/
│   ├── templates/
│   │   └── index.html       # Single-page UI with Bootstrap 5.3, Quill.js & SRI hashes
│   └── static/
│       ├── css/style.css    # Google Docs paper canvas & layout styling
│       └── js/app.js        # Autosave, flushPendingSave, saveQueued lock & API communications
├── scripts/
│   └── deploy.sh            # One-click 10-step automated build and preflight deployment script
├── docs/
│   └── audit.md             # Formal System Architecture & Resource Audit
├── ARCHITECTURE.md          # Architectural decisions & scope tradeoff notes
├── AI_WORKFLOW.md           # AI tooling reflection note
└── SUBMISSION.md            # Deliverable index & walkthrough video outline
```
