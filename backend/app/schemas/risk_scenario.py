"""Payloads for the scenario library and asset-driven risk generation."""
from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.services.risk_scenarios import IMPACT_RULES

_RULE_PATTERN = "^(" + "|".join(IMPACT_RULES) + ")$"


# ------------------------------------------------------------ the library ---
class ScenarioBase(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    description: str = ""
    category: str = Field(default="", max_length=100)
    asset_classes: str = Field(default="", max_length=120)
    threat: str = Field(default="", max_length=200)
    vulnerability: str = Field(default="", max_length=200)
    likelihood: int = Field(default=3, ge=1, le=5)
    impact_rule: str = Field(default="from_criticality", pattern=_RULE_PATTERN)
    impact_property: str = Field(default="", pattern="^(|confidentiality|integrity|availability)$")
    fixed_impact: int = Field(default=0, ge=0, le=5)
    treatment_hint: str = ""
    enabled: bool = True


class ScenarioCreate(ScenarioBase):
    reference: str = Field(default="", max_length=32)


class ScenarioUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    category: str | None = Field(default=None, max_length=100)
    asset_classes: str | None = Field(default=None, max_length=120)
    threat: str | None = Field(default=None, max_length=200)
    vulnerability: str | None = Field(default=None, max_length=200)
    likelihood: int | None = Field(default=None, ge=1, le=5)
    impact_rule: str | None = Field(default=None, pattern=_RULE_PATTERN)
    impact_property: str | None = Field(default=None, pattern="^(|confidentiality|integrity|availability)$")
    fixed_impact: int | None = Field(default=None, ge=0, le=5)
    treatment_hint: str | None = None
    enabled: bool | None = None


class ScenarioRead(ScenarioBase):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    reference: str
    created_at: datetime


class LibraryInstallResult(BaseModel):
    installed: int
    skipped: int  # already present, left untouched so local edits survive a re-install
    total: int


# -------------------------------------------------------------- generation ---
class GenerateRequest(BaseModel):
    """Which assets to run the library against.

    Either name the assets explicitly or filter by class/criticality — a bank onboarding
    a few thousand assets will not paste ids.
    """

    asset_ids: list[uuid.UUID] = Field(default_factory=list)
    asset_class: str | None = Field(default=None, pattern="^(information_asset|it_asset)$")
    min_criticality: str | None = Field(default=None, pattern="^(low|medium|high|critical)$")
    scenario_ids: list[uuid.UUID] = Field(default_factory=list)  # empty = every enabled scenario
    category: str | None = None
    limit: int = Field(default=500, ge=1, le=2000)


class RiskProposal(BaseModel):
    """A pre-filled risk the user reviews before anything is written."""

    scenario_id: uuid.UUID
    scenario_reference: str
    asset_id: uuid.UUID
    asset_name: str
    title: str
    description: str
    category: str
    inherent_likelihood: int
    inherent_impact: int
    inherent_score: int
    threat: str
    vulnerability: str
    treatment_description: str
    #: Controls already linked to this asset — pre-attached so the residual suggestion
    #: has something to work with the moment the risk exists.
    control_ids: list[uuid.UUID] = []
    control_labels: list[str] = []


class GenerateResponse(BaseModel):
    proposals: list[RiskProposal]
    assets_considered: int
    scenarios_considered: int
    duplicates_skipped: int
    truncated: bool


class CommitItem(BaseModel):
    """One reviewed proposal, with any edits the user made."""

    asset_id: uuid.UUID
    title: str = Field(min_length=1, max_length=255)
    description: str = ""
    category: str = ""
    inherent_likelihood: int = Field(ge=1, le=6)
    inherent_impact: int = Field(ge=1, le=6)
    threat: str = ""
    vulnerability: str = ""
    treatment_description: str = ""
    control_ids: list[uuid.UUID] = []


class CommitRequest(BaseModel):
    items: list[CommitItem] = Field(min_length=1)


class CommitError(BaseModel):
    title: str
    message: str


class CommitResult(BaseModel):
    created: int
    skipped: int
    references: list[str]
    errors: list[CommitError]
