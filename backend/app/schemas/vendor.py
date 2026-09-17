from __future__ import annotations

import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.schemas.common import GraphRef, LookupRef, UserRef
from app.schemas.tenant_settings import validate_currency

from app.models.base import WorkflowState
from app.models.enums import AssessmentStatus, Criticality, ReviewFrequency, Severity, VendorStatus


# Phase 1 picker fields. ``category_id`` wins over the legacy ``category`` text when both
# are sent; the text is still accepted this release and matched to a lookup value when it
# names exactly one. ``country_id`` has no text twin: ``location`` is a city or address
# and stays free text.
_CATEGORY = "Value from the `vendor_category` lookup list; wins over `category` text."
_COUNTRY = (
    "Country, from the `country` lookup list. Not the same thing as `location`, "
    "which stays free text for a city or street address."
)
_LOCATION = "City or street address, free text. The country is `country_id`, picked from the country list."
_WF_OWNER = "User who owns the approval workflow. `workflow_status` changes only through the workflow endpoints."
_REL_OWNER = "The bank's accountable owner of the relationship (a user). Read back as `relationship_owner_ref`."
_DATA_CLASS = "Highest classification of bank data the third party accesses, from the `data_classification` list."
_SPEND_CCY = "ISO 4217 code of `annual_spend`; blank means the organisation's currency."
_CONTRACT_CCY = "ISO 4217 code of the contract value; blank means the organisation's currency."
_RESIDENCY = "Countries (from the `country` list) where the third party stores or processes our data."
_PROCESSES = "Business processes this third party supports."
_SUBS = "The third party's own sub-contractors (fourth parties), from the vendor register. A vendor can't be its own."
_TIER_REASON = (
    "Why the criticality differs from the one the inherent risk tier proposes. Required "
    "whenever it differs; cleared when the criticality matches the proposal."
)

#: Certification types a third party can hold (value -> label). Fixed list.
CERT_TYPES: dict[str, str] = {
    "iso_27001": "ISO 27001",
    "iso_22301": "ISO 22301",
    "soc1": "SOC 1",
    "soc2_type1": "SOC 2 Type I",
    "soc2_type2": "SOC 2 Type II",
    "pci_dss": "PCI DSS",
    "csa_star": "CSA STAR",
    "other": "Other",
}


def _currency_or_blank(value: str | None) -> str | None:
    if value is None:
        return None
    return validate_currency(value) if value.strip() else ""


def _cert_type(value: str | None) -> str | None:
    if value is None:
        return None
    key = value.strip()
    if key in CERT_TYPES:
        return key
    by_label = {label.lower(): k for k, label in CERT_TYPES.items()}
    if key.lower() in by_label:
        return by_label[key.lower()]
    raise ValueError(f"'{value}' is not a certification type; use one of: {', '.join(CERT_TYPES.values())}.")


class VendorRefItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    reference: str = ""
    title: str = ""
    name: str = ""


# ----------------------------------------------------------------- vendor types
class VendorTypeCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str = ""


class VendorTypeUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = None


class VendorTypeRead(VendorTypeCreate):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID


# -------------------------------------------------------------- service contracts
class ServiceContractCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = ""
    value: float | None = Field(default=None, ge=0)
    currency: str = Field(default="", description=_CONTRACT_CCY)
    start_date: date | None = None
    end_date: date | None = None

    _ccy = field_validator("currency")(_currency_or_blank)


class ServiceContractRead(ServiceContractCreate):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    is_expired: bool
    created_at: datetime

    @field_validator("currency", mode="before")
    @classmethod
    def _stored(cls, v):  # stored rows are read back as they are, never re-validated
        return v or ""


# ----------------------------------------------------------------- certifications
class VendorCertificationCreate(BaseModel):
    cert_type: str = Field(description="One of: " + ", ".join(CERT_TYPES.values()) + " (value or label).")
    issuer: str = Field(default="", max_length=200)
    certificate_number: str = Field(default="", max_length=120)
    scope: str = ""
    issued_on: date | None = None
    expires_on: date | None = None

    _type = field_validator("cert_type")(_cert_type)


class VendorCertificationUpdate(BaseModel):
    cert_type: str | None = None
    issuer: str | None = Field(default=None, max_length=200)
    certificate_number: str | None = Field(default=None, max_length=120)
    scope: str | None = None
    issued_on: date | None = None
    expires_on: date | None = None

    _type = field_validator("cert_type")(_cert_type)


class VendorCertificationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    vendor_id: uuid.UUID
    cert_type: str
    cert_type_label: str = ""
    issuer: str = ""
    certificate_number: str = ""
    scope: str = ""
    issued_on: date | None = None
    expires_on: date | None = None
    #: valid | expiring (within 60 days) | expired | no_expiry
    expiry_state: str = "no_expiry"
    days_to_expiry: int | None = None
    created_at: datetime | None = None

    @model_validator(mode="after")
    def _label(self):
        self.cert_type_label = CERT_TYPES.get(self.cert_type, self.cert_type)
        return self


# ------------------------------------------------------------ read-only blocks
class VendorOutsourcingFacts(BaseModel):
    """The SBP outsourcing facts recorded on an arrangement with this vendor (read-only
    here; edited under Outsourcing)."""

    id: uuid.UUID
    reference: str = ""
    title: str = ""
    status: str = ""
    materiality: str = ""
    is_cloud: bool = False
    data_offshored: bool = False
    country: str = ""
    sbp_approval_status: str = ""
    contract_end: date | None = None
    exit_plan: str = ""
    exit_plan_tested: bool = False
    #: Why it is (or is not) material.
    materiality_assessment: str = ""
    #: easy | moderate | difficult | none | "" (not assessed).
    substitutability: str = ""
    #: low | medium | high | "" (not assessed).
    concentration_level: str = ""
    concentration_note: str = ""


class VendorConcentration(BaseModel):
    """How much of the bank depends on this third party, derived from what is on file
    (see ``api/v1/vendors.concentration_view``). ``level`` is high when an arrangement
    records high concentration, two or more live material arrangements rely on the
    provider, or three or more high / critical processes do."""

    #: Live (not terminated) material arrangements with this vendor.
    material_arrangements: int = 0
    #: Live arrangements of any materiality.
    arrangements: int = 0
    #: Supported processes rated high or critical, and all supported processes.
    critical_processes: int = 0
    processes: int = 0
    #: The highest concentration level recorded on a live arrangement ("" if none).
    recorded_level: str = ""
    #: low | medium | high.
    level: str = "low"
    flagged: bool = False
    reasons: list[str] = []
    #: The vendor's criticality or tier is high / critical, or it supports a high /
    #: critical process — but no outsourcing arrangement is recorded.
    arrangement_expected: bool = False


class VendorTiering(BaseModel):
    """How the vendor's inherent tier was derived, from its latest completed
    "Inherent risk tiering" assessment (see services/vendor_tiering.py)."""

    tier: str | None = None
    proposed_criticality: str | None = None
    #: True when the vendor's criticality differs from the proposal (override on record).
    overridden: bool = False
    override_reason: str = ""
    assessment: GraphRef | None = None
    submitted_at: date | None = None
    total_score: float | None = None
    max_score: float | None = None
    score_pct: float | None = None
    band_tier: str | None = None
    worst_case_answers: int | None = None
    floor_applied: bool = False
    explanation: str = ""
    #: The latest completed assessment now gives a different tier from the one stored
    #: (re-run POST /vendors/{id}/tiering), or it can't be scored (see ``problem``).
    stale: bool = False
    problem: str = ""
    #: The tenant's tiering questionnaire, to start a new tiering assessment.
    questionnaire_id: uuid.UUID | None = None


