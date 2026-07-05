"""AI Assist — "Circular Intelligence" + GRC copilot.

A Pakistan-specific AI workspace: paste an SBP circular, policy, incident note or free
text and extract regulatory obligations, a summary, risk suggestions, or ISO 27001
control mappings. Every run is stored as an :class:`AiExtraction` so the workspace keeps
a searchable history and the extracted obligations can be fed into the Regulatory Change
module.

The extraction itself (see ``app/api/v1/ai_assist.py``) runs with OR without an LLM key:
when an Anthropic key is configured the Messages API is called, otherwise a deterministic
offline heuristic runs. ``model_used`` records which path produced the output.
"""
from __future__ import annotations

import enum

from sqlalchemy import String, Text
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import (
    Base,
    SoftDeleteMixin,
    TenantMixin,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
)


# ---------------------------------------------------------------- local enums ---
# NOTE: every SAEnum name is prefixed with the module key ("ai_") so it is globally
# unique in Postgres. These enums are module-local and intentionally NOT in enums.py.
class AiSourceType(str, enum.Enum):
    circular = "circular"
    policy = "policy"
    free_text = "free_text"
    incident = "incident"


class AiExtractionType(str, enum.Enum):
    obligations = "obligations"
    summary = "summary"
    risk_suggestions = "risk_suggestions"
    control_mapping = "control_mapping"


class AiJobStatus(str, enum.Enum):
    pending = "pending"
    completed = "completed"
    failed = "failed"


# ---------------------------------------------------------------- extractions ---
class AiExtraction(UUIDPrimaryKeyMixin, TimestampMixin, TenantMixin, SoftDeleteMixin, Base):
    """A single stored AI (or heuristic) extraction over a piece of source text."""

    __tablename__ = "ai_extractions"

    reference: Mapped[str] = mapped_column(String(32), default="", index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    source_type: Mapped[AiSourceType] = mapped_column(
        SAEnum(AiSourceType, name="ai_source_type"),
        default=AiSourceType.circular, nullable=False,
    )
    extraction_type: Mapped[AiExtractionType] = mapped_column(
        SAEnum(AiExtractionType, name="ai_extraction_type"),
        default=AiExtractionType.obligations, nullable=False,
    )
    input_text: Mapped[str] = mapped_column(Text, default="")
    output_text: Mapped[str] = mapped_column(Text, default="")
    # "heuristic" when produced offline, otherwise the LLM model id (e.g. claude-sonnet-4-5).
    model_used: Mapped[str] = mapped_column(String(64), default="heuristic")
    status: Mapped[AiJobStatus] = mapped_column(
        SAEnum(AiJobStatus, name="ai_job_status"),
        default=AiJobStatus.pending, nullable=False,
    )
    created_by: Mapped[str] = mapped_column(String(200), default="")
