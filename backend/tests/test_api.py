"""
Comprehensive automated test suite for Ajaia Collaborative Document Editor.
Validates authentication, authorization, sharing RBAC, XSS sanitization,
atomic batch uploads, exports, OpenAPI schemas, and security headers.
"""

import io
import pytest


# ==============================================================================
# 1. AUTHENTICATION & PERSONA TESTS
# ==============================================================================

def test_seeded_personas(client):
    """Verify default test personas (Alice & Bob) are seeded and retrievable."""
    res = client.get("/api/v1/users")
    assert res.status_code == 200
    users = res.json()
    emails = [u["email"] for u in users]
    assert "alice@ajaia.test" in emails
    assert "bob@ajaia.test" in emails


def test_unauthenticated_request_rejected_401(client):
    """Verify that requests missing X-User-Email header are rejected with 401 Unauthorized."""
    res = client.get("/api/v1/documents")
    assert res.status_code == 401
    assert "Missing required X-User-Email" in res.json()["detail"]


def test_unknown_persona_rejected_401(client):
    """Verify that an unregistered persona email is rejected with 401 Unauthorized."""
    headers = {"X-User-Email": "intruder@external.io"}
    res = client.get("/api/v1/documents", headers=headers)
    assert res.status_code == 401
    assert "intruder@external.io" in res.json()["detail"]


def test_get_current_user_me(client):
    """Verify that GET /api/v1/users/me returns the active authenticated persona."""
    headers = {"X-User-Email": "alice@ajaia.test"}
    res = client.get("/api/v1/users/me", headers=headers)
    assert res.status_code == 200
    data = res.json()
    assert data["email"] == "alice@ajaia.test"
    assert data["name"] == "Alice Johnson"


# ==============================================================================
# 2. DOCUMENT CREATION & VALIDATION TESTS
# ==============================================================================

def test_create_document_success(client):
    """Verify document creation assigned to active persona with owner permission."""
    headers = {"X-User-Email": "alice@ajaia.test"}
    payload = {
        "title": "Quarterly Product Strategy",
        "content_html": "<p>Focus on high-leverage outcomes.</p>",
    }
    res = client.post("/api/v1/documents", json=payload, headers=headers)
    assert res.status_code == 201
    data = res.json()
    assert data["title"] == "Quarterly Product Strategy"
    assert data["owner_email"] == "alice@ajaia.test"
    assert data["permission"] == "owner"


def test_create_document_title_too_long(client):
    """Verify that title exceeding 255 characters is rejected with 422 Unprocessable Entity."""
    headers = {"X-User-Email": "alice@ajaia.test"}
    payload = {
        "title": "A" * 256,
        "content_html": "<p>Overly long title.</p>",
    }
    res = client.post("/api/v1/documents", json=payload, headers=headers)
    assert res.status_code == 422


def test_create_document_empty_title_validation(client):
    """Verify that empty string title is rejected with 422 Unprocessable Entity."""
    headers = {"X-User-Email": "alice@ajaia.test"}
    payload = {"title": "", "content_html": "<p>Content</p>"}
    res = client.post("/api/v1/documents", json=payload, headers=headers)
    assert res.status_code == 422


def test_get_nonexistent_document_404(client):
    """Verify that querying an unknown document ID yields 404 Not Found."""
    headers = {"X-User-Email": "alice@ajaia.test"}
    res = client.get("/api/v1/documents/nonexistent-uuid-1234", headers=headers)
    assert res.status_code == 404


# ==============================================================================
# 3. ACCESS CONTROL & ROLE-BASED SHARING TESTS
# ==============================================================================

def test_document_access_isolation_forbidden(client):
    """Verify Bob cannot read an unshared document owned by Alice (403 Forbidden)."""
    alice_headers = {"X-User-Email": "alice@ajaia.test"}
    doc_res = client.post(
        "/api/v1/documents",
        json={"title": "Alice Confidential", "content_html": "<p>Secret</p>"},
        headers=alice_headers,
    )
    doc_id = doc_res.json()["id"]

    bob_headers = {"X-User-Email": "bob@ajaia.test"}
    res = client.get(f"/api/v1/documents/{doc_id}", headers=bob_headers)
    assert res.status_code == 403


