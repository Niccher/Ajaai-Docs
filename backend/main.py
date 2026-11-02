import io
import os
import re
import uuid
import logging
from contextlib import asynccontextmanager
from typing import List, Optional

import markdown
from fastapi import FastAPI, Depends, HTTPException, status, UploadFile, File, Header, Request, Response
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.database import get_db, init_db_and_seed
from backend.models import User, Document, DocumentShare
from backend.schemas import (
    UserResponse,
    DocumentResponse,
    DocumentCreate,
    DocumentUpdate,
    DocumentShareResponse,
    DocumentListResponse,
    ShareRequest,
)
from backend.storage import storage_service

# Logging setup
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("ajaia_docs")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Initializing Ajaia Docs service...")
    try:
        init_db_and_seed()
    except Exception as e:
        logger.error(f"Database setup error during lifespan: {e}")

    try:
        storage_service.ensure_bucket_exists()
    except Exception as e:
        logger.error(f"MinIO setup warning during lifespan: {e}")

    yield
    logger.info("Shutting down Ajaia Docs service...")


app = FastAPI(
    title="Ajaia Collaborative Document Editor API",
    description="Lightweight collaborative document editor with rich-text, MinIO S3 ingestion, and persona-based sharing.",
    version="1.0.0",
    lifespan=lifespan,
)


# Dependency: Active User Persona
def get_current_user(
    request: Request,
    x_user_email: Optional[str] = Header(None),
    db: Session = Depends(get_db)
) -> User:
    # Accept from Header, or fallback to Query param (e.g. for window.open direct downloads)
    email = x_user_email or request.query_params.get("x_user_email") or "alice@ajaia.test"
    user = db.query(User).filter(User.email == email).first()
    if not user:
        # Fallback to creating user if email doesn't exist
        user = User(email=email, name=email.split("@")[0].capitalize())
        db.add(user)
        db.commit()
        db.refresh(user)
    return user


def serialize_doc(doc: Document, current_user_id: str) -> DocumentResponse:
    # Determine user's permission
    if doc.owner_id == current_user_id:
        perm = "owner"
    else:
        share = next((s for s in doc.shares if s.user_id == current_user_id), None)
        perm = share.permission if share else "view"

    shares_list = [
        DocumentShareResponse(
            id=s.id,
            user_id=s.user_id,
            user_email=s.user.email if s.user else "",
            user_name=s.user.name if s.user else "",
            permission=s.permission,
            created_at=s.created_at,
        )
        for s in doc.shares
    ]

    return DocumentResponse(
        id=doc.id,
        title=doc.title,
        content_html=doc.content_html or "",
        content_text=doc.content_text or "",
        owner_id=doc.owner_id,
        owner_email=doc.owner.email if doc.owner else "",
        owner_name=doc.owner.name if doc.owner else "",
        minio_object_key=doc.minio_object_key,
        file_type=doc.file_type or "native",
        created_at=doc.created_at,
        updated_at=doc.updated_at,
        permission=perm,
        shares=shares_list,
    )


# ==========================================
# API v1 ROUTES
# ==========================================

@app.get("/api/v1/health", tags=["Health"])
def health_check(db: Session = Depends(get_db)):
    """Health check reporting API, DB, and MinIO status."""
    db_ok = True
    try:
        db.execute(text("SELECT 1"))
    except Exception:
        db_ok = False

    minio_ok = bool(storage_service.client and storage_service.client.bucket_exists(storage_service.bucket))

    return {
        "status": "healthy" if db_ok else "degraded",
        "database_connected": db_ok,
        "minio_connected": minio_ok,
        "bucket": storage_service.bucket,
    }


@app.get("/api/v1/users", response_model=List[UserResponse], tags=["Users"])
def list_users(db: Session = Depends(get_db)):
    """List all seeded test persona users."""
    users = db.query(User).order_by(User.name.asc()).all()
    return users


