"""
Ajaia Collaborative Document Editor - Database Engine & Lifecycle
Manages SQLAlchemy engine, connection retries, Alembic programmatic migrations, and seed data.
"""

import os
import time
import logging
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker, Session
from backend.models import Base, User, Document, DocumentShare

logger = logging.getLogger("ajaia_database")

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://postgres:postgrespassword@localhost:5432/ajaia_docs"
)

# Normalize postgresql:// to postgresql+psycopg2:// for SQLAlchemy 2.0+ with psycopg2-binary
if DATABASE_URL.startswith("postgresql://"):
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+psycopg2://", 1)

# SQLite fallback compatibility if running locally without Docker
if DATABASE_URL.startswith("sqlite"):
    engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
else:
    engine = create_engine(
        DATABASE_URL,
        pool_pre_ping=True,
        pool_size=10,
        max_overflow=20
    )

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db():
    """FastAPI database session dependency."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def wait_for_db(max_retries: int = 15, delay: float = 2.0):
    """Wait for database server connection to become ready."""
    if os.getenv("TESTING") == "1" or DATABASE_URL.startswith("sqlite"):
        return True

    for attempt in range(1, max_retries + 1):
        try:
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
                logger.info("Successfully established connection to PostgreSQL database.")
                return True
        except Exception as e:
            logger.warning(f"Database connection attempt {attempt}/{max_retries} failed: {e}")
            if attempt == max_retries:
                raise e
            time.sleep(delay)


def run_migrations():
    """Apply Alembic migrations programmatically on startup."""
    if os.getenv("TESTING") == "1" or DATABASE_URL.startswith("sqlite"):
        return

    try:
        from alembic.config import Config
        from alembic import command

        alembic_ini_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "alembic.ini")
        if not os.path.exists(alembic_ini_path):
            alembic_ini_path = "alembic.ini"

        alembic_cfg = Config(alembic_ini_path)
        alembic_cfg.set_main_option("sqlalchemy.url", DATABASE_URL)

        with engine.connect() as conn:
            inspector = inspect(conn)
            tables = inspector.get_table_names()
            if "users" in tables and "alembic_version" not in tables:
                logger.info("Existing schema detected without alembic_version table. Stamping 'head'...")
                command.stamp(alembic_cfg, "head")
            else:
                logger.info("Running Alembic upgrade to 'head'...")
                command.upgrade(alembic_cfg, "head")
    except Exception as e:
        logger.warning(f"Alembic programmatic migration note: {e}. Ensuring tables via Base.metadata.create_all.")
        Base.metadata.create_all(bind=engine)


def init_db_and_seed():
    """Initialize schema migrations and seed default personas and sample document."""
    if os.getenv("TESTING") == "1":
        return

    wait_for_db()
    run_migrations()
    Base.metadata.create_all(bind=engine)

    db: Session = SessionLocal()
    try:
        # Check and seed Alice (Primary Owner)
        alice = db.query(User).filter(User.email == "alice@ajaia.test").first()
        if not alice:
            alice = User(
                email="alice@ajaia.test",
                name="Alice Johnson"
            )
            db.add(alice)

        # Check and seed Bob (Reviewer / Collaborator)
        bob = db.query(User).filter(User.email == "bob@ajaia.test").first()
        if not bob:
            bob = User(
                email="bob@ajaia.test",
                name="Bob Smith"
            )
            db.add(bob)

        db.commit()
        db.refresh(alice)
        db.refresh(bob)

        # Seed an initial welcome document owned by Alice if no docs exist
        total_docs = db.query(Document).count()
        if total_docs == 0:
            welcome_doc = Document(
                title="Welcome to Ajaia Docs",
                owner_id=alice.id,
                file_type="native",
                content_html="""<h2><strong>Welcome to Ajaia Docs!</strong></h2>
<p>This is a lightweight collaborative document editor built for the Ajaia Full Stack Product Engineer assessment.</p>
<hr>
<h3><strong>Key Capabilities Built-In:</strong></h3>
<ul>
  <li><strong>Rich Text Editing:</strong> Bold, italic, underline, headers, and bulleted/numbered lists via Quill.js.</li>
  <li><strong>File Ingestion:</strong> Drag and drop or upload <code>.md</code> and <code>.txt</code> files (up to 20MB) directly into editable documents.</li>
  <li><strong>MinIO S3 Storage:</strong> Raw imported files are preserved in object storage.</li>
  <li><strong>Role-Based Sharing:</strong> Share with collaborators (view or edit access) with real-time UI segregation.</li>
  <li><strong>Persona Switcher:</strong> Switch between Alice and Bob in the top-right navbar to test sharing instantly!</li>
</ul>
<p><em>Try editing this text, changing the title above, or clicking the blue "Share" button to invite Bob!</em></p>""",
                content_text="Welcome to Ajaia Docs! This is a lightweight collaborative document editor built for the Ajaia Full Stack Product Engineer assessment."
            )
            db.add(welcome_doc)
            db.commit()
            db.refresh(welcome_doc)

            # Share this welcome doc with Bob as an 'edit' collaborator by default so reviewers see it immediately!
            sample_share = DocumentShare(
                document_id=welcome_doc.id,
                user_id=bob.id,
                permission="edit"
            )
            db.add(sample_share)
            db.commit()
            logger.info("Database initialized and seeded with default personas and sample document.")

    except Exception as e:
        db.rollback()
        logger.error(f"Error seeding database: {e}")
        raise e
    finally:
        db.close()