def test_sharing_workflow_grants_access(client):
    """Verify Alice shares with Bob, who can then read and edit the document."""
    alice_headers = {"X-User-Email": "alice@ajaia.test"}
    create_res = client.post(
        "/api/v1/documents",
        json={"title": "Collaboration Sprint", "content_html": "<p>Draft v1</p>"},
        headers=alice_headers,
    )
    doc_id = create_res.json()["id"]

    # Alice shares with Bob
    share_payload = {"email": "bob@ajaia.test", "permission": "edit"}
    share_res = client.post(f"/api/v1/documents/{doc_id}/shares", json=share_payload, headers=alice_headers)
    assert share_res.status_code == 201
    assert share_res.json()["permission"] == "edit"

    # Bob accesses the document
    bob_headers = {"X-User-Email": "bob@ajaia.test"}
    bob_get_res = client.get(f"/api/v1/documents/{doc_id}", headers=bob_headers)
    assert bob_get_res.status_code == 200
    assert bob_get_res.json()["permission"] == "edit"

    # Bob edits the document
    update_res = client.put(
        f"/api/v1/documents/{doc_id}",
        json={"content_html": "<p>Bob added revisions.</p>"},
        headers=bob_headers,
    )
    assert update_res.status_code == 200
    assert "<p>Bob added revisions.</p>" in update_res.json()["content_html"]


def test_read_only_viewer_cannot_edit(client):
    """Verify that collaborator with 'view' permission cannot modify the document (403 Forbidden)."""
    alice_headers = {"X-User-Email": "alice@ajaia.test"}
    doc = client.post(
        "/api/v1/documents",
        json={"title": "Frozen Spec", "content_html": "<p>Immutable</p>"},
        headers=alice_headers,
    ).json()

    # Share with Bob as 'view'
    client.post(
        f"/api/v1/documents/{doc['id']}/shares",
        json={"email": "bob@ajaia.test", "permission": "view"},
        headers=alice_headers,
    )

    # Bob attempts edit
    bob_headers = {"X-User-Email": "bob@ajaia.test"}
    res = client.put(
        f"/api/v1/documents/{doc['id']}",
        json={"title": "Tampered Spec"},
        headers=bob_headers,
    )
    assert res.status_code == 403
    assert "read-only" in res.json()["detail"].lower()


def test_editor_cannot_delete(client):
    """Verify collaborator with 'edit' permission cannot delete the document (403 Forbidden)."""
    alice_headers = {"X-User-Email": "alice@ajaia.test"}
    doc = client.post(
        "/api/v1/documents",
        json={"title": "Company Policy", "content_html": "<p>Rules</p>"},
        headers=alice_headers,
    ).json()

    client.post(
        f"/api/v1/documents/{doc['id']}/shares",
        json={"email": "bob@ajaia.test", "permission": "edit"},
        headers=alice_headers,
    )

    # Bob attempts delete
    bob_headers = {"X-User-Email": "bob@ajaia.test"}
    res = client.delete(f"/api/v1/documents/{doc['id']}", headers=bob_headers)
    assert res.status_code == 403
    assert "owner" in res.json()["detail"].lower()


def test_owner_can_delete(client):
    """Verify document owner can delete the document (204 No Content)."""
    alice_headers = {"X-User-Email": "alice@ajaia.test"}
    doc = client.post(
        "/api/v1/documents",
        json={"title": "Temporary Scratchpad", "content_html": "<p>Delete me</p>"},
        headers=alice_headers,
    ).json()

    res = client.delete(f"/api/v1/documents/{doc['id']}", headers=alice_headers)
    assert res.status_code == 204

    # Verify gone
    get_res = client.get(f"/api/v1/documents/{doc['id']}", headers=alice_headers)
    assert get_res.status_code == 404


def test_cannot_share_with_self(client):
    """Verify owner cannot share document with themselves (400 Bad Request)."""
    alice_headers = {"X-User-Email": "alice@ajaia.test"}
    doc = client.post(
        "/api/v1/documents",
        json={"title": "Self Share Test", "content_html": "<p>Testing</p>"},
        headers=alice_headers,
    ).json()

    res = client.post(
        f"/api/v1/documents/{doc['id']}/shares",
        json={"email": "alice@ajaia.test", "permission": "view"},
        headers=alice_headers,
    )
    assert res.status_code == 400
    assert "owner" in res.json()["detail"].lower()


def test_share_with_invalid_email(client):
    """Verify that inviting an invalid email address triggers 422 Unprocessable Entity."""
    alice_headers = {"X-User-Email": "alice@ajaia.test"}
    doc = client.post(
        "/api/v1/documents",
        json={"title": "Invalid Share Test", "content_html": "<p>Testing</p>"},
        headers=alice_headers,
    ).json()

    res = client.post(
        f"/api/v1/documents/{doc['id']}/shares",
        json={"email": "not-an-email", "permission": "view"},
        headers=alice_headers,
    )
    assert res.status_code == 422


