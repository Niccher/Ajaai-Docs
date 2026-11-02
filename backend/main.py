import io
import os
import re
import uuid
import logging
from contextlib import asynccontextmanager
from typing import List, Optional, Union

import markdown
from fastapi import FastAPI, Depends, HTTPException, status, UploadFile, File, Header, Request, Response, Query
from fastapi.middleware.cors import CORSMiddleware
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

# Security & Upload Configuration
MAX_FILE_SIZE = 20 * 1024 * 1024  # 20 MB ceiling


def sanitize_html(html_str: str) -> str:
    """
    Sanitize HTML to neutralize XSS attacks.
    Strips script tags, iframes, inline event handlers (on*), and javascript: URIs.
    """
    if not html_str:
        return ""
    # Strip <script>...</script>
    cleaned = re.sub(r"<script.*?>.*?</script>", "", html_str, flags=re.IGNORECASE | re.DOTALL)
    # Strip <iframe...></iframe>
    cleaned = re.sub(r"<iframe.*?>.*?</iframe>", "", cleaned, flags=re.IGNORECASE | re.DOTALL)
    # Strip on* event handlers (e.g. onerror=, onclick=, onload=)
    cleaned = re.sub(r"\s+on\w+\s*=\s*['\"].*?['\"]", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s+on\w+\s*=\s*[^ >]+", "", cleaned, flags=re.IGNORECASE)
    # Neutralize javascript: hrefs
    cleaned = re.sub(r"href\s*=\s*['\"]javascript:.*?['\"]", "href='#'", cleaned, flags=re.IGNORECASE)
    return cleaned


def html_to_markdown(html_str: str) -> str:
    """Convert HTML markup back into Markdown representation for clean export."""
    if not html_str:
        return ""
    text_content = html_str
    # Convert headings
    text_content = re.sub(r"<h1>(.*?)</h1>", r"# \1\n\n", text_content, flags=re.IGNORECASE | re.DOTALL)
    text_content = re.sub(r"<h2>(.*?)</h2>", r"## \1\n\n", text_content, flags=re.IGNORECASE | re.DOTALL)
    text_content = re.sub(r"<h3>(.*?)</h3>", r"### \1\n\n", text_content, flags=re.IGNORECASE | re.DOTALL)
    # Convert strong/b
    text_content = re.sub(r"<(?:strong|b)>(.*?)</(?:strong|b)>", r"**\1**", text_content, flags=re.IGNORECASE | re.DOTALL)
    # Convert em/i
    text_content = re.sub(r"<(?:em|i)>(.*?)</(?:em|i)>", r"*\1*", text_content, flags=re.IGNORECASE | re.DOTALL)
    # Convert blockquotes
    text_content = re.sub(r"<blockquote>(.*?)</blockquote>", r"> \1\n\n", text_content, flags=re.IGNORECASE | re.DOTALL)
    # Convert list items
    text_content = re.sub(r"<li>(.*?)</li>", r"- \1\n", text_content, flags=re.IGNORECASE | re.DOTALL)
    # Convert paragraphs and line breaks
    text_content = re.sub(r"<p>(.*?)</p>", r"\1\n\n", text_content, flags=re.IGNORECASE | re.DOTALL)
    text_content = re.sub(r"<br\s*/?>", r"\n", text_content, flags=re.IGNORECASE)
    # Strip remaining HTML tags
    text_content = re.sub(r"<[^>]+>", "", text_content)
    # Deduplicate whitespace lines
    text_content = re.sub(r"\n{3,}", "\n\n", text_content)
    return text_content.strip()


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
    version="1.1.0",
    lifespan=lifespan,
)

# CORS Configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Dependency: Active User Persona
def get_current_user(
    request: Request,
    x_user_email: Optional[str] = Header(None),
    db: Session = Depends(get_db)
) -> User:
    email = x_user_email or request.query_params.get("x_user_email") or "alice@ajaia.test"
    user = db.query(User).filter(User.email == email).first()
    if not user:
        user = User(email=email, name=email.split("@")[0].capitalize())
        db.add(user)
        db.commit()
        db.refresh(user)
    return user


