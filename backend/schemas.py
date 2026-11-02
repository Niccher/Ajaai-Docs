from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel, ConfigDict, Field


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    email: str
    name: str
    created_at: datetime


class DocumentCreate(BaseModel):
    title: Optional[str] = Field(default="Untitled Document")
    content_html: Optional[str] = Field(default="")
    content_text: Optional[str] = Field(default="")


class DocumentUpdate(BaseModel):
    title: Optional[str] = None
    content_html: Optional[str] = None
    content_text: Optional[str] = None


class DocumentShareResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    user_id: str
    user_email: str
    user_name: str
    permission: str
    created_at: datetime


class DocumentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    title: str
    content_html: str
    content_text: Optional[str] = ""
    owner_id: str
    owner_email: Optional[str] = None
    owner_name: Optional[str] = None
    minio_object_key: Optional[str] = None
    file_type: Optional[str] = "native"
    created_at: datetime
    updated_at: datetime
    permission: str = "owner"  # 'owner', 'edit', 'view'
    shares: List[DocumentShareResponse] = []


class ShareRequest(BaseModel):
    email: str = Field(min_length=3, max_length=255)
    permission: str = Field(default="edit", pattern="^(edit|view)$")


class DocumentListResponse(BaseModel):
    owned: List[DocumentResponse]
    shared: List[DocumentResponse]