def test_revoke_share_access(client):
    """Verify owner revokes collaborator access and collaborator is subsequently blocked."""
    alice_headers = {"X-User-Email": "alice@ajaia.test"}
    doc = client.post(
        "/api/v1/documents",
        json={"title": "Revocation Test", "content_html": "<p>Shared</p>"},
        headers=alice_headers,
    ).json()

    # Share with Bob
    share = client.post(
        f"/api/v1/documents/{doc['id']}/shares",
        json={"email": "bob@ajaia.test", "permission": "view"},
        headers=alice_headers,
    ).json()

    # Revoke Bob's access
    del_share = client.delete(f"/api/v1/documents/{doc['id']}/shares/{share['user_id']}", headers=alice_headers)
    assert del_share.status_code == 204

    # Bob attempts read
    bob_headers = {"X-User-Email": "bob@ajaia.test"}
    get_res = client.get(f"/api/v1/documents/{doc['id']}", headers=bob_headers)
    assert get_res.status_code == 403


# ==============================================================================
# 4. SECURITY & XSS SANITIZATION TESTS
# ==============================================================================

def test_xss_script_tag_stripped(client):
    """Verify that script tags and inline event handlers are completely removed by nh3."""
    headers = {"X-User-Email": "alice@ajaia.test"}
    malicious_payload = {
        "title": "XSS Probe",
        "content_html": '<h3>Safe Heading</h3><script>alert("hacked")</script><p onclick="stealCookies()">Text</p>',
    }
    res = client.post("/api/v1/documents", json=malicious_payload, headers=headers)
    assert res.status_code == 201
    sanitized_html = res.json()["content_html"]

    assert "<script" not in sanitized_html
    assert "alert(" not in sanitized_html
    assert "onclick" not in sanitized_html
    assert "Safe Heading" in sanitized_html


def test_xss_javascript_protocol_neutralized(client):
    """Verify that javascript: URI protocols in anchor tags are stripped."""
    headers = {"X-User-Email": "alice@ajaia.test"}
    malicious_payload = {
        "title": "URI Probe",
        "content_html": '<a href="javascript:alert(\'xss\')">Click me</a>',
    }
    res = client.post("/api/v1/documents", json=malicious_payload, headers=headers)
    assert res.status_code == 201
    sanitized_html = res.json()["content_html"]
    assert "javascript:" not in sanitized_html


# ==============================================================================
# 5. ATOMIC FILE UPLOAD & INGESTION TESTS
# ==============================================================================

def test_file_upload_markdown_conversion(client):
    """Verify uploading a Markdown file converts formatting into rich-text HTML."""
    headers = {"X-User-Email": "alice@ajaia.test"}
    md_content = b"# Architecture Design\n\n- Component A\n- Component B\n\n**Important:** Ready for review."
    files = {"files": ("design.md", io.BytesIO(md_content), "text/markdown")}

    res = client.post("/api/v1/documents/upload", files=files, headers=headers)
    assert res.status_code == 201
    doc = res.json()
    assert doc["title"] == "Design"
    assert "<h1>Architecture Design</h1>" in doc["content_html"]
    assert "Component A" in doc["content_html"]
    assert doc["minio_object_key"] is not None


def test_file_upload_unsupported_extension(client):
    """Verify that uploading files with unsupported extensions (.pdf, .exe) is rejected (400)."""
    headers = {"X-User-Email": "alice@ajaia.test"}
    files = {"files": ("document.pdf", io.BytesIO(b"%PDF-1.4"), "application/pdf")}
    res = client.post("/api/v1/documents/upload", files=files, headers=headers)
    assert res.status_code == 400
    assert "unsupported extension" in res.json()["detail"].lower()


def test_file_size_limit_exceeded(client):
    """Verify that files exceeding the 20MB limit return 413 Content Too Large."""
    headers = {"X-User-Email": "alice@ajaia.test"}
    large_payload = b"A" * (20 * 1024 * 1024 + 10)
    files = {"files": ("giant.txt", io.BytesIO(large_payload), "text/plain")}

    res = client.post("/api/v1/documents/upload", files=files, headers=headers)
    assert res.status_code == 413
    assert "exceeds" in res.json()["detail"].lower()