def serialize_doc(doc: Document, current_user_id: str) -> DocumentResponse:
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
        "max_upload_size_mb": MAX_FILE_SIZE // (1024 * 1024),
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
    """List documents partitioned into 'owned' and 'shared'."""
    owned_docs = (
        db.query(Document)
        .filter(Document.owner_id == current_user.id)
        .order_by(Document.updated_at.desc())
        .all()
    )

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
    safe_html = sanitize_html(doc_in.content_html or "<p><br></p>")
    new_doc = Document(
        title=(doc_in.title or "Untitled Document").strip(),
        content_html=safe_html,
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
        doc.content_html = sanitize_html(doc_in.content_html)
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
    """Share document with another user by email (Editor or Viewer)."""
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

    target_user = db.query(User).filter(User.email == target_email).first()
    if not target_user:
        target_user = User(
            email=target_email,
            name=target_email.split("@")[0].capitalize()
        )
        db.add(target_user)
        db.commit()
        db.refresh(target_user)

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


# ==========================================
# FILE INGESTION & EXPORT (TASK 2 & STRETCH)
# ==========================================

async def process_single_upload(file: UploadFile, current_user: User, db: Session) -> DocumentResponse:
    """Helper to process a single uploaded file with size limit, MinIO storage, and HTML conversion."""
    filename = file.filename or "uploaded_document.txt"
    ext = os.path.splitext(filename)[1].lower()

    if ext not in [".txt", ".md"]:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type '{ext}'. Supported file types: .md, .txt"
        )

    content_bytes = await file.read()
    if len(content_bytes) > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File '{filename}' exceeds maximum allowed size of {MAX_FILE_SIZE // (1024 * 1024)} MB."
        )

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
        object_key = None

    # Step 2: Convert to sanitized HTML AST
    if ext == ".md":
        parsed_html = markdown.markdown(
            raw_text,
            extensions=["extra", "nl2br", "sane_lists"]
        )
        html_content = sanitize_html(parsed_html)
        file_type = "markdown"
    else:
        escaped_text = raw_text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        paragraphs = [f"<p>{p.strip()}</p>" for p in escaped_text.split("\n\n") if p.strip()]
        html_content = "".join(paragraphs) if paragraphs else f"<p>{escaped_text}</p>"
        file_type = "plaintext"

    doc_title = os.path.splitext(filename)[0].replace("_", " ").replace("-", " ").capitalize()

    # Step 3: Insert Document into PostgreSQL with rollback compensation
    new_doc = Document(
        title=doc_title or "Imported Document",
        content_html=html_content,
        content_text=raw_text[:500],
        owner_id=current_user.id,
        minio_object_key=object_key,
        file_type=file_type,
    )
    try:
        db.add(new_doc)
        db.commit()
        db.refresh(new_doc)
    except Exception as e:
        db.rollback()
        if object_key:
            storage_service.delete_file(object_key)
        raise HTTPException(status_code=500, detail=f"Database commit error: {e}")

    return serialize_doc(new_doc, current_user.id)


@app.post("/api/v1/documents/upload", status_code=status.HTTP_201_CREATED, tags=["Files"])
async def upload_document_files(
    files: Optional[List[UploadFile]] = File(None),
    file: Optional[UploadFile] = File(None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Upload one or multiple .txt / .md files (up to 20 MB each).
    Preserves raw files in MinIO S3 and converts them into editable rich-text documents.
    """
    file_list = []
    if files:
        file_list.extend(files)
    if file:
        file_list.append(file)

    if not file_list:
        raise HTTPException(status_code=400, detail="No files provided for upload.")

    results = []
    for f in file_list:
        doc = await process_single_upload(f, current_user, db)
        results.append(doc)

    # Return single doc if single uploaded, or list if multiple
    if len(results) == 1:
        return results[0]
    return results


@app.get("/api/v1/documents/{doc_id}/export", tags=["Files"])
def export_document(
    doc_id: str,
    format: str = Query("md", pattern="^(md|txt|html)$"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Export document content to Markdown (.md), Plain Text (.txt), or HTML.
    Supports download streaming with proper Content-Disposition header.
    """
    doc = db.query(Document).filter(Document.id == doc_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    is_owner = (doc.owner_id == current_user.id)
    is_shared = any(s.user_id == current_user.id for s in doc.shares)
    if not is_owner and not is_shared:
        raise HTTPException(status_code=403, detail="Access denied.")

    safe_title = re.sub(r'[^a-zA-Z0-9_-]', '_', doc.title.lower().replace(" ", "_")) or "document"

    if format == "md":
        content = html_to_markdown(doc.content_html)
        media_type = "text/markdown; charset=utf-8"
        filename = f"{safe_title}.md"
    elif format == "txt":
        content = doc.content_text or html_to_markdown(doc.content_html)
        media_type = "text/plain; charset=utf-8"
        filename = f"{safe_title}.txt"
    else:
        content = doc.content_html or ""
        media_type = "text/html; charset=utf-8"
        filename = f"{safe_title}.html"

    return StreamingResponse(
        io.BytesIO(content.encode("utf-8")),
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'}
    )


@app.get("/api/v1/documents/{doc_id}/raw", tags=["Files"])
def download_raw_file(
    doc_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Download original imported file directly from MinIO."""
    doc = db.query(Document).filter(Document.id == doc_id).first()
    if not doc or not doc.minio_object_key:
        raise HTTPException(status_code=404, detail="No raw file associated with this document.")

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
    return HTMLResponse("<h1>Ajaia Docs</h1><p>Frontend template not found.</p>")
