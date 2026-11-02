"""
Shared pytest configuration and test fixtures for Ajaia Collaborative Document Editor.
Runs tests in isolated in-memory SQLite with mocked MinIO storage.
"""

import os
os.environ["TESTING"] = "1"

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.models import Base, User
from backend.database import get_db
from backend.main import app
from backend.storage import storage_service

# Isolated in-memory SQLite database
SQLALCHEMY_DATABASE_URL = "sqlite:///:memory:"

engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class MockMinioClient:
    """Mock MinIO client for offline testing."""
    def bucket_exists(self, bucket_name: str) -> bool:
        return True


@pytest.fixture(scope="session", autouse=True)
def setup_test_db():
    """Create tables and seed initial personas for the entire test session."""
    Base.metadata.create_all(bind=engine)
    db = TestingSessionLocal()
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
    """Provide a transactional database session rolled back after every test."""
    connection = engine.connect()
    transaction = connection.begin()
    session = TestingSessionLocal(bind=connection)
    yield session
    session.close()
    transaction.rollback()
    connection.close()


@pytest.fixture
def client(db_session, monkeypatch):
    """Provide a TestClient with overridden DB session and mocked MinIO storage driver."""
    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db

    # Mock MinIO storage methods during unit tests
    monkeypatch.setattr(storage_service, "client", MockMinioClient())
    monkeypatch.setattr(storage_service, "ensure_bucket_exists", lambda *args, **kwargs: True)
    monkeypatch.setattr(storage_service, "upload_file", lambda object_name, data, *args, **kwargs: object_name)
    monkeypatch.setattr(storage_service, "get_file", lambda object_name: b"# Sample Markdown Content\n\n- Point A\n- Point B")
    monkeypatch.setattr(storage_service, "delete_file", lambda object_name: None)

    with TestClient(app) as test_client:
        yield test_client

    app.dependency_overrides.clear()