def test_batch_file_upload_success(client):
    """Verify batch upload of multiple files in a single request."""
    headers = {"X-User-Email": "alice@ajaia.test"}
    file1 = ("notes_1.md", io.BytesIO(b"# Notes 1\n\nBody content"), "text/markdown")
    file2 = ("notes_2.txt", io.BytesIO(b"Plain text notes 2"), "text/plain")

    res = client.post(
        "/api/v1/documents/upload",
        files=[("files", file1), ("files", file2)],
        headers=headers,
    )
    assert res.status_code == 201
    docs = res.json()
    assert isinstance(docs, list)
    assert len(docs) == 2
    titles = [d["title"] for d in docs]
    assert "Notes 1" in titles
    assert "Notes 2" in titles


def test_batch_upload_atomic_validation_rollback(client):
    """Verify atomic validation: if second file in batch is invalid, first file is not created."""
    headers = {"X-User-Email": "alice@ajaia.test"}
    file1 = ("valid.md", io.BytesIO(b"# Valid doc"), "text/markdown")
    file2 = ("invalid.exe", io.BytesIO(b"binary"), "application/octet-stream")

    res = client.post(
        "/api/v1/documents/upload",
        files=[("files", file1), ("files", file2)],
        headers=headers,
    )
    assert res.status_code == 400
    assert "unsupported extension" in res.json()["detail"].lower()

    # Confirm valid.md was NOT created in the database
    docs = client.get("/api/v1/documents", headers=headers).json()
    owned_titles = [d["title"] for d in docs["owned"]]
    assert "Valid" not in owned_titles


# ==============================================================================
# 6. EXPORT & DOWNLOAD TESTS
# ==============================================================================

def test_export_markdown_conversion(client):
    """Verify document exports cleanly to Markdown format."""
    headers = {"X-User-Email": "alice@ajaia.test"}
    doc = client.post(
        "/api/v1/documents",
        json={
            "title": "Release Notes",
            "content_html": "<h1>Release v1.2</h1><p>Highlights:</p><ul><li data-list=\"bullet\">Feature A</li></ul>",
        },
        headers=headers,
    ).json()

    res = client.get(f"/api/v1/documents/{doc['id']}/export?format=md", headers=headers)
    assert res.status_code == 200
    assert res.headers["Content-Type"].startswith("text/markdown")
    content = res.content.decode("utf-8")
    assert "# Release v1.2" in content
    assert "- Feature A" in content


def test_export_text_conversion(client):
    """Verify document exports cleanly to plain text format."""
    headers = {"X-User-Email": "alice@ajaia.test"}
    doc = client.post(
        "/api/v1/documents",
        json={"title": "Plain Export", "content_html": "<h2>Title</h2><p>Body line.</p>"},
        headers=headers,
    ).json()

    res = client.get(f"/api/v1/documents/{doc['id']}/export?format=txt", headers=headers)
    assert res.status_code == 200
    assert res.headers["Content-Type"].startswith("text/plain")
    assert "Body line." in res.content.decode("utf-8")


def test_download_raw_native_doc_404(client):
    """Verify downloading raw file for native doc (no attached file) returns 404."""
    headers = {"X-User-Email": "alice@ajaia.test"}
    doc = client.post(
        "/api/v1/documents",
        json={"title": "Native Doc", "content_html": "<p>Native</p>"},
        headers=headers,
    ).json()

    res = client.get(f"/api/v1/documents/{doc['id']}/download-raw", headers=headers)
    assert res.status_code == 404


# ==============================================================================
# 7. HEALTH, SECURITY HEADERS & OPENAPI SPECS
# ==============================================================================

def test_health_check_endpoint(client):
    """Verify health endpoint reports DB, MinIO connectivity and 20MB limit."""
    res = client.get("/api/v1/health")
    assert res.status_code == 200
    data = res.json()
    assert data["database_connected"] is True
    assert data["max_upload_size_mb"] == 20


def test_openapi_security_scheme_present(client):
    """Verify Swagger OpenAPI schema includes X-User-Email securityScheme for Authorize modal."""
    res = client.get("/openapi.json")
    assert res.status_code == 200
    spec = res.json()
    assert "components" in spec
    assert "securitySchemes" in spec["components"]
    assert "APIKeyHeader" in spec["components"]["securitySchemes"]
    scheme = spec["components"]["securitySchemes"]["APIKeyHeader"]
    assert scheme["name"] == "X-User-Email"
    assert scheme["type"] == "apiKey"


def test_security_headers_present(client):
    """Verify response includes defense-in-depth security headers."""
    res = client.get("/api/v1/health")
    assert res.headers.get("X-Content-Type-Options") == "nosniff"
    assert res.headers.get("X-Frame-Options") == "DENY"
    assert res.headers.get("Referrer-Policy") == "strict-origin-when-cross-origin"
    assert "Content-Security-Policy" in res.headers
