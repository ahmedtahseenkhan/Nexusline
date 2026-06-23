from __future__ import annotations

import uuid

from pydantic import BaseModel, ConfigDict, Field


class NamedRef(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    name: str


class CatalogBase(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = ""
    category: str = ""


class ThreatCreate(CatalogBase):
    pass


class ThreatUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None
    category: str | None = None


class ThreatRead(CatalogBase):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    # Read-only reverse relationship: how many risks reference this threat
    # (via the risk_threats association). Populated by the list/detail endpoints.
    used_by_risks_count: int = 0


class VulnerabilityCreate(CatalogBase):
    pass


class VulnerabilityUpdate(ThreatUpdate):
    pass


class VulnerabilityRead(CatalogBase):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    # Read-only reverse relationship: how many risks reference this vulnerability
    # (via the risk_vulnerabilities association). Populated by the endpoints.
    used_by_risks_count: int = 0
