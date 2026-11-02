"""
Ajaia Collaborative Document Editor - Pydantic Schemas
Strict request/response models with field constraints, email pattern validation, and OpenAPI documentation metadata.
"""

from datetime import datetime
from typing import List, Optional, Literal
from pydantic import BaseModel, ConfigDict, Field


class ErrorResponse(BaseModel):
    """Standardized error response schema."""
    detail: str = Field(
        ...,
        description="Detailed human-readable error description.",
        examples=["Missing required X-User-Email header.", "Access denied: You only have read-only access."]
    )


class HealthResponse(BaseModel):
    """Service health and connectivity status."""
    status: str = Field(..., examples=["healthy", "degraded"])
    database_connected: bool = Field(..., description="PostgreSQL database connectivity status.")
    minio_connected: bool = Field(..., description="MinIO S3 object storage connectivity status.")
    bucket: str = Field(..., description="Active MinIO bucket name.")
    max_upload_size_mb: int = Field(..., description="Maximum allowed upload file size in megabytes.")


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str = Field(..., description="Unique user identifier.")
    email: str = Field(
        ...,
        min_length=5,
        max_length=255,
        pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$",
        description="User's email address.",
        examples=["alice@ajaia.test"]
    )
    name: str = Field(..., description="User's display name.", examples=["Alice Johnson"])
    created_at: datetime = Field(..., description="Timestamp when user was registered.")


class DocumentCreate(BaseModel):
    title: str = Field(
        default="Untitled Document",
        min_length=1,
        max_length=255,
        description="Document title (1 to 255 characters).",
        examples=["Q3 Product Roadmap"]
    )
    content_html: Optional[str] = Field(
        default="",
        description="Initial rich-text HTML content."
    )
    content_text: Optional[str] = Field(
        default="",
        description="Initial plain-text representation."
    )


class DocumentUpdate(BaseModel):
    title: Optional[str] = Field(
        default=None,
        min_length=1,
        max_length=255,
        description="Updated document title (1 to 255 characters)."
    )
    content_html: Optional[str] = Field(
        default=None,
        description="Updated rich-text HTML content."
    )
    content_text: Optional[str] = Field(
        default=None,
        description="Updated plain text content."
    )


class DocumentShareResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str = Field(..., description="Unique share record ID.")
    user_id: str = Field(..., description="User ID granted access.")
    user_email: str = Field(..., description="Collaborator's email address.")
    user_name: str = Field(..., description="Collaborator's display name.")
    permission: Literal["edit", "view"] = Field(..., description="Assigned role: edit or view.")
    created_at: datetime = Field(..., description="Timestamp when share was granted.")


class DocumentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str = Field(..., description="Unique document ID (UUID).")
    title: str = Field(..., description="Document title.")
    content_html: str = Field(..., description="Rich-text HTML markup.")
    content_text: Optional[str] = Field(default="", description="Plain text representation.")
    owner_id: str = Field(..., description="Owner's user ID.")
    owner_email: Optional[str] = Field(default=None, description="Owner's email address.")
    owner_name: Optional[str] = Field(default=None, description="Owner's display name.")
    minio_object_key: Optional[str] = Field(default=None, description="MinIO S3 object key for imported files.")
    file_type: Optional[str] = Field(default="native", description="File type: native, md, or txt.")
    created_at: datetime = Field(..., description="Creation timestamp.")
    updated_at: datetime = Field(..., description="Last update timestamp.")
    permission: str = Field(default="owner", description="Active caller's effective permission: owner, edit, or view.")
    shares: List[DocumentShareResponse] = Field(default=[], description="List of collaborators granted access.")


class ShareRequest(BaseModel):
    email: str = Field(
        ...,
        min_length=5,
        max_length=255,
        pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$",
        description="Email address of the collaborator to invite.",
        examples=["bob@ajaia.test"]
    )
    permission: Literal["edit", "view"] = Field(
        default="edit",
        description="Permission level: 'edit' or 'view'."
    )


class DocumentListResponse(BaseModel):
    owned: List[DocumentResponse] = Field(default=[], description="Documents owned by active caller.")
    shared: List[DocumentResponse] = Field(default=[], description="Documents shared with active caller.")
