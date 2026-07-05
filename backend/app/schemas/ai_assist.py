from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.ai_assist import AiExtractionType, AiJobStatus, AiSourceType


# ------------------------------------------------------------------ extractions ---
class AiExtractionBase(BaseModel):
    source_type: AiSourceType = AiSourceType.circular
    extraction_type: AiExtractionType = AiExtractionType.obligations
    title: str = Field(min_length=1, max_length=255)
    input_text: str = Field(min_length=1)


class AiExtractionCreate(AiExtractionBase):
    """Body for POST /ai-assist/extract — runs the extraction and stores the result."""


class AiExtractionUpdate(BaseModel):
    title: str | None = None
    source_type: AiSourceType | None = None
    extraction_type: AiExtractionType | None = None
    input_text: str | None = None


class AiExtractionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    reference: str
    source_type: AiSourceType
    extraction_type: AiExtractionType
    title: str
    input_text: str
    output_text: str
    model_used: str
    status: AiJobStatus
    created_by: str
    created_at: datetime
