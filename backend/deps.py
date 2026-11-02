"""
Ajaia Collaborative Document Editor - Dependencies Module
Handles authentication, persona extraction, Swagger Authorize security schemes, and document access controls.
"""

from typing import Optional
from fastapi import Depends, HTTPException, status, Security
from fastapi.security import APIKeyHeader
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.models import User, Document, DocumentShare

# Swagger OpenAPI Authorize integration: registers 'X-User-Email' in the OpenAPI securitySchemes
api_key_header = APIKeyHeader(
    name="X-User-Email",
    auto_error=False,
    description="Active test persona email header (e.g. alice@ajaia.test or bob@ajaia.test)."
)


def get_current_user(
    x_user_email: Optional[str] = Security(api_key_header),
    db: Session = Depends(get_db)
) -> User:
    """
    Authenticate the active user persona from the X-User-Email header.
    Rejects unauthenticated requests with 401 Unauthorized if the header is missing
    or the persona does not exist in the database.
    """
    if not x_user_email or not x_user_email.strip():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=(
                "Missing required X-User-Email header. "
                "Specify 'alice@ajaia.test' or 'bob@ajaia.test' in the X-User-Email header, "
                "or click 'Authorize' at the top of the /docs Swagger page."
            ),
        )

    clean_email = x_user_email.strip().lower()
    user = db.query(User).filter(User.email == clean_email).first()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=(
                f"User persona '{clean_email}' not found. "
                "Available test personas: 'alice@ajaia.test', 'bob@ajaia.test'."
            ),
        )

    return user


def get_document_or_404(document_id: str, db: Session) -> Document:
    """Retrieve document by ID or raise 404 Not Found."""
    doc = db.query(Document).filter(Document.id == document_id).first()
    if not doc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Document with ID '{document_id}' not found."
        )
    return doc


def require_document_access(doc: Document, user_id: str, required_perm: str = "view") -> str:
    """
    Check if the user has the required permission ('view', 'edit', or 'owner') on the document.
    Returns effective role string ('owner', 'edit', or 'view').
    Raises 403 Forbidden if permissions are insufficient.
    """
    if doc.owner_id == user_id:
        return "owner"

    share = next((s for s in doc.shares if s.user_id == user_id), None)
    if not share:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied: You do not have permission to access this document."
        )

    if required_perm == "owner":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied: Only the document owner can perform this operation."
        )

    if required_perm == "edit" and share.permission != "edit":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied: You only have read-only (viewer) access to this document."
        )

    return share.permission
