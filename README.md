# Ajaia Docs — Collaborative Document Editor

A lightweight, production-grade collaborative document editor inspired by Google Docs, built for the **Ajaia AI-Native Full Stack Product Engineer** evaluation.

![Ajaia Docs Banner](https://img.shields.io/badge/Architecture-FastAPI%20%2B%20PostgreSQL%20%2B%20MinIO%20%2B%20Bootstrap-blue)
![Tests](https://img.shields.io/badge/Tests-Pytest%20100%25%20Passing-brightgreen)
![Docker](https://img.shields.io/badge/Deploy-Docker%20Compose-2496ED)

---

## 🌟 Key Capabilities

1. **Rich-Text Document Editing:**
   - Powered by Quill.js with custom Google Docs styling.
   - Formatting: **Bold**, *Italic*, <u>Underline</u>, Strikethrough, Headings (H1, H2, H3), Bulleted Lists, Numbered Lists, Blockquotes, and Code blocks.
   - Debounced autosave (800ms) with visual status indicator (`Saving...` / `Saved`).
   - Dynamic document title renaming directly in the navigation bar.

2. **File Ingestion with MinIO S3 Storage:**
   - Drag & drop or upload `.md` (Markdown) and `.txt` (Plain text) files.
   - Raw uploaded files are preserved in **MinIO S3 Object Storage** (`ajaia-documents` bucket).
   - Ingested files are automatically parsed into the document's rich HTML AST for immediate editing.
   - Download the original file anytime from the editor view.

3. **Role-Based Sharing Model & Persona Switcher:**
   - Multi-tenant isolation: Clear UI separation between **"My Documents"** (owned) and **"Shared with Me"** (collaborative).
   - One-click **Persona Switcher** in the top navbar:
     - 👤 **Alice Johnson** (`alice@ajaia.test` — Owner persona)
     - 👤 **Bob Smith** (`bob@ajaia.test` — Collaborator / Reviewer persona)
   - Granular permission levels: **Editor** (read/write) vs. **Viewer** (read-only enforcement).
   - Instant permission revocation by document owner.

4. **Persistence & Relational Integrity:**
   - Backed by **PostgreSQL 16** with foreign key constraints, cascade deletes, and relational integrity.
   - Persistent Docker volume guarantees data survives container restarts.

5. **API Contract & Versioning:**
   - Strict versioning under `/api/v1/...`.
   - Automatic interactive Swagger API documentation at `http://localhost:8000/docs`.

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

That's it! All 3 containers will automatically boot and perform healthchecks:
- **Web App & Editor:** [http://localhost:5588](http://localhost:5588) *(Configurable via `PORT` env var, defaults to 5588)*
- **Interactive Swagger Docs:** [http://localhost:5588/docs](http://localhost:5588/docs)
- **MinIO S3 Console:** [http://localhost:9001](http://localhost:9001) *(User: `minioadmin`, Pass: `minioadminpassword`)*

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
uvicorn backend.main:app --reload --port 8000
```
Open [http://localhost:8000](http://localhost:8000) in your browser.

---

## 🧪 Running Automated Tests

A comprehensive Pytest test suite verifies access boundaries, sharing permissions, and file ingestion:

```bash
source .venv/bin/activate
pytest backend/tests/test_api.py -v
```

### Test Suite Coverage:
- `test_seeded_personas`: Verifies test personas (Alice & Bob) are initialized.
- `test_create_document`: Validates document instantiation and owner assignment.
- `test_document_access_isolation_forbidden`: Asserts Bob receives `403 Forbidden` on Alice's private unshared doc.
- `test_sharing_workflow_grants_access`: Verifies sharing grants read/write permissions and updates partitioned lists.
- `test_read_only_viewer_cannot_edit`: Asserts `403 Forbidden` when a viewer attempts document edits.
- `test_file_upload_markdown_conversion`: Tests `.md` parsing into rich HTML AST and MinIO persistence.
- `test_delete_access_control`: Asserts only the document owner can delete documents.

---

## 🧭 Reviewer Guide: Testing the 4 Core Flows

1. **Test Editing & Autosave:**
   - Logged in as **Alice Johnson** (default).
   - Click **"New Document"**.
   - Edit the title to *"Q4 Strategy Brief"*.
   - Add rich text: Heading 1, bold text, bullet list.
   - Notice the badge changes from `Saving...` to `Saved`. Refresh the browser—your content is preserved!

2. **Test File Upload (.md / .txt):**
   - Return to dashboard and click **"Import (.md, .txt)"** or drag-and-drop a markdown file.
   - The file is saved to MinIO object storage and converted into a rich-text document ready to edit.

3. **Test Sharing & Permissions:**
   - In your new document, click the blue **"Share"** button.
   - Select `bob@ajaia.test` with permission **"Editor"** and click **Invite**.
   - Switch personas: In the top-right navbar dropdown, switch to **Bob Smith**.
   - Under **"Shared with Me"**, the document appears immediately!
   - Open it as Bob and make an edit.
   - Switch back to Alice: The updates are reflected.

4. **Test Access Control (403 Isolation):**
   - As Alice, create a document *"Alice Private Notes"* and do **not** share it.
   - Switch to Bob. Notice the document is nowhere in Bob's dashboard.
   - If Bob attempts to query the document ID directly via API, the system rejects it with `403 Forbidden`.

---

## 📂 Project Architecture

```
Ajaia/
├── docker-compose.yml       # Orchestrates Web, PostgreSQL, and MinIO
├── Dockerfile               # Python 3.11-slim container
├── requirements.txt         # Pinned production dependencies
├── .env.example             # Configuration template
├── backend/
│   ├── main.py              # FastAPI application, /api/v1 routes & static mounting
│   ├── models.py            # SQLAlchemy relational models (User, Document, DocumentShare)
│   ├── database.py          # PostgreSQL/SQLite connection & auto-seeding
│   ├── schemas.py           # Pydantic v2 schemas
│   ├── storage.py           # MinIO S3 object storage driver
│   └── tests/
│       └── test_api.py      # Automated Pytest test suite
├── frontend/
│   ├── templates/
│   │   └── index.html       # Single-page UI with Bootstrap 5.3 & Quill.js
│   └── static/
│       ├── css/style.css    # Google Docs paper canvas & layout styles
│       └── js/app.js        # Autosave, Quill controller & API communications
├── docs/
│   └── audit.md             # Formal System Architecture & Resource Audit
├── ARCHITECTURE.md          # Architectural decisions & scope tradeoff notes
├── AI_WORKFLOW.md           # AI tooling reflection note
└── SUBMISSION.md            # Deliverable index & walkthrough video outline
```
