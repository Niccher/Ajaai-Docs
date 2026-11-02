# Ajaia LLC — Candidate Assessment Submission

**Candidate:** Dominic Chege Mbae  
**Email:** `dcmbae@gmail.com`  
**Phone:** `+254 727 614 575`  
**Role:** AI-Native Full Stack Product Engineer  
**Date:** November 2026  

---

## 1. Submission Links & Deliverables

- **Google Drive Folder:** `[PASTE GOOGLE DRIVE FOLDER LINK HERE]`  
  *(Contains: full source archive `.zip`, MP4 walkthrough video, database schema export, and documentation artifacts)*
- **Live Deployment URL:** `http://<GCP_EXTERNAL_IP>`  
  *(Deployed on Google Cloud Compute Engine instance via Docker Compose / `scripts/deploy.sh` on standard HTTP port 80)*
- **Interactive API Documentation:** `http://<GCP_EXTERNAL_IP>/docs`  
  *(Features built-in Swagger "Authorize" button to test with `alice@ajaia.test` or `bob@ajaia.test`)*
- **MinIO Object Storage Console:** `http://<GCP_EXTERNAL_IP>:9001`  
  - **Console Username:** `minioadmin`  
  - **Console Password:** `minioadminpassword`
- **Walkthrough Video Link:** `[PASTE UNLISTED LOOM / YOUTUBE LINK HERE]` *(Duration: ~3:30)*

---

## 2. Reviewer Credentials & Test Accounts (No Sign-up Required)

Reviewers can switch between personas in 1 click using the top-right navbar dropdown:
1. **Alice Johnson (Owner Persona):** `alice@ajaia.test`
2. **Bob Smith (Collaborator Persona):** `bob@ajaia.test`

*Note on Local Security Trade-offs:* Ports 5432 (Postgres) and 9000/9001 (MinIO S3) are mapped to the host intentionally to facilitate reviewer inspection with TablePlus, DBeaver, or MinIO Web Console. Requests require the `X-User-Email` header (injected automatically by the UI or via the Swagger Authorize button), returning `401 Unauthorized` if omitted or unrecognized.

---

## 3. How to Run Locally (Quick Start)

Full details are documented in [README.md](README.md).

### Option A: One-Click Production Deployment Pipeline (Recommended)
```bash
chmod +x scripts/deploy.sh
./scripts/deploy.sh
```
*This executes 10 automated steps: Docker environment check, network provisioning, container builds, database migration (`alembic upgrade head`), MinIO bucket verification, multi-container healthchecks, and runs the 29 automated Pytest cases.*

### Option B: Docker Compose
```bash
docker compose up -d --build
```
Access the application at `http://localhost` (or `http://localhost:8000` if `PORT=8000`).

---

## 4. Core Feature Status

### What is Working End-to-End:
1. **Document Creation & Rich-Text Editing:**
   - Full rich-text support: Bold, Italic, Underline, Strikethrough, Headings (H1/H2/H3), Bulleted & Numbered lists, Blockquotes, Code blocks.
   - Real-time inline document renaming.
   - Debounced autosave (800ms) with visual status feedback and race-condition prevention (`flushPendingSave()` on view/persona transitions and `beforeunload`).
   - Persistent across browser refresh and container restarts.
2. **File Ingestion with MinIO S3 Object Storage & Batch Uploads:**
   - Drag-and-drop and multi-file input for `.md` and `.txt` files up to 20 MB per batch.
   - Atomic rollback: If any file in a batch is invalid or fails, none are committed.
   - Raw uploaded files are preserved in MinIO S3 bucket (`ajaia-documents`).
   - Content is parsed directly into rich-text HTML for immediate editing.
   - Ability to download the original uploaded file from the editor header.
3. **Multi-User Sharing & Strict Access Control:**
   - Document owner can invite other users by email with **Editor** or **Viewer** roles.
   - Owner can revoke access at any time.
   - Strict `403 Forbidden` enforcement when uninvited users attempt to access private documents.
   - Dashboard separates documents into **"My Documents"** and **"Shared with Me"**.
4. **Document Export (Markdown, TXT, HTML):**
   - Direct export endpoints (`/api/v1/documents/{id}/export?format=markdown|text|html`) with sanitized conversion.
5. **Security Hardening & Quality Engineering:**
   - XSS defense via Mozilla/Rust `nh3` HTML sanitizer with strict tag/attribute allowlist and link protocol neutralizing.
   - HTTP security headers middleware (`CSP`, `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy`).
   - Subresource Integrity (SRI) SHA-384 hashes on CDN scripts and stylesheets.
   - Multi-stage Dockerfile running as non-root `appuser` (UID 1001) with integrated `HEALTHCHECK`.
   - 29/29 passing tests with 100% pass rate.
6. **Single-Command Docker Orchestration:**
   - `docker compose up -d --build` provisions FastAPI, PostgreSQL 16, and MinIO with automated bucket creation and healthchecks.

### What is Incomplete / Intentionally Deprioritized:
- **Real-Time Multi-Cursor Collaboration (Yjs/CRDTs):** Intentionally cut to eliminate concurrency race conditions and ensure rock-solid persistence within the 4-6 hour constraint.
- **Third-Party OAuth:** Replaced with an instant top-bar persona switcher to save reviewers login friction.

### What I Would Build Next (With 2–4 Additional Hours):
1. **Document Version Snapshots:** Allowing users to view and restore past revisions.
2. **Export to PDF:** While Markdown, Plain Text, and HTML export are now complete, headless PDF generation via Weasyprint would provide formatted printable documents.
3. **Inline Comments & Threaded Discussions:** Highlighting text selections and attaching collaborative comment threads.

---

## 5. Optional Stretch Achievements

The assessment rubric identified optional stretch goals if core functionality was completed early. Two were built and verified:
1. **Export to Markdown, Plain Text, and HTML:**
   - Built with backend AST converters (`backend/converters.py`), stripping markup for plain text and reconstructing clean GitHub-flavored Markdown.
   - Exposed directly in the editor header UI export dropdown and tested in `test_export_markdown_conversion` and `test_export_text_conversion`.
2. **Role-Based Sharing Permissions Beyond Basic Access:**
   - Differentiates between **Editor** (read/write) and **Viewer** (strictly read-only).
   - In the frontend, selecting Viewer freezes the Quill editor into read-only mode, hides formatting toolbars, and suppresses autosave.
   - In the backend, any write/update request from a Viewer is rejected with `403 Forbidden` (`test_read_only_viewer_cannot_edit`).
   - Owner-only protections prevent non-owners from deleting documents (`test_editor_cannot_delete`) or sharing documents with themselves (`test_cannot_share_with_self`).

---

## 6. Walkthrough Video Outline

- **Video Link:** [Paste your unlisted Loom / YouTube link here]
- **Duration:** ~3 minutes 30 seconds
- **Script / Flow Covered in Video:**
  1. **Core Editing (0:00 - 1:00):** Show document creation, rich text formatting, inline renaming, and debounced autosave.
  2. **File Ingestion & Export (1:00 - 1:45):** Drag-and-drop Markdown/Text files, show raw storage in MinIO console (:9001), and demonstrate export to `.md`.
  3. **Collaboration & Permission Isolation (1:45 - 2:45):** Share document with Bob as Viewer. Switch to Bob persona using navbar toggle. Show read-only enforcement and 403 prevention. Switch back to Alice and revoke.
  4. **Engineering & Architecture (2:45 - 3:30):** Highlight 29 passing Pytest tests, multi-stage Docker build, Rust `nh3` XSS sanitization, and Alembic migrations.
