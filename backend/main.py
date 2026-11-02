"""
Ajaia Collaborative Document Editor - Main Application
FastAPI application entrypoint with modular architecture, OpenAPI security schemas,
and robust document lifecycle, sharing, and batch upload endpoints.
"""

import io
import os
import uuid
import logging
from contextlib import asynccontextmanager
from typing import List, Optional, Union

from fastapi import (
    FastAPI,
    Depends,
    HTTPException,
    status,
    UploadFile,
    File,
    Query,
    Response,
)
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
    ErrorResponse,
    HealthResponse,
)
from backend.storage import storage_service
from backend.security import sanitize_html, SecurityHeadersMiddleware
from backend.converters import html_to_markdown, html_to_text, file_to_html
from backend.deps import (
    get_current_user,
    get_document_or_404,
    require_document_access,
)

# Logging configuration
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("ajaia_docs")

# Maximum upload file size: 20 MB ceiling
MAX_FILE_SIZE = 20 * 1024 * 1024


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan context manager for database initialization and MinIO bucket setup."""
    logger.info("Initializing Ajaia Docs service...")
    try:
        init_db_and_seed()
    except Exception as e:
        logger.error(f"Database setup notice during lifespan: {e}")

    try:
        storage_service.ensure_bucket_exists()
    except Exception as e:
        logger.warning(f"MinIO setup notice during lifespan: {e}")

    yield
    logger.info("Shutting down Ajaia Docs service...")


# FastAPI Application Definition with OpenAPI documentation
app = FastAPI(
    title="Ajaia Collaborative Document Editor API",
    description=(
        "Lightweight collaborative document editor inspired by Google Docs.\n\n"
        "### Key Capabilities:\n"
        "- **Rich Text Editing:** Full formatting with bold, italic, headings, lists, and autosave.\n"
        "- **File Uploads (20MB):** Supports batch uploads of Markdown (.md) and text (.txt) files.\n"
        "- **MinIO S3 Persistence:** Raw files preserved in S3 object storage; documents indexed in PostgreSQL.\n"
        "- **Role-Based Sharing:** Assign View or Edit roles between personas (Alice & Bob).\n\n"
        "### Authentication:\n"
        "Click the green **Authorize** button on the right to enter your active persona email "
        "(`alice@ajaia.test` or `bob@ajaia.test`). All document endpoints require this header."
    ),
    version="1.2.0",
    lifespan=lifespan,
    responses={
        401: {"model": ErrorResponse, "description": "Missing or invalid X-User-Email persona header."},
        403: {"model": ErrorResponse, "description": "Insufficient permissions for requested operation."},
        404: {"model": ErrorResponse, "description": "Resource not found."},
        413: {"model": ErrorResponse, "description": "Uploaded content exceeds 20MB limit."},
    },
)

# Security and CORS Middlewares
app.add_middleware(SecurityHeadersMiddleware)

cors_origins_raw = os.getenv(
    "CORS_ORIGINS",
    "http://localhost:5588,http://localhost:8000,http://127.0.0.1:5588,http://127.0.0.1:8000,http://testserver"
)
allowed_origins = (
    ["*"]
    if cors_origins_raw.strip() == "*"
    else [origin.strip() for origin in cors_origins_raw.split(",") if origin.strip()]
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True if "*" not in allowed_origins else False,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)


def serialize_doc(doc: Document, current_user_id: str) -> DocumentResponse:
    """Serialize a Document database model into DocumentResponse schema."""
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


# ==============================================================================
# HEALTH & METADATA ROUTES
# ==============================================================================

@app.get(
    "/api/v1/health",
    response_model=HealthResponse,
    tags=["Health"],
    summary="Service Health Check",
    description="Reports the live operational connectivity status of PostgreSQL and MinIO S3 storage."
)
def health_check(db: Session = Depends(get_db)):
    db_ok = True
    try:
        db.execute(text("SELECT 1"))
    except Exception:
        db_ok = False

    minio_ok = bool(storage_service.client and storage_service.client.bucket_exists(storage_service.bucket))

    return HealthResponse(
        status="healthy" if db_ok else "degraded",
        database_connected=db_ok,
        minio_connected=minio_ok,
        bucket=storage_service.bucket,
        max_upload_size_mb=MAX_FILE_SIZE // (1024 * 1024),
    )


@app.get(
    "/api/v1/users",
    response_model=List[UserResponse],
    tags=["Users"],
    summary="List Test Personas",
    description="Returns all registered test user personas available for collaborative switching."
)
def list_users(db: Session = Depends(get_db)):
    return db.query(User).order_by(User.name.asc()).all()


@app.get(
    "/api/v1/users/me",
    response_model=UserResponse,
    tags=["Users"],
    summary="Get Active Persona",
    description="Returns identity details for the persona identified by the X-User-Email header."
)
def get_me(current_user: User = Depends(get_current_user)):
    return current_user


# ==============================================================================
# DOCUMENT LIFECYCLE ROUTES
# ==============================================================================

@app.get(
    "/api/v1/documents",
    response_model=DocumentListResponse,
    tags=["Documents"],
    summary="List Documents",
    description="Returns documents separated into 'owned' and 'shared' buckets for the active persona."
)
def list_documents(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    owned_docs = (
        db.query(Document)
        .filter(Document.owner_id == current_user.id)
        .order_by(Document.updated_at.desc())
        .all()
    )

    shared_records = (
        db.query(DocumentShare)
        .filter(DocumentShare.user_id == current_user.id)
        .all()
    )
    shared_doc_ids = [s.document_id for s in shared_records]
    shared_docs = (
        db.query(Document)
        .filter(Document.id.in_(shared_doc_ids))
        .order_by(Document.updated_at.desc())
        .all()
    ) if shared_doc_ids else []

    return DocumentListResponse(
        owned=[serialize_doc(d, current_user.id) for d in owned_docs],
        shared=[serialize_doc(d, current_user.id) for d in shared_docs],
    )


@app.post(
    "/api/v1/documents",
    response_model=DocumentResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["Documents"],
    summary="Create Document",
    description="Creates a new document owned by the active persona. Content is sanitized against XSS."
)
def create_document(
    doc_in: DocumentCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    clean_html = sanitize_html(doc_in.content_html or "")
    clean_text = doc_in.content_text or html_to_text(clean_html)

    new_doc = Document(
        title=doc_in.title or "Untitled Document",
        content_html=clean_html,
        content_text=clean_text,
        owner_id=current_user.id,
        file_type="native",
    )
    db.add(new_doc)
    db.commit()
    db.refresh(new_doc)
    return serialize_doc(new_doc, current_user.id)


@app.get(
    "/api/v1/documents/{document_id}",
    response_model=DocumentResponse,
    tags=["Documents"],
    summary="Get Document",
    description="Retrieves a single document if the active caller is the owner or an authorized collaborator."
)
def get_document(
    document_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    doc = get_document_or_404(document_id, db)
    require_document_access(doc, current_user.id, required_perm="view")
    return serialize_doc(doc, current_user.id)


@app.put(
    "/api/v1/documents/{document_id}",
    response_model=DocumentResponse,
    tags=["Documents"],
    summary="Update Document",
    description="Updates document title and/or content. Requires 'owner' or 'edit' permission."
)
def update_document(
    document_id: str,
    doc_in: DocumentUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    doc = get_document_or_404(document_id, db)
    require_document_access(doc, current_user.id, required_perm="edit")

    if doc_in.title is not None:
        doc.title = doc_in.title

    if doc_in.content_html is not None:
        doc.content_html = sanitize_html(doc_in.content_html)
        doc.content_text = doc_in.content_text if doc_in.content_text is not None else html_to_text(doc.content_html)

    db.commit()
    db.refresh(doc)
    return serialize_doc(doc, current_user.id)


@app.delete(
    "/api/v1/documents/{document_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    tags=["Documents"],
    summary="Delete Document",
    description="Permanently deletes a document and associated MinIO raw files. Restricted strictly to document owner."
)
def delete_document(
    document_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    doc = get_document_or_404(document_id, db)
    require_document_access(doc, current_user.id, required_perm="owner")

    if doc.minio_object_key:
        try:
            storage_service.delete_file(doc.minio_object_key)
        except Exception as e:
            logger.warning(f"Could not delete MinIO object {doc.minio_object_key}: {e}")

    db.delete(doc)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ==============================================================================
# EXPORT & RAW FILE DOWNLOAD
# ==============================================================================

@app.get(
    "/api/v1/documents/{document_id}/export",
    tags=["Documents"],
    summary="Export Document",
    description="Exports document in markdown (.md) or plain text (.txt) format."
)
def export_document(
    document_id: str,
    format: str = Query(default="md", pattern="^(md|txt)$"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    doc = get_document_or_404(document_id, db)
    require_document_access(doc, current_user.id, required_perm="view")

    safe_title = "".join(c for c in doc.title if c.isalnum() or c in (" ", "-", "_")).strip() or "document"

    if format == "md":
        content = html_to_markdown(doc.content_html or "")
        filename = f"{safe_title}.md"
        media_type = "text/markdown; charset=utf-8"
    else:
        content = doc.content_text or html_to_text(doc.content_html or "")
        filename = f"{safe_title}.txt"
        media_type = "text/plain; charset=utf-8"

    return StreamingResponse(
        io.BytesIO(content.encode("utf-8")),
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'}
    )


@app.get(
    "/api/v1/documents/{document_id}/download-raw",
    tags=["Documents"],
    summary="Download Original Uploaded File",
    description="Streams original unparsed file bytes directly from MinIO S3 object storage."
)
def download_raw_file(
    document_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    doc = get_document_or_404(document_id, db)
    require_document_access(doc, current_user.id, required_perm="view")

    if not doc.minio_object_key:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="This document was created natively and has no raw file attached."
        )

    file_bytes = storage_service.get_file(doc.minio_object_key)
    if file_bytes is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Raw file not found in MinIO storage."
        )

    original_filename = doc.minio_object_key.split("/", 1)[-1] if "/" in doc.minio_object_key else doc.minio_object_key

    return StreamingResponse(
        io.BytesIO(file_bytes),
        media_type="application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{original_filename}"'}
    )


# ==============================================================================
# ATOMIC FILE UPLOAD ROUTES
# ==============================================================================

@app.post(
    "/api/v1/documents/upload",
    response_model=Union[DocumentResponse, List[DocumentResponse]],
    status_code=status.HTTP_201_CREATED,
    tags=["Uploads"],
    summary="Upload & Ingest Document Files",
    description=(
        "Upload one or more .md or .txt files (up to 20MB per file). "
        "Validates all files atomically before persisting to MinIO S3 and PostgreSQL."
    )
)
async def upload_document_file(
    files: Union[UploadFile, List[UploadFile]] = File(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    file_list = files if isinstance(files, list) else [files]
    if not file_list:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No files provided for upload.")

    # 1. ATOMIC VALIDATION: Read and validate all files BEFORE writing any storage or DB records
    validated_payloads = []
    for f in file_list:
        filename = f.filename or "uploaded_file.txt"
        ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
        if ext not in ["md", "txt"]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"File '{filename}' has unsupported extension '{ext}'. Only .md and .txt files are supported."
            )

        content_bytes = await f.read()
        if len(content_bytes) > MAX_FILE_SIZE:
            raise HTTPException(
                status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                detail=f"File '{filename}' exceeds the maximum allowed size of 20MB ({len(content_bytes)} bytes)."
            )

        validated_payloads.append((f, filename, ext, content_bytes))

    # 2. PERSISTENCE: Write validated files to MinIO and PostgreSQL
    created_docs = []
    for original_file, filename, ext, content_bytes in validated_payloads:
        # Convert file to HTML and plain text
        raw_html, raw_text = file_to_html(content_bytes, filename)
        clean_html = sanitize_html(raw_html)
        clean_text = raw_text or html_to_text(clean_html)

        # Upload raw bytes to MinIO S3
        unique_obj_name = f"uploads/{uuid.uuid4()}/{filename}"
        storage_service.upload_file(
            unique_obj_name,
            content_bytes,
            content_type=original_file.content_type or "text/plain"
        )

        title = filename.rsplit(".", 1)[0].replace("_", " ").replace("-", " ").title()

        new_doc = Document(
            title=title,
            content_html=clean_html,
            content_text=clean_text,
            owner_id=current_user.id,
            minio_object_key=unique_obj_name,
            file_type=ext,
        )
        db.add(new_doc)
        db.commit()
        db.refresh(new_doc)
        created_docs.append(serialize_doc(new_doc, current_user.id))

    if len(created_docs) == 1:
        return created_docs[0]
    return created_docs


# ==============================================================================
# SHARING & PERMISSIONS ROUTES
# ==============================================================================

@app.post(
    "/api/v1/documents/{document_id}/shares",
    response_model=DocumentShareResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["Sharing"],
    summary="Share Document",
    description="Grants view or edit permission to a collaborator by email. Only the document owner can share."
)
def share_document(
    document_id: str,
    share_req: ShareRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    doc = get_document_or_404(document_id, db)
    require_document_access(doc, current_user.id, required_perm="owner")

    target_email = share_req.email.strip().lower()
    target_user = db.query(User).filter(User.email == target_email).first()
    if not target_user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"User with email '{target_email}' does not exist."
        )

    if target_user.id == doc.owner_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot share a document with its owner."
        )

    # Check for existing share; update if exists, otherwise create
    share = (
        db.query(DocumentShare)
        .filter(DocumentShare.document_id == document_id, DocumentShare.user_id == target_user.id)
        .first()
    )

    if share:
        share.permission = share_req.permission
    else:
        share = DocumentShare(
            document_id=document_id,
            user_id=target_user.id,
            permission=share_req.permission,
        )
        db.add(share)

    db.commit()
    db.refresh(share)

    return DocumentShareResponse(
        id=share.id,
        user_id=target_user.id,
        user_email=target_user.email,
        user_name=target_user.name,
        permission=share.permission,
        created_at=share.created_at,
    )


@app.delete(
    "/api/v1/documents/{document_id}/shares/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    tags=["Sharing"],
    summary="Revoke Share Access",
    description="Revokes sharing access for a collaborator. Only the document owner can revoke access."
)
def revoke_share(
    document_id: str,
    user_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    doc = get_document_or_404(document_id, db)
    require_document_access(doc, current_user.id, required_perm="owner")

    share = (
        db.query(DocumentShare)
        .filter(DocumentShare.document_id == document_id, DocumentShare.user_id == user_id)
        .first()
    )
    if not share:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Share record not found.")

    db.delete(share)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ==============================================================================
# STATIC & UI FRONTEND MOUNT
# ==============================================================================

# Mount static asset directory
frontend_static_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "frontend", "static")
if os.path.exists(frontend_static_dir):
    app.mount("/static", StaticFiles(directory=frontend_static_dir), name="static")


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
def serve_index():
    """Serves the single-page application frontend."""
    template_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "frontend", "templates", "index.html")
    if not os.path.exists(template_path):
        return HTMLResponse("<h3>Ajaia Docs frontend template not found.</h3>", status_code=404)
    with open(template_path, "r", encoding="utf-8") as f:
        return HTMLResponse(f.read())
