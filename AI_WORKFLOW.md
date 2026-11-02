# AI-Native Workflow Note

**Candidate:** Dominic Chege Mbae (`dcmbae@gmail.com`)  
**Role:** AI-Native Full Stack Product Engineer  
**Date:** November 2026  

---

## 1. AI Tooling Employed

During this sprint, I utilized an integrated AI-native stack:
- **Google Antigravity & LLM Copilot (Gemini / Claude Engine):** Used as an intelligent pair programmer for rapid scaffolding, schema drafting, and test generation.
- **AI Shell & Code Generation:** Employed for generating repetitive boilerplate (SQLAlchemy models, Pydantic schemas, and Docker Compose definitions).

---

## 2. Where AI Materially Accelerated Delivery

AI was leveraged as a force multiplier in high-friction, repetitive areas:

1. **Test Suite Generation (Pytest):**
   - AI generated edge-case matrix scenarios: verifying that unshared documents return `403 Forbidden`, testing permission role escalation, and mocking MinIO client methods during isolated unit testing.
   - **Time Saved:** ~45 minutes.

2. **Quill.js Toolbar & Custom CSS Configuration:**
   - Rapidly generating the HTML toolbar configuration, custom icon bindings, and Google Docs "paper sheet" CSS styling with proper box-shadows and container constraints.
   - **Time Saved:** ~30 minutes.

3. **Docker Compose & MinIO Orchestration:**
   - Drafting multi-container healthcheck definitions (`pg_isready` for Postgres and `curl -f /minio/health/live` for MinIO) to prevent cold-start race conditions.
   - **Time Saved:** ~20 minutes.

---

## 3. What AI-Generated Output Was Changed or Rejected

Product judgment was strictly applied to filter hallucinated, fragile, or over-engineered suggestions:

1. **Rejected: Client-Side Regex Parsing for Markdown:**
   - The AI initially suggested parsing Markdown using a custom 40-line regular expression function in JavaScript.
   - **Reason for Rejection:** Fragile edge cases (nested lists, bold headers, and blockquotes break easily with regex).
   - **Correction:** Replaced with Python's mature `markdown` library on the backend with standard AST extensions (`extra`, `nl2br`, `sane_lists`), guaranteeing robust conversion.

2. **Rejected: Premature WebSockets & Socket.IO Mock Boilerplate:**
   - The AI attempted to introduce a complex WebSockets channel for "live simulated typing."
   - **Reason for Rejection:** A 4-hour assessment cannot afford ghost cursor synchronization bugs and race conditions.
   - **Correction:** Enforced a clean, debounced autosave architecture (800ms) with explicit visual save states (`Saving...` / `Saved`), which is reliable and deterministic.

3. **Audited & Modified: Database Cascade & Deletion Semantics:**
   - The initial AI-generated schema omitted `ondelete="CASCADE"` on `DocumentShare` and `Document` foreign keys, which would cause foreign key violation crashes if an owner deleted a document that had active shares.
   - **Correction:** Manually enforced `ondelete="CASCADE"` across all relational models.

---

## 4. Verification, Reliability, & Engineering Quality

To ensure AI suggestions did not compromise system reliability:

1. **Automated Unit Testing:**
   - Every single backend endpoint is backed by an automated test in `backend/tests/test_api.py`.
   - Tests assert not just 200 OK responses, but negative security boundaries (403 Forbidden on unshared docs, 403 on viewer edit attempts).

2. **Dual-Write Rollback Verification:**
   - Verified that if a database transaction fails after uploading an object to MinIO, a compensating `delete_file` call prevents orphaned storage bloat.

3. **Cross-Persona UI Verification:**
   - Manually tested user transitions between **Alice** (Owner) and **Bob** (Collaborator) in Chrome to verify that permissions immediately switch between read-write and read-only.
