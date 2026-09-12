"""Payloads for the scenario library, asset-driven risk generation and (phase 3) the
risk candidate queue."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.schemas.common import GraphRef, LookupRef, UnitRef, UserRef
from app.services.risk_scenarios import IMPACT_RULES
from app.services.risk_scoring import MAX_MATRIX_SIZE

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
    control_references: str = ""
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
    control_references: str | None = None
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
    #: Controls the scenario calls for that this organisation's catalogue does not have
    #: (by reference) — usually because the framework is not installed. Shown, not
    #: silently dropped, so the gap is visible in the proposal.
    unmapped_references: list[str] = []
    # Phase 3: which candidate this pair belongs to. Pairs with the same key become one
    # candidate in the queue (scenario + process + business unit; see
    # services.risk_scenarios.dedupe_key).
    dedupe_key: str = ""
    #: The candidate's scope as it reads: "Payments · Retail Banking".
    scope_label: str = ""
    #: The candidate's title when it covers several assets.
    group_title: str = ""
    #: A pending candidate with this key is already in the queue: the pair joins it.
    queued_proposal_id: uuid.UUID | None = None
    queued_title: str = ""
    #: The key's last candidate was rejected, and why — the preview leaves it unticked.
    rejected_note: str = ""
    rejected_at: datetime | None = None


class GenerateResponse(BaseModel):
    proposals: list[RiskProposal]
    assets_considered: int
    scenarios_considered: int
    #: Pairs already in the register — by title, or because a live risk covers the
    #: pair's candidate key (an accepted candidate, or an older generated risk).
    duplicates_skipped: int
    truncated: bool
    #: Distinct candidates the proposals would make (phase 3).
    candidates: int = 0
    #: Proposals that would join a candidate already waiting in the queue.
    queued: int = 0


class CommitItem(BaseModel):
    """One reviewed asset × scenario pair, with any edits the user made. Phase 3: the
    pair is queued as (part of) a candidate, not written to the register; the scenario
    (by id or reference) decides its candidate key."""

    asset_id: uuid.UUID
    scenario_id: uuid.UUID | None = None
    scenario_reference: str = Field(default="", max_length=32)
    title: str = Field(min_length=1, max_length=255)
    description: str = ""
    category: str = ""
    inherent_likelihood: int = Field(ge=1, le=MAX_MATRIX_SIZE)
    inherent_impact: int = Field(ge=1, le=MAX_MATRIX_SIZE)
    threat: str = ""
    vulnerability: str = ""
    treatment_description: str = ""
    control_ids: list[uuid.UUID] = []

    @model_validator(mode="after")
    def _names_a_scenario(self) -> "CommitItem":
        self.scenario_reference = self.scenario_reference.strip()
        if self.scenario_id is None and not self.scenario_reference:
            raise ValueError("Each item needs its scenario_id or scenario_reference")
        return self


class CommitRequest(BaseModel):
    items: list[CommitItem] = Field(min_length=1, max_length=2000)


class CommitError(BaseModel):
    title: str
    message: str


class CommitSkip(BaseModel):
    """A pair not queued because the register already covers it."""

    title: str
    asset_name: str = ""
    risk_reference: str = ""


class CommitResult(BaseModel):
    """What sending pairs to the queue did. Every pair either started a candidate
    (``created`` counts candidates), joined one (``merged`` — of which
    ``merged_into_existing`` joined a candidate already waiting from an earlier run), was
    ``skipped`` because the register already covers it, or failed (``errors``)."""

    run_id: uuid.UUID
    created: int
    merged: int
    merged_into_existing: int
    skipped: int
    #: Candidates this run created or added to.
    proposals: list[uuid.UUID] = []
    skipped_items: list[CommitSkip] = []
    errors: list[CommitError] = []


# ------------------------------------------------------------ the candidate queue ---
ProposalStatus = Literal["pending", "accepted", "rejected", "merged"]


class ProposalAssetRef(BaseModel):
    id: uuid.UUID
    name: str = ""
    asset_class: str = ""


class ProposalControlRef(BaseModel):
    id: uuid.UUID
    reference: str = ""
    name: str = ""


class ProposalRead(BaseModel):
    """A risk candidate as the queue shows it."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    run_id: uuid.UUID | None = None
    scenario_reference: str = ""
    #: The scenario as the library names it ("Ransomware encrypts …") and its category.
    scenario_title: str = ""
    scenario_category: str = ""
    title: str
    description: str = ""
    dedupe_key: str = ""
    status: ProposalStatus
    business_unit_id: uuid.UUID | None = None
    business_unit_ref: UnitRef | None = None
    process_id: uuid.UUID | None = None
    process_ref: UnitRef | None = None
    category_id: uuid.UUID | None = None
    category_ref: LookupRef | None = None
    inherent_likelihood: int | None = None
    inherent_impact: int | None = None
    inherent_score: int | None = None
    inherent_severity: str | None = None
    #: The references stored on the candidate; ``controls`` are those found in this
    #: organisation's catalogue now, ``unmapped_references`` the rest.
    control_references: list[str] = []
    controls: list[ProposalControlRef] = []
    unmapped_references: list[str] = []
    #: Live assets; ``archived_assets`` counts linked assets deleted since.
    assets: list[ProposalAssetRef] = []
    archived_assets: int = 0
    merged_into_id: uuid.UUID | None = None
    merged_into: GraphRef | None = None
    promoted_risk_id: uuid.UUID | None = None
    promoted_risk: GraphRef | None = None
    promoted_risk_archived: bool = False
    created_by_id: uuid.UUID | None = None
    created_by_ref: UserRef | None = None
    decided_by_id: uuid.UUID | None = None
    decided_by_ref: UserRef | None = None
    decided_at: datetime | None = None
    decision_note: str = ""
    created_at: datetime
    updated_at: datetime

    @field_validator("control_references", mode="before")
    @classmethod
    def _split(cls, value):
        if isinstance(value, str):
            return [r.strip() for r in value.split(",") if r.strip()]
        return value