# ----------------------------------------------------------------------- vendor
class VendorBase(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = ""
    category: str = ""
    category_id: uuid.UUID | None = Field(default=None, description=_CATEGORY)
    type_id: uuid.UUID | None = None
    contact_name: str = ""
    contact_email: str = ""
    contact_phone: str = ""
    website: str = ""
    location: str = Field(default="", description=_LOCATION)
    country_id: uuid.UUID | None = Field(default=None, description=_COUNTRY)
    criticality: Criticality = Criticality.medium
    status: VendorStatus = VendorStatus.active
    workflow_owner_id: uuid.UUID | None = Field(default=None, description=_WF_OWNER)
    risk_rating: Severity | None = None
    shares_data: bool = False
    assessment_status: AssessmentStatus = AssessmentStatus.not_started
    last_assessed_at: date | None = None
    onboarded_at: date | None = None
    offboarded_at: date | None = None
    review_frequency: ReviewFrequency = ReviewFrequency.annual
    next_review_date: date | None = None
    # Phase 2 due diligence.
    legal_name: str = Field(default="", max_length=255)
    registration_number: str = Field(default="", max_length=120, description="SECP / company registration number.")
    relationship_owner_id: uuid.UUID | None = Field(default=None, description=_REL_OWNER)
    data_classification_id: uuid.UUID | None = Field(default=None, description=_DATA_CLASS)
    annual_spend: float | None = Field(default=None, ge=0)
    spend_currency: str = Field(default="", description=_SPEND_CCY)


class VendorCreate(VendorBase):
    risk_ids: list[uuid.UUID] = []
    asset_ids: list[uuid.UUID] = []
    requirement_ids: list[uuid.UUID] = []
    control_ids: list[uuid.UUID] = []
    process_ids: list[uuid.UUID] = Field(default_factory=list, description=_PROCESSES)
    subcontractor_ids: list[uuid.UUID] = Field(default_factory=list, description=_SUBS)
    data_residency_country_ids: list[uuid.UUID] = Field(default_factory=list, description=_RESIDENCY)

    _ccy = field_validator("spend_currency")(_currency_or_blank)


class VendorUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None
    category: str | None = None
    category_id: uuid.UUID | None = Field(default=None, description=_CATEGORY)
    type_id: uuid.UUID | None = None
    contact_name: str | None = None
    contact_email: str | None = None
    contact_phone: str | None = None
    website: str | None = None
    location: str | None = Field(default=None, description=_LOCATION)
    country_id: uuid.UUID | None = Field(default=None, description=_COUNTRY)
    criticality: Criticality | None = None
    status: VendorStatus | None = None
    workflow_owner_id: uuid.UUID | None = Field(default=None, description=_WF_OWNER)
    risk_rating: Severity | None = None
    shares_data: bool | None = None
    assessment_status: AssessmentStatus | None = None
    last_assessed_at: date | None = None
    onboarded_at: date | None = None
    offboarded_at: date | None = None
    review_frequency: ReviewFrequency | None = None
    next_review_date: date | None = None
    risk_ids: list[uuid.UUID] | None = None
    asset_ids: list[uuid.UUID] | None = None
    requirement_ids: list[uuid.UUID] | None = None
    control_ids: list[uuid.UUID] | None = None
    legal_name: str | None = Field(default=None, max_length=255)
    registration_number: str | None = Field(default=None, max_length=120)
    relationship_owner_id: uuid.UUID | None = Field(default=None, description=_REL_OWNER)
    data_classification_id: uuid.UUID | None = Field(default=None, description=_DATA_CLASS)
    annual_spend: float | None = Field(default=None, ge=0)
    spend_currency: str | None = Field(default=None, description=_SPEND_CCY)
    process_ids: list[uuid.UUID] | None = Field(default=None, description=_PROCESSES)
    subcontractor_ids: list[uuid.UUID] | None = Field(default=None, description=_SUBS)
    data_residency_country_ids: list[uuid.UUID] | None = Field(default=None, description=_RESIDENCY)
    tier_override_reason: str | None = Field(default=None, description=_TIER_REASON)

    _ccy = field_validator("spend_currency")(_currency_or_blank)


class VendorRead(VendorBase):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    workflow_status: WorkflowState = WorkflowState.draft
    workflow_owner: str = ""
    category_ref: LookupRef | None = None
    country_ref: LookupRef | None = None
    workflow_owner_ref: UserRef | None = None
    type: VendorTypeRead | None = None
    contracts: list[ServiceContractRead] = []
    risks: list[VendorRefItem] = []
    assets: list[VendorRefItem] = []
    # Reverse links (read-only).
    incidents: list[GraphRef] = []
    assessments: list[GraphRef] = []
    outsourcing_arrangements: list[GraphRef] = []
    requirements: list[GraphRef] = []
    controls: list[GraphRef] = []
    contract_count: int = 0
    active_contract_value: float = 0.0
    #: Live contract value per currency (a blank contract currency counts as the
    #: organisation's). ``active_contract_value`` sums across currencies; kept for old clients.
    active_contract_totals: dict[str, float] = {}
    created_at: datetime
    # Phase 2 due diligence (read side).
    relationship_owner_ref: UserRef | None = None
    data_classification_ref: LookupRef | None = None
    data_residency_countries: list[LookupRef] = []
    processes: list[GraphRef] = []
    subcontractors: list[GraphRef] = []
    #: Reverse: the vendors that list this one as their sub-contractor.
    subcontractor_of: list[GraphRef] = []
    certifications: list[VendorCertificationRead] = []
    inherent_tier: str | None = None
    tier_override_reason: str = ""
    tiering: VendorTiering | None = None
    outsourcing: list[VendorOutsourcingFacts] = []
    concentration: VendorConcentration | None = None

    @field_validator("spend_currency", mode="before")
    @classmethod
    def _stored_ccy(cls, v):
        return v or ""
