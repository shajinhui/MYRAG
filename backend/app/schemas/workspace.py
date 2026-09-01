"""
知识库（工作区）的请求 / 响应校验模式。
"""
from pydantic import BaseModel, Field
from datetime import datetime


class WorkspaceCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = None
    kg_language: str | None = None
    kg_entity_types: list[str] | None = None


class WorkspaceUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    system_prompt: str | None = None
    kg_language: str | None = None
    kg_entity_types: list[str] | None = None


class WorkspaceResponse(BaseModel):
    id: int
    name: str
    description: str | None
    system_prompt: str | None = None
    kg_language: str | None = None
    kg_entity_types: list[str] | None = None
    document_count: int = 0
    indexed_count: int = 0
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class WorkspaceSummary(BaseModel):
    """供下拉选择器使用的精简摘要。"""
    id: int
    name: str
    document_count: int = 0

    model_config = {"from_attributes": True}