class ProposalPage(BaseModel):
    items: list[ProposalRead]
    total: int
    limit: int
    offset: int
    #: Candidates per status under the same filters, ignoring the status filter.
    counts: dict[str, int] = Field(default_factory=dict)


def _non_blank(value: str) -> str:
    value = (value or "").strip()
    if not value:
        raise ValueError("must not be blank")
    return value


class AcceptRequest(BaseModel):
    """Promote candidates to register risks (draft, source *generated*, level 3 —
    scenario). The optional category, owner and parent apply to every one."""

    ids: list[uuid.UUID] = Field(min_length=1, max_length=200)
    category_id: uuid.UUID | None = None
    owner_id: uuid.UUID | None = None
    parent_id: uuid.UUID | None = None
    note: str = Field(default="", max_length=2000)


class ProposalError(BaseModel):
    id: uuid.UUID
    title: str = ""
    message: str


class AcceptResult(BaseModel):
    accepted: int
    risks: list[GraphRef] = []
    errors: list[ProposalError] = []


class RejectRequest(BaseModel):
    ids: list[uuid.UUID] = Field(min_length=1, max_length=500)
    #: Why — required, kept on each candidate and in its audit entry.
    note: str = Field(min_length=1, max_length=2000)

    @field_validator("note")
    @classmethod
    def _note_not_blank(cls, value: str) -> str:
        return _non_blank(value)


class RejectResult(BaseModel):
    rejected: int
    #: Ids left alone (not pending any more, or not found).
    skipped: list[ProposalError] = []


class MergeRequest(BaseModel):
    """Fold ``ids`` into ``into_id``: their assets and control references move to it
    and they are marked merged. ``into_id`` may also appear in ``ids``."""

    ids: list[uuid.UUID] = Field(min_length=1, max_length=200)
    into_id: uuid.UUID
    note: str = Field(default="", max_length=2000)


class MergeResult(BaseModel):
    merged: int
    survivor: ProposalRead