@app.get("/api/v1/documents", response_model=DocumentListResponse, tags=["Documents"])
def list_documents(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    List documents partitioned into 'owned' and 'shared'.
    """
    # Owned documents
    owned_docs = (
        db.query(Document)
        .filter(Document.owner_id == current_user.id)
        .order_by(Document.updated_at.desc())
        .all()
    )

    # Shared documents
    shared_entries = (
        db.query(DocumentShare)
        .filter(DocumentShare.user_id == current_user.id)
        .all()
    )
    shared_doc_ids = [s.document_id for s in shared_entries]
    shared_docs = (
        db.query(Document)
        .filter(Document.id.in_(shared_doc_ids))
        .order_by(Document.updated_at.desc())
        .all()
    )

    return DocumentListResponse(
        owned=[serialize_doc(d, current_user.id) for d in owned_docs],
        shared=[serialize_doc(d, current_user.id) for d in shared_docs],
    )


@app.post("/api/v1/documents", response_model=DocumentResponse, status_code=status.HTTP_201_CREATED, tags=["Documents"])
def create_document(
    doc_in: DocumentCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Create a new blank document owned by the active user."""
    new_doc = Document(
        title=doc_in.title or "Untitled Document",
        content_html=doc_in.content_html or "<p><br></p>",
        content_text=doc_in.content_text or "",
        owner_id=current_user.id,
        file_type="native",
    )
    db.add(new_doc)
    db.commit()
    db.refresh(new_doc)
    return serialize_doc(new_doc, current_user.id)


@app.get("/api/v1/documents/{doc_id}", response_model=DocumentResponse, tags=["Documents"])
def get_document(
    doc_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Retrieve document by ID.
    Enforces authorization: 403 if user is neither owner nor shared.
    """
    doc = db.query(Document).filter(Document.id == doc_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    # Access control check
    is_owner = (doc.owner_id == current_user.id)
    is_shared = any(s.user_id == current_user.id for s in doc.shares)

    if not is_owner and not is_shared:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access forbidden: You do not have permission to view this document."
        )

    return serialize_doc(doc, current_user.id)


@app.put("/api/v1/documents/{doc_id}", response_model=DocumentResponse, tags=["Documents"])
def update_document(
    doc_id: str,
    doc_in: DocumentUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Update document title or content.
    Enforces edit permissions: 403 if user only has 'view' access.
    """
    doc = db.query(Document).filter(Document.id == doc_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    # Permission check
    is_owner = (doc.owner_id == current_user.id)
    share = next((s for s in doc.shares if s.user_id == current_user.id), None)

    if not is_owner and (not share or share.permission != "edit"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access forbidden: You have read-only permissions on this document."
        )

    if doc_in.title is not None:
        doc.title = doc_in.title.strip() or "Untitled Document"
    if doc_in.content_html is not None:
        doc.content_html = doc_in.content_html
    if doc_in.content_text is not None:
        doc.content_text = doc_in.content_text

    db.commit()
    db.refresh(doc)
    return serialize_doc(doc, current_user.id)


@app.delete("/api/v1/documents/{doc_id}", status_code=status.HTTP_204_NO_CONTENT, tags=["Documents"])
def delete_document(
    doc_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Delete document. Only the owner can delete."""
    doc = db.query(Document).filter(Document.id == doc_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    if doc.owner_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access forbidden: Only the document owner can delete this document."
        )

    # Clean up MinIO object if associated
    if doc.minio_object_key:
        try:
            storage_service.delete_file(doc.minio_object_key)
        except Exception as e:
            logger.warning(f"Failed to delete MinIO object on doc deletion: {e}")

    db.delete(doc)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@app.post("/api/v1/documents/{doc_id}/share", response_model=DocumentShareResponse, tags=["Sharing"])
def share_document(
    doc_id: str,
    share_in: ShareRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Share document with another user by email.
    Assigns role: 'edit' or 'view'.
    """
    doc = db.query(Document).filter(Document.id == doc_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    if doc.owner_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the document owner can manage sharing permissions."
        )

    target_email = share_in.email.lower().strip()
    if target_email == current_user.email.lower():
        raise HTTPException(status_code=400, detail="Cannot share document with yourself.")

    # Find or seed target user
    target_user = db.query(User).filter(User.email == target_email).first()
    if not target_user:
        target_user = User(
            email=target_email,
            name=target_email.split("@")[0].capitalize()
        )
        db.add(target_user)
        db.commit()
        db.refresh(target_user)

    # Check existing share
    existing_share = (
        db.query(DocumentShare)
        .filter(DocumentShare.document_id == doc.id, DocumentShare.user_id == target_user.id)
        .first()
    )

    if existing_share:
        existing_share.permission = share_in.permission
        db.commit()
        db.refresh(existing_share)
        return DocumentShareResponse(
            id=existing_share.id,
            user_id=target_user.id,
            user_email=target_user.email,
            user_name=target_user.name,
            permission=existing_share.permission,
            created_at=existing_share.created_at,
        )

    new_share = DocumentShare(
        document_id=doc.id,
        user_id=target_user.id,
        permission=share_in.permission,
    )
    db.add(new_share)
    db.commit()
    db.refresh(new_share)

    return DocumentShareResponse(
        id=new_share.id,
        user_id=target_user.id,
        user_email=target_user.email,
        user_name=target_user.name,
        permission=new_share.permission,
        created_at=new_share.created_at,
    )


@app.delete("/api/v1/documents/{doc_id}/share/{user_id}", status_code=status.HTTP_204_NO_CONTENT, tags=["Sharing"])
def revoke_share(
    doc_id: str,
    user_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Revoke shared access for a user."""
    doc = db.query(Document).filter(Document.id == doc_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    if doc.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="Only the document owner can revoke access.")

    share = (
        db.query(DocumentShare)
        .filter(DocumentShare.document_id == doc.id, DocumentShare.user_id == user_id)
        .first()
    )
    if share:
        db.delete(share)
        db.commit()

    return Response(status_code=status.HTTP_204_NO_CONTENT)


@app.post("/api/v1/documents/upload", response_model=DocumentResponse, status_code=status.HTTP_201_CREATED, tags=["Files"])
async def upload_document_file(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Upload a .txt or .md file:
    1. Persists the raw file to MinIO S3 object storage.
    2. Parses content into rich-text HTML.
    3. Creates a new Document record in PostgreSQL.
    """
    filename = file.filename or "uploaded_document.txt"
    ext = os.path.splitext(filename)[1].lower()

    if ext not in [".txt", ".md"]:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type '{ext}'. Supported file types: .md, .txt"
        )

    content_bytes = await file.read()
    try:
        raw_text = content_bytes.decode("utf-8")
    except UnicodeDecodeError:
        raw_text = content_bytes.decode("latin-1", errors="replace")

    # Step 1: Upload raw file to MinIO
    object_key = f"uploads/{uuid.uuid4()}_{re.sub(r'[^a-zA-Z0-9_.-]', '_', filename)}"
    try:
        storage_service.upload_file(
            object_name=object_key,
            data=content_bytes,
            content_type="text/markdown" if ext == ".md" else "text/plain",
        )
    except Exception as e:
        logger.error(f"MinIO upload error: {e}")
        # If MinIO is unavailable, record None but continue parsing so workflow is resilient
        object_key = None

    # Step 2: Convert to HTML AST
    if ext == ".md":
        html_content = markdown.markdown(
            raw_text,
            extensions=["extra", "nl2br", "sane_lists"]
        )
        file_type = "markdown"
    else:
        # Plain text into formatted paragraphs
        escaped_text = raw_text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        paragraphs = [f"<p>{p.strip()}</p>" for p in escaped_text.split("\n\n") if p.strip()]
        html_content = "".join(paragraphs) if paragraphs else f"<p>{escaped_text}</p>"
        file_type = "plaintext"

    doc_title = os.path.splitext(filename)[0].replace("_", " ").replace("-", " ").capitalize()

    # Step 3: Insert Document in PostgreSQL
    new_doc = Document(
        title=doc_title or "Imported Document",
        content_html=html_content,
        content_text=raw_text[:500],
        owner_id=current_user.id,
        minio_object_key=object_key,
        file_type=file_type,
    )
    db.add(new_doc)
    db.commit()
    db.refresh(new_doc)

    return serialize_doc(new_doc, current_user.id)


@app.get("/api/v1/documents/{doc_id}/raw", tags=["Files"])
def download_raw_file(
    doc_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Download original imported file from MinIO."""
    doc = db.query(Document).filter(Document.id == doc_id).first()
    if not doc or not doc.minio_object_key:
        raise HTTPException(status_code=404, detail="No raw file associated with this document.")

    # Access check
    is_owner = (doc.owner_id == current_user.id)
    is_shared = any(s.user_id == current_user.id for s in doc.shares)
    if not is_owner and not is_shared:
        raise HTTPException(status_code=403, detail="Access denied.")

    try:
        data = storage_service.get_file(doc.minio_object_key)
        filename = doc.minio_object_key.split("_", 1)[-1]
        return StreamingResponse(
            io.BytesIO(data),
            media_type="application/octet-stream",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'}
        )
    except Exception as e:
        logger.error(f"Failed to fetch file from MinIO: {e}")
        raise HTTPException(status_code=502, detail="Storage service error retrieving file.")


# ==========================================
# STATIC FRONTEND MOUNTING
# ==========================================

# Mount frontend static directory if exists
static_path = os.path.join(os.path.dirname(__file__), "..", "frontend", "static")
if os.path.exists(static_path):
    app.mount("/static", StaticFiles(directory=static_path), name="static")


@app.get("/", response_class=HTMLResponse, tags=["UI"])
def render_app():
    """Serve single-page frontend application."""
    index_path = os.path.join(os.path.dirname(__file__), "..", "frontend", "templates", "index.html")
    if os.path.exists(index_path):
        with open(index_path, "r", encoding="utf-8") as f:
            return HTMLResponse(content=f.read())
    return HTMLResponse("<h1>Ajaia Docs</h1><p>Frontend template not found. Ensure frontend/templates/index.html is created.</p>")
