import os
os.environ["TESTING"] = "1"
import io
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.models import Base, User, Document, DocumentShare
from backend.database import get_db
from backend.main import app
from backend.storage import storage_service

# Setup in-memory SQLite database for isolated test execution
SQLALCHEMY_DATABASE_URL = "sqlite:///:memory:"

engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


@pytest.fixture(scope="session", autouse=True)
def setup_test_db():
    Base.metadata.create_all(bind=engine)
    db = TestingSessionLocal()
    # Seed Alice and Bob
    alice = User(id="user_alice_1", email="alice@ajaia.test", name="Alice Johnson")
    bob = User(id="user_bob_2", email="bob@ajaia.test", name="Bob Smith")
    db.add(alice)
    db.add(bob)
    db.commit()
    db.close()
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def db_session():
    connection = engine.connect()
    transaction = connection.begin()
    session = TestingSessionLocal(bind=connection)
    yield session
    session.close()
    transaction.rollback()
    connection.close()


@pytest.fixture
def client(db_session, monkeypatch):
    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db

    # Mock MinIO storage methods during unit tests
    monkeypatch.setattr(storage_service, "ensure_bucket_exists", lambda *args, **kwargs: True)
    monkeypatch.setattr(storage_service, "upload_file", lambda object_name, data, *args, **kwargs: object_name)
    monkeypatch.setattr(storage_service, "get_file", lambda object_name: b"# Sample Markdown Content")
    monkeypatch.setattr(storage_service, "delete_file", lambda object_name: None)

    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


# ==========================================
# TESTS
# ==========================================

def test_seeded_personas(client):
    """Verify that default test personas (Alice & Bob) are available."""
    res = client.get("/api/v1/users")
    assert res.status_code == 200
    users = res.json()
    emails = [u["email"] for u in users]
    assert "alice@ajaia.test" in emails
    assert "bob@ajaia.test" in emails


def test_create_document(client):
    """Verify document creation assigned to active persona."""
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


def test_document_access_isolation_forbidden(client):
    """Verify that Bob CANNOT access Alice's private document (403 Forbidden)."""
    # 1. Alice creates a private document
    res_alice = client.post(
        "/api/v1/documents",
        json={"title": "Alice Secret Roadmap", "content_html": "<p>Confidential</p>"},
        headers={"X-User-Email": "alice@ajaia.test"}
    )
    doc_id = res_alice.json()["id"]

    # 2. Bob attempts to read Alice's unshared document
    res_bob = client.get(f"/api/v1/documents/{doc_id}", headers={"X-User-Email": "bob@ajaia.test"})
    assert res_bob.status_code == 403
    assert "Access forbidden" in res_bob.json()["detail"]


def test_sharing_workflow_grants_access(client):
    """Verify that sharing a document grants Bob access and shows up in shared list."""
    # 1. Alice creates document
    res_create = client.post(
        "/api/v1/documents",
        json={"title": "Shared Architecture Proposal", "content_html": "<p>Draft</p>"},
        headers={"X-User-Email": "alice@ajaia.test"}
    )
    doc_id = res_create.json()["id"]

    # 2. Alice shares with Bob as editor
    res_share = client.post(
        f"/api/v1/documents/{doc_id}/share",
        json={"email": "bob@ajaia.test", "permission": "edit"},
        headers={"X-User-Email": "alice@ajaia.test"}
    )
    assert res_share.status_code == 200
    assert res_share.json()["user_email"] == "bob@ajaia.test"
    assert res_share.json()["permission"] == "edit"

    # 3. Bob reads document -> should now succeed with 200
    res_bob = client.get(f"/api/v1/documents/{doc_id}", headers={"X-User-Email": "bob@ajaia.test"})
    assert res_bob.status_code == 200
    assert res_bob.json()["permission"] == "edit"

    # 4. Bob updates document content
    res_update = client.put(
        f"/api/v1/documents/{doc_id}",
        json={"content_html": "<p>Bob contributed feedback.</p>"},
        headers={"X-User-Email": "bob@ajaia.test"}
    )
    assert res_update.status_code == 200
    assert "<p>Bob contributed feedback.</p>" in res_update.json()["content_html"]

    # 5. Check Bob's document list partitions correctly
    res_list = client.get("/api/v1/documents", headers={"X-User-Email": "bob@ajaia.test"})
    assert res_list.status_code == 200
    shared_ids = [d["id"] for d in res_list.json()["shared"]]
    assert doc_id in shared_ids


def test_read_only_viewer_cannot_edit(client):
    """Verify that a user with 'view' permission cannot modify a document."""
    # 1. Alice creates doc
    doc_res = client.post(
        "/api/v1/documents",
        json={"title": "Read Only Policy", "content_html": "<p>Immutable</p>"},
        headers={"X-User-Email": "alice@ajaia.test"}
    )
    doc_id = doc_res.json()["id"]

    # 2. Alice shares with Bob as 'view' only
    client.post(
        f"/api/v1/documents/{doc_id}/share",
        json={"email": "bob@ajaia.test", "permission": "view"},
        headers={"X-User-Email": "alice@ajaia.test"}
    )

    # 3. Bob attempts to edit -> must return 403
    res_edit = client.put(
        f"/api/v1/documents/{doc_id}",
        json={"title": "Hacked Title"},
        headers={"X-User-Email": "bob@ajaia.test"}
    )
    assert res_edit.status_code == 403
    assert "read-only" in res_edit.json()["detail"].lower()


def test_file_upload_markdown_conversion(client):
    """Verify that uploading a .md file converts markdown to HTML and persists."""
    markdown_content = "# Project Apollo\n\n- Task 1: Scaffolding\n- Task 2: Persistence\n\n> Note: High priority"
    file_bytes = io.BytesIO(markdown_content.encode("utf-8"))

    res = client.post(
        "/api/v1/documents/upload",
        files={"file": ("apollo_spec.md", file_bytes, "text/markdown")},
        headers={"X-User-Email": "alice@ajaia.test"}
    )
    assert res.status_code == 201
    doc = res.json()
    assert doc["title"] == "Apollo spec"
    assert doc["file_type"] == "markdown"
    assert "<h1>Project Apollo</h1>" in doc["content_html"]
    assert "<li>Task 1: Scaffolding</li>" in doc["content_html"]
    assert "<blockquote>" in doc["content_html"]
    assert doc["minio_object_key"] is not None


def test_delete_access_control(client):
    """Verify only owner can delete a document."""
    # 1. Alice creates doc and shares with Bob
    doc_res = client.post(
        "/api/v1/documents",
        json={"title": "To be deleted"},
        headers={"X-User-Email": "alice@ajaia.test"}
    )
    doc_id = doc_res.json()["id"]
    client.post(
        f"/api/v1/documents/{doc_id}/share",
        json={"email": "bob@ajaia.test", "permission": "edit"},
        headers={"X-User-Email": "alice@ajaia.test"}
    )

    # 2. Bob attempts to delete Alice's doc -> 403
    res_bob_del = client.delete(f"/api/v1/documents/{doc_id}", headers={"X-User-Email": "bob@ajaia.test"})
    assert res_bob_del.status_code == 403

    # 3. Alice deletes her own doc -> 204
    res_alice_del = client.delete(f"/api/v1/documents/{doc_id}", headers={"X-User-Email": "alice@ajaia.test"})
    assert res_alice_del.status_code == 204
