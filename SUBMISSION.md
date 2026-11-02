# Ajaia LLC — Candidate Assessment Submission

**Candidate:** Dominic Chege Mbae  
**Email:** `dcmbae@gmail.com`  
**Phone:** `+254 727 614 575`  
**Role:** AI-Native Full Stack Product Engineer  
**Date:** November 2026  

---

## 1. Submission Overview & Deliverables Checklist

This package contains everything required for evaluating the collaborative document editor:

- [x] **Source Code:** Complete, clean full-stack application (FastAPI + PostgreSQL + MinIO + Bootstrap/Quill).
- [x] **README.md:** Clear setup and local run instructions for both `scripts/deploy.sh`, Docker Compose, and Python venv.
- [x] **ARCHITECTURE.md:** Short architecture note explaining core prioritizations, tradeoffs, and system design.
- [x] **AI_WORKFLOW.md:** Detailed AI usage breakdown, material accelerations, rejected outputs, and verification methods.
- [x] **docs/audit.md:** Formal system architecture, resource footprint, and failure mode audit.
- [x] **One-Click Deployment Pipeline (`scripts/deploy.sh`):** Automated pre-flight checks, container health verification, migrations, and test runner.
- [x] **Database Migrations:** Official Alembic environment (`alembic/`) with versioned schema tracking.
- [x] **Automated Tests:** 11 passing Pytest test cases (100% pass rate) covering CRUD, permissions (403), sharing, batch file uploads, 20 MB ceiling, Markdown export, and XSS sanitization.
- [x] **Walkthrough Video Outline:** Script and link placeholder for the 3-5 minute unlisted walkthrough video.

---

## 2. Live Deployment & Reviewer Credentials

- **Live Product URL:** `http://<GCP_EXTERNAL_IP>:5588` *(Deployed on Google Cloud Compute Engine instance via Docker Compose / `scripts/deploy.sh`)*
- **Interactive API Documentation:** `http://<GCP_EXTERNAL_IP>:5588/docs`
- **MinIO Object Storage Console:** `http://<GCP_EXTERNAL_IP>:9001`
  - **Console Username:** `minioadmin`
  - **Console Password:** `minioadminpassword`

### Test Accounts & Personas (No sign-up required)
Reviewers can switch between personas in 1 click using the top-right navbar dropdown:
1. **Alice Johnson (Owner Persona):** `alice@ajaia.test`
2. **Bob Smith (Collaborator Persona):** `bob@ajaia.test`

---

## 3. Core Feature Status

### What is Working End-to-End:
1. **Document Creation & Rich-Text Editing:**
   - Full rich-text support: Bold, Italic, Underline, Strikethrough, Headings (H1/H2/H3), Bulleted & Numbered lists, Blockquotes, Code blocks.
   - Real-time inline document renaming.
   - Debounced autosave (800ms) with visual status feedback.
   - Persistent across browser refresh and container restarts.
2. **File Ingestion with MinIO S3 Object Storage:**
   - Drag-and-drop and file input for `.md` and `.txt` files.
   - Raw uploaded files are preserved in MinIO S3 bucket (`ajaia-documents`).
   - Content is parsed directly into rich-text HTML for immediate editing.
   - Ability to download the original uploaded file from the editor header.
3. **Multi-User Sharing & Strict Access Control:**
   - Document owner can invite other users by email with **Editor** or **Viewer** roles.
   - Owner can revoke access at any time.
   - Strict `403 Forbidden` enforcement when uninvited users attempt to access private documents.
   - Dashboard separates documents into **"My Documents"** and **"Shared with Me"**.
4. **Single-Command Docker Orchestration:**
   - `docker compose up -d --build` provisions FastAPI, PostgreSQL 16, and MinIO with automated bucket creation and healthchecks.

### What is Incomplete / Intentionally Deprioritized:
- **Real-Time Multi-Cursor Collaboration (Yjs/CRDTs):** Intentionally cut to eliminate concurrency race conditions and ensure rock-solid persistence within the 4-hour timebox.
- **Third-Party OAuth:** Replaced with an instant top-bar persona switcher to save reviewers login friction.

### What I Would Build Next (With 2–4 Additional Hours):
1. **Document Version Snapshots:** Allowing users to view and restore past revisions.
2. **Export to PDF & Markdown:** Headless export service to download finished documents.
3. **Inline Comments & Threaded Discussions:** Highlighting text selections and attaching collaborative comment threads.

---

## 4. Walkthrough Video URL

- **Video Link:** [Paste your unlisted Loom / YouTube link here]
- **Duration:** ~3 minutes 30 seconds
- **Covered in Video:**
  1. Main document editing, rich-text formatting, and debounced autosave.
  2. Drag-and-drop file upload with MinIO S3 persistence.
  3. Sharing with Bob and switching personas to demonstrate permission isolation.
  4. Architecture decisions, deliberate scope cuts, and AI workflow reflection.
